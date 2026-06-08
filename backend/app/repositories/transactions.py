"""Repository for transaction_groups and transactions tables."""

from datetime import date
from decimal import Decimal
from typing import Optional
from uuid import UUID

from app.repositories.base import Connection


class TransactionRepository:
    def __init__(self, conn: Connection):
        self.conn = conn

    # ── transaction_groups ──

    async def create_group(
        self,
        household_id: UUID,
        source: str,
        idempotency_key: str,
        created_by: UUID,
        receipt_id: Optional[UUID] = None,
        description: Optional[str] = None,
    ) -> dict:
        row = await self.conn.fetchrow(
            """
            INSERT INTO transaction_groups
                (household_id, source, idempotency_key, created_by, receipt_id, description)
            VALUES ($1, $2::transaction_source, $3, $4, $5, $6)
            RETURNING id, household_id, source, idempotency_key, created_by,
                      receipt_id, description, created_at
            """,
            household_id, source, idempotency_key, created_by, receipt_id, description,
        )
        return dict(row)

    async def get_group_by_idempotency_key(self, key: str) -> Optional[dict]:
        row = await self.conn.fetchrow(
            """
            SELECT id, household_id, source, idempotency_key, created_by,
                   receipt_id, description, created_at
            FROM transaction_groups
            WHERE idempotency_key = $1
            """,
            key,
        )
        return dict(row) if row else None

    async def count_by_group(self, group_id: UUID) -> int:
        """Count the number of transactions in a group."""
        val = await self.conn.fetchval(
            "SELECT COUNT(*) FROM transactions WHERE group_id = $1",
            group_id,
        )
        return val or 0

    # ── transactions ──

    async def create_transaction(
        self,
        group_id: UUID,
        household_id: UUID,
        type: str,
        category_id: UUID,
        amount: Decimal,
        transaction_date: date,
        effective_date: date,
        source: str,
        posted_by: UUID,
        budget_month_id: Optional[UUID] = None,
        description: Optional[str] = None,
        details: Optional[str] = None,
        savings_proposal_id: Optional[UUID] = None,
    ) -> dict:
        row = await self.conn.fetchrow(
            """
            INSERT INTO transactions
                (group_id, household_id, type, category_id, amount,
                 transaction_date, effective_date, source, posted_by,
                 budget_month_id, description, details, savings_proposal_id)
            VALUES ($1, $2, $3::transaction_type, $4, $5, $6, $7,
                    $8::transaction_source, $9, $10, $11, $12, $13)
            RETURNING id, group_id, household_id, type, category_id, amount,
                      transaction_date, effective_date, source, posted_by,
                      budget_month_id, description, details, savings_proposal_id,
                      created_at, updated_at
            """,
            group_id, household_id, type, category_id, amount,
            transaction_date, effective_date, source, posted_by,
            budget_month_id, description, details, savings_proposal_id,
        )
        return dict(row)

    async def get_transaction(self, txn_id: UUID, household_id: UUID) -> Optional[dict]:
        row = await self.conn.fetchrow(
            """
            SELECT t.id, t.group_id, t.household_id, t.type, t.category_id, t.amount,
                   t.transaction_date, t.effective_date, t.source, t.posted_by,
                   t.budget_month_id, t.description, t.details, t.savings_proposal_id,
                   t.created_at, t.updated_at,
                   c.name AS category_name
            FROM transactions t
            JOIN categories c ON c.id = t.category_id
            WHERE t.id = $1 AND t.household_id = $2
            """,
            txn_id, household_id,
        )
        return dict(row) if row else None

    async def list_by_type_and_month(
        self,
        household_id: UUID,
        type: str,
        budget_month_id: UUID,
    ) -> list[dict]:
        rows = await self.conn.fetch(
            """
            SELECT t.id, t.group_id, t.household_id, t.type, t.category_id, t.amount,
                   t.transaction_date, t.effective_date, t.source, t.posted_by,
                   t.budget_month_id, t.description, t.details,
                   t.created_at, t.updated_at,
                   c.name AS category_name
            FROM transactions t
            JOIN categories c ON c.id = t.category_id
            WHERE t.household_id = $1 AND t.type = $2::transaction_type
                  AND t.budget_month_id = $3
            ORDER BY t.effective_date DESC, t.created_at DESC
            """,
            household_id, type, budget_month_id,
        )
        return [dict(r) for r in rows]

    async def update_transaction(
        self,
        txn_id: UUID,
        household_id: UUID,
        category_id: Optional[UUID] = None,
        amount: Optional[Decimal] = None,
        transaction_date: Optional[date] = None,
        effective_date: Optional[date] = None,
        budget_month_id: Optional[UUID] = None,
        description: Optional[str] = ...,
        details: Optional[str] = ...,
    ) -> Optional[dict]:
        sets = []
        params: list = []
        idx = 1
        if category_id is not None:
            sets.append(f"category_id = ${idx}")
            params.append(category_id)
            idx += 1
        if amount is not None:
            sets.append(f"amount = ${idx}")
            params.append(amount)
            idx += 1
        if transaction_date is not None:
            sets.append(f"transaction_date = ${idx}")
            params.append(transaction_date)
            idx += 1
        if effective_date is not None:
            sets.append(f"effective_date = ${idx}")
            params.append(effective_date)
            idx += 1
        if budget_month_id is not None:
            sets.append(f"budget_month_id = ${idx}")
            params.append(budget_month_id)
            idx += 1
        if description is not ...:
            sets.append(f"description = ${idx}")
            params.append(description)
            idx += 1
        if details is not ...:
            sets.append(f"details = ${idx}")
            params.append(details)
            idx += 1
        if not sets:
            return await self.get_transaction(txn_id, household_id)
        params.append(txn_id)
        params.append(household_id)
        query = f"""
            UPDATE transactions SET {', '.join(sets)}
            WHERE id = ${idx} AND household_id = ${idx + 1}
            RETURNING id, group_id, household_id, type, category_id, amount,
                      transaction_date, effective_date, source, posted_by,
                      budget_month_id, description, details, savings_proposal_id,
                      created_at, updated_at
        """
        row = await self.conn.fetchrow(query, *params)
        return dict(row) if row else None

    async def delete_transaction(self, txn_id: UUID, household_id: UUID) -> bool:
        result = await self.conn.execute(
            "DELETE FROM transactions WHERE id = $1 AND household_id = $2",
            txn_id, household_id,
        )
        return result == "DELETE 1"

    async def delete_group(self, group_id: UUID, household_id: UUID) -> bool:
        """Delete a transaction group and its child transactions (CASCADE)."""
        result = await self.conn.execute(
            "DELETE FROM transaction_groups WHERE id = $1 AND household_id = $2",
            group_id, household_id,
        )
        return result == "DELETE 1"

    # ── dashboard aggregation ──

    async def sum_by_type_and_category(
        self, household_id: UUID, budget_month_id: UUID
    ) -> list[dict]:
        """Sum transaction amounts grouped by type and category for a budget month.

        Returns all categories with actual transactions, including those
        that have no corresponding budget line.
        """
        rows = await self.conn.fetch(
            """
            SELECT t.type, t.category_id, c.name AS category_name,
                   SUM(t.amount) AS total
            FROM transactions t
            JOIN categories c ON c.id = t.category_id
            WHERE t.household_id = $1 AND t.budget_month_id = $2
            GROUP BY t.type, t.category_id, c.name
            """,
            household_id, budget_month_id,
        )
        return [dict(r) for r in rows]
