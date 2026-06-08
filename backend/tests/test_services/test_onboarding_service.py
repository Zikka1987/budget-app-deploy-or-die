"""Mock-based tests for OnboardingService."""

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest

from app.services.onboarding_service import OnboardingService


USER_ID = UUID("11111111-1111-1111-1111-111111111111")
HOUSEHOLD_ID = UUID("22222222-2222-2222-2222-222222222222")


@pytest.fixture
def fake_pool():
    pool = MagicMock()
    conn = MagicMock()
    acq_ctx = MagicMock()
    acq_ctx.__aenter__ = AsyncMock(return_value=conn)
    acq_ctx.__aexit__ = AsyncMock(return_value=None)
    pool.acquire = MagicMock(return_value=acq_ctx)
    return pool


@pytest.fixture
def fake_repo(monkeypatch):
    repo = MagicMock()
    repo.get_household_id_for_user = AsyncMock(return_value=None)
    repo.count_active_categories_by_type = AsyncMock(return_value={})
    repo_class = MagicMock(return_value=repo)
    monkeypatch.setattr(
        "app.services.onboarding_service.OnboardingRepository",
        repo_class,
    )
    return repo


class TestGetStatus:
    @pytest.mark.asyncio
    async def test_no_household(self, fake_pool, fake_repo):
        fake_repo.get_household_id_for_user.return_value = None
        service = OnboardingService(fake_pool)
        status = await service.get_status(USER_ID)
        assert status["has_household"] is False
        assert status["has_income_category"] is False
        assert status["has_expense_category"] is False
        assert status["has_savings_category"] is False
        assert status["is_ready"] is False

    @pytest.mark.asyncio
    async def test_household_no_categories(self, fake_pool, fake_repo):
        fake_repo.get_household_id_for_user.return_value = HOUSEHOLD_ID
        fake_repo.count_active_categories_by_type.return_value = {}
        service = OnboardingService(fake_pool)
        status = await service.get_status(USER_ID)
        assert status["has_household"] is True
        assert status["has_income_category"] is False
        assert status["has_expense_category"] is False
        assert status["is_ready"] is False

    @pytest.mark.asyncio
    async def test_income_only(self, fake_pool, fake_repo):
        fake_repo.get_household_id_for_user.return_value = HOUSEHOLD_ID
        fake_repo.count_active_categories_by_type.return_value = {"income": 1}
        service = OnboardingService(fake_pool)
        status = await service.get_status(USER_ID)
        assert status["has_income_category"] is True
        assert status["has_expense_category"] is False
        assert status["is_ready"] is False

    @pytest.mark.asyncio
    async def test_income_and_expense(self, fake_pool, fake_repo):
        fake_repo.get_household_id_for_user.return_value = HOUSEHOLD_ID
        fake_repo.count_active_categories_by_type.return_value = {
            "income": 2, "expense": 3,
        }
        service = OnboardingService(fake_pool)
        status = await service.get_status(USER_ID)
        assert status["has_income_category"] is True
        assert status["has_expense_category"] is True
        assert status["has_savings_category"] is False
        assert status["is_ready"] is True

    @pytest.mark.asyncio
    async def test_all_categories(self, fake_pool, fake_repo):
        fake_repo.get_household_id_for_user.return_value = HOUSEHOLD_ID
        fake_repo.count_active_categories_by_type.return_value = {
            "income": 1, "expense": 2, "savings": 1,
        }
        service = OnboardingService(fake_pool)
        status = await service.get_status(USER_ID)
        assert status["has_income_category"] is True
        assert status["has_expense_category"] is True
        assert status["has_savings_category"] is True
        assert status["is_ready"] is True

    @pytest.mark.asyncio
    async def test_archived_categories_not_counted(self, fake_pool, fake_repo):
        """The repo query filters by archived_at IS NULL, so archived
        categories are never counted. If the only expense category is
        archived, the count dict won't include 'expense' at all."""
        fake_repo.get_household_id_for_user.return_value = HOUSEHOLD_ID
        # Repo returns no expense count (archived ones filtered out at SQL level)
        fake_repo.count_active_categories_by_type.return_value = {"income": 1}
        service = OnboardingService(fake_pool)
        status = await service.get_status(USER_ID)
        assert status["has_expense_category"] is False
        assert status["is_ready"] is False
