"""Repository for budget_months and budget_lines tables."""

from datetime import date
from decimal import Decimal
from typing import Optional
from uuid import UUID

from app.repositories.base import Connection


class BudgetRepository:
    def __init__(self, conn: Connection):
        self.conn = conn

    # ── budget_months ──

    async def get_month(self, household_id: UUID, month: date) -> Optional[dict]:
        row = await self.conn.fetchrow(
            """
            SELECT id, household_id, month, notes, is_closed, created_at, updated_at
            FROM budget_months
            WHERE household_id = $1 AND month = $2
            """,
            household_id, month,
        )
        return dict(row) if row else None

    async def get_month_by_id(self, month_id: UUID, household_id: UUID) -> Optional[dict]:
        row = await self.conn.fetchrow(
            """
            SELECT id, household_id, month, notes, is_closed, created_at, updated_at
            FROM budget_months
            WHERE id = $1 AND household_id = $2
            """,
            month_id, household_id,
        )
        return dict(row) if row else None

    async def list_months(self, household_id: UUID) -> list[dict]:
        rows = await self.conn.fetch(
            """
            SELECT id, household_id, month, notes, is_closed, created_at, updated_at
            FROM budget_months
            WHERE household_id = $1
            ORDER BY month DESC
            """,
            household_id,
        )
        return [dict(r) for r in rows]

    async def get_previous_month(self, household_id: UUID, before: date) -> Optional[dict]:
        row = await self.conn.fetchrow(
            """
            SELECT id, household_id, month, notes, is_closed, created_at, updated_at
            FROM budget_months
            WHERE household_id = $1 AND month < $2
            ORDER BY month DESC LIMIT 1
            """,
            household_id, before,
        )
        return dict(row) if row else None

    async def create_month(self, household_id: UUID, month: date) -> dict:
        row = await self.conn.fetchrow(
            """
            INSERT INTO budget_months (household_id, month)
            VALUES ($1, $2)
            RETURNING id, household_id, month, notes, is_closed, created_at, updated_at
            """,
            household_id, month,
        )
        return dict(row)

    # ── budget_lines ──

    async def list_lines(self, budget_month_id: UUID) -> list[dict]:
        rows = await self.conn.fetch(
            """
            SELECT bl.id, bl.budget_month_id, bl.category_id, bl.planned_amount,
                   bl.notes, bl.created_at, bl.updated_at,
                   c.name AS category_name, c.type AS category_type
            FROM budget_lines bl
            JOIN categories c ON c.id = bl.category_id
            WHERE bl.budget_month_id = $1
            ORDER BY c.type, c.sort_order, c.name
            """,
            budget_month_id,
        )
        return [dict(r) for r in rows]

    async def create_line(
        self,
        budget_month_id: UUID,
        category_id: UUID,
        planned_amount: Decimal,
    ) -> dict:
        row = await self.conn.fetchrow(
            """
            INSERT INTO budget_lines (budget_month_id, category_id, planned_amount)
            VALUES ($1, $2, $3)
            RETURNING id, budget_month_id, category_id, planned_amount, notes,
                      created_at, updated_at
            """,
            budget_month_id, category_id, planned_amount,
        )
        return dict(row)

    async def upsert_line(
        self,
        budget_month_id: UUID,
        category_id: UUID,
        planned_amount: Decimal,
        notes: Optional[str] = None,
    ) -> dict:
        row = await self.conn.fetchrow(
            """
            INSERT INTO budget_lines (budget_month_id, category_id, planned_amount, notes)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (budget_month_id, category_id)
            DO UPDATE SET planned_amount = EXCLUDED.planned_amount,
                          notes = EXCLUDED.notes
            RETURNING id, budget_month_id, category_id, planned_amount, notes,
                      created_at, updated_at
            """,
            budget_month_id, category_id, planned_amount, notes,
        )
        return dict(row)

    async def update_line(
        self,
        line_id: UUID,
        planned_amount: Decimal,
        notes: Optional[str] = None,
    ) -> Optional[dict]:
        row = await self.conn.fetchrow(
            """
            UPDATE budget_lines SET planned_amount = $1, notes = $2
            WHERE id = $3
            RETURNING id, budget_month_id, category_id, planned_amount, notes,
                      created_at, updated_at
            """,
            planned_amount, notes, line_id,
        )
        return dict(row) if row else None

    async def get_line_by_id(self, line_id: UUID) -> Optional[dict]:
        row = await self.conn.fetchrow(
            """
            SELECT bl.id, bl.budget_month_id, bl.category_id, bl.planned_amount,
                   bl.notes, bl.created_at, bl.updated_at,
                   c.name AS category_name, c.type AS category_type
            FROM budget_lines bl
            JOIN categories c ON c.id = bl.category_id
            WHERE bl.id = $1
            """,
            line_id,
        )
        return dict(row) if row else None
