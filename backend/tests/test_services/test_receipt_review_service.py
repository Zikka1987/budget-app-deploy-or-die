"""Mock-based tests for ReceiptReviewService.

Tests cover the update_item and confirm_receipt flows: status gates,
category validation, requires_review computation, idempotency, atomic
posting, and error paths.
"""

from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.services.receipt_review_service import ReceiptReviewService


HOUSEHOLD_ID = UUID("11111111-1111-1111-1111-111111111111")
OTHER_HOUSEHOLD_ID = UUID("99999999-9999-9999-9999-999999999999")
USER_ID = UUID("22222222-2222-2222-2222-222222222222")
RECEIPT_ID = UUID("33333333-3333-3333-3333-333333333333")
ITEM_ID_1 = UUID("44444444-4444-4444-4444-444444444444")
ITEM_ID_2 = UUID("55555555-5555-5555-5555-555555555555")
ITEM_ID_3 = UUID("66666666-6666-6666-6666-666666666666")
CAT_EXPENSE_A = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
CAT_EXPENSE_B = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
CAT_INCOME = UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
GROUP_ID = UUID("dddddddd-dddd-dddd-dddd-dddddddddddd")
BUDGET_MONTH_ID = UUID("eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee")
NOW = datetime.now(timezone.utc)


def _receipt(status="ocr_complete", receipt_date=date(2026, 4, 5),
             total_amount=Decimal("100.00"), store_name="Netto"):
    return {
        "id": RECEIPT_ID,
        "household_id": HOUSEHOLD_ID,
        "uploaded_by": USER_ID,
        "status": status,
        "storage_path": "path/to/receipt",
        "file_name": "receipt.jpg",
        "mime_type": "image/jpeg",
        "store_name": store_name,
        "receipt_date": receipt_date,
        "total_amount": total_amount,
        "ocr_raw_text": None,
        "ocr_provider": "anthropic",
        "ocr_confidence": Decimal("0.95"),
        "error_message": None,
        "created_at": NOW,
        "updated_at": NOW,
    }


def _item(item_id=ITEM_ID_1, cat_id=CAT_EXPENSE_A, excluded=False,
          total_price=Decimal("50.00"), description="Maelk",
          line_number=1, suggested_cat_id=None):
    return {
        "id": item_id,
        "receipt_id": RECEIPT_ID,
        "line_number": line_number,
        "description": description,
        "quantity": Decimal("1"),
        "unit_price": total_price,
        "total_price": total_price,
        "suggested_category_id": suggested_cat_id,
        "confidence": 0.9,
        "requires_review": False,
        "user_confirmed_category_id": cat_id,
        "is_excluded": excluded,
        "created_at": NOW,
        "updated_at": NOW,
    }


def _enriched_item(**overrides):
    """Item dict with category name columns (as returned by get_item_with_category_names)."""
    base = _item(**{k: v for k, v in overrides.items()
                    if k in _item.__code__.co_varnames})
    base["suggested_category_name"] = None
    base["user_confirmed_category_name"] = "Groceries"
    base.update({k: v for k, v in overrides.items()
                 if k not in _item.__code__.co_varnames})
    return base


def _category(cat_id=CAT_EXPENSE_A, cat_type="expense", name="Groceries",
              archived=False):
    return {
        "id": cat_id,
        "household_id": HOUSEHOLD_ID,
        "type": cat_type,
        "name": name,
        "icon": None,
        "sort_order": 0,
        "archived_at": NOW if archived else None,
        "created_at": NOW,
        "updated_at": NOW,
    }


# ── Fixtures ──


@pytest.fixture
def fake_pool():
    pool = MagicMock()
    conn = MagicMock()
    # conn.transaction() must return an async context manager
    txn_ctx = MagicMock()
    txn_ctx.__aenter__ = AsyncMock(return_value=None)
    txn_ctx.__aexit__ = AsyncMock(return_value=None)
    conn.transaction = MagicMock(return_value=txn_ctx)
    # pool.acquire() must return an async context manager yielding conn
    acq_ctx = MagicMock()
    acq_ctx.__aenter__ = AsyncMock(return_value=conn)
    acq_ctx.__aexit__ = AsyncMock(return_value=None)
    pool.acquire = MagicMock(return_value=acq_ctx)
    return pool


