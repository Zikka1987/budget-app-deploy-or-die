"""Service for manual expense entry.

Mirrors income_service shape; expenses do NOT use late-income shift, so the
budget month resolves directly from `transaction_date` via
`determine_budget_month(..., "expense", ...)`.
"""

from datetime import date
from decimal import Decimal
from typing import Optional
from uuid import UUID

import asyncpg

from app.core.exceptions import NotFoundError, ValidationError
from app.repositories.budgets import BudgetRepository
from app.repositories.categories import CategoryRepository
from app.repositories.transactions import TransactionRepository
from app.rules.date_rules import determine_budget_month


class ExpenseService:
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def list_expenses(
        self, household_id: UUID, budget_month_id: UUID
    ) -> list[dict]:
        async with self.pool.acquire() as conn:
            repo = TransactionRepository(conn)
            return await repo.list_by_type_and_month(
                household_id, "expense", budget_month_id
            )

    async def create_expense(
        self,
        household_id: UUID,
        user_id: UUID,
        category_id: UUID,
        amount: Decimal,
        transaction_date: date,
        description: Optional[str] = None,
        details: Optional[str] = None,
    ) -> dict:
        if amount <= 0:
            raise ValidationError("Amount must be positive")

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                # Validate category exists and is expense type
                cat_repo = CategoryRepository(conn)
                cat = await cat_repo.get_by_id(category_id, household_id)
                if not cat:
                    raise NotFoundError(f"Category {category_id} not found")
                if cat["type"] != "expense":
                    raise ValidationError(
                        f"Category '{cat['name']}' is type '{cat['type']}', expected 'expense'"
                    )
                if cat["archived_at"] is not None:
                    raise ValidationError(f"Category '{cat['name']}' is archived")

                # Expenses always use the calendar month of transaction_date
                # (no late-income shift applies).
                effective_date = transaction_date
                budget_month = determine_budget_month(
                    effective_date, "expense", False, None
                )

                # Ensure budget month exists (auto-initialize if not)
                budget_repo = BudgetRepository(conn)
                bm = await budget_repo.get_month(household_id, budget_month)
                if not bm:
                    bm = await budget_repo.create_month(household_id, budget_month)

                # Create transaction group + transaction
                import uuid as _uuid
                idempotency_key = f"manual_expense:{_uuid.uuid4()}"

                txn_repo = TransactionRepository(conn)
                group = await txn_repo.create_group(
                    household_id=household_id,
                    source="manual_expense",
                    idempotency_key=idempotency_key,
                    created_by=user_id,
                    description=description,
                )

                txn = await txn_repo.create_transaction(
                    group_id=group["id"],
                    household_id=household_id,
                    type="expense",
                    category_id=category_id,
                    amount=amount,
                    transaction_date=transaction_date,
                    effective_date=effective_date,
                    source="manual_expense",
                    posted_by=user_id,
                    budget_month_id=bm["id"],
                    description=description,
                    details=details,
                )

                txn["category_name"] = cat["name"]
                txn["budget_month"] = budget_month
                return txn

    async def update_expense(
        self,
        txn_id: UUID,
        household_id: UUID,
        category_id: Optional[UUID] = None,
        amount: Optional[Decimal] = None,
        transaction_date: Optional[date] = None,
        description: Optional[str] = ...,
        details: Optional[str] = ...,
    ) -> dict:
        if amount is not None and amount <= 0:
            raise ValidationError("Amount must be positive")

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                txn_repo = TransactionRepository(conn)
                existing = await txn_repo.get_transaction(txn_id, household_id)
                if not existing:
                    raise NotFoundError(f"Expense transaction {txn_id} not found")
                if existing["type"] != "expense":
                    raise ValidationError("Transaction is not an expense entry")
                if existing["source"] != "manual_expense":
                    raise ValidationError("Can only edit manual expense entries")

                # If category changed, validate new category. Capture the name
                # so we can put it on the response without an extra DB read.
                new_category_name: Optional[str] = None
                if category_id is not None and category_id != existing["category_id"]:
                    cat_repo = CategoryRepository(conn)
                    cat = await cat_repo.get_by_id(category_id, household_id)
                    if not cat or cat["type"] != "expense":
                        raise ValidationError("Invalid expense category")
                    if cat["archived_at"] is not None:
                        raise ValidationError(f"Category '{cat['name']}' is archived")
                    new_category_name = cat["name"]

                # If transaction_date changed, recompute budget_month.
                # Expenses use calendar month directly — no late-shift logic.
                new_budget_month_id = None
                if transaction_date is not None and transaction_date != existing["transaction_date"]:
                    new_bm_date = determine_budget_month(
                        transaction_date, "expense", False, None
                    )
                    budget_repo = BudgetRepository(conn)
                    bm = await budget_repo.get_month(household_id, new_bm_date)
                    if not bm:
                        bm = await budget_repo.create_month(household_id, new_bm_date)
                    new_budget_month_id = bm["id"]

                updated = await txn_repo.update_transaction(
                    txn_id,
                    household_id,
                    category_id=category_id,
                    amount=amount,
                    transaction_date=transaction_date,
                    effective_date=transaction_date,
                    budget_month_id=new_budget_month_id,
                    description=description,
                    details=details,
                )

                # Mirror create_expense / update_income: include the resolved
                # budget_month and category_name so callers can detect month
                # reassignment and display the category without an extra fetch.
                bm_repo = BudgetRepository(conn)
                bm_row = await bm_repo.get_month_by_id(
                    updated["budget_month_id"], household_id
                )
                updated["budget_month"] = bm_row["month"] if bm_row else None
                updated["category_name"] = (
                    new_category_name
                    if new_category_name is not None
                    else existing["category_name"]
                )

                return updated

    async def delete_expense(
        self, txn_id: UUID, household_id: UUID
    ) -> bool:
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                txn_repo = TransactionRepository(conn)
                existing = await txn_repo.get_transaction(txn_id, household_id)
                if not existing:
                    raise NotFoundError(f"Expense transaction {txn_id} not found")
                if existing["type"] != "expense":
                    raise ValidationError("Transaction is not an expense entry")
                if existing["source"] != "manual_expense":
                    raise ValidationError("Can only delete manual expense entries")
                # Delete the group (CASCADE deletes the transaction)
                return await txn_repo.delete_group(existing["group_id"], household_id)
