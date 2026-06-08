"""Service for onboarding status checks."""

from uuid import UUID

import asyncpg

from app.repositories.onboarding import OnboardingRepository


class OnboardingService:
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def get_status(self, user_id: UUID) -> dict:
        """Check onboarding progress for a user."""
        async with self.pool.acquire() as conn:
            repo = OnboardingRepository(conn)
            household_id = await repo.get_household_id_for_user(user_id)

            if household_id is None:
                return {
                    "has_household": False,
                    "has_income_category": False,
                    "has_expense_category": False,
                    "has_savings_category": False,
                    "is_ready": False,
                }

            counts = await repo.count_active_categories_by_type(household_id)
            has_income = counts.get("income", 0) > 0
            has_expense = counts.get("expense", 0) > 0
            has_savings = counts.get("savings", 0) > 0

            return {
                "has_household": True,
                "has_income_category": has_income,
                "has_expense_category": has_expense,
                "has_savings_category": has_savings,
                "is_ready": has_income and has_expense,
            }
