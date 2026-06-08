"""Mock-based tests for SearchService.

Tests cover parameter forwarding, pagination, empty results,
and cross-field range validation for both receipt and transaction search.
"""

from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

from app.core.exceptions import ValidationError
from app.services.search_service import SearchService


HOUSEHOLD_ID = UUID("11111111-1111-1111-1111-111111111111")
CATEGORY_ID = UUID("33333333-3333-3333-3333-333333333333")
NOW = datetime.now(timezone.utc)


def _receipt_row():
    return {
        "id": UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        "store_name": "Netto",
        "receipt_date": date(2026, 4, 10),
        "total_amount": Decimal("245.50"),
        "status": "posted",
        "created_at": NOW,
    }


def _transaction_row():
    return {
        "id": UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
        "type": "expense",
        "source": "receipt",
        "category_id": CATEGORY_ID,
        "category_name": "Dagligvarer",
        "amount": Decimal("245.50"),
        "description": "Netto purchase",
        "transaction_date": date(2026, 4, 10),
        "effective_date": date(2026, 4, 10),
        "store_name": "Netto",
        "created_at": NOW,
    }


@pytest.fixture
def fake_pool():
    pool = MagicMock()
    conn = MagicMock()
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=None)
    pool.acquire = MagicMock(return_value=ctx)
    return pool


# ── Receipt search ──


class TestSearchReceipts:
    @pytest.mark.asyncio
    async def test_no_filters(self, fake_pool):
        with patch("app.services.search_service.SearchRepository") as MockRepo:
            repo = MockRepo.return_value
            repo.search_receipts = AsyncMock(return_value=([], 0))

            service = SearchService(fake_pool)
            result = await service.search_receipts(household_id=HOUSEHOLD_ID)

            repo.search_receipts.assert_called_once_with(
                household_id=HOUSEHOLD_ID,
                merchant=None,
                category_id=None,
                date_from=None,
                date_to=None,
                amount_min=None,
                amount_max=None,
                status=None,
                limit=50,
                offset=0,
            )
            assert result == {"results": [], "total": 0}

    @pytest.mark.asyncio
    async def test_all_filters(self, fake_pool):
        with patch("app.services.search_service.SearchRepository") as MockRepo:
            repo = MockRepo.return_value
            repo.search_receipts = AsyncMock(return_value=([_receipt_row()], 1))

            service = SearchService(fake_pool)
            result = await service.search_receipts(
                household_id=HOUSEHOLD_ID,
                merchant="Netto",
                category_id=CATEGORY_ID,
                date_from=date(2026, 4, 1),
                date_to=date(2026, 4, 30),
                amount_min=Decimal("100"),
                amount_max=Decimal("500"),
                status="posted",
                limit=25,
                offset=10,
            )

            repo.search_receipts.assert_called_once_with(
                household_id=HOUSEHOLD_ID,
                merchant="Netto",
                category_id=CATEGORY_ID,
                date_from=date(2026, 4, 1),
                date_to=date(2026, 4, 30),
                amount_min=Decimal("100"),
                amount_max=Decimal("500"),
                status="posted",
                limit=25,
                offset=10,
            )
            assert result["total"] == 1
            assert len(result["results"]) == 1

    @pytest.mark.asyncio
    async def test_pagination(self, fake_pool):
        with patch("app.services.search_service.SearchRepository") as MockRepo:
            repo = MockRepo.return_value
            repo.search_receipts = AsyncMock(return_value=([], 0))

            service = SearchService(fake_pool)
            await service.search_receipts(
                household_id=HOUSEHOLD_ID, limit=10, offset=20
            )

            call_kwargs = repo.search_receipts.call_args.kwargs
            assert call_kwargs["limit"] == 10
            assert call_kwargs["offset"] == 20

    @pytest.mark.asyncio
    async def test_empty_results(self, fake_pool):
        with patch("app.services.search_service.SearchRepository") as MockRepo:
            repo = MockRepo.return_value
            repo.search_receipts = AsyncMock(return_value=([], 0))

            service = SearchService(fake_pool)
            result = await service.search_receipts(household_id=HOUSEHOLD_ID)

            assert result == {"results": [], "total": 0}

    @pytest.mark.asyncio
    async def test_date_range_validation(self, fake_pool):
        service = SearchService(fake_pool)
        with pytest.raises(ValidationError, match="date_from must be <= date_to"):
            await service.search_receipts(
                household_id=HOUSEHOLD_ID,
                date_from=date(2026, 4, 30),
                date_to=date(2026, 4, 1),
            )

    @pytest.mark.asyncio
    async def test_amount_range_validation(self, fake_pool):
        service = SearchService(fake_pool)
        with pytest.raises(ValidationError, match="amount_min must be <= amount_max"):
            await service.search_receipts(
                household_id=HOUSEHOLD_ID,
                amount_min=Decimal("500"),
                amount_max=Decimal("100"),
            )


