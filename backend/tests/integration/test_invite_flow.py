"""Integration tests for invite accept transaction integrity."""

import pytest
import pytest_asyncio
from datetime import datetime, timedelta, timezone

from app.core.auth import AuthContext, UserContext
from app.core.exceptions import ConflictError, ForbiddenError, GoneError
from app.services.invite_service import InviteService
from tests.integration.seed_helpers import (
    create_test_household,
    create_test_invite,
    create_test_user,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest_asyncio.fixture
async def invite_env(db_conn):
    """Household with one owner and a pending invite."""
    owner_id = await create_test_user(db_conn, email="owner@test.dk")
    hh = await create_test_household(db_conn, owner_id)
    hid = hh["household_id"]

    invitee_id = await create_test_user(db_conn, email="invitee@test.dk")

    invite_row, raw_token = await create_test_invite(
        db_conn, hid, invited_by=owner_id, email="invitee@test.dk",
    )

    return {
        "household_id": hid,
        "owner_id": owner_id,
        "invitee_id": invitee_id,
        "invite": invite_row,
        "raw_token": raw_token,
    }


class TestAcceptInviteHappyPath:
    async def test_creates_membership_and_marks_accepted(
        self, pool_adapter, invite_env
    ):
        svc = InviteService(pool_adapter)
        env = invite_env
        user = UserContext(user_id=env["invitee_id"], email="invitee@test.dk")

        result = await svc.accept_invite(user, env["raw_token"], "Invitee Name")

        assert result["member"]["user_id"] == env["invitee_id"]
        assert result["member"]["role"] == "member"

        conn = pool_adapter._conn

        # Verify member count is now 2.
        count = await conn.fetchval(
            "SELECT count(*) FROM household_members WHERE household_id = $1",
            env["household_id"],
        )
        assert count == 2

        # Verify invite status.
        invite = await conn.fetchrow(
            "SELECT status::text, accepted_at, accepted_by_user_id "
            "FROM household_invites WHERE id = $1",
            env["invite"]["id"],
        )
        assert invite["status"] == "accepted"
        assert invite["accepted_at"] is not None
        assert invite["accepted_by_user_id"] == env["invitee_id"]


class TestAcceptInviteRejections:
    async def test_wrong_email_no_member_created(
        self, pool_adapter, invite_env
    ):
        svc = InviteService(pool_adapter)
        env = invite_env
        wrong_user_id = await create_test_user(
            pool_adapter._conn, email="wrong@test.dk"
        )
        user = UserContext(user_id=wrong_user_id, email="wrong@test.dk")

        with pytest.raises(ForbiddenError):
            await svc.accept_invite(user, env["raw_token"], "Wrong Person")

        conn = pool_adapter._conn
        count = await conn.fetchval(
            "SELECT count(*) FROM household_members WHERE household_id = $1",
            env["household_id"],
        )
        assert count == 1  # Only the owner.

    async def test_full_household_rejected(self, pool_adapter, db_conn):
        """A household at 2 members rejects a third accept."""
        owner_id = await create_test_user(db_conn, email="own@test.dk")
        hh = await create_test_household(db_conn, owner_id)
        hid = hh["household_id"]

        # Add a second member directly.
        second_id = await create_test_user(db_conn, email="second@test.dk")
        await db_conn.execute(
            """INSERT INTO household_members
                   (household_id, user_id, display_name, role)
               VALUES ($1, $2, 'Second', 'member')""",
            hid,
            second_id,
        )

        # Create invite for a third user (bypassing service cap check via raw SQL).
        third_id = await create_test_user(db_conn, email="third@test.dk")
        _, raw_token = await create_test_invite(
            db_conn, hid, invited_by=owner_id, email="third@test.dk",
        )

        svc = InviteService(pool_adapter)
        user = UserContext(user_id=third_id, email="third@test.dk")

        with pytest.raises(ConflictError, match="full"):
            await svc.accept_invite(user, raw_token, "Third")

        count = await db_conn.fetchval(
            "SELECT count(*) FROM household_members WHERE household_id = $1",
            hid,
        )
        assert count == 2  # No third member created.


class TestCreateInviteConstraints:
    async def test_one_pending_invite_per_household(self, pool_adapter, db_conn):
        """The partial unique index blocks a second pending invite."""
        owner_id = await create_test_user(db_conn, email="own2@test.dk")
        hh = await create_test_household(db_conn, owner_id)
        hid = hh["household_id"]

        auth = AuthContext(
            user_id=owner_id, household_id=hid, email="own2@test.dk",
        )
        svc = InviteService(pool_adapter)

        await svc.create_invite(auth, "first@test.dk")

        with pytest.raises(ConflictError, match="pending invite already exists"):
            await svc.create_invite(auth, "second@test.dk")

    async def test_expired_invite_is_lazily_transitioned(
        self, pool_adapter, db_conn
    ):
        """Looking up an expired invite transitions it and raises GoneError."""
        owner_id = await create_test_user(db_conn, email="own3@test.dk")
        hh = await create_test_household(db_conn, owner_id)
        hid = hh["household_id"]

        invitee_id = await create_test_user(db_conn, email="exp@test.dk")
        _, raw_token = await create_test_invite(
            db_conn, hid, invited_by=owner_id, email="exp@test.dk",
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )

        svc = InviteService(pool_adapter)
        user = UserContext(user_id=invitee_id, email="exp@test.dk")

        with pytest.raises(GoneError):
            await svc.lookup_invite(user, raw_token)

        # Status should now be 'expired' in DB.
        row = await db_conn.fetchrow(
            "SELECT status::text FROM household_invites WHERE household_id = $1",
            hid,
        )
        assert row["status"] == "expired"
