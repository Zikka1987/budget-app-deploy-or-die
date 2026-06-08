"""Service for household invite creation, lookup, acceptance, and revocation.

Enforces the hard rule that a verified JWT email must equal the invite email.
All financial consequences flow through `household_members`; this service
never bypasses `UNIQUE(user_id)`.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

import asyncpg

from app.core.auth import AuthContext, UserContext
from app.core.exceptions import (
    ConflictError,
    ForbiddenError,
    GoneError,
    NotFoundError,
    ValidationError,
)
from app.repositories.household import HouseholdRepository
from app.repositories.invites import InviteRepository


# Public invite window. Kept constant for v1 per CLAUDE.md.
INVITE_TTL = timedelta(days=7)

# v1 household cap: owner + one invited member.
MAX_HOUSEHOLD_MEMBERS = 2

# Minimal email format check. The authoritative validation is the
# CHECK (email = lower(email)) constraint plus Supabase's own signup
# validation; this layer just catches obvious garbage before we spend
# a DB round-trip.
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _validate_email(email: str) -> None:
    if not _EMAIL_RE.match(email) or len(email) > 254:
        raise ValidationError("Invalid email address")


def _generate_token() -> tuple[str, str]:
    """Return (raw_token, sha256_hex_hash). Raw token is returned once to caller."""
    raw = secrets.token_urlsafe(32)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return raw, digest


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class InviteService:
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    # ── Inviter side ──

    async def create_invite(self, auth: AuthContext, email: str) -> dict:
        """Create a pending invite. Returns the row + raw token.

        Rejects creation if the household is already full (>= 2 members)
        or if a live pending invite already exists for the household.
        """
        normalized = _normalize_email(email)
        _validate_email(normalized)

        if normalized == auth.email:
            raise ConflictError("Cannot invite yourself")

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                household_repo = HouseholdRepository(conn)
                invites = InviteRepository(conn)

                # v1 2-seat cap: refuse to issue a new invite if the
                # household is already full. Checked inside the transaction
                # so any race with an ongoing accept is serialized by the
                # household_invites_one_pending_per_household index (the
                # accept path holds FOR UPDATE on the invite row, which
                # blocks concurrent create + insert via the partial unique).
                member_count = await household_repo.count_members(auth.household_id)
                if member_count >= MAX_HOUSEHOLD_MEMBERS:
                    raise ConflictError(
                        "Household is full; v1 households are limited to "
                        f"{MAX_HOUSEHOLD_MEMBERS} members"
                    )

                existing = await household_repo.find_membership_by_email(normalized)
                if existing is not None:
                    raise ConflictError("Email already belongs to a household")

                # Free the single-pending-per-household slot if a stale
                # (past-expiry) pending row is still occupying it.
                await invites.expire_stale_for_household(auth.household_id)

                expires_at = datetime.now(timezone.utc) + INVITE_TTL

                # Retry loop is effectively never entered (2^256 collision
                # space), but we guard against the vanishing chance of a
                # token_hash collision anyway.
                last_error: Optional[BaseException] = None
                for _ in range(3):
                    raw_token, token_hash = _generate_token()
                    try:
                        row = await invites.create(
                            household_id=auth.household_id,
                            invited_by_user_id=auth.user_id,
                            email=normalized,
                            token_hash=token_hash,
                            expires_at=expires_at,
                        )
                    except asyncpg.UniqueViolationError as exc:
                        constraint = getattr(exc, "constraint_name", "") or ""
                        if "one_pending_per_household" in constraint:
                            raise ConflictError(
                                "A pending invite already exists for this "
                                "household; revoke it before creating another"
                            )
                        if "token_hash" in constraint:
                            last_error = exc
                            continue
                        raise
                    row["token"] = raw_token
                    return row

                # If we somehow fell through the retry loop, surface the error.
                raise ConflictError("Failed to allocate unique invite token") from last_error

    async def list_invites(
        self, auth: AuthContext, status: Optional[str] = None
    ) -> list[dict]:
        if status is not None and status not in ("pending", "accepted", "revoked", "expired"):
            raise ValidationError("Invalid status filter")
        async with self.pool.acquire() as conn:
            invites = InviteRepository(conn)
            rows = await invites.list_by_household(auth.household_id, status)
            # token_hash is never included in the list query, but strip
            # defensively in case the query changes.
            for r in rows:
                r.pop("token_hash", None)
            return rows

    async def revoke_invite(self, auth: AuthContext, invite_id: UUID) -> None:
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                invites = InviteRepository(conn)
                invite = await invites.get_by_id_in_household(
                    invite_id, auth.household_id
                )
                if invite is None:
                    raise NotFoundError("Invite not found")
                if invite["status"] != "pending":
                    raise ConflictError("Invite is not pending")
                affected = await invites.mark_revoked(invite_id, auth.household_id)
                if affected != 1:
                    # Raced with another transition (accept / expire).
                    raise ConflictError("Invite is no longer pending")

    # ── Invitee side ──

    async def lookup_invite(self, user: UserContext, token: str) -> dict:
        token_hash = _hash_token(token)
        async with self.pool.acquire() as conn:
            # The expire_one UPDATE must commit even when we raise
            # GoneError, so we let the transaction block exit normally
            # and raise after it.
            _raise_gone = False
            _raise_conflict: Optional[str] = None
            _raise_forbidden = False
            result: Optional[dict] = None

            async with conn.transaction():
                invites = InviteRepository(conn)
                invite = await invites.get_by_token_hash(token_hash)
                if invite is None:
                    raise NotFoundError("Invite not found")

                if invite["status"] == "pending" and invite["expires_at"] <= datetime.now(
                    timezone.utc
                ):
                    await invites.expire_one(invite["id"])
                    _raise_gone = True
                elif invite["status"] == "expired":
                    _raise_gone = True
                elif invite["status"] in ("accepted", "revoked"):
                    _raise_conflict = "Invite has already been resolved"
                elif invite["email"] != user.email:
                    _raise_forbidden = True
                else:
                    result = {
                        "household_name": invite["household_name"],
                        "email": invite["email"],
                        "expires_at": invite["expires_at"],
                        "status": invite["status"],
                    }

            if _raise_gone:
                raise GoneError("Invite has expired")
            if _raise_conflict:
                raise ConflictError(_raise_conflict)
            if _raise_forbidden:
                raise ForbiddenError("This invite is for a different account")
            return result  # type: ignore[return-value]

    async def accept_invite(
        self, user: UserContext, token: str, display_name: str
    ) -> dict:
        token_hash = _hash_token(token)
        async with self.pool.acquire() as conn:
            # If the invite is stale-pending, expire_one must commit
            # before we raise GoneError, so we handle that path by
            # letting the transaction exit normally and raising after.
            _expired_lazy = False

            async with conn.transaction():
                invites = InviteRepository(conn)
                household_repo = HouseholdRepository(conn)

                invite = await invites.get_by_token_hash_for_update(token_hash)
                if invite is None:
                    raise NotFoundError("Invite not found")

                if invite["status"] == "pending" and invite["expires_at"] <= datetime.now(
                    timezone.utc
                ):
                    await invites.expire_one(invite["id"])
                    _expired_lazy = True
                elif invite["status"] == "expired":
                    raise GoneError("Invite has expired")
                elif invite["status"] in ("accepted", "revoked"):
                    raise ConflictError("Invite has already been resolved")

                if _expired_lazy:
                    pass  # exit transaction normally so expire_one commits
                else:
                    # Email match is enforced BEFORE any write.
                    if invite["email"] != user.email:
                        raise ForbiddenError("This invite is for a different account")

                    # Pre-check: invitee must not already belong to a household.
                    existing = await household_repo.get_member_by_user(user.user_id)
                    if existing is not None:
                        raise ConflictError("User already belongs to a household")

                    # v1 2-seat cap: refuse to add a member if the household is
                    # already full. This is defense-in-depth against any code
                    # path (now or future) that could bring the household to its
                    # cap between invite creation and acceptance. We hold a
                    # FOR UPDATE row lock on the invite above, which means this
                    # is the only accept executing for this household, so the
                    # count read here is effectively serialized.
                    member_count = await household_repo.count_members(
                        invite["household_id"]
                    )
                    if member_count >= MAX_HOUSEHOLD_MEMBERS:
                        raise ConflictError(
                            "Household is full; v1 households are limited to "
                            f"{MAX_HOUSEHOLD_MEMBERS} members"
                        )

                    try:
                        member = await household_repo.create_member(
                            invite["household_id"],
                            user.user_id,
                            display_name,
                            role="member",
                        )
                    except asyncpg.UniqueViolationError:
                        # Raced with another transaction inserting a member for
                        # this user. UNIQUE(user_id) preserves the invariant.
                        raise ConflictError("User already belongs to a household")

                    affected = await invites.mark_accepted(invite["id"], user.user_id)
                    if affected != 1:
                        # Someone else either revoked the invite or it just
                        # crossed expiry between our initial check and this
                        # UPDATE. Roll back the membership insert by raising.
                        raise ConflictError("Invite is no longer pending")

                    household = await household_repo.get_household(invite["household_id"])
                    if household is None:
                        raise NotFoundError("Household not found")

                    return {"household": household, "member": member}

            # Transaction committed — safe to raise now.
            if _expired_lazy:
                raise GoneError("Invite has expired")
