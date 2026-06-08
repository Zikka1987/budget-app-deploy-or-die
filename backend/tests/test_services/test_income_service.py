"""Mock-based tests for IncomeService.

Focus: response shape parity between create_income and update_income.

The mobile client compares the returned `budget_month` against its currently
selected month to detect late-income shifts, and reads `category_name` for
display. The create response always included both fields; the update
response did not, which broke edit-mode shift detection in the UI and
left a latent display gap. These tests pin the contract for both fields.
"""

from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest

from app.services.income_service import IncomeService


USER_ID = UUID("11111111-1111-1111-1111-111111111111")
HOUSEHOLD_ID = UUID("22222222-2222-2222-2222-222222222222")
CATEGORY_ID = UUID("33333333-3333-3333-3333-333333333333")
NEW_CATEGORY_ID = UUID("99999999-9999-9999-9999-999999999999")
TXN_ID = UUID("44444444-4444-4444-4444-444444444444")
GROUP_ID = UUID("55555555-5555-5555-5555-555555555555")
OLD_BM_ID = UUID("66666666-6666-6666-6666-666666666666")
NEW_BM_ID = UUID("77777777-7777-7777-7777-777777777777")
NOW = datetime.now(timezone.utc)

OLD_MONTH = date(2026, 4, 1)
NEW_MONTH = date(2026, 5, 1)


def _existing_txn(transaction_date: date = date(2026, 4, 15)) -> dict:
    return {
        "id": TXN_ID,
        "group_id": GROUP_ID,
        "household_id": HOUSEHOLD_ID,
        "type": "income",
        "category_id": CATEGORY_ID,
        "amount": Decimal("6400.00"),
        "transaction_date": transaction_date,
        "effective_date": transaction_date,
        "source": "manual_income",
        "posted_by": USER_ID,
        "budget_month_id": OLD_BM_ID,
        "description": None,
        "details": None,
        "savings_proposal_id": None,
        "created_at": NOW,
        "updated_at": NOW,
        "category_name": "Salary",
    }


def _bm_row(bm_id: UUID, month: date) -> dict:
    return {
        "id": bm_id,
        "household_id": HOUSEHOLD_ID,
        "month": month,
        "notes": None,
        "is_closed": False,
        "created_at": NOW,
        "updated_at": NOW,
    }


