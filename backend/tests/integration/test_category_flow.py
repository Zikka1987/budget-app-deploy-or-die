"""Integration tests for category rename alias/history invariants."""

import pytest
import pytest_asyncio

from app.core.exceptions import ConflictError
from app.services.category_service import CategoryService
from tests.integration.seed_helpers import (
    create_test_category,
    create_test_household,
    create_test_user,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest_asyncio.fixture
async def cat_env(db_conn):
    """Household with two expense categories."""
    user_id = await create_test_user(db_conn, email="cat@test.dk")
    hh = await create_test_household(db_conn, user_id)
    hid = hh["household_id"]

    cat_a = await create_test_category(db_conn, hid, "expense", "Dagligvarer")
    cat_b = await create_test_category(db_conn, hid, "expense", "Transport")

    return {
        "user_id": user_id,
        "household_id": hid,
        "cat_a": cat_a,
        "cat_b": cat_b,
    }


class TestRenameCreatesAlias:
    async def test_old_name_stored_as_alias(self, pool_adapter, cat_env):
        svc = CategoryService(pool_adapter)
        env = cat_env

        await svc.update_category(
            category_id=env["cat_a"]["id"],
            household_id=env["household_id"],
            name="Mad og Drikke",
        )

        conn = pool_adapter._conn
        aliases = await conn.fetch(
            "SELECT alias FROM category_aliases WHERE category_id = $1",
            env["cat_a"]["id"],
        )
        assert len(aliases) == 1
        assert aliases[0]["alias"] == "Dagligvarer"

    async def test_multiple_renames_accumulate_aliases(
        self, pool_adapter, cat_env
    ):
        svc = CategoryService(pool_adapter)
        env = cat_env

        await svc.update_category(
            category_id=env["cat_a"]["id"],
            household_id=env["household_id"],
            name="Mad",
        )
        await svc.update_category(
            category_id=env["cat_a"]["id"],
            household_id=env["household_id"],
            name="Mad og Drikke",
        )

        conn = pool_adapter._conn
        aliases = await conn.fetch(
            "SELECT alias FROM category_aliases WHERE category_id = $1 "
            "ORDER BY created_at",
            env["cat_a"]["id"],
        )
        assert len(aliases) == 2
        assert aliases[0]["alias"] == "Dagligvarer"
        assert aliases[1]["alias"] == "Mad"

    async def test_category_name_updated_correctly(self, pool_adapter, cat_env):
        svc = CategoryService(pool_adapter)
        env = cat_env

        result = await svc.update_category(
            category_id=env["cat_a"]["id"],
            household_id=env["household_id"],
            name="Mad",
        )

        assert result["name"] == "Mad"


class TestRenameRejections:
    async def test_rename_to_existing_name_fails(self, pool_adapter, cat_env):
        svc = CategoryService(pool_adapter)
        env = cat_env

        with pytest.raises(ConflictError, match="already exists"):
            await svc.update_category(
                category_id=env["cat_a"]["id"],
                household_id=env["household_id"],
                name="Transport",  # cat_b's name
            )

        # No alias created on failure.
        conn = pool_adapter._conn
        aliases = await conn.fetch(
            "SELECT * FROM category_aliases WHERE category_id = $1",
            env["cat_a"]["id"],
        )
        assert len(aliases) == 0

    async def test_rename_archived_category_fails(
        self, pool_adapter, cat_env, db_conn
    ):
        env = cat_env

        await db_conn.execute(
            "UPDATE categories SET archived_at = now() WHERE id = $1",
            env["cat_a"]["id"],
        )

        svc = CategoryService(pool_adapter)
        with pytest.raises(ConflictError, match="archived"):
            await svc.update_category(
                category_id=env["cat_a"]["id"],
                household_id=env["household_id"],
                name="New Name",
            )