@pytest.fixture
def fake_receipt_repo(monkeypatch):
    repo = MagicMock()
    repo.get_by_id = AsyncMock()
    repo.get_item_by_id = AsyncMock()
    repo.update_item_user_fields = AsyncMock()
    repo.get_item_with_category_names = AsyncMock()
    repo.list_items_by_receipt = AsyncMock(return_value=[])
    repo.update_status = AsyncMock()
    repo_class = MagicMock(return_value=repo)
    monkeypatch.setattr(
        "app.services.receipt_review_service.ReceiptRepository",
        repo_class,
    )
    return repo


@pytest.fixture
def fake_cat_repo(monkeypatch):
    repo = MagicMock()
    repo.get_by_id = AsyncMock()
    repo_class = MagicMock(return_value=repo)
    monkeypatch.setattr(
        "app.services.receipt_review_service.CategoryRepository",
        repo_class,
    )
    return repo


@pytest.fixture
def fake_txn_repo(monkeypatch):
    repo = MagicMock()
    repo.get_group_by_idempotency_key = AsyncMock(return_value=None)
    repo.create_group = AsyncMock()
    repo.create_transaction = AsyncMock()
    repo.count_by_group = AsyncMock(return_value=0)
    repo_class = MagicMock(return_value=repo)
    monkeypatch.setattr(
        "app.services.receipt_review_service.TransactionRepository",
        repo_class,
    )
    return repo


@pytest.fixture
def fake_budget_repo(monkeypatch):
    repo = MagicMock()
    repo.get_month = AsyncMock()
    repo.create_month = AsyncMock()
    repo_class = MagicMock(return_value=repo)
    monkeypatch.setattr(
        "app.services.receipt_review_service.BudgetRepository",
        repo_class,
    )
    return repo


# ── TestUpdateItem ──


