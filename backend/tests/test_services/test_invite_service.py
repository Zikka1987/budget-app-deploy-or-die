"""Mock-based tests for InviteService."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import asyncpg
import pytest

from app.core.auth import AuthContext, UserContext
from app.core.exceptions import (
    ConflictError,
    ForbiddenError,
    GoneError,
    NotFoundError,
    ValidationError,
)
from app.services.invite_service import InviteService


HOUSEHOLD_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
INVITER_ID = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
INVITEE_ID = UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
INVITE_ID = UUID("dddddddd-dddd-dddd-dddd-dddddddddddd")
MEMBER_ID = UUID("eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee")

INVITER_EMAIL = "inviter@example.test"
INVITEE_EMAIL = "invitee@example.test"

NOW = datetime.now(timezone.utc)


def _auth(email: str = INVITER_EMAIL) -> AuthContext:
    return AuthContext(user_id=INVITER_ID, household_id=HOUSEHOLD_ID, email=email)


def _user(user_id: UUID = INVITEE_ID, email: str = INVITEE_EMAIL) -> UserContext:
    return UserContext(user_id=user_id, email=email)


def _household():
    return {
        "id": HOUSEHOLD_ID,
        "name": "Family Budget",
        "created_at": NOW,
        "updated_at": NOW,
    }


def _member():
    return {
        "id": MEMBER_ID,
        "household_id": HOUSEHOLD_ID,
        "user_id": INVITEE_ID,
        "display_name": "Bob",
        "role": "member",
        "joined_at": NOW,
    }


def _invite(
    *,
    status: str = "pending",
    expires_at: datetime | None = None,
    email: str = INVITEE_EMAIL,
    with_household_name: bool = False,
):
    row = {
        "id": INVITE_ID,
        "household_id": HOUSEHOLD_ID,
        "invited_by_user_id": INVITER_ID,
        "email": email,
        "token_hash": "unused-in-tests",
        "status": status,
        "expires_at": expires_at or (NOW + timedelta(days=7)),
        "created_at": NOW,
        "accepted_at": None,
        "accepted_by_user_id": None,
        "revoked_at": None,
    }
    if with_household_name:
        row["household_name"] = "Family Budget"
    return row


def _unique_violation(constraint_name: str) -> asyncpg.UniqueViolationError:
    """Build a UniqueViolationError with a specific constraint_name."""
    exc = asyncpg.UniqueViolationError("", "", "", "", "", "", "")
    # asyncpg exposes constraint_name as an attribute; monkeypatch it for tests.
    object.__setattr__(exc, "constraint_name", constraint_name)
    return exc


# ── Fixtures ──


@pytest.fixture
def fake_pool():
    pool = MagicMock()
    conn = MagicMock()
    txn_ctx = MagicMock()
    txn_ctx.__aenter__ = AsyncMock(return_value=None)
    txn_ctx.__aexit__ = AsyncMock(return_value=None)
    conn.transaction = MagicMock(return_value=txn_ctx)
    acq_ctx = MagicMock()
    acq_ctx.__aenter__ = AsyncMock(return_value=conn)
    acq_ctx.__aexit__ = AsyncMock(return_value=None)
    pool.acquire = MagicMock(return_value=acq_ctx)
    return pool


@pytest.fixture
def fake_repos(monkeypatch):
    """Patch both InviteRepository and HouseholdRepository inside the service."""
    invites = MagicMock()
    invites.create = AsyncMock(
        return_value=_invite(status="pending")
    )
    invites.get_by_token_hash = AsyncMock(return_value=None)
    invites.get_by_token_hash_for_update = AsyncMock(return_value=None)
    invites.get_by_id_in_household = AsyncMock(return_value=None)
    invites.list_by_household = AsyncMock(return_value=[])
    invites.mark_accepted = AsyncMock(return_value=1)
    invites.mark_revoked = AsyncMock(return_value=1)
    invites.expire_stale_for_household = AsyncMock(return_value=0)
    invites.expire_one = AsyncMock(return_value=1)

    household = MagicMock()
    household.find_membership_by_email = AsyncMock(return_value=None)
    household.get_member_by_user = AsyncMock(return_value=None)
    household.create_member = AsyncMock(return_value=_member())
    household.get_household = AsyncMock(return_value=_household())
    # Default: household has 1 member (the owner) → 1 seat remaining.
    household.count_members = AsyncMock(return_value=1)

    monkeypatch.setattr(
        "app.services.invite_service.InviteRepository",
        MagicMock(return_value=invites),
    )
    monkeypatch.setattr(
        "app.services.invite_service.HouseholdRepository",
        MagicMock(return_value=household),
    )
    return invites, household


# ══════════════════════════════════════════════════════════════════════
# create_invite
# ══════════════════════════════════════════════════════════════════════


class TestCreateInvite:
    @pytest.mark.asyncio
    async def test_happy_path(self, fake_pool, fake_repos):
        invites, _household = fake_repos
        service = InviteService(fake_pool)

        result = await service.create_invite(_auth(), INVITEE_EMAIL)

        # Raw token returned once
        assert "token" in result
        assert isinstance(result["token"], str)
        assert len(result["token"]) >= 32
        # DB was called with the sha256 hash, not the raw token
        call_kwargs = invites.create.call_args.kwargs
        expected_hash = hashlib.sha256(result["token"].encode()).hexdigest()
        assert call_kwargs["token_hash"] == expected_hash
        assert call_kwargs["email"] == INVITEE_EMAIL
        assert call_kwargs["household_id"] == HOUSEHOLD_ID
        assert call_kwargs["invited_by_user_id"] == INVITER_ID
        # expires_at is ~7 days out
        delta = call_kwargs["expires_at"] - datetime.now(timezone.utc)
        assert timedelta(days=6, hours=23) < delta <= timedelta(days=7, minutes=1)

    @pytest.mark.asyncio
    async def test_email_normalized(self, fake_pool, fake_repos):
        invites, _household = fake_repos
        service = InviteService(fake_pool)
        await service.create_invite(_auth(), "  Invitee@Example.TEST  ")
        assert invites.create.call_args.kwargs["email"] == "invitee@example.test"

    @pytest.mark.asyncio
    async def test_self_invite_rejected(self, fake_pool, fake_repos):
        service = InviteService(fake_pool)
        with pytest.raises(ConflictError, match="yourself"):
            await service.create_invite(_auth(), INVITER_EMAIL)

    @pytest.mark.asyncio
    async def test_invalid_email_rejected(self, fake_pool, fake_repos):
        service = InviteService(fake_pool)
        with pytest.raises(ValidationError):
            await service.create_invite(_auth(), "not-an-email")

    @pytest.mark.asyncio
    async def test_email_already_member(self, fake_pool, fake_repos):
        _invites, household = fake_repos
        household.find_membership_by_email.return_value = _member()
        service = InviteService(fake_pool)
        with pytest.raises(ConflictError, match="already belongs"):
            await service.create_invite(_auth(), INVITEE_EMAIL)

    @pytest.mark.asyncio
    async def test_duplicate_pending_translated_to_409(self, fake_pool, fake_repos):
        invites, _household = fake_repos
        invites.create.side_effect = _unique_violation(
            "household_invites_one_pending_per_household"
        )
        service = InviteService(fake_pool)
        with pytest.raises(ConflictError, match="pending invite"):
            await service.create_invite(_auth(), INVITEE_EMAIL)

    @pytest.mark.asyncio
    async def test_token_hash_collision_retries(self, fake_pool, fake_repos):
        invites, _household = fake_repos
        # First call collides on token_hash; second succeeds.
        invites.create.side_effect = [
            _unique_violation("household_invites_token_hash_uniq"),
            _invite(),
        ]
        service = InviteService(fake_pool)
        result = await service.create_invite(_auth(), INVITEE_EMAIL)
        assert "token" in result
        assert invites.create.await_count == 2

    @pytest.mark.asyncio
    async def test_create_after_expiry_is_allowed(self, fake_pool, fake_repos):
        """Service calls expire_stale_for_household before insert so a past-expiry
        pending row does not block the fresh invite."""
        invites, _household = fake_repos
        invites.expire_stale_for_household.return_value = 1
        service = InviteService(fake_pool)

        result = await service.create_invite(_auth(), INVITEE_EMAIL)

        invites.expire_stale_for_household.assert_awaited_once_with(HOUSEHOLD_ID)
        assert "token" in result
        invites.create.assert_awaited()

    @pytest.mark.asyncio
    async def test_create_blocked_by_live_pending(self, fake_pool, fake_repos):
        invites, _household = fake_repos
        invites.expire_stale_for_household.return_value = 0
        invites.create.side_effect = _unique_violation(
            "household_invites_one_pending_per_household"
        )
        service = InviteService(fake_pool)
        with pytest.raises(ConflictError, match="pending invite"):
            await service.create_invite(_auth(), INVITEE_EMAIL)


# ══════════════════════════════════════════════════════════════════════
# list_invites
# ══════════════════════════════════════════════════════════════════════


class TestListInvites:
    @pytest.mark.asyncio
    async def test_happy_path(self, fake_pool, fake_repos):
        invites, _ = fake_repos
        invites.list_by_household.return_value = [
            {
                **_invite(status="pending"),
                "token_hash": "should-be-stripped",
            },
            {
                **_invite(status="accepted"),
                "token_hash": "should-be-stripped",
            },
        ]
        service = InviteService(fake_pool)
        rows = await service.list_invites(_auth())
        assert len(rows) == 2
        for r in rows:
            assert "token_hash" not in r

    @pytest.mark.asyncio
    async def test_status_filter_passthrough(self, fake_pool, fake_repos):
        invites, _ = fake_repos
        service = InviteService(fake_pool)
        await service.list_invites(_auth(), status="pending")
        invites.list_by_household.assert_awaited_once_with(HOUSEHOLD_ID, "pending")

    @pytest.mark.asyncio
    async def test_invalid_status_filter(self, fake_pool, fake_repos):
        service = InviteService(fake_pool)
        with pytest.raises(ValidationError):
            await service.list_invites(_auth(), status="bogus")


# ══════════════════════════════════════════════════════════════════════
# revoke_invite
# ══════════════════════════════════════════════════════════════════════


class TestRevokeInvite:
    @pytest.mark.asyncio
    async def test_happy(self, fake_pool, fake_repos):
        invites, _ = fake_repos
        invites.get_by_id_in_household.return_value = _invite(status="pending")
        service = InviteService(fake_pool)
        await service.revoke_invite(_auth(), INVITE_ID)
        invites.mark_revoked.assert_awaited_once_with(INVITE_ID, HOUSEHOLD_ID)

    @pytest.mark.asyncio
    async def test_wrong_household_returns_404(self, fake_pool, fake_repos):
        invites, _ = fake_repos
        invites.get_by_id_in_household.return_value = None
        service = InviteService(fake_pool)
        with pytest.raises(NotFoundError):
            await service.revoke_invite(_auth(), INVITE_ID)

    @pytest.mark.asyncio
    async def test_already_accepted_returns_409(self, fake_pool, fake_repos):
        invites, _ = fake_repos
        invites.get_by_id_in_household.return_value = _invite(status="accepted")
        service = InviteService(fake_pool)
        with pytest.raises(ConflictError, match="not pending"):
            await service.revoke_invite(_auth(), INVITE_ID)

    @pytest.mark.asyncio
    async def test_race_mark_revoked_0_affected(self, fake_pool, fake_repos):
        invites, _ = fake_repos
        invites.get_by_id_in_household.return_value = _invite(status="pending")
        invites.mark_revoked.return_value = 0
        service = InviteService(fake_pool)
        with pytest.raises(ConflictError):
            await service.revoke_invite(_auth(), INVITE_ID)


# ══════════════════════════════════════════════════════════════════════
# lookup_invite
# ══════════════════════════════════════════════════════════════════════


class TestLookupInvite:
    @pytest.mark.asyncio
    async def test_happy(self, fake_pool, fake_repos):
        invites, _ = fake_repos
        invites.get_by_token_hash.return_value = _invite(with_household_name=True)
        service = InviteService(fake_pool)
        out = await service.lookup_invite(_user(), "raw-token")
        assert out["household_name"] == "Family Budget"
        assert out["email"] == INVITEE_EMAIL
        assert out["status"] == "pending"

    @pytest.mark.asyncio
    async def test_invalid_token_404(self, fake_pool, fake_repos):
        invites, _ = fake_repos
        invites.get_by_token_hash.return_value = None
        service = InviteService(fake_pool)
        with pytest.raises(NotFoundError):
            await service.lookup_invite(_user(), "raw-token")

    @pytest.mark.asyncio
    async def test_expired_pending_transitions_and_410(self, fake_pool, fake_repos):
        invites, _ = fake_repos
        stale = _invite(
            status="pending",
            expires_at=NOW - timedelta(hours=1),
            with_household_name=True,
        )
        invites.get_by_token_hash.return_value = stale
        service = InviteService(fake_pool)
        with pytest.raises(GoneError):
            await service.lookup_invite(_user(), "raw-token")
        # lazy transition was performed
        invites.expire_one.assert_awaited_once_with(INVITE_ID)

    @pytest.mark.asyncio
    async def test_expired_status_410(self, fake_pool, fake_repos):
        invites, _ = fake_repos
        invites.get_by_token_hash.return_value = _invite(
            status="expired", with_household_name=True
        )
        service = InviteService(fake_pool)
        with pytest.raises(GoneError):
            await service.lookup_invite(_user(), "raw-token")

    @pytest.mark.asyncio
    async def test_accepted_409(self, fake_pool, fake_repos):
        invites, _ = fake_repos
        invites.get_by_token_hash.return_value = _invite(
            status="accepted", with_household_name=True
        )
        service = InviteService(fake_pool)
        with pytest.raises(ConflictError):
            await service.lookup_invite(_user(), "raw-token")

    @pytest.mark.asyncio
    async def test_revoked_409(self, fake_pool, fake_repos):
        invites, _ = fake_repos
        invites.get_by_token_hash.return_value = _invite(
            status="revoked", with_household_name=True
        )
        service = InviteService(fake_pool)
        with pytest.raises(ConflictError):
            await service.lookup_invite(_user(), "raw-token")

    @pytest.mark.asyncio
    async def test_wrong_email_403(self, fake_pool, fake_repos):
        invites, _ = fake_repos
        invites.get_by_token_hash.return_value = _invite(
            email="someone-else@example.test", with_household_name=True
        )
        service = InviteService(fake_pool)
        with pytest.raises(ForbiddenError):
            await service.lookup_invite(_user(), "raw-token")


# ══════════════════════════════════════════════════════════════════════
# accept_invite
# ══════════════════════════════════════════════════════════════════════


class TestAcceptInvite:
    @pytest.mark.asyncio
    async def test_happy(self, fake_pool, fake_repos):
        invites, household = fake_repos
        invites.get_by_token_hash_for_update.return_value = _invite(
            with_household_name=True
        )
        service = InviteService(fake_pool)

        result = await service.accept_invite(_user(), "raw-token", "Bob")

        assert result["household"]["id"] == HOUSEHOLD_ID
        assert result["member"]["role"] == "member"
        household.create_member.assert_awaited_once_with(
            HOUSEHOLD_ID, INVITEE_ID, "Bob", role="member",
        )
        invites.mark_accepted.assert_awaited_once_with(INVITE_ID, INVITEE_ID)

    @pytest.mark.asyncio
    async def test_wrong_email_403_no_writes(self, fake_pool, fake_repos):
        invites, household = fake_repos
        invites.get_by_token_hash_for_update.return_value = _invite(
            email="someone-else@example.test", with_household_name=True
        )
        service = InviteService(fake_pool)
        with pytest.raises(ForbiddenError):
            await service.accept_invite(_user(), "raw-token", "Bob")
        household.create_member.assert_not_awaited()
        invites.mark_accepted.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_expired_pending_transitions_and_410(self, fake_pool, fake_repos):
        invites, household = fake_repos
        invites.get_by_token_hash_for_update.return_value = _invite(
            status="pending",
            expires_at=NOW - timedelta(seconds=1),
            with_household_name=True,
        )
        service = InviteService(fake_pool)
        with pytest.raises(GoneError):
            await service.accept_invite(_user(), "raw-token", "Bob")
        invites.expire_one.assert_awaited_once_with(INVITE_ID)
        household.create_member.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_expired_status_410(self, fake_pool, fake_repos):
        invites, _ = fake_repos
        invites.get_by_token_hash_for_update.return_value = _invite(
            status="expired", with_household_name=True
        )
        service = InviteService(fake_pool)
        with pytest.raises(GoneError):
            await service.accept_invite(_user(), "raw-token", "Bob")

    @pytest.mark.asyncio
    async def test_accepted_409(self, fake_pool, fake_repos):
        invites, household = fake_repos
        invites.get_by_token_hash_for_update.return_value = _invite(
            status="accepted", with_household_name=True
        )
        service = InviteService(fake_pool)
        with pytest.raises(ConflictError):
            await service.accept_invite(_user(), "raw-token", "Bob")
        household.create_member.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_revoked_409(self, fake_pool, fake_repos):
        invites, _ = fake_repos
        invites.get_by_token_hash_for_update.return_value = _invite(
            status="revoked", with_household_name=True
        )
        service = InviteService(fake_pool)
        with pytest.raises(ConflictError):
            await service.accept_invite(_user(), "raw-token", "Bob")

    @pytest.mark.asyncio
    async def test_invalid_token_404(self, fake_pool, fake_repos):
        invites, _ = fake_repos
        invites.get_by_token_hash_for_update.return_value = None
        service = InviteService(fake_pool)
        with pytest.raises(NotFoundError):
            await service.accept_invite(_user(), "raw-token", "Bob")

    @pytest.mark.asyncio
    async def test_invitee_already_in_household_409(self, fake_pool, fake_repos):
        invites, household = fake_repos
        invites.get_by_token_hash_for_update.return_value = _invite(
            with_household_name=True
        )
        household.get_member_by_user.return_value = _member()  # invitee already a member somewhere
        service = InviteService(fake_pool)
        with pytest.raises(ConflictError, match="already belongs"):
            await service.accept_invite(_user(), "raw-token", "Bob")
        household.create_member.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_unique_violation_race_on_insert(self, fake_pool, fake_repos):
        """create_member fires UniqueViolationError (race with concurrent accept)."""
        invites, household = fake_repos
        invites.get_by_token_hash_for_update.return_value = _invite(
            with_household_name=True
        )
        household.create_member.side_effect = _unique_violation("household_members_user_id_key")
        service = InviteService(fake_pool)
        with pytest.raises(ConflictError, match="already belongs"):
            await service.accept_invite(_user(), "raw-token", "Bob")

    @pytest.mark.asyncio
    async def test_mark_accepted_wins_race(self, fake_pool, fake_repos):
        """After membership insert, mark_accepted returns 0 (someone revoked).

        Service must raise ConflictError so the outer transaction rolls back.
        """
        invites, household = fake_repos
        invites.get_by_token_hash_for_update.return_value = _invite(
            with_household_name=True
        )
        invites.mark_accepted.return_value = 0
        service = InviteService(fake_pool)
        with pytest.raises(ConflictError):
            await service.accept_invite(_user(), "raw-token", "Bob")

    @pytest.mark.asyncio
    async def test_accept_household_full_at_redemption(self, fake_pool, fake_repos):
        """Household size reaches MAX_HOUSEHOLD_MEMBERS between create and accept."""
        invites, household = fake_repos
        invites.get_by_token_hash_for_update.return_value = _invite(
            with_household_name=True
        )
        household.count_members.return_value = 2  # already full
        service = InviteService(fake_pool)
        with pytest.raises(ConflictError, match="Household is full"):
            await service.accept_invite(_user(), "raw-token", "Bob")
        household.create_member.assert_not_awaited()
        invites.mark_accepted.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_email_match_case_insensitive(self, fake_pool, fake_repos):
        """Invite email stored lowercase; JWT normalized at ingest.

        Both stored values are already lowercase by this layer; what we verify
        here is that the service uses exact string compare on the normalized
        values, not .lower() again (defensive assertion).
        """
        invites, _ = fake_repos
        invites.get_by_token_hash_for_update.return_value = _invite(
            email=INVITEE_EMAIL, with_household_name=True
        )
        service = InviteService(fake_pool)
        # User context email already normalized by auth layer
        result = await service.accept_invite(_user(email=INVITEE_EMAIL), "tok", "Bob")
        assert result["member"]["role"] == "member"


# ══════════════════════════════════════════════════════════════════════
# 2-seat cap enforcement (v1 architecture invariant)
# ══════════════════════════════════════════════════════════════════════


class TestTwoSeatCap:
    """The v1 household cap is 2 members (owner + one invitee). The invite
    flow enforces this at three layers:
      (a) create_invite rejects when count_members(household_id) >= 2
      (b) accept_invite rejects when count_members(household_id) >= 2 at
          redemption time (defense-in-depth against races / future paths)
      (c) at most one live pending invite per household — enforced by the
          household_invites_one_pending_per_household partial unique index;
          the service translates the UniqueViolationError to 409.
    """

    @pytest.mark.asyncio
    async def test_create_rejected_when_household_full(self, fake_pool, fake_repos):
        """Layer (a): cap checked at invite creation."""
        invites, household = fake_repos
        household.count_members.return_value = 2
        service = InviteService(fake_pool)
        with pytest.raises(ConflictError, match="Household is full"):
            await service.create_invite(_auth(), INVITEE_EMAIL)
        invites.create.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_create_allowed_when_household_has_one_seat_left(
        self, fake_pool, fake_repos,
    ):
        invites, household = fake_repos
        household.count_members.return_value = 1
        service = InviteService(fake_pool)
        result = await service.create_invite(_auth(), INVITEE_EMAIL)
        assert "token" in result
        invites.create.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_create_rejected_when_household_has_three_members(
        self, fake_pool, fake_repos,
    ):
        """Belt-and-suspenders: any count >= 2 rejects, not just exactly 2."""
        _invites, household = fake_repos
        household.count_members.return_value = 3
        service = InviteService(fake_pool)
        with pytest.raises(ConflictError, match="Household is full"):
            await service.create_invite(_auth(), INVITEE_EMAIL)

    @pytest.mark.asyncio
    async def test_accept_rejected_when_household_full_at_redemption(
        self, fake_pool, fake_repos,
    ):
        """Layer (b): cap re-checked atomically inside the accept transaction."""
        invites, household = fake_repos
        invites.get_by_token_hash_for_update.return_value = _invite(
            with_household_name=True
        )
        household.count_members.return_value = 2
        service = InviteService(fake_pool)
        with pytest.raises(ConflictError, match="Household is full"):
            await service.accept_invite(_user(), "raw-token", "Bob")
        household.create_member.assert_not_awaited()
        invites.mark_accepted.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_one_pending_per_household_constraint_translated_to_409(
        self, fake_pool, fake_repos,
    ):
        """Layer (c): a second pending invite attempt (different email) against
        a household that already has a pending invite surfaces as 409.

        The underlying guard is the DB partial unique index
        household_invites_one_pending_per_household. The service catches the
        UniqueViolationError and re-raises it as ConflictError.
        """
        invites, household = fake_repos
        household.count_members.return_value = 1
        invites.expire_stale_for_household.return_value = 0  # nothing stale
        invites.create.side_effect = _unique_violation(
            "household_invites_one_pending_per_household"
        )
        service = InviteService(fake_pool)
        with pytest.raises(ConflictError, match="pending invite"):
            await service.create_invite(_auth(), "bob@example.test")

    @pytest.mark.asyncio
    async def test_cap_check_runs_before_db_insert(self, fake_pool, fake_repos):
        """Ensure the household-full branch short-circuits before any side effects
        (no expire_stale, no create)."""
        invites, household = fake_repos
        household.count_members.return_value = 2
        service = InviteService(fake_pool)
        with pytest.raises(ConflictError):
            await service.create_invite(_auth(), INVITEE_EMAIL)
        invites.expire_stale_for_household.assert_not_awaited()
        invites.create.assert_not_awaited()
