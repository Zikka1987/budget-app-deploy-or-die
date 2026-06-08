"""Mock-based tests for ExpenseService.

Focus: v1 surface — the create + delete paths the mobile app exercises.
Mirrors test_income_service.py shape; expenses do not use late-income shift,
so there's no shift-edge-case suite. update_expense follows the same logic
as update_income (already covered by test_income_service.py); a single test
that pins the response shape is enough for v1.
"""

from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest

from app.core.exceptions import ValidationError
from app.services.expense_service import ExpenseService


USER_ID = UUID("11111111-1111-1111-1111-111111111111")
HOUSEHOLD_ID = UUID("22222222-2222-2222-2222-222222222222")
CATEGORY_ID = UUID("33333333-3333-3333-3333-333333333333")
TXN_ID = UUID("44444444-4444-4444-4444-444444444444")
GROUP_ID = UUID("55555555-5555-5555-5555-555555555555")
BM_ID = UUID("66666666-6666-6666-6666-666666666666")
NOW = datetime.now(timezone.utc)
APRIL_FIRST = date(2026, 4, 1)


def _expense_category(archived_at=None):
    return {
        "id": CATEGORY_ID,
        "household_id": HOUSEHOLD_ID,
        "type": "expense",
        "name": "Groceries",
        "icon": None,
        "sort_order": 0,
        "archived_at": archived_at,
        "created_at": NOW,
        "updated_at": NOW,
    }


def _bm_row():
    return {
        "id": BM_ID,
        "household_id": HOUSEHOLD_ID,
        "month": APRIL_FIRST,
        "notes": None,
        "is_closed": False,
        "created_at": NOW,
        "updated_at": NOW,
    }


def _group():
    return {
        "id": GROUP_ID,
        "household_id": HOUSEHOLD_ID,
        "source": "manual_expense",
        "idempotency_key": "manual_expense:abc",
        "created_by": USER_ID,
        "receipt_id": None,
        "description": None,
        "created_at": NOW,
    }


def _txn():
    return {
        "id": TXN_ID,
        "group_id": GROUP_ID,
        "household_id": HOUSEHOLD_ID,
        "type": "expense",
        "category_id": CATEGORY_ID,
        "amount": Decimal("250.00"),
        "transaction_date": date(2026, 4, 15),
        "effective_date": date(2026, 4, 15),
        "source": "manual_expense",
        "posted_by": USER_ID,
        "budget_month_id": BM_ID,
        "description": None,
        "details": None,
        "savings_proposal_id": None,
        "created_at": NOW,
        "updated_at": NOW,
        "category_name": "Groceries",
    }


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
def fake_category_repo(monkeypatch):
    repo = MagicMock()
    repo.get_by_id = AsyncMock(return_value=_expense_category())
    monkeypatch.setattr(
        "app.services.expense_service.CategoryRepository",
        lambda conn: repo,
    )
    return repo


@pytest.fixture
def fake_budget_repo(monkeypatch):
    repo = MagicMock()
    repo.get_month = AsyncMock(return_value=_bm_row())
    repo.create_month = AsyncMock(return_value=_bm_row())
    repo.get_month_by_id = AsyncMock(return_value=_bm_row())
    monkeypatch.setattr(
        "app.services.expense_service.BudgetRepository",
        lambda conn: repo,
    )
    return repo


@pytest.fixture
def fake_txn_repo(monkeypatch):
    repo = MagicMock()
    repo.create_group = AsyncMock(return_value=_group())
    repo.create_transaction = AsyncMock(return_value=_txn())
    repo.get_transaction = AsyncMock(return_value=_txn())
    repo.update_transaction = AsyncMock(return_value=_txn())
    repo.delete_group = AsyncMock(return_value=True)
    monkeypatch.setattr(
        "app.services.expense_service.TransactionRepository",
        lambda conn: repo,
    )
    return repo


# ── Tests ──


@pytest.mark.asyncio
async def test_create_expense_returns_response_with_category_name_and_budget_month(
    fake_pool, fake_category_repo, fake_budget_repo, fake_txn_repo
):
    """Happy path: response carries category_name + budget_month so the
    mobile client can detect month assignment and display the row."""
    service = ExpenseService(fake_pool)
    result = await service.create_expense(
        household_id=HOUSEHOLD_ID,
        user_id=USER_ID,
        category_id=CATEGORY_ID,
        amount=Decimal("250.00"),
        transaction_date=date(2026, 4, 15),
    )

    assert result["category_name"] == "Groceries"
    assert result["budget_month"] == APRIL_FIRST
    assert result["source"] == "manual_expense"
    assert result["type"] == "expense"
    fake_txn_repo.create_transaction.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_expense_rejects_non_expense_category(
    fake_pool, fake_category_repo, fake_budget_repo, fake_txn_repo
):
    """Selecting an income or savings category must raise ValidationError
    rather than write a transaction."""
    fake_category_repo.get_by_id = AsyncMock(
        return_value={**_expense_category(), "type": "income"}
    )
    service = ExpenseService(fake_pool)
    with pytest.raises(ValidationError):
        await service.create_expense(
            household_id=HOUSEHOLD_ID,
            user_id=USER_ID,
            category_id=CATEGORY_ID,
            amount=Decimal("250.00"),
            transaction_date=date(2026, 4, 15),
        )
    fake_txn_repo.create_transaction.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_expense_rejects_archived_category(
    fake_pool, fake_category_repo, fake_budget_repo, fake_txn_repo
):
    fake_category_repo.get_by_id = AsyncMock(
        return_value=_expense_category(archived_at=NOW)
    )
    service = ExpenseService(fake_pool)
    with pytest.raises(ValidationError):
        await service.create_expense(
            household_id=HOUSEHOLD_ID,
            user_id=USER_ID,
            category_id=CATEGORY_ID,
            amount=Decimal("250.00"),
            transaction_date=date(2026, 4, 15),
        )
    fake_txn_repo.create_transaction.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_expense_rejects_non_positive_amount(
    fake_pool, fake_category_repo, fake_budget_repo, fake_txn_repo
):
    service = ExpenseService(fake_pool)
    with pytest.raises(ValidationError):
        await service.create_expense(
            household_id=HOUSEHOLD_ID,
            user_id=USER_ID,
            category_id=CATEGORY_ID,
            amount=Decimal("0"),
            transaction_date=date(2026, 4, 15),
        )


@pytest.mark.asyncio
async def test_delete_expense_deletes_group(
    fake_pool, fake_txn_repo
):
    """Deleting the manual expense should cascade-delete its transaction
    via the group, mirroring the income delete path."""
    service = ExpenseService(fake_pool)
    ok = await service.delete_expense(TXN_ID, HOUSEHOLD_ID)
    assert ok is True
    fake_txn_repo.delete_group.assert_awaited_once_with(GROUP_ID, HOUSEHOLD_ID)


@pytest.mark.asyncio
async def test_delete_expense_rejects_non_manual_source(
    fake_pool, fake_txn_repo
):
    """Receipt-sourced expense transactions must NOT be deletable through
    the manual-expense endpoint — those go through receipt void/correction
    flows (out of v1 scope)."""
    fake_txn_repo.get_transaction = AsyncMock(
        return_value={**_txn(), "source": "receipt"}
    )
    service = ExpenseService(fake_pool)
    with pytest.raises(ValidationError):
        await service.delete_expense(TXN_ID, HOUSEHOLD_ID)
    fake_txn_repo.delete_group.assert_not_awaited()