def _settings(shift: bool = False, cutoff: int | None = None) -> dict:
    return {
        "id": UUID("88888888-8888-8888-8888-888888888888"),
        "household_id": HOUSEHOLD_ID,
        "currency": "DKK",
        "shift_late_income": shift,
        "late_income_cutoff_day": cutoff,
        "created_at": NOW,
        "updated_at": NOW,
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
def fake_txn_repo(monkeypatch):
    repo = MagicMock()
    repo.get_transaction = AsyncMock(return_value=_existing_txn())
    # update_transaction default echoes back the existing row with the
    # incoming budget_month_id (or the existing one if not changed).
    monkeypatch.setattr(
        "app.services.income_service.TransactionRepository",
        lambda conn: repo,
    )
    return repo


@pytest.fixture
def fake_budget_repo(monkeypatch):
    repo = MagicMock()
    repo.get_month = AsyncMock(return_value=_bm_row(NEW_BM_ID, NEW_MONTH))
    repo.create_month = AsyncMock(return_value=_bm_row(NEW_BM_ID, NEW_MONTH))
    repo.get_month_by_id = AsyncMock()
    monkeypatch.setattr(
        "app.services.income_service.BudgetRepository",
        lambda conn: repo,
    )
    return repo


@pytest.fixture
def fake_household_repo(monkeypatch):
    repo = MagicMock()
    repo.get_settings = AsyncMock(return_value=_settings(shift=True, cutoff=25))
    monkeypatch.setattr(
        "app.services.income_service.HouseholdRepository",
        lambda conn: repo,
    )
    return repo


@pytest.fixture
def fake_category_repo(monkeypatch):
    repo = MagicMock()
    repo.get_by_id = AsyncMock()  # not invoked when category_id is unchanged
    monkeypatch.setattr(
        "app.services.income_service.CategoryRepository",
        lambda conn: repo,
    )
    return repo


# ── Tests ──


@pytest.mark.asyncio
async def test_update_income_no_date_change_includes_existing_budget_month_and_category_name(
    fake_pool, fake_txn_repo, fake_budget_repo
):
    """Editing only the amount must still return both budget_month (the
    existing one) and category_name (also the existing one)."""
    # Updated row preserves the original budget_month_id (no date change).
    updated = _existing_txn()
    updated["amount"] = Decimal("6300.00")
    fake_txn_repo.update_transaction = AsyncMock(return_value=updated)
    fake_budget_repo.get_month_by_id = AsyncMock(
        return_value=_bm_row(OLD_BM_ID, OLD_MONTH)
    )

    service = IncomeService(fake_pool)
    result = await service.update_income(
        txn_id=TXN_ID,
        household_id=HOUSEHOLD_ID,
        amount=Decimal("6300.00"),
    )

    assert result["budget_month"] == OLD_MONTH
    assert result["category_name"] == "Salary"
    # The lookup must use the budget_month_id from the post-update row.
    fake_budget_repo.get_month_by_id.assert_awaited_once_with(OLD_BM_ID, HOUSEHOLD_ID)


@pytest.mark.asyncio
@pytest.mark.usefixtures("fake_household_repo")
async def test_update_income_with_month_shift_includes_new_budget_month(
    fake_pool, fake_txn_repo, fake_budget_repo
):
    """Changing transaction_date enough to land in a new month must surface
    the new month in the response so the client can show the shift alert.
    category_name is still the existing one (category_id unchanged)."""
    # Updated row reflects the new budget_month_id assigned by the service.
    updated = _existing_txn(transaction_date=date(2026, 5, 20))
    updated["budget_month_id"] = NEW_BM_ID
    fake_txn_repo.update_transaction = AsyncMock(return_value=updated)
    fake_budget_repo.get_month_by_id = AsyncMock(
        return_value=_bm_row(NEW_BM_ID, NEW_MONTH)
    )

    service = IncomeService(fake_pool)
    result = await service.update_income(
        txn_id=TXN_ID,
        household_id=HOUSEHOLD_ID,
        transaction_date=date(2026, 5, 20),
    )

    assert result["budget_month"] == NEW_MONTH
    assert result["category_name"] == "Salary"
    fake_budget_repo.get_month_by_id.assert_awaited_once_with(NEW_BM_ID, HOUSEHOLD_ID)


@pytest.mark.asyncio
async def test_update_income_with_category_change_uses_new_category_name(
    fake_pool, fake_txn_repo, fake_budget_repo, fake_category_repo
):
    """Changing the category_id must put the NEW category_name on the
    response (reusing the name fetched during validation, no extra DB read)."""
    fake_category_repo.get_by_id = AsyncMock(
        return_value={
            "id": NEW_CATEGORY_ID,
            "household_id": HOUSEHOLD_ID,
            "type": "income",
            "name": "Bonus",
            "icon": None,
            "sort_order": 0,
            "archived_at": None,
            "created_at": NOW,
            "updated_at": NOW,
        }
    )
    updated = _existing_txn()
    updated["category_id"] = NEW_CATEGORY_ID
    fake_txn_repo.update_transaction = AsyncMock(return_value=updated)
    fake_budget_repo.get_month_by_id = AsyncMock(
        return_value=_bm_row(OLD_BM_ID, OLD_MONTH)
    )

    service = IncomeService(fake_pool)
    result = await service.update_income(
        txn_id=TXN_ID,
        household_id=HOUSEHOLD_ID,
        category_id=NEW_CATEGORY_ID,
    )

    assert result["category_name"] == "Bonus"
    assert result["budget_month"] == OLD_MONTH
