"""Integration tests for receipt confirm/post transaction integrity."""

import pytest
import pytest_asyncio
from datetime import date
from decimal import Decimal
from app.core.exceptions import ConflictError, ValidationError
from app.services.receipt_review_service import ReceiptReviewService
from tests.integration.seed_helpers import (
    create_test_category,
    create_test_household,
    create_test_receipt,
    create_test_receipt_item,
    create_test_user,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest_asyncio.fixture
async def receipt_env(db_conn):
    """Set up a household with an owner, two expense categories, and a
    receipt in ocr_complete status with two confirmed items."""
    user_id = await create_test_user(db_conn, email="owner@test.dk")
    hh = await create_test_household(db_conn, user_id)
    hid = hh["household_id"]

    cat_a = await create_test_category(db_conn, hid, "expense", "Dagligvarer")
    cat_b = await create_test_category(db_conn, hid, "expense", "Husholdning")

    receipt = await create_test_receipt(
        db_conn, hid, user_id,
        status="ocr_complete",
        store_name="Netto",
        receipt_date=date(2026, 4, 15),
        total_amount=Decimal("70.50"),
    )

    item_a = await create_test_receipt_item(
        db_conn, receipt["id"],
        description="Maelk",
        total_price=Decimal("25.50"),
        user_confirmed_category_id=cat_a["id"],
        requires_review=False,
    )
    item_b = await create_test_receipt_item(
        db_conn, receipt["id"],
        description="Vanish",
        total_price=Decimal("45.00"),
        user_confirmed_category_id=cat_b["id"],
        requires_review=False,
    )

    return {
        "user_id": user_id,
        "household_id": hid,
        "cat_a": cat_a,
        "cat_b": cat_b,
        "receipt": receipt,
        "items": [item_a, item_b],
    }


class TestConfirmReceiptHappyPath:
    async def test_creates_transaction_group_and_transactions(
        self, pool_adapter, receipt_env
    ):
        svc = ReceiptReviewService(pool_adapter)
        env = receipt_env

        result = await svc.confirm_receipt(
            receipt_id=env["receipt"]["id"],
            household_id=env["household_id"],
            user_id=env["user_id"],
        )

        assert result["status"] == "posted"
        assert result["receipt_id"] == env["receipt"]["id"]
        assert result["transactions_created"] == 2

        # Verify transaction_group exists with correct idempotency_key.
        conn = pool_adapter._conn
        group = await conn.fetchrow(
            "SELECT * FROM transaction_groups WHERE id = $1",
            result["transaction_group_id"],
        )
        assert group is not None
        assert group["idempotency_key"] == f"receipt:{env['receipt']['id']}"
        assert group["source"] == "receipt"

        # Verify transactions.
        txns = await conn.fetch(
            "SELECT * FROM transactions WHERE group_id = $1 ORDER BY amount",
            group["id"],
        )
        assert len(txns) == 2
        assert txns[0]["amount"] == Decimal("25.50")
        assert txns[1]["amount"] == Decimal("45.00")

        # Verify receipt status is now 'posted'.
        receipt_row = await conn.fetchrow(
            "SELECT status::text FROM receipts WHERE id = $1",
            env["receipt"]["id"],
        )
        assert receipt_row["status"] == "posted"

    async def test_auto_creates_budget_month(self, pool_adapter, receipt_env):
        """Confirming a receipt for a month with no budget_month creates one."""
        svc = ReceiptReviewService(pool_adapter)
        env = receipt_env

        result = await svc.confirm_receipt(
            receipt_id=env["receipt"]["id"],
            household_id=env["household_id"],
            user_id=env["user_id"],
        )

        conn = pool_adapter._conn
        txn = await conn.fetchrow(
            "SELECT budget_month_id FROM transactions WHERE group_id = $1 LIMIT 1",
            result["transaction_group_id"],
        )
        bm = await conn.fetchrow(
            "SELECT * FROM budget_months WHERE id = $1",
            txn["budget_month_id"],
        )
        assert bm is not None
        assert bm["month"] == date(2026, 4, 1)


class TestConfirmReceiptIdempotency:
    async def test_second_confirm_returns_same_group(
        self, pool_adapter, receipt_env
    ):
        svc = ReceiptReviewService(pool_adapter)
        env = receipt_env

        first = await svc.confirm_receipt(
            receipt_id=env["receipt"]["id"],
            household_id=env["household_id"],
            user_id=env["user_id"],
        )
        second = await svc.confirm_receipt(
            receipt_id=env["receipt"]["id"],
            household_id=env["household_id"],
            user_id=env["user_id"],
        )

        assert first["transaction_group_id"] == second["transaction_group_id"]
        assert second["transactions_created"] == first["transactions_created"]


class TestConfirmReceiptRejections:
    async def test_wrong_status_no_side_effects(self, pool_adapter, db_conn):
        """Receipt in 'uploaded' status cannot be confirmed."""
        user_id = await create_test_user(db_conn, email="u@test.dk")
        hh = await create_test_household(db_conn, user_id)
        hid = hh["household_id"]
        receipt = await create_test_receipt(db_conn, hid, user_id, status="uploaded")

        svc = ReceiptReviewService(pool_adapter)
        with pytest.raises(ConflictError):
            await svc.confirm_receipt(
                receipt_id=receipt["id"],
                household_id=hid,
                user_id=user_id,
            )

        # No transaction_group created.
        count = await db_conn.fetchval(
            "SELECT count(*) FROM transaction_groups WHERE household_id = $1",
            hid,
        )
        assert count == 0

    async def test_unconfirmed_items_rejected(self, pool_adapter, db_conn):
        """Items without user_confirmed_category_id block confirmation."""
        user_id = await create_test_user(db_conn, email="u2@test.dk")
        hh = await create_test_household(db_conn, user_id)
        hid = hh["household_id"]
        receipt = await create_test_receipt(db_conn, hid, user_id, status="ocr_complete")
        await create_test_receipt_item(
            db_conn, receipt["id"],
            description="Loose item",
            total_price=Decimal("10.00"),
            user_confirmed_category_id=None,
            requires_review=True,
        )

        svc = ReceiptReviewService(pool_adapter)
        with pytest.raises(ValidationError):
            await svc.confirm_receipt(
                receipt_id=receipt["id"],
                household_id=hid,
                user_id=user_id,
            )

        # Receipt status unchanged.
        row = await db_conn.fetchrow(
            "SELECT status::text FROM receipts WHERE id = $1", receipt["id"]
        )
        assert row["status"] == "ocr_complete"
