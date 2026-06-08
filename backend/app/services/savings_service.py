"""Service for savings rules, proposal generation, approval, posting,
and manual savings entry.

Proposal approval runs in a single DB transaction (pending → posted):
1. Verify proposal status is 'pending' and transaction_id is NULL
2. Create transaction_group with idempotency_key = 'savings_proposal:{proposal_id}'
3. Create savings transaction
4. Update proposal with transaction_id and status = 'posted'
"""

import uuid as _uuid
from datetime import date
from decimal import Decimal
from typing import Optional
from uuid import UUID

import asyncpg

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.repositories.budgets import BudgetRepository
from app.repositories.categories import CategoryRepository
from app.repositories.savings import SavingsRepository
from app.repositories.transactions import TransactionRepository
from app.rules.date_rules import determine_budget_month
from app.rules.savings_rules import build_proposals


class SavingsService:
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    # ── rules ──

    async def create_rule(
        self,
        household_id: UUID,
        user_id: UUID,
        category_id: UUID,
        rule_type: str,
        label: str,
        percent_value: Optional[Decimal],
        fixed_amount: Optional[Decimal],
    ) -> dict:
        # Validate rule_type / value consistency
        if rule_type == "percent_of_income":
            if percent_value is None or percent_value <= 0:
                raise ValidationError("percent_value must be positive for percent_of_income rule")
            if fixed_amount is not None:
                raise ValidationError("fixed_amount must not be set for percent_of_income rule")
        elif rule_type == "fixed_monthly":
            if fixed_amount is None or fixed_amount <= 0:
                raise ValidationError("fixed_amount must be positive for fixed_monthly rule")
            if percent_value is not None:
                raise ValidationError("percent_value must not be set for fixed_monthly rule")
        else:
            raise ValidationError(f"Unknown rule_type: {rule_type}")

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                # Validate category
                cat_repo = CategoryRepository(conn)
                cat = await cat_repo.get_by_id(category_id, household_id)
                if not cat:
                    raise NotFoundError(f"Category {category_id} not found")
                if cat["type"] != "savings":
                    raise ValidationError(
                        f"Category '{cat['name']}' is type '{cat['type']}', expected 'savings'"
                    )
                if cat["archived_at"] is not None:
                    raise ValidationError(f"Category '{cat['name']}' is archived")

                savings_repo = SavingsRepository(conn)
                rule = await savings_repo.create_rule(
                    household_id=household_id,
                    category_id=category_id,
                    rule_type=rule_type,
                    label=label,
                    percent_value=percent_value,
                    fixed_amount=fixed_amount,
                    created_by=user_id,
                )
                rule["category_name"] = cat["name"]
                return rule

    async def list_rules(self, household_id: UUID) -> list[dict]:
        async with self.pool.acquire() as conn:
            repo = SavingsRepository(conn)
            return await repo.list_rules_by_household(household_id)

    async def update_rule(
        self,
        household_id: UUID,
        rule_id: UUID,
        fields_set: set[str],
        label: Optional[str] = None,
        percent_value: Optional[Decimal] = None,
        fixed_amount: Optional[Decimal] = None,
        is_active: Optional[bool] = None,
    ) -> dict:
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                savings_repo = SavingsRepository(conn)
                existing = await savings_repo.get_rule_by_id(rule_id, household_id)
                if not existing:
                    raise NotFoundError(f"Savings rule {rule_id} not found")

                existing_type = existing["rule_type"]

                # Cross-type field guard
                if "percent_value" in fields_set and existing_type == "fixed_monthly":
                    raise ValidationError(
                        "Cannot set percent_value on a fixed_monthly rule"
                    )
                if "fixed_amount" in fields_set and existing_type == "percent_of_income":
                    raise ValidationError(
                        "Cannot set fixed_amount on a percent_of_income rule"
                    )

                # Validate positive values when provided
                if "percent_value" in fields_set and percent_value is not None and percent_value <= 0:
                    raise ValidationError("percent_value must be positive")
                if "fixed_amount" in fields_set and fixed_amount is not None and fixed_amount <= 0:
                    raise ValidationError("fixed_amount must be positive")

                # Build repo kwargs: sentinel ... for fields not in fields_set
                repo_label = label if "label" in fields_set else None
                repo_percent = percent_value if "percent_value" in fields_set else ...
                repo_fixed = fixed_amount if "fixed_amount" in fields_set else ...
                repo_active = is_active if "is_active" in fields_set else None

                await savings_repo.update_rule(
                    rule_id=rule_id,
                    household_id=household_id,
                    label=repo_label,
                    percent_value=repo_percent,
                    fixed_amount=repo_fixed,
                    is_active=repo_active,
                )
                # Re-fetch with join for category_name
                return await savings_repo.get_rule_by_id(rule_id, household_id)

    # ── proposals ──

    async def generate_proposals(
        self,
        household_id: UUID,
        user_id: UUID,
        budget_month_id: UUID,
    ) -> list[dict]:
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                # Verify budget month exists
                budget_repo = BudgetRepository(conn)
                bm = await budget_repo.get_month_by_id(budget_month_id, household_id)
                if not bm:
                    raise NotFoundError(f"Budget month {budget_month_id} not found")

                savings_repo = SavingsRepository(conn)

                # Get total actual income for the month
                total_income = await savings_repo.get_total_income_for_month(
                    household_id, budget_month_id
                )

                # Get active rules
                rules = await savings_repo.list_rules_by_household(
                    household_id, active_only=True
                )

                # Build proposals via pure function
                proposals = build_proposals(rules, total_income)

                # Insert each proposal (ON CONFLICT DO NOTHING for idempotency)
                for p in proposals:
                    rule_id = p.savings_rule_id
                    if not isinstance(rule_id, UUID):
                        rule_id = UUID(str(rule_id))
                    await savings_repo.insert_proposal(
                        household_id=household_id,
                        savings_rule_id=rule_id,
                        budget_month_id=budget_month_id,
                        proposed_amount=p.proposed_amount,
                        calculation_basis=p.calculation_basis,
                    )

                # Return all proposals for the month (new + pre-existing)
                return await savings_repo.list_proposals_by_month(
                    household_id, budget_month_id
                )

    async def list_proposals(
        self, household_id: UUID, budget_month_id: UUID
    ) -> list[dict]:
        async with self.pool.acquire() as conn:
            repo = SavingsRepository(conn)
            return await repo.list_proposals_by_month(household_id, budget_month_id)

    async def approve_proposal(
        self,
        household_id: UUID,
        user_id: UUID,
        proposal_id: UUID,
        final_amount: Optional[Decimal] = None,
    ) -> dict:
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                savings_repo = SavingsRepository(conn)
                txn_repo = TransactionRepository(conn)
                budget_repo = BudgetRepository(conn)

                # Fetch and validate proposal
                proposal = await savings_repo.get_proposal_by_id(
                    proposal_id, household_id
                )
                if not proposal:
                    raise NotFoundError(f"Savings proposal {proposal_id} not found")
                if proposal["status"] != "pending":
                    raise ConflictError(
                        f"Proposal status is '{proposal['status']}', expected 'pending'"
                    )
                if proposal["transaction_id"] is not None:
                    raise ConflictError("Proposal already posted")

                # Resolve final amount
                amount = final_amount if final_amount is not None else proposal["proposed_amount"]
                if amount <= 0:
                    raise ValidationError("Amount must be positive")

                # Fetch rule for category_id
                rule = await savings_repo.get_rule_by_id(
                    proposal["savings_rule_id"], household_id
                )

                # Fetch budget month for effective_date
                bm = await budget_repo.get_month_by_id(
                    proposal["budget_month_id"], household_id
                )

                effective_date = bm["month"]  # 1st of the month

                # Idempotency check
                idempotency_key = f"savings_proposal:{proposal_id}"
                existing_group = await txn_repo.get_group_by_idempotency_key(
                    idempotency_key
                )
                if existing_group:
                    raise ConflictError("Proposal already posted")

                # Create transaction group
                group = await txn_repo.create_group(
                    household_id=household_id,
                    source="savings_proposal",
                    idempotency_key=idempotency_key,
                    created_by=user_id,
                    description=rule["label"],
                )

                # Create savings transaction
                txn = await txn_repo.create_transaction(
                    group_id=group["id"],
                    household_id=household_id,
                    type="savings",
                    category_id=rule["category_id"],
                    amount=amount,
                    transaction_date=effective_date,
                    effective_date=effective_date,
                    source="savings_proposal",
                    posted_by=user_id,
                    budget_month_id=proposal["budget_month_id"],
                    savings_proposal_id=proposal_id,
                )

                # Update proposal to posted
                await savings_repo.update_proposal_status(
                    proposal_id=proposal_id,
                    household_id=household_id,
                    status="posted",
                    final_amount=amount,
                    reviewed_by=user_id,
                    transaction_id=txn["id"],
                )

                # Re-fetch with joins for response
                return await savings_repo.get_proposal_by_id(
                    proposal_id, household_id
                )

    # ── manual savings ──

    async def create_manual_savings(
        self,
        household_id: UUID,
        user_id: UUID,
        category_id: UUID,
        amount: Decimal,
        transaction_date: date,
        description: Optional[str] = None,
        details: Optional[str] = None,
    ) -> dict:
        if amount <= 0:
            raise ValidationError("Amount must be positive")

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                # Validate category
                cat_repo = CategoryRepository(conn)
                cat = await cat_repo.get_by_id(category_id, household_id)
                if not cat:
                    raise NotFoundError(f"Category {category_id} not found")
                if cat["type"] != "savings":
                    raise ValidationError(
                        f"Category '{cat['name']}' is type '{cat['type']}', expected 'savings'"
                    )
                if cat["archived_at"] is not None:
                    raise ValidationError(f"Category '{cat['name']}' is archived")

                # Resolve budget month — savings never uses late-income shift
                effective_date = transaction_date
                budget_month = determine_budget_month(
                    effective_date, "savings",
                    shift_late_income=False,
                    late_income_cutoff_day=None,
                )

                # Ensure budget month exists
                budget_repo = BudgetRepository(conn)
                bm = await budget_repo.get_month(household_id, budget_month)
                if not bm:
                    bm = await budget_repo.create_month(household_id, budget_month)

                # Create transaction group + transaction
                idempotency_key = f"manual_savings:{_uuid.uuid4()}"

                txn_repo = TransactionRepository(conn)
                group = await txn_repo.create_group(
                    household_id=household_id,
                    source="manual_savings",
                    idempotency_key=idempotency_key,
                    created_by=user_id,
                    description=description,
                )

                txn = await txn_repo.create_transaction(
                    group_id=group["id"],
                    household_id=household_id,
                    type="savings",
                    category_id=category_id,
                    amount=amount,
                    transaction_date=transaction_date,
                    effective_date=effective_date,
                    source="manual_savings",
                    posted_by=user_id,
                    budget_month_id=bm["id"],
                    description=description,
                    details=details,
                )

                txn["category_name"] = cat["name"]
                txn["budget_month"] = budget_month
                return txn

    async def reject_proposal(
        self,
        household_id: UUID,
        user_id: UUID,
        proposal_id: UUID,
    ) -> dict:
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                savings_repo = SavingsRepository(conn)

                proposal = await savings_repo.get_proposal_by_id(
                    proposal_id, household_id
                )
                if not proposal:
                    raise NotFoundError(f"Savings proposal {proposal_id} not found")
                if proposal["status"] != "pending":
                    raise ConflictError(
                        f"Proposal status is '{proposal['status']}', expected 'pending'"
                    )

                await savings_repo.update_proposal_status(
                    proposal_id=proposal_id,
                    household_id=household_id,
                    status="rejected",
                    final_amount=None,
                    reviewed_by=user_id,
                    transaction_id=None,
                )

                return await savings_repo.get_proposal_by_id(
                    proposal_id, household_id
                )
