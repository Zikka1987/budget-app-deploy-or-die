"""Service for budget month initialization and budget line management."""

from datetime import date
from decimal import Decimal
from typing import Optional
from uuid import UUID

import asyncpg

from app.core.exceptions import ConflictError, NotFoundError
from app.repositories.budgets import BudgetRepository
from app.repositories.categories import CategoryRepository


class BudgetService:
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def list_months(self, household_id: UUID) -> list[dict]:
        async with self.pool.acquire() as conn:
            repo = BudgetRepository(conn)
            return await repo.list_months(household_id)

    async def get_month_detail(self, month_id: UUID, household_id: UUID) -> dict:
        """Get a budget month with its lines and actual amounts."""
        async with self.pool.acquire() as conn:
            repo = BudgetRepository(conn)
            month = await repo.get_month_by_id(month_id, household_id)
            if not month:
                raise NotFoundError(f"Budget month {month_id} not found")
            lines = await repo.list_lines(month_id)
            # Compute actual amounts per category for this month
            actuals = await self._get_actuals_by_category(conn, household_id, month_id)
            enriched_lines = []
            for line in lines:
                actual = actuals.get(line["category_id"], Decimal("0"))
                enriched_lines.append({
                    **line,
                    "actual_amount": actual,
                })
            month["lines"] = enriched_lines
            return month

    async def initialize_month(self, household_id: UUID, month: date) -> dict:
        """Initialize a new budget month. Copies previous month's lines. Idempotent."""
        # Ensure month is 1st of month
        month = date(month.year, month.month, 1)

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                repo = BudgetRepository(conn)

                # Idempotent: return existing if found
                existing = await repo.get_month(household_id, month)
                if existing:
                    return existing

                # Create month
                new_month = await repo.create_month(household_id, month)

                # Find previous month to copy from
                prev = await repo.get_previous_month(household_id, month)
                if prev:
                    prev_lines = await repo.list_lines(prev["id"])
                    cat_repo = CategoryRepository(conn)
                    for line in prev_lines:
                        # Only copy if category is still active
                        cat = await cat_repo.get_by_id(line["category_id"], household_id)
                        if cat and cat["archived_at"] is None:
                            await repo.create_line(
                                new_month["id"],
                                line["category_id"],
                                line["planned_amount"],
                            )

                return new_month

    async def upsert_budget_line(
        self,
        month_id: UUID,
        household_id: UUID,
        category_id: UUID,
        planned_amount: Decimal,
        notes: Optional[str] = None,
    ) -> dict:
        async with self.pool.acquire() as conn:
            repo = BudgetRepository(conn)
            month = await repo.get_month_by_id(month_id, household_id)
            if not month:
                raise NotFoundError(f"Budget month {month_id} not found")
            if month["is_closed"]:
                raise ConflictError("Cannot modify a closed budget month")
            return await repo.upsert_line(month_id, category_id, planned_amount, notes)

    async def update_budget_line(
        self,
        line_id: UUID,
        household_id: UUID,
        planned_amount: Decimal,
        notes: Optional[str] = None,
    ) -> dict:
        async with self.pool.acquire() as conn:
            repo = BudgetRepository(conn)
            line = await repo.get_line_by_id(line_id)
            if not line:
                raise NotFoundError(f"Budget line {line_id} not found")
            # Verify ownership via the budget month
            month = await repo.get_month_by_id(line["budget_month_id"], household_id)
            if not month:
                raise NotFoundError(f"Budget line {line_id} not found")
            if month["is_closed"]:
                raise ConflictError("Cannot modify a closed budget month")
            updated = await repo.update_line(line_id, planned_amount, notes)
            return updated

    async def _get_actuals_by_category(
        self,
        conn: asyncpg.Connection,
        household_id: UUID,
        budget_month_id: UUID,
    ) -> dict[UUID, Decimal]:
        """Sum actual transaction amounts grouped by category for a budget month."""
        rows = await conn.fetch(
            """
            SELECT category_id, SUM(amount) AS total
            FROM transactions
            WHERE household_id = $1 AND budget_month_id = $2
            GROUP BY category_id
            """,
            household_id, budget_month_id,
        )
        return {row["category_id"]: row["total"] for row in rows}
