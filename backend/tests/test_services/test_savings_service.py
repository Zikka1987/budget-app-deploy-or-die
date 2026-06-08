"""Mock-based tests for SavingsService.

Tests cover rule CRUD, proposal generation (including idempotency and
zero-income), proposal approve+post, and proposal rejection.
"""

from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.services.savings_service import SavingsService


USER_ID = UUID("11111111-1111-1111-1111-111111111111")
HOUSEHOLD_ID = UUID("22222222-2222-2222-2222-222222222222")
CATEGORY_ID = UUID("33333333-3333-3333-3333-333333333333")
RULE_ID = UUID("44444444-4444-4444-4444-444444444444")
PROPOSAL_ID = UUID("55555555-5555-5555-5555-555555555555")
BUDGET_MONTH_ID = UUID("66666666-6666-6666-6666-666666666666")
TXN_ID = UUID("77777777-7777-7777-7777-777777777777")
GROUP_ID = UUID("88888888-8888-8888-8888-888888888888")
NOW = datetime.now(timezone.utc)


def _category(type_="savings", archived_at=None):
    return {
        "id": CATEGORY_ID,
        "household_id": HOUSEHOLD_ID,
        "type": type_,
        "name": "General Savings",
        "icon": None,
        "sort_order": 0,
        "archived_at": archived_at,
        "created_at": NOW,
        "updated_at": NOW,
    }


def _rule(rule_type="percent_of_income"):
    return {
        "id": RULE_ID,
        "household_id": HOUSEHOLD_ID,
        "category_id": CATEGORY_ID,
        "rule_type": rule_type,
        "label": "10% savings",
        "percent_value": Decimal("10") if rule_type == "percent_of_income" else None,
        "fixed_amount": Decimal("2000.00") if rule_type == "fixed_monthly" else None,
        "is_active": True,
        "created_by": USER_ID,
        "created_at": NOW,
        "updated_at": NOW,
        "category_name": "General Savings",
    }


def _budget_month():
    return {
        "id": BUDGET_MONTH_ID,
        "household_id": HOUSEHOLD_ID,
        "month": date(2026, 4, 1),
        "notes": None,
        "is_closed": False,
        "created_at": NOW,
        "updated_at": NOW,
    }


def _proposal(status="pending", transaction_id=None):
    return {
        "id": PROPOSAL_ID,
        "household_id": HOUSEHOLD_ID,
        "savings_rule_id": RULE_ID,
        "budget_month_id": BUDGET_MONTH_ID,
        "proposed_amount": Decimal("4500.00"),
        "final_amount": None,
        "status": status,
        "calculation_basis": {"rule_type": "percent_of_income", "total_income": "45000", "percent": "10"},
        "reviewed_by": None,
        "reviewed_at": None,
        "transaction_id": transaction_id,
        "created_at": NOW,
        "updated_at": NOW,
        "rule_label": "10% savings",
        "budget_month": date(2026, 4, 1),
    }


def _group():
    return {
        "id": GROUP_ID,
        "household_id": HOUSEHOLD_ID,
        "source": "savings_proposal",
        "idempotency_key": f"savings_proposal:{PROPOSAL_ID}",
        "created_by": USER_ID,
        "receipt_id": None,
        "description": "10% savings",
        "created_at": NOW,
    }