class TestUpdateItem:
    @pytest.mark.asyncio
    async def test_set_category(
        self, fake_pool, fake_receipt_repo, fake_cat_repo
    ):
        fake_receipt_repo.get_by_id.return_value = _receipt()
        fake_receipt_repo.get_item_by_id.return_value = _item(cat_id=None)
        fake_cat_repo.get_by_id.return_value = _category()
        fake_receipt_repo.update_item_user_fields.return_value = _item()
        fake_receipt_repo.get_item_with_category_names.return_value = (
            _enriched_item()
        )

        service = ReceiptReviewService(fake_pool)
        result = await service.update_item(
            RECEIPT_ID, HOUSEHOLD_ID, ITEM_ID_1,
            fields_set={"user_confirmed_category_id"},
            user_confirmed_category_id=CAT_EXPENSE_A,
        )
        assert result["user_confirmed_category_name"] == "Groceries"

        # requires_review should be False (category confirmed)
        call_kwargs = fake_receipt_repo.update_item_user_fields.call_args
        assert call_kwargs.kwargs.get("requires_review") is False or \
            call_kwargs[1].get("requires_review") is False

    @pytest.mark.asyncio
    async def test_toggle_excluded(
        self, fake_pool, fake_receipt_repo, fake_cat_repo
    ):
        fake_receipt_repo.get_by_id.return_value = _receipt()
        fake_receipt_repo.get_item_by_id.return_value = _item(excluded=False)
        fake_receipt_repo.update_item_user_fields.return_value = _item(
            excluded=True
        )
        fake_receipt_repo.get_item_with_category_names.return_value = (
            _enriched_item()
        )

        service = ReceiptReviewService(fake_pool)
        await service.update_item(
            RECEIPT_ID, HOUSEHOLD_ID, ITEM_ID_1,
            fields_set={"is_excluded"},
            is_excluded=True,
        )

        call_kwargs = fake_receipt_repo.update_item_user_fields.call_args[1]
        assert call_kwargs["is_excluded"] is True
        assert call_kwargs["requires_review"] is False

    @pytest.mark.asyncio
    async def test_clear_category(
        self, fake_pool, fake_receipt_repo, fake_cat_repo
    ):
        fake_receipt_repo.get_by_id.return_value = _receipt()
        fake_receipt_repo.get_item_by_id.return_value = _item(
            cat_id=CAT_EXPENSE_A, excluded=False
        )
        fake_receipt_repo.update_item_user_fields.return_value = _item(
            cat_id=None
        )
        fake_receipt_repo.get_item_with_category_names.return_value = (
            _enriched_item(cat_id=None)
        )

        service = ReceiptReviewService(fake_pool)
        await service.update_item(
            RECEIPT_ID, HOUSEHOLD_ID, ITEM_ID_1,
            fields_set={"user_confirmed_category_id"},
            user_confirmed_category_id=None,
        )

        call_kwargs = fake_receipt_repo.update_item_user_fields.call_args[1]
        assert call_kwargs["requires_review"] is True

    @pytest.mark.asyncio
    async def test_unexclude_without_category(
        self, fake_pool, fake_receipt_repo, fake_cat_repo
    ):
        fake_receipt_repo.get_by_id.return_value = _receipt()
        fake_receipt_repo.get_item_by_id.return_value = _item(
            cat_id=None, excluded=True
        )
        fake_receipt_repo.update_item_user_fields.return_value = _item(
            cat_id=None, excluded=False
        )
        fake_receipt_repo.get_item_with_category_names.return_value = (
            _enriched_item(cat_id=None)
        )

        service = ReceiptReviewService(fake_pool)
        await service.update_item(
            RECEIPT_ID, HOUSEHOLD_ID, ITEM_ID_1,
            fields_set={"is_excluded"},
            is_excluded=False,
        )

        call_kwargs = fake_receipt_repo.update_item_user_fields.call_args[1]
        assert call_kwargs["requires_review"] is True

    @pytest.mark.asyncio
    async def test_receipt_not_found(
        self, fake_pool, fake_receipt_repo, fake_cat_repo
    ):
        fake_receipt_repo.get_by_id.return_value = None

        service = ReceiptReviewService(fake_pool)
        with pytest.raises(NotFoundError):
            await service.update_item(
                RECEIPT_ID, HOUSEHOLD_ID, ITEM_ID_1,
                fields_set={"is_excluded"},
                is_excluded=True,
            )

    @pytest.mark.asyncio
    async def test_wrong_status_posted(
        self, fake_pool, fake_receipt_repo, fake_cat_repo
    ):
        fake_receipt_repo.get_by_id.return_value = _receipt(status="posted")

        service = ReceiptReviewService(fake_pool)
        with pytest.raises(ConflictError, match="posted"):
            await service.update_item(
                RECEIPT_ID, HOUSEHOLD_ID, ITEM_ID_1,
                fields_set={"is_excluded"},
                is_excluded=True,
            )

    @pytest.mark.asyncio
    async def test_wrong_status_uploaded(
        self, fake_pool, fake_receipt_repo, fake_cat_repo
    ):
        fake_receipt_repo.get_by_id.return_value = _receipt(status="uploaded")

        service = ReceiptReviewService(fake_pool)
        with pytest.raises(ConflictError, match="uploaded"):
            await service.update_item(
                RECEIPT_ID, HOUSEHOLD_ID, ITEM_ID_1,
                fields_set={"is_excluded"},
                is_excluded=True,
            )

    @pytest.mark.asyncio
    async def test_item_not_found(
        self, fake_pool, fake_receipt_repo, fake_cat_repo
    ):
        fake_receipt_repo.get_by_id.return_value = _receipt()
        fake_receipt_repo.get_item_by_id.return_value = None

        service = ReceiptReviewService(fake_pool)
        with pytest.raises(NotFoundError):
            await service.update_item(
                RECEIPT_ID, HOUSEHOLD_ID, ITEM_ID_1,
                fields_set={"user_confirmed_category_id"},
                user_confirmed_category_id=CAT_EXPENSE_A,
            )

    @pytest.mark.asyncio
    async def test_category_not_found(
        self, fake_pool, fake_receipt_repo, fake_cat_repo
    ):
        fake_receipt_repo.get_by_id.return_value = _receipt()
        fake_receipt_repo.get_item_by_id.return_value = _item(cat_id=None)
        fake_cat_repo.get_by_id.return_value = None

        service = ReceiptReviewService(fake_pool)
        with pytest.raises(NotFoundError, match="Category"):
            await service.update_item(
                RECEIPT_ID, HOUSEHOLD_ID, ITEM_ID_1,
                fields_set={"user_confirmed_category_id"},
                user_confirmed_category_id=CAT_EXPENSE_A,
            )

    @pytest.mark.asyncio
    async def test_category_wrong_type(
        self, fake_pool, fake_receipt_repo, fake_cat_repo
    ):
        fake_receipt_repo.get_by_id.return_value = _receipt()
        fake_receipt_repo.get_item_by_id.return_value = _item(cat_id=None)
        fake_cat_repo.get_by_id.return_value = _category(
            cat_id=CAT_INCOME, cat_type="income", name="Salary"
        )

        service = ReceiptReviewService(fake_pool)
        with pytest.raises(ValidationError, match="income"):
            await service.update_item(
                RECEIPT_ID, HOUSEHOLD_ID, ITEM_ID_1,
                fields_set={"user_confirmed_category_id"},
                user_confirmed_category_id=CAT_INCOME,
            )

    @pytest.mark.asyncio
    async def test_category_archived(
        self, fake_pool, fake_receipt_repo, fake_cat_repo
    ):
        fake_receipt_repo.get_by_id.return_value = _receipt()
        fake_receipt_repo.get_item_by_id.return_value = _item(cat_id=None)
        fake_cat_repo.get_by_id.return_value = _category(archived=True)

        service = ReceiptReviewService(fake_pool)
        with pytest.raises(ValidationError, match="archived"):
            await service.update_item(
                RECEIPT_ID, HOUSEHOLD_ID, ITEM_ID_1,
                fields_set={"user_confirmed_category_id"},
                user_confirmed_category_id=CAT_EXPENSE_A,
            )

    @pytest.mark.asyncio
    async def test_no_fields_provided(
        self, fake_pool, fake_receipt_repo, fake_cat_repo
    ):
        service = ReceiptReviewService(fake_pool)
        with pytest.raises(ValidationError, match="At least one"):
            await service.update_item(
                RECEIPT_ID, HOUSEHOLD_ID, ITEM_ID_1,
                fields_set=set(),
            )


