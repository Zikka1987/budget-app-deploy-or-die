"""Repository for household_invites."""

from datetime import datetime
from typing import Optional
from uuid import UUID

from app.repositories.base import Connection


class InviteRepository:
    def __init__(self, conn: Connection):
        self.conn = conn

    async def create(
        self,
        *,
        household_id: UUID,
        invited_by_user_id: UUID,
        email: str,
        token_hash: str,
        expires_at: datetime,
    ) -> dict:
        row = await self.conn.fetchrow(
            """
            INSERT INTO household_invites
                (household_id, invited_by_user_id, email, token_hash, expires_at)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id, household_id, invited_by_user_id, email, token_hash,
                      status, expires_at, created_at, accepted_at,
                      accepted_by_user_id, revoked_at
            """,
            household_id,
            invited_by_user_id,
            email,
            token_hash,
            expires_at,
        )
        return dict(row)

    async def get_by_token_hash(self, token_hash: str) -> Optional[dict]:
        """Fetch invite + inviting household's name by token hash."""
        row = await self.conn.fetchrow(
            """
            SELECT hi.id, hi.household_id, hi.invited_by_user_id, hi.email,
                   hi.token_hash, hi.status, hi.expires_at, hi.created_at,
                   hi.accepted_at, hi.accepted_by_user_id, hi.revoked_at,
                   h.name AS household_name
            FROM household_invites hi
            JOIN households h ON h.id = hi.household_id
            WHERE hi.token_hash = $1
            """,
            token_hash,
        )
        return dict(row) if row else None

    async def get_by_token_hash_for_update(self, token_hash: str) -> Optional[dict]:
        """Row-locked fetch for the accept transaction.

        FOR UPDATE is applied to the invite row; the households join is read
        without locking (FOR UPDATE OF hi).
        """
        row = await self.conn.fetchrow(
            """
            SELECT hi.id, hi.household_id, hi.invited_by_user_id, hi.email,
                   hi.token_hash, hi.status, hi.expires_at, hi.created_at,
                   hi.accepted_at, hi.accepted_by_user_id, hi.revoked_at,
                   h.name AS household_name
            FROM household_invites hi
            JOIN households h ON h.id = hi.household_id
            WHERE hi.token_hash = $1
            FOR UPDATE OF hi
            """,
            token_hash,
        )
        return dict(row) if row else None

    async def get_by_id_in_household(
        self, invite_id: UUID, household_id: UUID
    ) -> Optional[dict]:
        row = await self.conn.fetchrow(
            """
            SELECT id, household_id, invited_by_user_id, email, status,
                   expires_at, created_at, accepted_at, accepted_by_user_id,
                   revoked_at
            FROM household_invites
            WHERE id = $1 AND household_id = $2
            """,
            invite_id,
            household_id,
        )
        return dict(row) if row else None

    async def list_by_household(
        self, household_id: UUID, status: Optional[str] = None
    ) -> list[dict]:
        if status is None:
            rows = await self.conn.fetch(
                """
                SELECT id, household_id, invited_by_user_id, email, status,
                       expires_at, created_at, accepted_at,
                       accepted_by_user_id, revoked_at
                FROM household_invites
                WHERE household_id = $1
                ORDER BY created_at DESC
                """,
                household_id,
            )
        else:
            rows = await self.conn.fetch(
                """
                SELECT id, household_id, invited_by_user_id, email, status,
                       expires_at, created_at, accepted_at,
                       accepted_by_user_id, revoked_at
                FROM household_invites
                WHERE household_id = $1 AND status = $2::household_invite_status
                ORDER BY created_at DESC
                """,
                household_id,
                status,
            )
        return [dict(r) for r in rows]

    async def mark_accepted(
        self, invite_id: UUID, accepted_by_user_id: UUID
    ) -> int:
        """Atomically flip status pending -> accepted.

        Returns affected row count. 0 means another transaction won the race
        (revoked, already accepted, or just expired). Caller must treat 0
        as a failure and roll back its transaction.
        """
        result = await self.conn.execute(
            """
            UPDATE household_invites
               SET status = 'accepted',
                   accepted_at = now(),
                   accepted_by_user_id = $2
             WHERE id = $1
               AND status = 'pending'
               AND now() < expires_at
            """,
            invite_id,
            accepted_by_user_id,
        )
        return _affected_rows(result)

    async def mark_revoked(self, invite_id: UUID, household_id: UUID) -> int:
        result = await self.conn.execute(
            """
            UPDATE household_invites
               SET status = 'revoked',
                   revoked_at = now()
             WHERE id = $1
               AND household_id = $2
               AND status = 'pending'
            """,
            invite_id,
            household_id,
        )
        return _affected_rows(result)

    async def expire_stale_for_household(self, household_id: UUID) -> int:
        """Flip any past-expires_at pending row for the household to expired.

        The v1 cap is one pending invite per household, so this zeroes or
        ones the single possible stale row. Called by create_invite before
        the insert so the partial unique index slot is freed for a fresh
        pending invite.
        """
        result = await self.conn.execute(
            """
            UPDATE household_invites
               SET status = 'expired'
             WHERE household_id = $1
               AND status = 'pending'
               AND expires_at <= now()
            """,
            household_id,
        )
        return _affected_rows(result)

    async def expire_one(self, invite_id: UUID) -> int:
        """Transition a single stale-pending invite to expired (lazy)."""
        result = await self.conn.execute(
            """
            UPDATE household_invites
               SET status = 'expired'
             WHERE id = $1
               AND status = 'pending'
               AND expires_at <= now()
            """,
            invite_id,
        )
        return _affected_rows(result)


def _affected_rows(execute_result: str) -> int:
    """Parse asyncpg execute() status tags like 'UPDATE 1' or 'INSERT 0 1'."""
    # asyncpg returns the final numeric token as the affected row count.
    parts = execute_result.split()
    if not parts:
        return 0
    try:
        return int(parts[-1])
    except ValueError:
        return 0
