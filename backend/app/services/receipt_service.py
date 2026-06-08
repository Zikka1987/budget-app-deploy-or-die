"""Service for receipt upload, storage, parsing, categorization, review.

Upload flow (phase 1): validate → store in Supabase → create DB row.
Parse flow (phase 2): CAS status → download → AI parse → persist → ocr_complete.
Re-parse failures from ocr_complete preserve the last good OCR data.
Categorize flow (phase 3): ocr_complete → AI categorize → validate → full
refresh of suggested_category_id/confidence/requires_review on items.
Review payload (phase 3): read-only enriched review data for the client.
"""

import uuid
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Optional
from uuid import UUID

from app.ai.factory import get_categorizer, get_receipt_parser
from app.core.config import settings
from app.core.database import get_supabase
from app.core.exceptions import AppError, NotFoundError, ValidationError, ConflictError
from app.repositories.categories import CategoryRepository
from app.repositories.receipts import ReceiptRepository
from app.rules.receipt_rules import (
    build_duplicate_candidates,
    build_storage_path,
    build_suggestion_updates,
    fold_adjacent_discounts,
    items_to_categorize_from_rows,
    parsed_receipt_to_item_dicts,
    validate_category_suggestions,
    validate_upload_file,
)

if TYPE_CHECKING:
    import asyncpg