# ── Transaction search ──


class TestSearchTransactions:
    @pytest.mark.asyncio
    async def test_no_filters(self, fake_pool):
        with patch("app.services.search_service.SearchRepository") as MockRepo:
            repo = MockRepo.return_value
            repo.search_transactions = AsyncMock(return_value=([], 0))

            service = SearchService(fake_pool)
            result = await service.search_transactions(household_id=HOUSEHOLD_ID)

            repo.search_transactions.assert_called_once_with(
                household_id=HOUSEHOLD_ID,
                category_id=None,
                type=None,
                source=None,
                date_from=None,
                date_to=None,
                amount_min=None,
                amount_max=None,
                limit=50,
                offset=0,
            )
            assert result == {"results": [], "total": 0}

    @pytest.mark.asyncio
    async def test_all_filters(self, fake_pool):
        with patch("app.services.search_service.SearchRepository") as MockRepo:
            repo = MockRepo.return_value
            repo.search_transactions = AsyncMock(
                return_value=([_transaction_row()], 1)
            )

            service = SearchService(fake_pool)
            result = await service.search_transactions(
                household_id=HOUSEHOLD_ID,
                category_id=CATEGORY_ID,
                type="expense",
                source="receipt",
                date_from=date(2026, 4, 1),
                date_to=date(2026, 4, 30),
                amount_min=Decimal("100"),
                amount_max=Decimal("500"),
                limit=25,
                offset=10,
            )

            repo.search_transactions.assert_called_once_with(
                household_id=HOUSEHOLD_ID,
                category_id=CATEGORY_ID,
                type="expense",
                source="receipt",
                date_from=date(2026, 4, 1),
                date_to=date(2026, 4, 30),
                amount_min=Decimal("100"),
                amount_max=Decimal("500"),
                limit=25,
                offset=10,
            )
            assert result["total"] == 1
            assert len(result["results"]) == 1

    @pytest.mark.asyncio
    async def test_pagination(self, fake_pool):
        with patch("app.services.search_service.SearchRepository") as MockRepo:
            repo = MockRepo.return_value
            repo.search_transactions = AsyncMock(return_value=([], 0))

            service = SearchService(fake_pool)
            await service.search_transactions(
                household_id=HOUSEHOLD_ID, limit=10, offset=20
            )

            call_kwargs = repo.search_transactions.call_args.kwargs
            assert call_kwargs["limit"] == 10
            assert call_kwargs["offset"] == 20

    @pytest.mark.asyncio
    async def test_with_results(self, fake_pool):
        row = _transaction_row()
        with patch("app.services.search_service.SearchRepository") as MockRepo:
            repo = MockRepo.return_value
            repo.search_transactions = AsyncMock(return_value=([row], 1))

            service = SearchService(fake_pool)
            result = await service.search_transactions(household_id=HOUSEHOLD_ID)

            assert result["total"] == 1
            assert result["results"][0]["store_name"] == "Netto"
            assert result["results"][0]["category_name"] == "Dagligvarer"

    @pytest.mark.asyncio
    async def test_date_range_validation(self, fake_pool):
        service = SearchService(fake_pool)
        with pytest.raises(ValidationError, match="date_from must be <= date_to"):
            await service.search_transactions(
                household_id=HOUSEHOLD_ID,
                date_from=date(2026, 4, 30),
                date_to=date(2026, 4, 1),
            )

    @pytest.mark.asyncio
    async def test_amount_range_validation(self, fake_pool):
        service = SearchService(fake_pool)
        with pytest.raises(ValidationError, match="amount_min must be <= amount_max"):
            await service.search_transactions(
                household_id=HOUSEHOLD_ID,
                amount_min=Decimal("500"),
                amount_max=Decimal("100"),
            )