def _transaction():
    return {
        "id": TXN_ID,
        "group_id": GROUP_ID,
        "household_id": HOUSEHOLD_ID,
        "type": "savings",
        "category_id": CATEGORY_ID,
        "amount": Decimal("4500.00"),
        "transaction_date": date(2026, 4, 1),
        "effective_date": date(2026, 4, 1),
        "source": "savings_proposal",
        "posted_by": USER_ID,
        "budget_month_id": BUDGET_MONTH_ID,
        "description": None,
        "details": None,
        "savings_proposal_id": PROPOSAL_ID,
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
def fake_savings_repo(monkeypatch):
    repo = MagicMock()
    repo.create_rule = AsyncMock(return_value=_rule())
    repo.list_rules_by_household = AsyncMock(return_value=[_rule()])
    repo.get_rule_by_id = AsyncMock(return_value=_rule())
    repo.update_rule = AsyncMock(return_value=_rule())
    repo.insert_proposal = AsyncMock(return_value=_proposal())
    repo.list_proposals_by_month = AsyncMock(return_value=[_proposal()])
    repo.get_proposal_by_id = AsyncMock(return_value=_proposal())
    repo.update_proposal_status = AsyncMock(return_value=_proposal(status="posted"))
    repo.get_total_income_for_month = AsyncMock(return_value=Decimal("45000"))
    monkeypatch.setattr(
        "app.services.savings_service.SavingsRepository",
        lambda conn: repo,
    )
    return repo


@pytest.fixture
def fake_category_repo(monkeypatch):
    repo = MagicMock()
    repo.get_by_id = AsyncMock(return_value=_category())
    monkeypatch.setattr(
        "app.services.savings_service.CategoryRepository",
        lambda conn: repo,
    )
    return repo


@pytest.fixture
def fake_budget_repo(monkeypatch):
    repo = MagicMock()
    repo.get_month_by_id = AsyncMock(return_value=_budget_month())
    monkeypatch.setattr(
        "app.services.savings_service.BudgetRepository",
        lambda conn: repo,
    )
    return repo


@pytest.fixture
def fake_txn_repo(monkeypatch):
    repo = MagicMock()
    repo.get_group_by_idempotency_key = AsyncMock(return_value=None)
    repo.create_group = AsyncMock(return_value=_group())
    repo.create_transaction = AsyncMock(return_value=_transaction())
    monkeypatch.setattr(
        "app.services.savings_service.TransactionRepository",
        lambda conn: repo,
    )
    return repo


# ── TestCreateRule ──


class TestCreateRule:
    @pytest.mark.asyncio
    async def test_create_percent_rule(self, fake_pool, fake_savings_repo, fake_category_repo):
        service = SavingsService(fake_pool)
        result = await service.create_rule(
            household_id=HOUSEHOLD_ID,
            user_id=USER_ID,
            category_id=CATEGORY_ID,
            rule_type="percent_of_income",
            label="10% savings",
            percent_value=Decimal("10"),
            fixed_amount=None,
        )
        assert result["id"] == RULE_ID
        assert result["category_name"] == "General Savings"
        fake_savings_repo.create_rule.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_create_fixed_rule(self, fake_pool, fake_savings_repo, fake_category_repo):
        fake_savings_repo.create_rule = AsyncMock(return_value=_rule("fixed_monthly"))
        service = SavingsService(fake_pool)
        result = await service.create_rule(
            household_id=HOUSEHOLD_ID,
            user_id=USER_ID,
            category_id=CATEGORY_ID,
            rule_type="fixed_monthly",
            label="Fixed 2000",
            percent_value=None,
            fixed_amount=Decimal("2000.00"),
        )
        assert result["id"] == RULE_ID
        fake_savings_repo.create_rule.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_rejects_percent_value_on_fixed_type(self, fake_pool):
        service = SavingsService(fake_pool)
        with pytest.raises(ValidationError, match="percent_value must not be set"):
            await service.create_rule(
                household_id=HOUSEHOLD_ID,
                user_id=USER_ID,
                category_id=CATEGORY_ID,
                rule_type="fixed_monthly",
                label="Bad",
                percent_value=Decimal("10"),
                fixed_amount=Decimal("2000.00"),
            )

    @pytest.mark.asyncio
    async def test_rejects_missing_category(self, fake_pool, fake_savings_repo, fake_category_repo):
        fake_category_repo.get_by_id = AsyncMock(return_value=None)
        service = SavingsService(fake_pool)
        with pytest.raises(NotFoundError, match="not found"):
            await service.create_rule(
                household_id=HOUSEHOLD_ID,
                user_id=USER_ID,
                category_id=CATEGORY_ID,
                rule_type="percent_of_income",
                label="10%",
                percent_value=Decimal("10"),
                fixed_amount=None,
            )

    @pytest.mark.asyncio
    async def test_rejects_non_savings_category(self, fake_pool, fake_savings_repo, fake_category_repo):
        fake_category_repo.get_by_id = AsyncMock(return_value=_category(type_="expense"))
        service = SavingsService(fake_pool)
        with pytest.raises(ValidationError, match="expected 'savings'"):
            await service.create_rule(
                household_id=HOUSEHOLD_ID,
                user_id=USER_ID,
                category_id=CATEGORY_ID,
                rule_type="percent_of_income",
                label="10%",
                percent_value=Decimal("10"),
                fixed_amount=None,
            )

    @pytest.mark.asyncio
    async def test_rejects_archived_category(self, fake_pool, fake_savings_repo, fake_category_repo):
        fake_category_repo.get_by_id = AsyncMock(return_value=_category(archived_at=NOW))
        service = SavingsService(fake_pool)
        with pytest.raises(ValidationError, match="archived"):
            await service.create_rule(
                household_id=HOUSEHOLD_ID,
                user_id=USER_ID,
                category_id=CATEGORY_ID,
                rule_type="percent_of_income",
                label="10%",
                percent_value=Decimal("10"),
                fixed_amount=None,
            )


# ── TestListRules ──


class TestListRules:
    @pytest.mark.asyncio
    async def test_returns_rules(self, fake_pool, fake_savings_repo):
        service = SavingsService(fake_pool)
        result = await service.list_rules(HOUSEHOLD_ID)
        assert len(result) == 1
        assert result[0]["id"] == RULE_ID
        fake_savings_repo.list_rules_by_household.assert_awaited_once_with(HOUSEHOLD_ID)


# ── TestUpdateRule ──


class TestUpdateRule:
    @pytest.mark.asyncio
    async def test_update_label(self, fake_pool, fake_savings_repo):
        service = SavingsService(fake_pool)
        result = await service.update_rule(
            household_id=HOUSEHOLD_ID,
            rule_id=RULE_ID,
            fields_set={"label"},
            label="New label",
        )
        assert result["id"] == RULE_ID
        fake_savings_repo.update_rule.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_deactivate_rule(self, fake_pool, fake_savings_repo):
        service = SavingsService(fake_pool)
        result = await service.update_rule(
            household_id=HOUSEHOLD_ID,
            rule_id=RULE_ID,
            fields_set={"is_active"},
            is_active=False,
        )
        assert result["id"] == RULE_ID
        fake_savings_repo.update_rule.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_rejects_not_found(self, fake_pool, fake_savings_repo):
        fake_savings_repo.get_rule_by_id = AsyncMock(return_value=None)
        service = SavingsService(fake_pool)
        with pytest.raises(NotFoundError, match="not found"):
            await service.update_rule(
                household_id=HOUSEHOLD_ID,
                rule_id=RULE_ID,
                fields_set={"label"},
                label="New label",
            )

    @pytest.mark.asyncio
    async def test_rejects_cross_type_field(self, fake_pool, fake_savings_repo):
        # percent_of_income rule — cannot set fixed_amount
        service = SavingsService(fake_pool)
        with pytest.raises(ValidationError, match="Cannot set fixed_amount"):
            await service.update_rule(
                household_id=HOUSEHOLD_ID,
                rule_id=RULE_ID,
                fields_set={"fixed_amount"},
                fixed_amount=Decimal("1000"),
            )


# ── TestGenerateProposals ──


class TestGenerateProposals:
    @pytest.mark.asyncio
    async def test_happy_path(self, fake_pool, fake_savings_repo, fake_budget_repo):
        service = SavingsService(fake_pool)
        result = await service.generate_proposals(
            household_id=HOUSEHOLD_ID,
            user_id=USER_ID,
            budget_month_id=BUDGET_MONTH_ID,
        )
        assert len(result) == 1
        fake_savings_repo.insert_proposal.assert_awaited()
        fake_savings_repo.list_proposals_by_month.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_idempotent_skips_existing(self, fake_pool, fake_savings_repo, fake_budget_repo):
        # insert_proposal returns None on conflict
        fake_savings_repo.insert_proposal = AsyncMock(return_value=None)
        # but list still returns the pre-existing proposals
        fake_savings_repo.list_proposals_by_month = AsyncMock(return_value=[_proposal()])
        service = SavingsService(fake_pool)
        result = await service.generate_proposals(
            household_id=HOUSEHOLD_ID,
            user_id=USER_ID,
            budget_month_id=BUDGET_MONTH_ID,
        )
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_rejects_unknown_budget_month(self, fake_pool, fake_savings_repo, fake_budget_repo):
        fake_budget_repo.get_month_by_id = AsyncMock(return_value=None)
        service = SavingsService(fake_pool)
        with pytest.raises(NotFoundError, match="not found"):
            await service.generate_proposals(
                household_id=HOUSEHOLD_ID,
                user_id=USER_ID,
                budget_month_id=BUDGET_MONTH_ID,
            )

    @pytest.mark.asyncio
    async def test_zero_income_delegates_to_rules(self, fake_pool, fake_savings_repo, fake_budget_repo):
        """With zero income, service delegates to build_proposals without
        inventing its own behavior. fixed_monthly rules still produce
        proposals; percent_of_income rules produce 0 and are filtered
        by the rules layer (amount > 0 check in build_proposals)."""
        fake_savings_repo.get_total_income_for_month = AsyncMock(return_value=Decimal("0"))
        # Two rules: one percent, one fixed
        fake_savings_repo.list_rules_by_household = AsyncMock(return_value=[
            {
                "id": str(RULE_ID),
                "category_id": str(CATEGORY_ID),
                "rule_type": "percent_of_income",
                "percent_value": Decimal("10"),
                "fixed_amount": None,
            },
            {
                "id": str(UUID("99999999-9999-9999-9999-999999999999")),
                "category_id": str(CATEGORY_ID),
                "rule_type": "fixed_monthly",
                "percent_value": None,
                "fixed_amount": Decimal("2000.00"),
            },
        ])
        # Only the fixed rule generates a proposal (percent produces 0, filtered)
        service = SavingsService(fake_pool)
        await service.generate_proposals(
            household_id=HOUSEHOLD_ID,
            user_id=USER_ID,
            budget_month_id=BUDGET_MONTH_ID,
        )
        # insert_proposal called once (only for the fixed_monthly rule)
        assert fake_savings_repo.insert_proposal.await_count == 1


# ── TestApproveProposal ──


class TestApproveProposal:
    @pytest.mark.asyncio
    async def test_happy_path(
        self, fake_pool, fake_savings_repo, fake_txn_repo, fake_budget_repo
    ):
        # After posting, get_proposal_by_id returns the posted version
        posted = _proposal(status="posted", transaction_id=TXN_ID)
        fake_savings_repo.get_proposal_by_id = AsyncMock(
            side_effect=[_proposal(), posted]
        )
        service = SavingsService(fake_pool)
        result = await service.approve_proposal(
            household_id=HOUSEHOLD_ID,
            user_id=USER_ID,
            proposal_id=PROPOSAL_ID,
        )
        assert result["status"] == "posted"
        assert result["transaction_id"] == TXN_ID
        fake_txn_repo.create_group.assert_awaited_once()
        fake_txn_repo.create_transaction.assert_awaited_once()
        fake_savings_repo.update_proposal_status.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_amount_override(
        self, fake_pool, fake_savings_repo, fake_txn_repo, fake_budget_repo
    ):
        posted = _proposal(status="posted", transaction_id=TXN_ID)
        fake_savings_repo.get_proposal_by_id = AsyncMock(
            side_effect=[_proposal(), posted]
        )
        service = SavingsService(fake_pool)
        await service.approve_proposal(
            household_id=HOUSEHOLD_ID,
            user_id=USER_ID,
            proposal_id=PROPOSAL_ID,
            final_amount=Decimal("3000.00"),
        )
        # Verify the overridden amount was passed to create_transaction
        call_kwargs = fake_txn_repo.create_transaction.call_args
        assert call_kwargs.kwargs["amount"] == Decimal("3000.00")

    @pytest.mark.asyncio
    async def test_rejects_non_pending(
        self, fake_pool, fake_savings_repo, fake_txn_repo, fake_budget_repo
    ):
        fake_savings_repo.get_proposal_by_id = AsyncMock(
            return_value=_proposal(status="posted", transaction_id=TXN_ID)
        )
        service = SavingsService(fake_pool)
        with pytest.raises(ConflictError, match="expected 'pending'"):
            await service.approve_proposal(
                household_id=HOUSEHOLD_ID,
                user_id=USER_ID,
                proposal_id=PROPOSAL_ID,
            )

    @pytest.mark.asyncio
    async def test_rejects_already_posted_transaction_id(
        self, fake_pool, fake_savings_repo, fake_txn_repo, fake_budget_repo
    ):
        # Pending status but transaction_id already set (shouldn't happen, defense in depth)
        proposal = _proposal()
        proposal["transaction_id"] = TXN_ID
        fake_savings_repo.get_proposal_by_id = AsyncMock(return_value=proposal)
        service = SavingsService(fake_pool)
        with pytest.raises(ConflictError, match="already posted"):
            await service.approve_proposal(
                household_id=HOUSEHOLD_ID,
                user_id=USER_ID,
                proposal_id=PROPOSAL_ID,
            )


# ── TestRejectProposal ──


# ── TestCreateManualSavings ──


class TestCreateManualSavings:
    @pytest.mark.asyncio
    async def test_happy_path(self, fake_pool, fake_category_repo, fake_txn_repo, monkeypatch):
        # Mock BudgetRepository with get_month / create_month
        budget_repo = MagicMock()
        budget_repo.get_month = AsyncMock(return_value=_budget_month())
        monkeypatch.setattr(
            "app.services.savings_service.BudgetRepository",
            lambda conn: budget_repo,
        )

        service = SavingsService(fake_pool)
        result = await service.create_manual_savings(
            household_id=HOUSEHOLD_ID,
            user_id=USER_ID,
            category_id=CATEGORY_ID,
            amount=Decimal("5000.00"),
            transaction_date=date(2026, 4, 15),
            description="Monthly transfer",
            details="General savings",
        )
        assert result["category_name"] == "General Savings"
        assert result["budget_month"] == date(2026, 4, 1)
        fake_txn_repo.create_group.assert_awaited_once()
        fake_txn_repo.create_transaction.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_transaction_has_correct_type_and_source(
        self, fake_pool, fake_category_repo, fake_txn_repo, monkeypatch
    ):
        budget_repo = MagicMock()
        budget_repo.get_month = AsyncMock(return_value=_budget_month())
        monkeypatch.setattr(
            "app.services.savings_service.BudgetRepository",
            lambda conn: budget_repo,
        )

        service = SavingsService(fake_pool)
        await service.create_manual_savings(
            household_id=HOUSEHOLD_ID,
            user_id=USER_ID,
            category_id=CATEGORY_ID,
            amount=Decimal("1000.00"),
            transaction_date=date(2026, 4, 10),
        )
        call_kwargs = fake_txn_repo.create_transaction.call_args.kwargs
        assert call_kwargs["type"] == "savings"
        assert call_kwargs["source"] == "manual_savings"

        group_kwargs = fake_txn_repo.create_group.call_args.kwargs
        assert group_kwargs["source"] == "manual_savings"

    @pytest.mark.asyncio
    async def test_no_late_income_shift(
        self, fake_pool, fake_category_repo, fake_txn_repo, monkeypatch
    ):
        """Manual savings on the 28th of a month should stay in that month,
        not shift to the next (late-income shift does not apply to savings)."""
        budget_repo = MagicMock()
        bm_dec = _budget_month()
        bm_dec["month"] = date(2026, 12, 1)
        budget_repo.get_month = AsyncMock(return_value=bm_dec)
        monkeypatch.setattr(
            "app.services.savings_service.BudgetRepository",
            lambda conn: budget_repo,
        )

        service = SavingsService(fake_pool)
        result = await service.create_manual_savings(
            household_id=HOUSEHOLD_ID,
            user_id=USER_ID,
            category_id=CATEGORY_ID,
            amount=Decimal("3000.00"),
            transaction_date=date(2026, 12, 28),
        )
        # Should resolve to December, not January
        assert result["budget_month"] == date(2026, 12, 1)
        budget_repo.get_month.assert_awaited_once_with(HOUSEHOLD_ID, date(2026, 12, 1))

    @pytest.mark.asyncio
    async def test_auto_creates_budget_month(
        self, fake_pool, fake_category_repo, fake_txn_repo, monkeypatch
    ):
        budget_repo = MagicMock()
        budget_repo.get_month = AsyncMock(return_value=None)
        budget_repo.create_month = AsyncMock(return_value=_budget_month())
        monkeypatch.setattr(
            "app.services.savings_service.BudgetRepository",
            lambda conn: budget_repo,
        )

        service = SavingsService(fake_pool)
        await service.create_manual_savings(
            household_id=HOUSEHOLD_ID,
            user_id=USER_ID,
            category_id=CATEGORY_ID,
            amount=Decimal("2000.00"),
            transaction_date=date(2026, 4, 10),
        )
        budget_repo.create_month.assert_awaited_once_with(HOUSEHOLD_ID, date(2026, 4, 1))

    @pytest.mark.asyncio
    async def test_rejects_zero_amount(self, fake_pool):
        service = SavingsService(fake_pool)
        with pytest.raises(ValidationError, match="positive"):
            await service.create_manual_savings(
                household_id=HOUSEHOLD_ID,
                user_id=USER_ID,
                category_id=CATEGORY_ID,
                amount=Decimal("0"),
                transaction_date=date(2026, 4, 10),
            )

    @pytest.mark.asyncio
    async def test_rejects_negative_amount(self, fake_pool):
        service = SavingsService(fake_pool)
        with pytest.raises(ValidationError, match="positive"):
            await service.create_manual_savings(
                household_id=HOUSEHOLD_ID,
                user_id=USER_ID,
                category_id=CATEGORY_ID,
                amount=Decimal("-100"),
                transaction_date=date(2026, 4, 10),
            )

    @pytest.mark.asyncio
    async def test_rejects_missing_category(self, fake_pool, fake_category_repo, monkeypatch):
        fake_category_repo.get_by_id = AsyncMock(return_value=None)
        budget_repo = MagicMock()
        monkeypatch.setattr(
            "app.services.savings_service.BudgetRepository",
            lambda conn: budget_repo,
        )

        service = SavingsService(fake_pool)
        with pytest.raises(NotFoundError, match="not found"):
            await service.create_manual_savings(
                household_id=HOUSEHOLD_ID,
                user_id=USER_ID,
                category_id=CATEGORY_ID,
                amount=Decimal("1000.00"),
                transaction_date=date(2026, 4, 10),
            )

    @pytest.mark.asyncio
    async def test_rejects_non_savings_category(self, fake_pool, fake_category_repo, monkeypatch):
        fake_category_repo.get_by_id = AsyncMock(return_value=_category(type_="expense"))
        budget_repo = MagicMock()
        monkeypatch.setattr(
            "app.services.savings_service.BudgetRepository",
            lambda conn: budget_repo,
        )

        service = SavingsService(fake_pool)
        with pytest.raises(ValidationError, match="expected 'savings'"):
            await service.create_manual_savings(
                household_id=HOUSEHOLD_ID,
                user_id=USER_ID,
                category_id=CATEGORY_ID,
                amount=Decimal("1000.00"),
                transaction_date=date(2026, 4, 10),
            )

    @pytest.mark.asyncio
    async def test_rejects_archived_category(self, fake_pool, fake_category_repo, monkeypatch):
        fake_category_repo.get_by_id = AsyncMock(return_value=_category(archived_at=NOW))
        budget_repo = MagicMock()
        monkeypatch.setattr(
            "app.services.savings_service.BudgetRepository",
            lambda conn: budget_repo,
        )

        service = SavingsService(fake_pool)
        with pytest.raises(ValidationError, match="archived"):
            await service.create_manual_savings(
                household_id=HOUSEHOLD_ID,
                user_id=USER_ID,
                category_id=CATEGORY_ID,
                amount=Decimal("1000.00"),
                transaction_date=date(2026, 4, 10),
            )


# ── TestRejectProposal ──


class TestRejectProposal:
    @pytest.mark.asyncio
    async def test_happy_path(self, fake_pool, fake_savings_repo):
        rejected = _proposal(status="rejected")
        fake_savings_repo.get_proposal_by_id = AsyncMock(
            side_effect=[_proposal(), rejected]
        )
        service = SavingsService(fake_pool)
        result = await service.reject_proposal(
            household_id=HOUSEHOLD_ID,
            user_id=USER_ID,
            proposal_id=PROPOSAL_ID,
        )
        assert result["status"] == "rejected"
        fake_savings_repo.update_proposal_status.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_rejects_non_pending(self, fake_pool, fake_savings_repo):
        fake_savings_repo.get_proposal_by_id = AsyncMock(
            return_value=_proposal(status="posted", transaction_id=TXN_ID)
        )
        service = SavingsService(fake_pool)
        with pytest.raises(ConflictError, match="expected 'pending'"):
            await service.reject_proposal(
                household_id=HOUSEHOLD_ID,
                user_id=USER_ID,
                proposal_id=PROPOSAL_ID,
            )
