"""Repository for savings_rules and savings_proposals tables."""

import json
from decimal import Decimal
from typing import Optional
from uuid import UUID

from app.repositories.base import Connection


class SavingsRepository:
    def __init__(self, conn: Connection):
        self.conn = conn

    # ── savings_rules ──

    async def create_rule(
        self,
        household_id: UUID,
        category_id: UUID,
        rule_type: str,
        label: str,
        percent_value: Optional[Decimal],
        fixed_amount: Optional[Decimal],
        created_by: UUID,
    ) -> dict:
        row = await self.conn.fetchrow(
            """
            INSERT INTO savings_rules
                (household_id, category_id, rule_type, label,
                 percent_value, fixed_amount, created_by)
            VALUES ($1, $2, $3::savings_rule_type, $4, $5, $6, $7)
            RETURNING id, household_id, category_id, rule_type, label,
                      percent_value, fixed_amount, is_active, created_by,
                      created_at, updated_at
            """,
            household_id, category_id, rule_type, label,
            percent_value, fixed_amount, created_by,
        )
        return dict(row)

    async def list_rules_by_household(
        self,
        household_id: UUID,
        active_only: bool = False,
    ) -> list[dict]:
        query = """
            SELECT sr.id, sr.household_id, sr.category_id, sr.rule_type,
                   sr.label, sr.percent_value, sr.fixed_amount, sr.is_active,
                   sr.created_by, sr.created_at, sr.updated_at,
                   c.name AS category_name
            FROM savings_rules sr
            JOIN categories c ON c.id = sr.category_id
            WHERE sr.household_id = $1
        """
        params: list = [household_id]
        if active_only:
            query += " AND sr.is_active = TRUE"
        query += " ORDER BY sr.created_at"
        rows = await self.conn.fetch(query, *params)
        return [dict(r) for r in rows]

    async def get_rule_by_id(
        self, rule_id: UUID, household_id: UUID
    ) -> Optional[dict]:
        row = await self.conn.fetchrow(
            """
            SELECT sr.id, sr.household_id, sr.category_id, sr.rule_type,
                   sr.label, sr.percent_value, sr.fixed_amount, sr.is_active,
                   sr.created_by, sr.created_at, sr.updated_at,
                   c.name AS category_name
            FROM savings_rules sr
            JOIN categories c ON c.id = sr.category_id
            WHERE sr.id = $1 AND sr.household_id = $2
            """,
            rule_id, household_id,
        )
        return dict(row) if row else None

    async def update_rule(
        self,
        rule_id: UUID,
        household_id: UUID,
        label: Optional[str] = None,
        percent_value: Optional[Decimal] = ...,
        fixed_amount: Optional[Decimal] = ...,
        is_active: Optional[bool] = None,
    ) -> Optional[dict]:
        sets = []
        params: list = []
        idx = 1
        if label is not None:
            sets.append(f"label = ${idx}")
            params.append(label)
            idx += 1
        if percent_value is not ...:
            sets.append(f"percent_value = ${idx}")
            params.append(percent_value)
            idx += 1
        if fixed_amount is not ...:
            sets.append(f"fixed_amount = ${idx}")
            params.append(fixed_amount)
            idx += 1
        if is_active is not None:
            sets.append(f"is_active = ${idx}")
            params.append(is_active)
            idx += 1
        if not sets:
            return await self.get_rule_by_id(rule_id, household_id)

        params.append(rule_id)
        params.append(household_id)
        query = f"""
            UPDATE savings_rules SET {', '.join(sets)}
            WHERE id = ${idx} AND household_id = ${idx + 1}
            RETURNING id, household_id, category_id, rule_type, label,
                      percent_value, fixed_amount, is_active, created_by,
                      created_at, updated_at
        """
        row = await self.conn.fetchrow(query, *params)
        return dict(row) if row else None

    # ── savings_proposals ──

    async def insert_proposal(
        self,
        household_id: UUID,
        savings_rule_id: UUID,
        budget_month_id: UUID,
        proposed_amount: Decimal,
        calculation_basis: dict,
    ) -> Optional[dict]:
        row = await self.conn.fetchrow(
            """
            INSERT INTO savings_proposals
                (household_id, savings_rule_id, budget_month_id,
                 proposed_amount, status, calculation_basis)
            VALUES ($1, $2, $3, $4, 'pending'::proposal_status, $5::jsonb)
            ON CONFLICT (savings_rule_id, budget_month_id) DO NOTHING
            RETURNING id, household_id, savings_rule_id, budget_month_id,
                      proposed_amount, final_amount, status, calculation_basis,
                      reviewed_by, reviewed_at, transaction_id,
                      created_at, updated_at
            """,
            household_id, savings_rule_id, budget_month_id,
            proposed_amount, json.dumps(calculation_basis),
        )
        return dict(row) if row else None

    async def list_proposals_by_month(
        self, household_id: UUID, budget_month_id: UUID
    ) -> list[dict]:
        rows = await self.conn.fetch(
            """
            SELECT sp.id, sp.household_id, sp.savings_rule_id,
                   sp.budget_month_id, sp.proposed_amount, sp.final_amount,
                   sp.status, sp.calculation_basis, sp.reviewed_by,
                   sp.reviewed_at, sp.transaction_id,
                   sp.created_at, sp.updated_at,
                   sr.label AS rule_label,
                   bm.month AS budget_month
            FROM savings_proposals sp
            JOIN savings_rules sr ON sr.id = sp.savings_rule_id
            JOIN budget_months bm ON bm.id = sp.budget_month_id
            WHERE sp.household_id = $1 AND sp.budget_month_id = $2
            ORDER BY sp.created_at
            """,
            household_id, budget_month_id,
        )
        return [dict(r) for r in rows]

    async def get_proposal_by_id(
        self, proposal_id: UUID, household_id: UUID
    ) -> Optional[dict]:
        row = await self.conn.fetchrow(
            """
            SELECT sp.id, sp.household_id, sp.savings_rule_id,
                   sp.budget_month_id, sp.proposed_amount, sp.final_amount,
                   sp.status, sp.calculation_basis, sp.reviewed_by,
                   sp.reviewed_at, sp.transaction_id,
                   sp.created_at, sp.updated_at,
                   sr.label AS rule_label,
                   bm.month AS budget_month
            FROM savings_proposals sp
            JOIN savings_rules sr ON sr.id = sp.savings_rule_id
            JOIN budget_months bm ON bm.id = sp.budget_month_id
            WHERE sp.id = $1 AND sp.household_id = $2
            """,
            proposal_id, household_id,
        )
        return dict(row) if row else None

    async def update_proposal_status(
        self,
        proposal_id: UUID,
        household_id: UUID,
        status: str,
        final_amount: Optional[Decimal],
        reviewed_by: UUID,
        transaction_id: Optional[UUID],
    ) -> Optional[dict]:
        row = await self.conn.fetchrow(
            """
            UPDATE savings_proposals
            SET status = $1::proposal_status,
                final_amount = $2,
                reviewed_by = $3,
                reviewed_at = now(),
                transaction_id = $4
            WHERE id = $5 AND household_id = $6
            RETURNING id, household_id, savings_rule_id, budget_month_id,
                      proposed_amount, final_amount, status, calculation_basis,
                      reviewed_by, reviewed_at, transaction_id,
                      created_at, updated_at
            """,
            status, final_amount, reviewed_by, transaction_id,
            proposal_id, household_id,
        )
        return dict(row) if row else None

    # ── aggregation ──

    async def get_total_income_for_month(
        self, household_id: UUID, budget_month_id: UUID
    ) -> Decimal:
        val = await self.conn.fetchval(
            """
            SELECT COALESCE(SUM(amount), 0)
            FROM transactions
            WHERE household_id = $1
              AND budget_month_id = $2
              AND type = 'income'::transaction_type
            """,
            household_id, budget_month_id,
        )
        return val
