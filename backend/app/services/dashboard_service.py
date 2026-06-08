"""Service for dashboard: monthly totals, budget vs actual, savings rate, balance metrics."""

from datetime import date
from uuid import UUID

import asyncpg

from app.repositories.budgets import BudgetRepository
from app.repositories.transactions import TransactionRepository
from app.rules.budget_rules import build_dashboard_data, DashboardData


class DashboardService:
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def get_summary(
        self, household_id: UUID, year: int, month: int
    ) -> DashboardData:
        month_date = date(year, month, 1)

        async with self.pool.acquire() as conn:
            budget_repo = BudgetRepository(conn)
            txn_repo = TransactionRepository(conn)

            bm = await budget_repo.get_month(household_id, month_date)
            if not bm:
                return build_dashboard_data(
                    month=month_date.isoformat(),
                    budget_lines=[],
                    actuals_by_category=[],
                )

            budget_lines = await budget_repo.list_lines(bm["id"])
            actuals = await txn_repo.sum_by_type_and_category(household_id, bm["id"])

            return build_dashboard_data(
                month=month_date.isoformat(),
                budget_lines=budget_lines,
                actuals_by_category=actuals,
            )