class ReceiptService:
    def __init__(self, pool: "asyncpg.Pool"):
        self.pool = pool

    async def upload_receipt(
        self,
        household_id: UUID,
        user_id: UUID,
        file_bytes: bytes,
        mime_type: str,
        file_name: Optional[str],
        store_name: Optional[str] = None,
        receipt_date: Optional[date] = None,
    ) -> dict:
        """Upload a receipt file to Supabase Storage and create a draft row.

        Order of operations:
        1. Validate MIME + size (pure function)
        2. Pre-generate receipt UUID so storage path matches DB row
        3. Upload bytes to Supabase Storage
        4. Insert DB row; on insert failure, attempt to delete from storage
        """
        # 1. Validate file (pure function)
        try:
            extension = validate_upload_file(mime_type, len(file_bytes))
        except ValueError as e:
            raise ValidationError(str(e))

        # 2. Pre-generate id so storage_path matches DB row
        receipt_id = uuid.uuid4()
        storage_path = build_storage_path(household_id, receipt_id, extension)

        # 3. Upload to Supabase Storage.
        # file_options values must be strings (HTTP headers).
        # Per official Supabase Python docs, "upsert" is the string "false".
        supabase = get_supabase()
        try:
            supabase.storage.from_(settings.supabase_receipts_bucket).upload(
                path=storage_path,
                file=file_bytes,
                file_options={
                    "content-type": mime_type,
                    "upsert": "false",
                },
            )
        except Exception as e:
            raise AppError(f"Storage upload failed: {e}", status_code=502)

        # 4. Create DB row. Roll back storage on failure.
        async with self.pool.acquire() as conn:
            try:
                repo = ReceiptRepository(conn)
                receipt = await repo.create(
                    receipt_id=receipt_id,
                    household_id=household_id,
                    uploaded_by=user_id,
                    storage_path=storage_path,
                    file_name=file_name,
                    mime_type=mime_type,
                    store_name=store_name,
                    receipt_date=receipt_date,
                )
            except Exception:
                try:
                    supabase.storage.from_(
                        settings.supabase_receipts_bucket
                    ).remove([storage_path])
                except Exception:
                    pass  # best-effort cleanup
                raise

        receipt["items"] = []  # No OCR yet, always empty at upload time
        return receipt

    async def get_receipt(self, receipt_id: UUID, household_id: UUID) -> dict:
        """Fetch a receipt with a short-lived signed URL for image viewing."""
        async with self.pool.acquire() as conn:
            repo = ReceiptRepository(conn)
            receipt = await repo.get_by_id(receipt_id, household_id)
            if not receipt:
                raise NotFoundError(f"Receipt {receipt_id} not found")

        receipt["image_url"] = self._signed_url(receipt["storage_path"])
        receipt["items"] = []  # No OCR yet
        return receipt

    async def list_receipts(
        self, household_id: UUID, limit: int = 100, offset: int = 0
    ) -> list[dict]:
        """List receipts for a household with basic pagination."""
        async with self.pool.acquire() as conn:
            repo = ReceiptRepository(conn)
            return await repo.list_by_household(
                household_id, limit=limit, offset=offset
            )

    async def parse_receipt(
        self, receipt_id: UUID, household_id: UUID
    ) -> dict:
        """Download a receipt file, parse it with AI, persist results.

        Status transitions:
          uploaded | failed | ocr_complete  →  processing  →  ocr_complete
        On failure from uploaded/failed, transitions to 'failed' with
        error_message. On failure from ocr_complete (re-parse), the previous
        OCR data is preserved — status reverts to ocr_complete, but an
        AppError is still raised to inform the caller.
        """
        # 1. Verify receipt exists and capture its current mime_type + storage_path.
        #    Also run the atomic CAS that transitions to 'processing' and
        #    returns the prior status (for the preservation rule).
        async with self.pool.acquire() as conn:
            repo = ReceiptRepository(conn)
            receipt = await repo.get_by_id(receipt_id, household_id)
            if not receipt:
                raise NotFoundError(f"Receipt {receipt_id} not found")

            cas_result = await repo.mark_processing(receipt_id, household_id)
            if cas_result is None:
                raise ConflictError(
                    f"Cannot parse receipt in status '{receipt['status']}'"
                )
            prior_status: str = cas_result["prior_status"]
            storage_path: str = receipt["storage_path"]
            mime_type: str = receipt["mime_type"] or "image/jpeg"

        # 2. Download the file from storage (no DB connection held during I/O).
        try:
            file_bytes = self._download_file(storage_path)
        except Exception as e:
            await self._mark_failed(
                receipt_id, household_id,
                f"Storage download failed: {e}", prior_status,
            )
            raise AppError(f"Storage download failed: {e}", status_code=502)

        # 3. Call the AI parser (slow: no DB connection held).
        try:
            parser = get_receipt_parser()
            parsed = await parser.parse(file_bytes, mime_type)
        except Exception as e:
            await self._mark_failed(
                receipt_id, household_id, str(e), prior_status,
            )
            raise AppError(f"Receipt parsing failed: {e}", status_code=502)

        parsed.items = fold_adjacent_discounts(parsed.items)

        # 4. Persist parsed fields + items in a single transaction.
        #    delete_items runs here — only after the AI call has returned a
        #    usable ParsedReceipt. If anything above failed, the old items
        #    and OCR fields are still untouched.
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                repo = ReceiptRepository(conn)
                await repo.delete_items(receipt_id)
                updated = await repo.update_parse_result(
                    receipt_id=receipt_id,
                    household_id=household_id,
                    store_name=parsed.store_name,
                    receipt_date=parsed.receipt_date,
                    total_amount=parsed.total_amount,
                    ocr_raw_text=parsed.raw_text,
                    ocr_provider=settings.ocr_provider,
                    ocr_confidence=(
                        Decimal(str(parsed.confidence))
                        if parsed.confidence is not None
                        else None
                    ),
                )
                if updated is None:
                    # Should not happen: receipt existed moments ago and we
                    # hold its id + household. Still, fail loudly rather than
                    # silently returning None.
                    raise NotFoundError(f"Receipt {receipt_id} not found")

                item_dicts = parsed_receipt_to_item_dicts(parsed)
                items = await repo.insert_items(receipt_id, item_dicts)
                existing = await repo.list_for_duplicate_check(
                    household_id, exclude_id=receipt_id
                )

        # 5. Build the response. Duplicate detection is non-blocking: matches
        #    are surfaced for the UI but the parse has already succeeded.
        duplicates = build_duplicate_candidates(parsed, existing)
        updated["items"] = items
        updated["duplicate_candidates"] = [
            {
                "id": r["id"],
                "store_name": r["store_name"],
                "receipt_date": r["receipt_date"],
                "total_amount": r["total_amount"],
            }
            for r in duplicates
        ]
        updated["image_url"] = self._signed_url(updated["storage_path"])
        return updated

    def _download_file(self, storage_path: str) -> bytes:
        """Download a file from the private receipts bucket."""
        supabase = get_supabase()
        return supabase.storage.from_(
            settings.supabase_receipts_bucket
        ).download(storage_path)

    async def _mark_failed(
        self,
        receipt_id: UUID,
        household_id: UUID,
        error_message: str,
        prior_status: str,
    ) -> None:
        """Record a parse failure, respecting the preservation rule.

        If prior_status was 'ocr_complete', preserve the previous OCR data
        by reverting status to 'ocr_complete' instead of moving to 'failed'.
        Only the error_message field is updated. Best-effort: any exception
        here is swallowed so the caller's original error is not masked.
        """
        try:
            async with self.pool.acquire() as conn:
                repo = ReceiptRepository(conn)
                await repo.mark_failed(
                    receipt_id, household_id, error_message[:1000], prior_status,
                )
        except Exception:
            pass  # don't mask the original error

    def _signed_url(
        self, storage_path: str, expires_in: int = 3600
    ) -> Optional[str]:
        """Generate a short-lived signed URL for a private receipt image.

        Non-fatal: returns None if signing fails for any reason.
        """
        try:
            supabase = get_supabase()
            result = supabase.storage.from_(
                settings.supabase_receipts_bucket
            ).create_signed_url(storage_path, expires_in)
            if isinstance(result, dict):
                return result.get("signedURL") or result.get("signed_url")
            return None
        except Exception:
            return None

    # ── Categorization + review payload (phase 3) ──

    async def categorize_receipt(
        self, receipt_id: UUID, household_id: UUID
    ) -> dict:
        """Run AI categorization on an ocr_complete receipt's items.

        Full-refresh semantics: every item's (suggested_category_id,
        confidence, requires_review) is rewritten in a single transaction.
        Items without a valid suggestion in this run are reset to
        (NULL, NULL, TRUE). user_confirmed_category_id is NEVER touched.
        Receipt status is NEVER changed — it stays ocr_complete. The
        next phase handles the review → reviewed → posted transition.
        """
        # 1. Load receipt + items + active expense categories.
        async with self.pool.acquire() as conn:
            repo = ReceiptRepository(conn)
            receipt = await repo.get_by_id(receipt_id, household_id)
            if not receipt:
                raise NotFoundError(f"Receipt {receipt_id} not found")
            if receipt["status"] != "ocr_complete":
                raise ConflictError(
                    f"Cannot categorize receipt in status '{receipt['status']}'"
                )

            items = await repo.list_items_by_receipt(receipt_id)
            cat_repo = CategoryRepository(conn)
            active_expense_categories = await cat_repo.list_by_household(
                household_id,
                type_filter="expense",
                include_archived=False,
            )

        if not active_expense_categories:
            raise ValidationError(
                "Cannot categorize receipt: household has no active expense "
                "categories. Create at least one expense category before "
                "categorizing receipts."
            )

        # Short-circuit: no items to categorize.
        if not items:
            return await self._load_review_payload_dict(receipt_id, household_id)

        # 2. Call AI (no DB connection held).
        items_for_ai = items_to_categorize_from_rows(items)
        category_options = _build_category_options(active_expense_categories)

        try:
            categorizer = get_categorizer()
            result = await categorizer.categorize(items_for_ai, category_options)
        except Exception as e:
            raise AppError(
                f"Receipt categorization failed: {e}", status_code=502,
            )

        # 3. Validate AI output deterministically.
        item_ids_in_receipt = {item["id"] for item in items}
        active_category_ids = {cat["id"] for cat in active_expense_categories}
        validated = validate_category_suggestions(
            result.suggestions,
            item_ids_in_receipt=item_ids_in_receipt,
            active_expense_category_ids=active_category_ids,
        )

        # 4. Build a full-refresh update list and persist in one transaction.
        updates = build_suggestion_updates(
            items,
            validated,
            threshold=settings.categorization_confidence_threshold,
        )
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                repo = ReceiptRepository(conn)
                await repo.update_item_suggestions(updates)

        # 5. Build and return the fresh review payload.
        return await self._load_review_payload_dict(receipt_id, household_id)

    async def get_review_payload(
        self, receipt_id: UUID, household_id: UUID
    ) -> dict:
        """Read-only review payload.

        Allowed for receipts in status 'ocr_complete' or 'reviewed'. Other
        statuses (including 'uploaded', 'processing', 'failed', 'posted')
        are not valid review targets at this phase.
        """
        async with self.pool.acquire() as conn:
            repo = ReceiptRepository(conn)
            receipt = await repo.get_by_id(receipt_id, household_id)
            if not receipt:
                raise NotFoundError(f"Receipt {receipt_id} not found")
            if receipt["status"] not in ("ocr_complete", "reviewed"):
                raise ConflictError(
                    f"Receipt is not ready for review (status='{receipt['status']}')"
                )
        return await self._load_review_payload_dict(receipt_id, household_id)

    async def _load_review_payload_dict(
        self, receipt_id: UUID, household_id: UUID
    ) -> dict:
        """Shared helper: load receipt + items with category names + duplicates.

        Returns a dict suitable for wrapping with ReceiptResponse(**). Never
        raises NotFoundError — callers must verify receipt exists first.
        """
        async with self.pool.acquire() as conn:
            repo = ReceiptRepository(conn)
            receipt = await repo.get_by_id(receipt_id, household_id)
            items = await repo.list_items_with_category_names(receipt_id)
            existing = await repo.list_for_duplicate_check(
                household_id, exclude_id=receipt_id,
            )

        # Build a pseudo-parsed receipt for the duplicate check.
        from app.ai.base import ParsedReceipt
        pseudo = ParsedReceipt(
            store_name=receipt["store_name"],
            receipt_date=receipt["receipt_date"],
            total_amount=receipt["total_amount"],
        )
        duplicates = build_duplicate_candidates(pseudo, existing)

        receipt["items"] = items
        receipt["duplicate_candidates"] = [
            {
                "id": r["id"],
                "store_name": r["store_name"],
                "receipt_date": r["receipt_date"],
                "total_amount": r["total_amount"],
            }
            for r in duplicates
        ]
        receipt["image_url"] = self._signed_url(receipt["storage_path"])
        return receipt


def _build_category_options(category_rows: list[dict]):
    """Adapter: DB category rows → CategorizerBase.CategoryOption dataclasses."""
    from app.ai.base import CategorizerBase
    return [
        CategorizerBase.CategoryOption(
            id=row["id"], name=row["name"], type=row["type"],
        )
        for row in category_rows
    ]
