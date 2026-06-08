"""Mock-based tests for HouseholdService.

Tests cover household creation (happy path, conflict, race), get/read,
and settings update with model_fields_set semantics.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import asyncpg
import pytest

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.services.household_service import HouseholdService


USER_ID = UUID("11111111-1111-1111-1111-111111111111")
HOUSEHOLD_ID = UUID("22222222-2222-2222-2222-222222222222")
MEMBER_ID = UUID("33333333-3333-3333-3333-333333333333")
SETTINGS_ID = UUID("44444444-4444-4444-4444-444444444444")
NOW = datetime.now(timezone.utc)


def _household():
    return {
        "id": HOUSEHOLD_ID,
        "name": "Test Household",
        "created_at": NOW,
        "updated_at": NOW,
    }


def _member():
    return {
        "id": MEMBER_ID,
        "household_id": HOUSEHOLD_ID,
        "user_id": USER_ID,
        "display_name": "Andreas",
        "role": "owner",
        "joined_at": NOW,
    }


def _settings(shift=False, cutoff=None):
    return {
        "id": SETTINGS_ID,
        "household_id": HOUSEHOLD_ID,
        "currency": "DKK",
        "shift_late_income": shift,
        "late_income_cutoff_day": cutoff,
        "created_at": NOW,
        "updated_at": NOW,
    }


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
def fake_repo(monkeypatch):
    repo = MagicMock()
    repo.get_member_by_user = AsyncMock(return_value=None)
    repo.create_household = AsyncMock(return_value=_household())
    repo.create_member = AsyncMock(return_value=_member())
    repo.create_settings = AsyncMock(return_value=_settings())
    repo.get_household = AsyncMock(return_value=_household())
    repo.get_settings = AsyncMock(return_value=_settings())
    repo.update_settings = AsyncMock(return_value=_settings())
    repo_class = MagicMock(return_value=repo)
    monkeypatch.setattr(
        "app.services.household_service.HouseholdRepository",
        repo_class,
    )
    return repo


# ── TestCreateHousehold ──


class TestCreateHousehold:
    @pytest.mark.asyncio
    async def test_happy_path(self, fake_pool, fake_repo):
        service = HouseholdService(fake_pool)
        result = await service.create_household(
            USER_ID, "My Household", "Andreas",
        )
        assert result["household"]["id"] == HOUSEHOLD_ID
        assert result["member"]["role"] == "owner"
        assert result["member"]["user_id"] == USER_ID
        assert result["settings"]["currency"] == "DKK"
        fake_repo.create_household.assert_awaited_once_with("My Household")
        fake_repo.create_member.assert_awaited_once_with(
            HOUSEHOLD_ID, USER_ID, "Andreas", role="owner",
        )
        fake_repo.create_settings.assert_awaited_once_with(HOUSEHOLD_ID)

    @pytest.mark.asyncio
    async def test_user_already_has_household(self, fake_pool, fake_repo):
        fake_repo.get_member_by_user.return_value = _member()
        service = HouseholdService(fake_pool)
        with pytest.raises(ConflictError):
            await service.create_household(USER_ID, "My Household", "Andreas")

    @pytest.mark.asyncio
    async def test_unique_violation_race(self, fake_pool, fake_repo):
        fake_repo.create_member.side_effect = asyncpg.UniqueViolationError(
            "", "", "", "", "", "", "",
        )
        service = HouseholdService(fake_pool)
        with pytest.raises(ConflictError):
            await service.create_household(USER_ID, "My Household", "Andreas")

    @pytest.mark.asyncio
    async def test_settings_use_defaults(self, fake_pool, fake_repo):
        service = HouseholdService(fake_pool)
        await service.create_household(USER_ID, "My Household", "Andreas")
        # create_settings called with only household_id — defaults come from DB
        fake_repo.create_settings.assert_awaited_once_with(HOUSEHOLD_ID)


# ── TestGetMyHousehold ──


class TestGetMyHousehold:
    @pytest.mark.asyncio
    async def test_found(self, fake_pool, fake_repo):
        service = HouseholdService(fake_pool)
        result = await service.get_my_household(HOUSEHOLD_ID)
        assert result["id"] == HOUSEHOLD_ID

    @pytest.mark.asyncio
    async def test_not_found(self, fake_pool, fake_repo):
        fake_repo.get_household.return_value = None
        service = HouseholdService(fake_pool)
        with pytest.raises(NotFoundError):
            await service.get_my_household(HOUSEHOLD_ID)


# ── TestGetSettings ──


class TestGetSettings:
    @pytest.mark.asyncio
    async def test_found(self, fake_pool, fake_repo):
        service = HouseholdService(fake_pool)
        result = await service.get_settings(HOUSEHOLD_ID)
        assert result["currency"] == "DKK"

    @pytest.mark.asyncio
    async def test_not_found(self, fake_pool, fake_repo):
        fake_repo.get_settings.return_value = None
        service = HouseholdService(fake_pool)
        with pytest.raises(NotFoundError):
            await service.get_settings(HOUSEHOLD_ID)


# ── TestUpdateSettings ──


class TestUpdateSettings:
    @pytest.mark.asyncio
    async def test_update_shift_with_cutoff(self, fake_pool, fake_repo):
        fake_repo.update_settings.return_value = _settings(shift=True, cutoff=25)
        service = HouseholdService(fake_pool)
        result = await service.update_settings(
            HOUSEHOLD_ID,
            fields_set={"shift_late_income", "late_income_cutoff_day"},
            shift_late_income=True,
            late_income_cutoff_day=25,
        )
        assert result["shift_late_income"] is True
        assert result["late_income_cutoff_day"] == 25

    @pytest.mark.asyncio
    async def test_enable_shift_cutoff_already_in_db(self, fake_pool, fake_repo):
        fake_repo.get_settings.return_value = _settings(shift=False, cutoff=20)
        fake_repo.update_settings.return_value = _settings(shift=True, cutoff=20)
        service = HouseholdService(fake_pool)
        result = await service.update_settings(
            HOUSEHOLD_ID,
            fields_set={"shift_late_income"},
            shift_late_income=True,
        )
        assert result["shift_late_income"] is True

    @pytest.mark.asyncio
    async def test_enable_shift_no_cutoff_anywhere(self, fake_pool, fake_repo):
        fake_repo.get_settings.return_value = _settings(shift=False, cutoff=None)
        service = HouseholdService(fake_pool)
        with pytest.raises(ValidationError, match="required"):
            await service.update_settings(
                HOUSEHOLD_ID,
                fields_set={"shift_late_income"},
                shift_late_income=True,
            )

    @pytest.mark.asyncio
    async def test_explicit_null_cutoff_while_shift_true(self, fake_pool, fake_repo):
        fake_repo.get_settings.return_value = _settings(shift=True, cutoff=20)
        service = HouseholdService(fake_pool)
        with pytest.raises(ValidationError, match="Cannot clear"):
            await service.update_settings(
                HOUSEHOLD_ID,
                fields_set={"late_income_cutoff_day"},
                late_income_cutoff_day=None,
            )

    @pytest.mark.asyncio
    async def test_explicit_null_cutoff_while_shift_false(self, fake_pool, fake_repo):
        fake_repo.get_settings.return_value = _settings(shift=False, cutoff=20)
        fake_repo.update_settings.return_value = _settings(shift=False, cutoff=None)
        service = HouseholdService(fake_pool)
        result = await service.update_settings(
            HOUSEHOLD_ID,
            fields_set={"late_income_cutoff_day"},
            late_income_cutoff_day=None,
        )
        assert result["late_income_cutoff_day"] is None

    @pytest.mark.asyncio
    async def test_omitted_cutoff_no_change(self, fake_pool, fake_repo):
        fake_repo.get_settings.return_value = _settings(shift=False, cutoff=15)
        fake_repo.update_settings.return_value = _settings(shift=False, cutoff=15)
        service = HouseholdService(fake_pool)
        await service.update_settings(
            HOUSEHOLD_ID,
            fields_set={"shift_late_income"},
            shift_late_income=False,
        )
        # Cutoff should be passed as sentinel ... (not updated)
        call_kwargs = fake_repo.update_settings.call_args.kwargs
        assert call_kwargs["late_income_cutoff_day"] is ...

    @pytest.mark.asyncio
    async def test_disable_shift(self, fake_pool, fake_repo):
        fake_repo.get_settings.return_value = _settings(shift=True, cutoff=20)
        fake_repo.update_settings.return_value = _settings(shift=False, cutoff=20)
        service = HouseholdService(fake_pool)
        result = await service.update_settings(
            HOUSEHOLD_ID,
            fields_set={"shift_late_income"},
            shift_late_income=False,
        )
        assert result["shift_late_income"] is False

    @pytest.mark.asyncio
    async def test_empty_fields_set(self, fake_pool, fake_repo):
        service = HouseholdService(fake_pool)
        with pytest.raises(ValidationError, match="At least one field"):
            await service.update_settings(
                HOUSEHOLD_ID,
                fields_set=set(),
            )

    @pytest.mark.asyncio
    async def test_not_found(self, fake_pool, fake_repo):
        fake_repo.get_settings.return_value = None
        service = HouseholdService(fake_pool)
        with pytest.raises(NotFoundError):
            await service.update_settings(
                HOUSEHOLD_ID,
                fields_set={"shift_late_income"},
                shift_late_income=False,
            )