# ── TestConfirmReceipt ──


class TestConfirmReceipt:
    def _setup_happy_path(
        self, fake_receipt_repo, fake_cat_repo, fake_txn_repo,
        fake_budget_repo, items=None, receipt_kwargs=None,
    ):
        """Wire up mocks for a successful confirm."""
        fake_receipt_repo.get_by_id.return_value = _receipt(
            **(receipt_kwargs or {})
        )
        if items is None:
            items = [
                _item(ITEM_ID_1, CAT_EXPENSE_A, total_price=Decimal("50.00"),
                      description="Maelk", line_number=1),
                _item(ITEM_ID_2, CAT_EXPENSE_B, total_price=Decimal("45.00"),
                      description="Vanish", line_number=2),
            ]
        fake_receipt_repo.list_items_by_receipt.return_value = items
        fake_cat_repo.get_by_id.side_effect = lambda cid, hid: _category(
            cat_id=cid, name=f"Cat-{cid}"
        )
        fake_receipt_repo.update_status.return_value = _receipt(
            status="reviewed"
        )
        fake_budget_repo.get_month.return_value = {
            "id": BUDGET_MONTH_ID, "household_id": HOUSEHOLD_ID,
            "month": date(2026, 4, 1),
        }
        fake_txn_repo.create_group.return_value = {
            "id": GROUP_ID, "household_id": HOUSEHOLD_ID,
            "source": "receipt", "idempotency_key": f"receipt:{RECEIPT_ID}",
            "created_by": USER_ID, "receipt_id": RECEIPT_ID,
            "description": "Receipt from Netto", "created_at": NOW,
        }
        fake_txn_repo.create_transaction.return_value = {
            "id": UUID("ffffffff-ffff-ffff-ffff-ffffffffffff"),
        }

    @pytest.mark.asyncio
    async def test_happy_path(
        self, fake_pool, fake_receipt_repo, fake_cat_repo, fake_txn_repo,
        fake_budget_repo,
    ):
        self._setup_happy_path(
            fake_receipt_repo, fake_cat_repo, fake_txn_repo, fake_budget_repo,
        )

        service = ReceiptReviewService(fake_pool)
        result = await service.confirm_receipt(
            RECEIPT_ID, HOUSEHOLD_ID, USER_ID,
        )

        assert result["transaction_group_id"] == GROUP_ID
        assert result["transactions_created"] == 2
        assert result["status"] == "posted"
        assert fake_txn_repo.create_transaction.call_count == 2

    @pytest.mark.asyncio
    async def test_excluded_items_skipped(
        self, fake_pool, fake_receipt_repo, fake_cat_repo, fake_txn_repo,
        fake_budget_repo,
    ):
        items = [
            _item(ITEM_ID_1, CAT_EXPENSE_A, total_price=Decimal("50.00")),
            _item(ITEM_ID_2, CAT_EXPENSE_B, total_price=Decimal("30.00")),
            _item(ITEM_ID_3, CAT_EXPENSE_A, total_price=Decimal("20.00"),
                  excluded=True, description="Excluded"),
        ]
        self._setup_happy_path(
            fake_receipt_repo, fake_cat_repo, fake_txn_repo, fake_budget_repo,
            items=items,
        )

        service = ReceiptReviewService(fake_pool)
        result = await service.confirm_receipt(
            RECEIPT_ID, HOUSEHOLD_ID, USER_ID,
        )

        assert result["transactions_created"] == 2

    @pytest.mark.asyncio
    async def test_items_grouped_by_category(
        self, fake_pool, fake_receipt_repo, fake_cat_repo, fake_txn_repo,
        fake_budget_repo,
    ):
        items = [
            _item(ITEM_ID_1, CAT_EXPENSE_A, total_price=Decimal("25.00"),
                  description="Maelk", line_number=1),
            _item(ITEM_ID_2, CAT_EXPENSE_A, total_price=Decimal("15.00"),
                  description="Broed", line_number=2),
            _item(ITEM_ID_3, CAT_EXPENSE_B, total_price=Decimal("45.00"),
                  description="Vanish", line_number=3),
        ]
        self._setup_happy_path(
            fake_receipt_repo, fake_cat_repo, fake_txn_repo, fake_budget_repo,
            items=items, receipt_kwargs={"total_amount": Decimal("85.00")},
        )

        service = ReceiptReviewService(fake_pool)
        result = await service.confirm_receipt(
            RECEIPT_ID, HOUSEHOLD_ID, USER_ID,
        )

        # 2 groups: A (25+15=40) and B (45)
        assert result["transactions_created"] == 2
        assert fake_txn_repo.create_transaction.call_count == 2

    @pytest.mark.asyncio
    async def test_idempotent_duplicate(
        self, fake_pool, fake_receipt_repo, fake_cat_repo, fake_txn_repo,
        fake_budget_repo,
    ):
        fake_receipt_repo.get_by_id.return_value = _receipt(status="posted")
        fake_txn_repo.get_group_by_idempotency_key.return_value = {
            "id": GROUP_ID, "household_id": HOUSEHOLD_ID,
            "source": "receipt",
            "idempotency_key": f"receipt:{RECEIPT_ID}",
            "created_by": USER_ID, "receipt_id": RECEIPT_ID,
            "description": "Receipt from Netto", "created_at": NOW,
        }
        fake_txn_repo.count_by_group.return_value = 2

        service = ReceiptReviewService(fake_pool)
        result = await service.confirm_receipt(
            RECEIPT_ID, HOUSEHOLD_ID, USER_ID,
        )

        assert result["transaction_group_id"] == GROUP_ID
        assert result["transactions_created"] == 2
        assert result["status"] == "posted"
        assert result["total_mismatch"] is False
        # No new transactions created
        assert fake_txn_repo.create_group.call_count == 0
        assert fake_txn_repo.create_transaction.call_count == 0

    @pytest.mark.asyncio
    async def test_receipt_not_found(
        self, fake_pool, fake_receipt_repo, fake_cat_repo, fake_txn_repo,
        fake_budget_repo,
    ):
        fake_receipt_repo.get_by_id.return_value = None

        service = ReceiptReviewService(fake_pool)
        with pytest.raises(NotFoundError):
            await service.confirm_receipt(
                RECEIPT_ID, HOUSEHOLD_ID, USER_ID,
            )

    @pytest.mark.asyncio
    async def test_wrong_status(
        self, fake_pool, fake_receipt_repo, fake_cat_repo, fake_txn_repo,
        fake_budget_repo,
    ):
        fake_receipt_repo.get_by_id.return_value = _receipt(status="uploaded")

        service = ReceiptReviewService(fake_pool)
        with pytest.raises(ConflictError, match="uploaded"):
            await service.confirm_receipt(
                RECEIPT_ID, HOUSEHOLD_ID, USER_ID,
            )

    @pytest.mark.asyncio
    async def test_unresolved_item_fails_before_status_change(
        self, fake_pool, fake_receipt_repo, fake_cat_repo, fake_txn_repo,
        fake_budget_repo,
    ):
        items = [
            _item(ITEM_ID_1, cat_id=None, description="No category"),
        ]
        fake_receipt_repo.get_by_id.return_value = _receipt()
        fake_receipt_repo.list_items_by_receipt.return_value = items

        service = ReceiptReviewService(fake_pool)
        with pytest.raises(ValidationError, match="confirmed category"):
            await service.confirm_receipt(
                RECEIPT_ID, HOUSEHOLD_ID, USER_ID,
            )

        # update_status must NOT have been called
        fake_receipt_repo.update_status.assert_not_called()

    @pytest.mark.asyncio
    async def test_all_items_excluded(
        self, fake_pool, fake_receipt_repo, fake_cat_repo, fake_txn_repo,
        fake_budget_repo,
    ):
        items = [
            _item(ITEM_ID_1, CAT_EXPENSE_A, excluded=True),
            _item(ITEM_ID_2, CAT_EXPENSE_B, excluded=True),
        ]
        fake_receipt_repo.get_by_id.return_value = _receipt()
        fake_receipt_repo.list_items_by_receipt.return_value = items

        service = ReceiptReviewService(fake_pool)
        with pytest.raises(ValidationError, match="all items are excluded"):
            await service.confirm_receipt(
                RECEIPT_ID, HOUSEHOLD_ID, USER_ID,
            )

    @pytest.mark.asyncio
    async def test_archived_category_at_confirm(
        self, fake_pool, fake_receipt_repo, fake_cat_repo, fake_txn_repo,
        fake_budget_repo,
    ):
        items = [_item(ITEM_ID_1, CAT_EXPENSE_A)]
        fake_receipt_repo.get_by_id.return_value = _receipt()
        fake_receipt_repo.list_items_by_receipt.return_value = items
        fake_cat_repo.get_by_id.return_value = _category(archived=True)

        service = ReceiptReviewService(fake_pool)
        with pytest.raises(ValidationError, match="archived"):
            await service.confirm_receipt(
                RECEIPT_ID, HOUSEHOLD_ID, USER_ID,
            )

    @pytest.mark.asyncio
    async def test_category_wrong_type_at_confirm(
        self, fake_pool, fake_receipt_repo, fake_cat_repo, fake_txn_repo,
        fake_budget_repo,
    ):
        items = [_item(ITEM_ID_1, CAT_INCOME)]
        fake_receipt_repo.get_by_id.return_value = _receipt()
        fake_receipt_repo.list_items_by_receipt.return_value = items
        fake_cat_repo.get_by_id.return_value = _category(
            cat_id=CAT_INCOME, cat_type="income", name="Salary"
        )

        service = ReceiptReviewService(fake_pool)
        with pytest.raises(ValidationError, match="income"):
            await service.confirm_receipt(
                RECEIPT_ID, HOUSEHOLD_ID, USER_ID,
            )

    @pytest.mark.asyncio
    async def test_no_receipt_date_no_override(
        self, fake_pool, fake_receipt_repo, fake_cat_repo, fake_txn_repo,
        fake_budget_repo,
    ):
        items = [_item(ITEM_ID_1, CAT_EXPENSE_A)]
        fake_receipt_repo.get_by_id.return_value = _receipt(receipt_date=None)
        fake_receipt_repo.list_items_by_receipt.return_value = items
        fake_cat_repo.get_by_id.return_value = _category()

        service = ReceiptReviewService(fake_pool)
        with pytest.raises(ValidationError, match="no date"):
            await service.confirm_receipt(
                RECEIPT_ID, HOUSEHOLD_ID, USER_ID,
            )

    @pytest.mark.asyncio
    async def test_no_receipt_date_with_override(
        self, fake_pool, fake_receipt_repo, fake_cat_repo, fake_txn_repo,
        fake_budget_repo,
    ):
        items = [_item(ITEM_ID_1, CAT_EXPENSE_A)]
        self._setup_happy_path(
            fake_receipt_repo, fake_cat_repo, fake_txn_repo, fake_budget_repo,
            items=items,
            receipt_kwargs={"receipt_date": None, "total_amount": Decimal("50.00")},
        )

        service = ReceiptReviewService(fake_pool)
        result = await service.confirm_receipt(
            RECEIPT_ID, HOUSEHOLD_ID, USER_ID,
            transaction_date_override=date(2026, 3, 15),
        )

        assert result["status"] == "posted"
        # Verify the override date was used
        call_args = fake_txn_repo.create_transaction.call_args
        assert call_args[1]["transaction_date"] == date(2026, 3, 15)

    @pytest.mark.asyncio
    async def test_receipt_date_takes_priority(
        self, fake_pool, fake_receipt_repo, fake_cat_repo, fake_txn_repo,
        fake_budget_repo,
    ):
        items = [_item(ITEM_ID_1, CAT_EXPENSE_A)]
        self._setup_happy_path(
            fake_receipt_repo, fake_cat_repo, fake_txn_repo, fake_budget_repo,
            items=items,
        )

        service = ReceiptReviewService(fake_pool)
        await service.confirm_receipt(
            RECEIPT_ID, HOUSEHOLD_ID, USER_ID,
            transaction_date_override=date(2026, 1, 1),
        )

        # receipt_date (April 5) should be used, not the override (Jan 1)
        call_args = fake_txn_repo.create_transaction.call_args
        assert call_args[1]["transaction_date"] == date(2026, 4, 5)

    @pytest.mark.asyncio
    async def test_total_mismatch_non_blocking(
        self, fake_pool, fake_receipt_repo, fake_cat_repo, fake_txn_repo,
        fake_budget_repo,
    ):
        # Receipt total is 100 but only 50 in postable items (other 50 excluded)
        items = [
            _item(ITEM_ID_1, CAT_EXPENSE_A, total_price=Decimal("50.00")),
            _item(ITEM_ID_2, CAT_EXPENSE_B, total_price=Decimal("50.00"),
                  excluded=True),
        ]
        self._setup_happy_path(
            fake_receipt_repo, fake_cat_repo, fake_txn_repo, fake_budget_repo,
            items=items,
            receipt_kwargs={"total_amount": Decimal("100.00")},
        )

        service = ReceiptReviewService(fake_pool)
        result = await service.confirm_receipt(
            RECEIPT_ID, HOUSEHOLD_ID, USER_ID,
        )

        # Confirm succeeds despite mismatch
        assert result["status"] == "posted"
        assert result["total_mismatch"] is True

    @pytest.mark.asyncio
    async def test_budget_month_auto_created(
        self, fake_pool, fake_receipt_repo, fake_cat_repo, fake_txn_repo,
        fake_budget_repo,
    ):
        items = [_item(ITEM_ID_1, CAT_EXPENSE_A)]
        self._setup_happy_path(
            fake_receipt_repo, fake_cat_repo, fake_txn_repo, fake_budget_repo,
            items=items,
        )
        # Override: no existing budget month
        fake_budget_repo.get_month.return_value = None
        fake_budget_repo.create_month.return_value = {
            "id": BUDGET_MONTH_ID, "household_id": HOUSEHOLD_ID,
            "month": date(2026, 4, 1),
        }

        service = ReceiptReviewService(fake_pool)
        result = await service.confirm_receipt(
            RECEIPT_ID, HOUSEHOLD_ID, USER_ID,
        )

        assert result["status"] == "posted"
        fake_budget_repo.create_month.assert_called_once()

    @pytest.mark.asyncio
    async def test_uses_confirmed_not_suggested(
        self, fake_pool, fake_receipt_repo, fake_cat_repo, fake_txn_repo,
        fake_budget_repo,
    ):
        """Transaction must use user_confirmed_category_id, not suggested."""
        suggested = UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")
        items = [
            _item(ITEM_ID_1, cat_id=CAT_EXPENSE_A,
                  suggested_cat_id=suggested),
        ]
        self._setup_happy_path(
            fake_receipt_repo, fake_cat_repo, fake_txn_repo, fake_budget_repo,
            items=items,
        )

        service = ReceiptReviewService(fake_pool)
        await service.confirm_receipt(RECEIPT_ID, HOUSEHOLD_ID, USER_ID)

        call_kwargs = fake_txn_repo.create_transaction.call_args[1]
        assert call_kwargs["category_id"] == CAT_EXPENSE_A
        assert call_kwargs["category_id"] != suggested

    @pytest.mark.asyncio
    async def test_rollback_on_failure(
        self, fake_pool, fake_receipt_repo, fake_cat_repo, fake_txn_repo,
        fake_budget_repo,
    ):
        items = [_item(ITEM_ID_1, CAT_EXPENSE_A)]
        self._setup_happy_path(
            fake_receipt_repo, fake_cat_repo, fake_txn_repo, fake_budget_repo,
            items=items,
        )
        fake_txn_repo.create_transaction.side_effect = Exception("DB error")

        service = ReceiptReviewService(fake_pool)
        with pytest.raises(Exception, match="DB error"):
            await service.confirm_receipt(
                RECEIPT_ID, HOUSEHOLD_ID, USER_ID,
            )

    @pytest.mark.asyncio
    async def test_cross_household_blocked(
        self, fake_pool, fake_receipt_repo, fake_cat_repo, fake_txn_repo,
        fake_budget_repo,
    ):
        """Receipt belongs to another household — 404 before idempotency check."""
        fake_receipt_repo.get_by_id.return_value = None  # scoped query returns nothing

        service = ReceiptReviewService(fake_pool)
        with pytest.raises(NotFoundError):
            await service.confirm_receipt(
                RECEIPT_ID, OTHER_HOUSEHOLD_ID, USER_ID,
            )

        # Idempotency check must not run
        fake_txn_repo.get_group_by_idempotency_key.assert_not_called()

    @pytest.mark.asyncio
    async def test_zero_amount_groups_rejected(
        self, fake_pool, fake_receipt_repo, fake_cat_repo, fake_txn_repo,
        fake_budget_repo,
    ):
        items = [
            _item(ITEM_ID_1, CAT_EXPENSE_A, total_price=Decimal("0.00")),
        ]
        fake_receipt_repo.get_by_id.return_value = _receipt()
        fake_receipt_repo.list_items_by_receipt.return_value = items
        fake_cat_repo.get_by_id.return_value = _category()

        service = ReceiptReviewService(fake_pool)
        with pytest.raises(ValidationError, match="positive amounts"):
            await service.confirm_receipt(
                RECEIPT_ID, HOUSEHOLD_ID, USER_ID,
            )
