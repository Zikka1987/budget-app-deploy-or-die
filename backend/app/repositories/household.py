"""Repository for households, household_members, and household_settings."""

from typing import Optional
from uuid import UUID

from app.repositories.base import Connection


class HouseholdRepository:
    def __init__(self, conn: Connection):
        self.conn = conn

    # ── Households ──

    async def create_household(self, name: str) -> dict:
        row = await self.conn.fetchrow(
            """
            INSERT INTO households (name)
            VALUES ($1)
            RETURNING id, name, created_at, updated_at
            """,
            name,
        )
        return dict(row)

    async def get_household(self, household_id: UUID) -> Optional[dict]:
        row = await self.conn.fetchrow(
            """
            SELECT id, name, created_at, updated_at
            FROM households
            WHERE id = $1
            """,
            household_id,
        )
        return dict(row) if row else None

    # ── Members ──

    async def create_member(
        self,
        household_id: UUID,
        user_id: UUID,
        display_name: str,
        role: str = "owner",
    ) -> dict:
        row = await self.conn.fetchrow(
            """
            INSERT INTO household_members (household_id, user_id, display_name, role)
            VALUES ($1, $2, $3, $4)
            RETURNING id, household_id, user_id, display_name, role, joined_at
            """,
            household_id,
            user_id,
            display_name,
            role,
        )
        return dict(row)

    async def get_member_by_user(self, user_id: UUID) -> Optional[dict]:
        row = await self.conn.fetchrow(
            """
            SELECT id, household_id, user_id, display_name, role, joined_at
            FROM household_members
            WHERE user_id = $1
            """,
            user_id,
        )
        return dict(row) if row else None

    async def count_members(self, household_id: UUID) -> int:
        """Count current household_members rows for the household.

        Used by the invite flow to enforce the v1 2-seat cap at both
        create time and accept time.
        """
        count = await self.conn.fetchval(
            "SELECT count(*) FROM household_members WHERE household_id = $1",
            household_id,
        )
        return int(count or 0)

    async def find_membership_by_email(self, email: str) -> Optional[dict]:
        """Find any household_members row for the user owning this auth email.

        Best-effort pre-check for invite creation: returns None if no
        Supabase user exists for this email yet. Email is normalized by
        the caller; the query lowercases auth.users.email defensively.
        """
        row = await self.conn.fetchrow(
            """
            SELECT hm.id, hm.household_id, hm.user_id, hm.display_name,
                   hm.role, hm.joined_at
            FROM household_members hm
            JOIN auth.users u ON u.id = hm.user_id
            WHERE lower(u.email) = $1
            LIMIT 1
            """,
            email,
        )
        return dict(row) if row else None

    # ── Settings ──

    async def get_settings(self, household_id: UUID) -> Optional[dict]:
        row = await self.conn.fetchrow(
            """
            SELECT id, household_id, currency, shift_late_income,
                   late_income_cutoff_day, created_at, updated_at
            FROM household_settings
            WHERE household_id = $1
            """,
            household_id,
        )
        return dict(row) if row else None

    async def create_settings(self, household_id: UUID) -> dict:
        row = await self.conn.fetchrow(
            """
            INSERT INTO household_settings (household_id)
            VALUES ($1)
            RETURNING id, household_id, currency, shift_late_income,
                      late_income_cutoff_day, created_at, updated_at
            """,
            household_id,
        )
        return dict(row)

    async def update_settings(
        self,
        household_id: UUID,
        shift_late_income=...,
        late_income_cutoff_day=...,
    ) -> Optional[dict]:
        """Dynamic UPDATE using sentinel pattern. Only updates fields that are not ``...``."""
        sets = []
        params: list = []
        idx = 1

        if shift_late_income is not ...:
            sets.append(f"shift_late_income = ${idx}")
            params.append(shift_late_income)
            idx += 1
        if late_income_cutoff_day is not ...:
            sets.append(f"late_income_cutoff_day = ${idx}")
            params.append(late_income_cutoff_day)
            idx += 1

        if not sets:
            return await self.get_settings(household_id)

        sets.append(f"updated_at = now()")
        params.append(household_id)
        query = f"""
            UPDATE household_settings SET {', '.join(sets)}
            WHERE household_id = ${idx}
            RETURNING id, household_id, currency, shift_late_income,
                      late_income_cutoff_day, created_at, updated_at
        """
        row = await self.conn.fetchrow(query, *params)
        return dict(row) if row else None
