"""Integration tests for savings proposal approval and manual savings."""

import pytest
import pytest_asyncio
from datetime import date
from decimal import Decimal

from app.core.exceptions import ConflictError, ValidationError
from app.services.savings_service import SavingsService
from tests.integration.seed_helpers import (
    create_test_budget_month,
    create_test_category,
    create_test_household,
    create_test_savings_proposal,
    create_test_savings_rule,
    create_test_user,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest_asyncio.fixture
async def savings_env(db_conn):
    """Household with savings category, rule, budget month, and pending proposal."""
    user_id = await create_test_user(db_conn, email="saver@test.dk")
    hh = await create_test_household(db_conn, user_id)
    hid = hh["household_id"]

    cat = await create_test_category(db_conn, hid, "savings", "Opsparing")
    bm = await create_test_budget_month(db_conn, hid, date(2026, 4, 1))
    rule = await create_test_savings_rule(
        db_conn, hid, cat["id"], user_id,
        rule_type="fixed_monthly",
        label="Monthly Savings",
        fixed_amount=Decimal("2000.00"),
    )
    proposal = await create_test_savings_proposal(
        db_conn, hid, rule["id"], bm["id"],
        proposed_amount=Decimal("2000.00"),
    )

    return {
        "user_id": user_id,
        "household_id": hid,
        "category": cat,
        "budget_month": bm,
        "rule": rule,
        "proposal": proposal,
    }


class TestApproveProposal:
    async def test_happy_path_creates_transaction(
        self, pool_adapter, savings_env
    ):
        svc = SavingsService(pool_adapter)
        env = savings_env

        result = await svc.approve_proposal(
            household_id=env["household_id"],
            user_id=env["user_id"],
            proposal_id=env["proposal"]["id"],
        )

        assert result["status"] == "posted"
        assert result["transaction_id"] is not None

        conn = pool_adapter._conn

        # Verify transaction_group with idempotency key.
        group = await conn.fetchrow(
            "SELECT * FROM transaction_groups WHERE idempotency_key = $1",
            f"savings_proposal:{env['proposal']['id']}",
        )
        assert group is not None
        assert group["source"] == "savings_proposal"

        # Verify savings transaction.
        txn = await conn.fetchrow(
            "SELECT * FROM transactions WHERE group_id = $1",
            group["id"],
        )
        assert txn is not None
        assert txn["type"] == "savings"
        assert txn["amount"] == Decimal("2000.00")
        assert txn["category_id"] == env["category"]["id"]
        assert txn["savings_proposal_id"] == env["proposal"]["id"]

        # Verify proposal updated.
        proposal = await conn.fetchrow(
            "SELECT status::text, transaction_id, final_amount "
            "FROM savings_proposals WHERE id = $1",
            env["proposal"]["id"],
        )
        assert proposal["status"] == "posted"
        assert proposal["transaction_id"] == txn["id"]
        assert proposal["final_amount"] == Decimal("2000.00")

    async def test_idempotency_key_prevents_double_post(
        self, pool_adapter, savings_env
    ):
        svc = SavingsService(pool_adapter)
        env = savings_env

        await svc.approve_proposal(
            household_id=env["household_id"],
            user_id=env["user_id"],
            proposal_id=env["proposal"]["id"],
        )

        with pytest.raises(ConflictError):
            await svc.approve_proposal(
                household_id=env["household_id"],
                user_id=env["user_id"],
                proposal_id=env["proposal"]["id"],
            )

    async def test_approve_with_custom_amount(
        self, pool_adapter, savings_env
    ):
        svc = SavingsService(pool_adapter)
        env = savings_env

        await svc.approve_proposal(
            household_id=env["household_id"],
            user_id=env["user_id"],
            proposal_id=env["proposal"]["id"],
            final_amount=Decimal("1500.00"),
        )

        conn = pool_adapter._conn
        txn = await conn.fetchrow(
            "SELECT amount FROM transactions WHERE savings_proposal_id = $1",
            env["proposal"]["id"],
        )
        assert txn["amount"] == Decimal("1500.00")


class TestManualSavings:
    async def test_creates_budget_month_if_missing(
        self, pool_adapter, db_conn
    ):
        user_id = await create_test_user(db_conn, email="manual@test.dk")
        hh = await create_test_household(db_conn, user_id)
        hid = hh["household_id"]
        cat = await create_test_category(db_conn, hid, "savings", "Opsparing")

        svc = SavingsService(pool_adapter)
        result = await svc.create_manual_savings(
            household_id=hid,
            user_id=user_id,
            category_id=cat["id"],
            amount=Decimal("500.00"),
            transaction_date=date(2026, 5, 10),
            description="Extra savings",
        )

        assert result["amount"] == Decimal("500.00")
        assert result["budget_month"] == date(2026, 5, 1)

        # Verify budget month was created.
        bm = await db_conn.fetchrow(
            "SELECT * FROM budget_months WHERE household_id = $1 AND month = $2",
            hid,
            date(2026, 5, 1),
        )
        assert bm is not None

    async def test_rejects_expense_category(
        self, pool_adapter, db_conn
    ):
        user_id = await create_test_user(db_conn, email="wrong@test.dk")
        hh = await create_test_household(db_conn, user_id)
        hid = hh["household_id"]
        cat = await create_test_category(db_conn, hid, "expense", "Dagligvarer")

        svc = SavingsService(pool_adapter)
        with pytest.raises(ValidationError, match="expected 'savings'"):
            await svc.create_manual_savings(
                household_id=hid,
                user_id=user_id,
                category_id=cat["id"],
                amount=Decimal("500.00"),
                transaction_date=date(2026, 5, 10),
            )

    async def test_rejects_archived_category(
        self, pool_adapter, db_conn
    ):
        user_id = await create_test_user(db_conn, email="arch@test.dk")
        hh = await create_test_household(db_conn, user_id)
        hid = hh["household_id"]
        cat = await create_test_category(db_conn, hid, "savings", "Old Savings")

        # Archive the category.
        await db_conn.execute(
            "UPDATE categories SET archived_at = now() WHERE id = $1",
            cat["id"],
        )

        svc = SavingsService(pool_adapter)
        with pytest.raises(ValidationError, match="archived"):
            await svc.create_manual_savings(
                household_id=hid,
                user_id=user_id,
                category_id=cat["id"],
                amount=Decimal("500.00"),
                transaction_date=date(2026, 5, 10),
            )
