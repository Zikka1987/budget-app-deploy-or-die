"""Integration tests for budget month initialization and carry-forward."""

import pytest
import pytest_asyncio
from datetime import date
from decimal import Decimal

from app.services.budget_service import BudgetService
from tests.integration.seed_helpers import (
    create_test_budget_line,
    create_test_budget_month,
    create_test_category,
    create_test_household,
    create_test_user,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest_asyncio.fixture
async def budget_env(db_conn):
    """Household with 2 expense categories and a March budget month with lines."""
    user_id = await create_test_user(db_conn, email="budget@test.dk")
    hh = await create_test_household(db_conn, user_id)
    hid = hh["household_id"]

    cat_a = await create_test_category(db_conn, hid, "expense", "Dagligvarer")
    cat_b = await create_test_category(db_conn, hid, "expense", "Transport")

    march = await create_test_budget_month(db_conn, hid, date(2026, 3, 1))
    await create_test_budget_line(db_conn, march["id"], cat_a["id"], Decimal("5000.00"))
    await create_test_budget_line(db_conn, march["id"], cat_b["id"], Decimal("1500.00"))

    return {
        "user_id": user_id,
        "household_id": hid,
        "cat_a": cat_a,
        "cat_b": cat_b,
        "march": march,
    }


class TestInitializeMonth:
    async def test_idempotent_returns_same_row(self, pool_adapter, budget_env):
        svc = BudgetService(pool_adapter)
        env = budget_env

        first = await svc.initialize_month(env["household_id"], date(2026, 4, 1))
        second = await svc.initialize_month(env["household_id"], date(2026, 4, 1))

        assert first["id"] == second["id"]

    async def test_carries_forward_previous_lines(
        self, pool_adapter, budget_env
    ):
        svc = BudgetService(pool_adapter)
        env = budget_env

        april = await svc.initialize_month(env["household_id"], date(2026, 4, 1))

        conn = pool_adapter._conn
        lines = await conn.fetch(
            "SELECT category_id, planned_amount FROM budget_lines "
            "WHERE budget_month_id = $1 ORDER BY planned_amount",
            april["id"],
        )
        assert len(lines) == 2
        assert lines[0]["planned_amount"] == Decimal("1500.00")
        assert lines[1]["planned_amount"] == Decimal("5000.00")
        cat_ids = {l["category_id"] for l in lines}
        assert cat_ids == {env["cat_a"]["id"], env["cat_b"]["id"]}

    async def test_skips_archived_categories(
        self, pool_adapter, budget_env, db_conn
    ):
        env = budget_env

        # Archive cat_b.
        await db_conn.execute(
            "UPDATE categories SET archived_at = now() WHERE id = $1",
            env["cat_b"]["id"],
        )

        svc = BudgetService(pool_adapter)
        april = await svc.initialize_month(env["household_id"], date(2026, 4, 1))

        conn = pool_adapter._conn
        lines = await conn.fetch(
            "SELECT category_id FROM budget_lines WHERE budget_month_id = $1",
            april["id"],
        )
        assert len(lines) == 1
        assert lines[0]["category_id"] == env["cat_a"]["id"]

    async def test_no_previous_month_creates_empty(
        self, pool_adapter, db_conn
    ):
        """First month in a household has no lines copied."""
        user_id = await create_test_user(db_conn, email="fresh@test.dk")
        hh = await create_test_household(db_conn, user_id)

        svc = BudgetService(pool_adapter)
        month = await svc.initialize_month(hh["household_id"], date(2026, 1, 1))

        conn = pool_adapter._conn
        lines = await conn.fetch(
            "SELECT * FROM budget_lines WHERE budget_month_id = $1",
            month["id"],
        )
        assert len(lines) == 0
