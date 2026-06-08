"""Service for receipt review editing and confirmation-to-transaction posting."""

from datetime import date
from decimal import Decimal
from typing import Optional
from uuid import UUID

import asyncpg

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.repositories.budgets import BudgetRepository
from app.repositories.categories import CategoryRepository
from app.repositories.receipts import ReceiptRepository
from app.repositories.transactions import TransactionRepository
from app.rules.date_rules import determine_budget_month
from app.rules.receipt_rules import (
    determine_requires_review_after_edit,
    group_items_by_category,
    validate_items_ready_for_confirm,
    validate_receipt_total,
)


_SENTINEL = object()
"""Sentinel distinct from None, used to distinguish 'field not provided'
from 'field explicitly set to None' in update_item."""


class ReceiptReviewService:
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def update_item(
        self,
        receipt_id: UUID,
        household_id: UUID,
        item_id: UUID,
        fields_set: set[str],
        user_confirmed_category_id: Optional[UUID] = _SENTINEL,
        is_excluded: Optional[bool] = _SENTINEL,
    ) -> dict:
        """Update user-editable fields on a receipt item during review.

        fields_set comes from the Pydantic model's model_fields_set and
        tells us which fields were explicitly provided in the request body.
        """
        if not fields_set & {"user_confirmed_category_id", "is_excluded"}:
            raise ValidationError("At least one field must be provided")

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                repo = ReceiptRepository(conn)

                # 1. Fetch receipt — ownership check
                receipt = await repo.get_by_id(receipt_id, household_id)
                if not receipt:
                    raise NotFoundError("Receipt not found")

                # 2. Status gate
                if receipt["status"] != "ocr_complete":
                    raise ConflictError(
                        f"Receipt is '{receipt['status']}'; editing is only "
                        f"allowed when status is 'ocr_complete'"
                    )

                # 3. Fetch item — scoped to receipt
                item = await repo.get_item_by_id(item_id, receipt_id)
                if not item:
                    raise NotFoundError("Receipt item not found")

                # 4. Validate category if provided and not None
                cat_id_provided = "user_confirmed_category_id" in fields_set
                if cat_id_provided and user_confirmed_category_id is not None:
                    cat_repo = CategoryRepository(conn)
                    cat = await cat_repo.get_by_id(
                        user_confirmed_category_id, household_id
                    )
                    if not cat:
                        raise NotFoundError("Category not found")
                    if cat["type"] != "expense":
                        raise ValidationError(
                            f"Category '{cat['name']}' is type "
                            f"'{cat['type']}', expected 'expense'"
                        )
                    if cat["archived_at"] is not None:
                        raise ValidationError(
                            f"Category '{cat['name']}' is archived"
                        )

                # 5. Compute final state and requires_review
                final_cat_id = (
                    user_confirmed_category_id
                    if cat_id_provided
                    else item["user_confirmed_category_id"]
                )
                excluded_provided = "is_excluded" in fields_set
                final_excluded = (
                    is_excluded if excluded_provided else item["is_excluded"]
                )
                new_requires_review = determine_requires_review_after_edit(
                    final_cat_id, final_excluded
                )

                # 6. Build update kwargs — only pass fields that were sent
                update_kwargs: dict = {"requires_review": new_requires_review}
                if cat_id_provided:
                    update_kwargs["user_confirmed_category_id"] = (
                        user_confirmed_category_id
                    )
                if excluded_provided:
                    update_kwargs["is_excluded"] = is_excluded

                await repo.update_item_user_fields(
                    item_id, receipt_id, **update_kwargs
                )

                # 7. Re-fetch with category names for the response
                enriched = await repo.get_item_with_category_names(
                    item_id, receipt_id
                )
                return enriched

    async def confirm_receipt(
        self,
        receipt_id: UUID,
        household_id: UUID,
        user_id: UUID,
        transaction_date_override: Optional[date] = None,
    ) -> dict:
        """Confirm a receipt and create grouped expense transactions.

        Runs ocr_complete → reviewed → posted inside one atomic DB
        transaction. If any step fails, everything rolls back.
        """
        async with self.pool.acquire() as conn:
            try:
                return await self._confirm_receipt_inner(
                    conn,
                    receipt_id,
                    household_id,
                    user_id,
                    transaction_date_override,
                )
            except asyncpg.UniqueViolationError:
                # Race condition: another request posted concurrently.
                # Return the idempotent response.
                txn_repo = TransactionRepository(conn)
                existing = await txn_repo.get_group_by_idempotency_key(
                    f"receipt:{receipt_id}"
                )
                if existing:
                    count = await txn_repo.count_by_group(existing["id"])
                    return {
                        "transaction_group_id": existing["id"],
                        "transactions_created": count,
                        "receipt_id": receipt_id,
                        "status": "posted",
                        "total_mismatch": False,
                    }
                raise  # pragma: no cover — should not happen

    async def _confirm_receipt_inner(
        self,
        conn,
        receipt_id: UUID,
        household_id: UUID,
        user_id: UUID,
        transaction_date_override: Optional[date],
    ) -> dict:
        async with conn.transaction():
            repo = ReceiptRepository(conn)
            txn_repo = TransactionRepository(conn)

            # ── Phase A: Ownership + idempotency ──

            # 1. Fetch receipt — household ownership check first
            receipt = await repo.get_by_id(receipt_id, household_id)
            if not receipt:
                raise NotFoundError("Receipt not found")

            # 2. Idempotency check
            existing_group = await txn_repo.get_group_by_idempotency_key(
                f"receipt:{receipt_id}"
            )
            if existing_group:
                count = await txn_repo.count_by_group(existing_group["id"])
                return {
                    "transaction_group_id": existing_group["id"],
                    "transactions_created": count,
                    "receipt_id": receipt_id,
                    "status": "posted",
                    "total_mismatch": False,
                }

            # ── Phase B: Pre-transition validation ──

            # 3. Status gate
            if receipt["status"] != "ocr_complete":
                raise ConflictError(
                    f"Receipt is '{receipt['status']}'; confirm requires "
                    f"'ocr_complete'"
                )

            # 4. Load all items
            items = await repo.list_items_by_receipt(receipt_id)

            # 5. Validate items ready
            errors = validate_items_ready_for_confirm(items)
            if errors:
                raise ValidationError(
                    "Items not ready for confirm: " + "; ".join(errors)
                )

            # 6. Build posting set — explicit filter
            postable_items = [
                i for i in items if not i.get("is_excluded", False)
            ]
            if not postable_items:
                raise ValidationError(
                    "Cannot confirm receipt: all items are excluded. "
                    "Un-exclude at least one item or delete the receipt."
                )

            # 7. Re-validate confirmed categories
            cat_repo = CategoryRepository(conn)
            seen_cat_ids: set[UUID] = set()
            for item in postable_items:
                cat_id = item["user_confirmed_category_id"]
                if cat_id in seen_cat_ids:
                    continue
                seen_cat_ids.add(cat_id)
                cat = await cat_repo.get_by_id(cat_id, household_id)
                if not cat:
                    raise ValidationError(
                        f"Category {cat_id} no longer exists"
                    )
                if cat["type"] != "expense":
                    raise ValidationError(
                        f"Category '{cat['name']}' is type "
                        f"'{cat['type']}', expected 'expense'"
                    )
                if cat["archived_at"] is not None:
                    raise ValidationError(
                        f"Category '{cat['name']}' has been archived"
                    )

            # 8. Determine dates
            transaction_date = (
                receipt["receipt_date"]
                if receipt["receipt_date"] is not None
                else transaction_date_override
            )
            if transaction_date is None:
                raise ValidationError(
                    "Receipt has no date. Supply 'transaction_date' in the "
                    "confirm request body, or re-parse the receipt."
                )
            effective_date = transaction_date
            budget_month_date = determine_budget_month(
                effective_date,
                "expense",
                shift_late_income=False,
                late_income_cutoff_day=None,
            )

            # 9. Group postable items by category
            grouped = group_items_by_category(postable_items)
            grouped = [g for g in grouped if g.total_amount > 0]
            if not grouped:
                raise ValidationError(
                    "No postable items with positive amounts."
                )

            # 10. Receipt-total validation (non-blocking)
            total_mismatch = False
            if receipt["total_amount"] is not None:
                posted_total = sum(
                    g.total_amount for g in grouped
                )
                total_mismatch = not validate_receipt_total(
                    posted_total, Decimal(str(receipt["total_amount"]))
                )

            # ── Phase C: Atomic posting ──

            # 11. CAS to reviewed
            cas_result = await repo.update_status(
                receipt_id, household_id, "ocr_complete", "reviewed"
            )
            if not cas_result:
                raise ConflictError(
                    "Failed to transition receipt to 'reviewed' — "
                    "another request may have confirmed it concurrently"
                )

            # 12. Resolve budget month
            budget_repo = BudgetRepository(conn)
            bm = await budget_repo.get_month(household_id, budget_month_date)
            if not bm:
                bm = await budget_repo.create_month(
                    household_id, budget_month_date
                )

            # 13. Create transaction group
            store = receipt.get("store_name") or "unknown store"
            txn_group = await txn_repo.create_group(
                household_id=household_id,
                source="receipt",
                idempotency_key=f"receipt:{receipt_id}",
                created_by=user_id,
                receipt_id=receipt_id,
                description=f"Receipt from {store}",
            )

            # 14. Create transactions
            for group in grouped:
                await txn_repo.create_transaction(
                    group_id=txn_group["id"],
                    household_id=household_id,
                    type="expense",
                    category_id=group.category_id,
                    amount=group.total_amount,
                    transaction_date=transaction_date,
                    effective_date=effective_date,
                    source="receipt",
                    posted_by=user_id,
                    budget_month_id=bm["id"],
                    description="; ".join(group.item_descriptions),
                )

            # 15. CAS to posted
            await repo.update_status(
                receipt_id, household_id, "reviewed", "posted"
            )

            # 16. Return
            return {
                "transaction_group_id": txn_group["id"],
                "transactions_created": len(grouped),
                "receipt_id": receipt_id,
                "status": "posted",
                "total_mismatch": total_mismatch,
            }
