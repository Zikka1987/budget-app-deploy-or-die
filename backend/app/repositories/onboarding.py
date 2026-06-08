"""Read-only repository for onboarding status queries."""

from typing import Optional
from uuid import UUID

from app.repositories.base import Connection


class OnboardingRepository:
    def __init__(self, conn: Connection):
        self.conn = conn

    async def get_household_id_for_user(self, user_id: UUID) -> Optional[UUID]:
        return await self.conn.fetchval(
            "SELECT household_id FROM household_members WHERE user_id = $1",
            user_id,
        )

    async def count_active_categories_by_type(
        self, household_id: UUID
    ) -> dict[str, int]:
        rows = await self.conn.fetch(
            """
            SELECT type, COUNT(*)::int AS cnt
            FROM categories
            WHERE household_id = $1 AND archived_at IS NULL
            GROUP BY type
            """,
            household_id,
        )
        return {row["type"]: row["cnt"] for row in rows}
