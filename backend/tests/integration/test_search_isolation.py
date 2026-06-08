"""Integration tests for search service household scoping.

Verifies that SearchService never leaks data across households.
These are application-level scoping tests, not RLS tests.
"""

import pytest
import pytest_asyncio
from datetime import date
from decimal import Decimal

from app.services.search_service import SearchService
from tests.integration.seed_helpers import (
    create_test_budget_month,
    create_test_category,
    create_test_household,
    create_test_receipt,
    create_test_transaction,
    create_test_user,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest_asyncio.fixture
async def two_households(db_conn):
    """Two separate households, each with a category, budget month,
    receipt, and transaction."""
    # Household A
    user_a = await create_test_user(db_conn, email="a@test.dk")
    hh_a = await create_test_household(db_conn, user_a, name="Household A")
    hid_a = hh_a["household_id"]
    cat_a = await create_test_category(db_conn, hid_a, "expense", "Groceries A")
    bm_a = await create_test_budget_month(db_conn, hid_a, date(2026, 4, 1))
    receipt_a = await create_test_receipt(
        db_conn, hid_a, user_a,
        store_name="Netto",
        receipt_date=date(2026, 4, 10),
    )
    txn_a = await create_test_transaction(
        db_conn, hid_a, user_a, cat_a["id"], bm_a["id"],
        amount=Decimal("150.00"),
        description="HH-A transaction",
    )

    # Household B
    user_b = await create_test_user(db_conn, email="b@test.dk")
    hh_b = await create_test_household(db_conn, user_b, name="Household B")
    hid_b = hh_b["household_id"]
    cat_b = await create_test_category(db_conn, hid_b, "expense", "Groceries B")
    bm_b = await create_test_budget_month(db_conn, hid_b, date(2026, 4, 1))
    receipt_b = await create_test_receipt(
        db_conn, hid_b, user_b,
        store_name="Foetex",
        receipt_date=date(2026, 4, 10),
    )
    txn_b = await create_test_transaction(
        db_conn, hid_b, user_b, cat_b["id"], bm_b["id"],
        amount=Decimal("250.00"),
        description="HH-B transaction",
    )

    return {
        "a": {"household_id": hid_a, "receipt": receipt_a, "txn": txn_a},
        "b": {"household_id": hid_b, "receipt": receipt_b, "txn": txn_b},
    }


class TestTransactionSearchIsolation:
    async def test_household_a_sees_only_own_transactions(
        self, pool_adapter, two_households
    ):
        svc = SearchService(pool_adapter)
        hh = two_households

        result = await svc.search_transactions(
            household_id=hh["a"]["household_id"],
        )

        assert result["total"] == 1
        assert result["results"][0]["description"] == "HH-A transaction"

    async def test_household_b_sees_only_own_transactions(
        self, pool_adapter, two_households
    ):
        svc = SearchService(pool_adapter)
        hh = two_households

        result = await svc.search_transactions(
            household_id=hh["b"]["household_id"],
        )

        assert result["total"] == 1
        assert result["results"][0]["description"] == "HH-B transaction"


class TestReceiptSearchIsolation:
    async def test_household_a_sees_only_own_receipts(
        self, pool_adapter, two_households
    ):
        svc = SearchService(pool_adapter)
        hh = two_households

        result = await svc.search_receipts(
            household_id=hh["a"]["household_id"],
        )

        assert result["total"] == 1
        assert result["results"][0]["store_name"] == "Netto"

    async def test_household_b_sees_only_own_receipts(
        self, pool_adapter, two_households
    ):
        svc = SearchService(pool_adapter)
        hh = two_households

        result = await svc.search_receipts(
            household_id=hh["b"]["household_id"],
        )

        assert result["total"] == 1
        assert result["results"][0]["store_name"] == "Foetex"
