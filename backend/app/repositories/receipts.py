"""Repository for receipts and receipt_items tables."""

from datetime import date
from decimal import Decimal
from typing import Optional
from uuid import UUID

from app.repositories.base import Connection


_RECEIPT_COLUMNS = """
    id, household_id, uploaded_by, status, storage_path,
    file_name, mime_type, store_name, receipt_date,
    total_amount, ocr_raw_text, ocr_provider, ocr_confidence,
    error_message, created_at, updated_at
"""

_RECEIPT_LIST_COLUMNS = """
    id, household_id, uploaded_by, status, storage_path,
    file_name, mime_type, store_name, receipt_date,
    total_amount, ocr_provider, ocr_confidence,
    error_message, created_at, updated_at
"""


class ReceiptRepository:
    def __init__(self, conn: Connection):
        self.conn = conn

    async def create(
        self,
        receipt_id: UUID,
        household_id: UUID,
        uploaded_by: UUID,
        storage_path: str,
        file_name: Optional[str],
        mime_type: str,
        store_name: Optional[str] = None,
        receipt_date: Optional[date] = None,
    ) -> dict:
        """Insert a new receipt row with status='uploaded'.

        receipt_id is provided explicitly (not DB-generated) so the storage
        path {household_id}/{receipt_id}/original.{ext} can be built BEFORE
        the row is inserted, ensuring storage and DB agree on the id.
        """
        row = await self.conn.fetchrow(
            f"""
            INSERT INTO receipts
                (id, household_id, uploaded_by, status, storage_path,
                 file_name, mime_type, store_name, receipt_date)
            VALUES ($1, $2, $3, 'uploaded'::receipt_status, $4, $5, $6, $7, $8)
            RETURNING {_RECEIPT_COLUMNS}
            """,
            receipt_id, household_id, uploaded_by, storage_path, file_name,
            mime_type, store_name, receipt_date,
        )
        return dict(row)

    async def get_by_id(
        self, receipt_id: UUID, household_id: UUID
    ) -> Optional[dict]:
        """Fetch a single receipt, scoped to household."""
        row = await self.conn.fetchrow(
            f"""
            SELECT {_RECEIPT_COLUMNS}
            FROM receipts
            WHERE id = $1 AND household_id = $2
            """,
            receipt_id, household_id,
        )
        return dict(row) if row else None

    async def list_by_household(
        self, household_id: UUID, limit: int = 100, offset: int = 0
    ) -> list[dict]:
        """List receipts for a household, ordered by created_at DESC.

        Excludes ocr_raw_text from SELECT to keep list responses small.
        Supports basic limit/offset pagination.
        """
        rows = await self.conn.fetch(
            f"""
            SELECT {_RECEIPT_LIST_COLUMNS}
            FROM receipts
            WHERE household_id = $1
            ORDER BY created_at DESC
            LIMIT $2 OFFSET $3
            """,
            household_id, limit, offset,
        )
        return [dict(r) for r in rows]

    # ── Parse lifecycle ──

    async def mark_processing(
        self, receipt_id: UUID, household_id: UUID
    ) -> Optional[dict]:
        """Atomic CAS: transition uploaded/failed/ocr_complete → processing.

        Returns {id, prior_status} on success, None if the CAS failed (the
        receipt is in a locked status or does not exist). The prior_status
        is needed by the service to implement the re-parse preservation rule.
        """
        row = await self.conn.fetchrow(
            """
            WITH prior AS (
                SELECT id, status AS prior_status
                FROM receipts
                WHERE id = $1 AND household_id = $2
                FOR UPDATE
            )
            UPDATE receipts r
            SET status = 'processing'::receipt_status
            FROM prior
            WHERE r.id = prior.id
              AND prior.prior_status IN (
                  'uploaded'::receipt_status,
                  'failed'::receipt_status,
                  'ocr_complete'::receipt_status
              )
            RETURNING r.id, prior.prior_status::text AS prior_status
            """,
            receipt_id, household_id,
        )
        return dict(row) if row else None

    async def mark_failed(
        self,
        receipt_id: UUID,
        household_id: UUID,
        error_message: str,
        prior_status: str,
    ) -> Optional[dict]:
        """Record a parse failure.

        If prior_status == 'ocr_complete', reverts status to 'ocr_complete'
        and preserves all existing OCR fields and items (only updates
        error_message). Otherwise sets status to 'failed'.

        See the v1 re-parse failure preservation rule for rationale.
        """
        if prior_status == "ocr_complete":
            row = await self.conn.fetchrow(
                """
                UPDATE receipts
                SET status = 'ocr_complete'::receipt_status,
                    error_message = $3
                WHERE id = $1 AND household_id = $2
                RETURNING id, status, error_message
                """,
                receipt_id, household_id, error_message,
            )
        else:
            row = await self.conn.fetchrow(
                """
                UPDATE receipts
                SET status = 'failed'::receipt_status,
                    error_message = $3
                WHERE id = $1 AND household_id = $2
                RETURNING id, status, error_message
                """,
                receipt_id, household_id, error_message,
            )
        return dict(row) if row else None

    async def update_parse_result(
        self,
        receipt_id: UUID,
        household_id: UUID,
        store_name: Optional[str],
        receipt_date: Optional[date],
        total_amount: Optional[Decimal],
        ocr_raw_text: Optional[str],
        ocr_provider: str,
        ocr_confidence: Optional[Decimal],
    ) -> Optional[dict]:
        """Persist parsed OCR data and transition status to 'ocr_complete'.

        Clears error_message since this is a successful parse. Returns the
        updated row, or None if the receipt was not found in the household.
        """
        row = await self.conn.fetchrow(
            f"""
            UPDATE receipts
            SET status = 'ocr_complete'::receipt_status,
                store_name = $3,
                receipt_date = $4,
                total_amount = $5,
                ocr_raw_text = $6,
                ocr_provider = $7,
                ocr_confidence = $8,
                error_message = NULL
            WHERE id = $1 AND household_id = $2
            RETURNING {_RECEIPT_COLUMNS}
            """,
            receipt_id, household_id, store_name, receipt_date, total_amount,
            ocr_raw_text, ocr_provider, ocr_confidence,
        )
        return dict(row) if row else None

    # ── receipt_items ──

    async def delete_items(self, receipt_id: UUID) -> None:
        """Delete all receipt_items for a receipt.

        Used before replacing items on a re-parse. Must only be called after
        a successful AI parse; callers in the service layer are responsible
        for the ordering.
        """
        await self.conn.execute(
            "DELETE FROM receipt_items WHERE receipt_id = $1",
            receipt_id,
        )

    async def insert_items(
        self, receipt_id: UUID, items: list[dict]
    ) -> list[dict]:
        """Bulk insert receipt_items rows.

        Each dict must have: line_number, description, quantity, unit_price,
        total_price, suggested_category_id, confidence, requires_review,
        user_confirmed_category_id, is_excluded.
        Returns the inserted rows in line_number order.
        """
        if not items:
            return []
        inserted: list[dict] = []
        for item in items:
            row = await self.conn.fetchrow(
                """
                INSERT INTO receipt_items
                    (receipt_id, line_number, description, quantity,
                     unit_price, total_price, suggested_category_id,
                     confidence, requires_review,
                     user_confirmed_category_id, is_excluded)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                RETURNING id, receipt_id, line_number, description, quantity,
                          unit_price, total_price, suggested_category_id,
                          confidence, requires_review,
                          user_confirmed_category_id, is_excluded,
                          created_at, updated_at
                """,
                receipt_id,
                item["line_number"],
                item["description"],
                item["quantity"],
                item["unit_price"],
                item["total_price"],
                item["suggested_category_id"],
                item["confidence"],
                item["requires_review"],
                item["user_confirmed_category_id"],
                item["is_excluded"],
            )
            inserted.append(dict(row))
        return inserted

    async def list_for_duplicate_check(
        self, household_id: UUID, exclude_id: UUID
    ) -> list[dict]:
        """List receipts in the household that have parsed dedup fields.

        Returns only receipts with store_name, receipt_date, and total_amount
        populated (i.e. parsed receipts), excluding the given receipt id.
        Used by build_duplicate_candidates() to flag potential duplicates.
        """
        rows = await self.conn.fetch(
            """
            SELECT id, store_name, receipt_date, total_amount
            FROM receipts
            WHERE household_id = $1
              AND id != $2
              AND store_name IS NOT NULL
              AND receipt_date IS NOT NULL
              AND total_amount IS NOT NULL
            """,
            household_id, exclude_id,
        )
        return [dict(r) for r in rows]

    # ── Status transitions ──

    async def update_status(
        self,
        receipt_id: UUID,
        household_id: UUID,
        from_status: str,
        to_status: str,
    ) -> Optional[dict]:
        """Atomic CAS: transition receipt from one status to another.

        Returns the updated row on success, None if the CAS failed
        (receipt not found, wrong household, or status mismatch).
        """
        row = await self.conn.fetchrow(
            f"""
            UPDATE receipts
            SET status = $4::receipt_status
            WHERE id = $1 AND household_id = $2 AND status = $3::receipt_status
            RETURNING {_RECEIPT_COLUMNS}
            """,
            receipt_id, household_id, from_status, to_status,
        )
        return dict(row) if row else None

    # ── Categorization / review payload ──

    async def get_item_by_id(
        self, item_id: UUID, receipt_id: UUID
    ) -> Optional[dict]:
        """Fetch a single receipt item scoped to a receipt."""
        row = await self.conn.fetchrow(
            """
            SELECT id, receipt_id, line_number, description, quantity,
                   unit_price, total_price, suggested_category_id,
                   confidence, requires_review,
                   user_confirmed_category_id, is_excluded,
                   created_at, updated_at
            FROM receipt_items
            WHERE id = $1 AND receipt_id = $2
            """,
            item_id, receipt_id,
        )
        return dict(row) if row else None

    async def update_item_user_fields(
        self,
        item_id: UUID,
        receipt_id: UUID,
        user_confirmed_category_id: Optional[UUID] = ...,
        is_excluded: Optional[bool] = ...,
        requires_review: Optional[bool] = ...,
    ) -> Optional[dict]:
        """Update user-editable fields on a receipt item.

        Uses sentinel default (...) so callers can distinguish "not
        provided" from "explicitly set to None". Only builds SET
        clauses for fields that are not the sentinel.

        Never touches suggested_category_id or confidence.
        """
        sets = []
        params: list = []
        idx = 1
        if user_confirmed_category_id is not ...:
            sets.append(f"user_confirmed_category_id = ${idx}")
            params.append(user_confirmed_category_id)
            idx += 1
        if is_excluded is not ...:
            sets.append(f"is_excluded = ${idx}")
            params.append(is_excluded)
            idx += 1
        if requires_review is not ...:
            sets.append(f"requires_review = ${idx}")
            params.append(requires_review)
            idx += 1
        if not sets:
            return await self.get_item_by_id(item_id, receipt_id)
        params.append(item_id)
        params.append(receipt_id)
        query = f"""
            UPDATE receipt_items SET {', '.join(sets)}
            WHERE id = ${idx} AND receipt_id = ${idx + 1}
            RETURNING id, receipt_id, line_number, description, quantity,
                      unit_price, total_price, suggested_category_id,
                      confidence, requires_review,
                      user_confirmed_category_id, is_excluded,
                      created_at, updated_at
        """
        row = await self.conn.fetchrow(query, *params)
        return dict(row) if row else None

    async def get_item_with_category_names(
        self, item_id: UUID, receipt_id: UUID
    ) -> Optional[dict]:
        """Fetch a single receipt item with category names JOINed.

        Used after an item update to return a response with both
        suggested and confirmed category names populated.
        """
        row = await self.conn.fetchrow(
            """
            SELECT ri.id, ri.receipt_id, ri.line_number, ri.description,
                   ri.quantity, ri.unit_price, ri.total_price,
                   ri.suggested_category_id, sc.name AS suggested_category_name,
                   ri.user_confirmed_category_id, uc.name AS user_confirmed_category_name,
                   ri.confidence, ri.requires_review, ri.is_excluded,
                   ri.created_at, ri.updated_at
            FROM receipt_items ri
            LEFT JOIN categories sc ON sc.id = ri.suggested_category_id
            LEFT JOIN categories uc ON uc.id = ri.user_confirmed_category_id
            WHERE ri.id = $1 AND ri.receipt_id = $2
            """,
            item_id, receipt_id,
        )
        return dict(row) if row else None

    async def list_items_by_receipt(self, receipt_id: UUID) -> list[dict]:
        """Return all receipt_items for a receipt, ordered by line_number.

        Used by the categorize flow to load the items currently on the
        receipt before calling the AI.
        """
        rows = await self.conn.fetch(
            """
            SELECT id, receipt_id, line_number, description, quantity,
                   unit_price, total_price, suggested_category_id,
                   confidence, requires_review,
                   user_confirmed_category_id, is_excluded,
                   created_at, updated_at
            FROM receipt_items
            WHERE receipt_id = $1
            ORDER BY line_number NULLS LAST, created_at
            """,
            receipt_id,
        )
        return [dict(r) for r in rows]

    async def update_item_suggestions(
        self, update_dicts: list[dict]
    ) -> None:
        """Batch-update suggested_category_id, confidence, requires_review.

        Callers pass a full-refresh list containing one dict per item,
        including entries that reset suggestions back to NULL (the
        categorization service uses this to clear stale data from a
        previous run). user_confirmed_category_id and is_excluded are
        NEVER touched by this method.

        Each dict must have: id, suggested_category_id, confidence,
        requires_review.
        """
        if not update_dicts:
            return
        for update in update_dicts:
            await self.conn.execute(
                """
                UPDATE receipt_items
                SET suggested_category_id = $2,
                    confidence = $3,
                    requires_review = $4
                WHERE id = $1
                """,
                update["id"],
                update["suggested_category_id"],
                update["confidence"],
                update["requires_review"],
            )

    async def list_items_with_category_names(
        self, receipt_id: UUID
    ) -> list[dict]:
        """Return receipt_items joined to categories for both suggested + confirmed.

        Used to build the review payload response. LEFT JOINs are
        important: items may have no suggested category yet, and
        user_confirmed_category_id is always null in this phase.
        """
        rows = await self.conn.fetch(
            """
            SELECT ri.id, ri.receipt_id, ri.line_number, ri.description,
                   ri.quantity, ri.unit_price, ri.total_price,
                   ri.suggested_category_id, sc.name AS suggested_category_name,
                   ri.user_confirmed_category_id, uc.name AS user_confirmed_category_name,
                   ri.confidence, ri.requires_review, ri.is_excluded,
                   ri.created_at, ri.updated_at
            FROM receipt_items ri
            LEFT JOIN categories sc ON sc.id = ri.suggested_category_id
            LEFT JOIN categories uc ON uc.id = ri.user_confirmed_category_id
            WHERE ri.receipt_id = $1
            ORDER BY ri.line_number NULLS LAST, ri.created_at
            """,
            receipt_id,
        )
        return [dict(r) for r in rows]
