"""Repository for receipt and transaction search queries."""

from datetime import date
from decimal import Decimal
from typing import Optional
from uuid import UUID

from app.repositories.base import Connection


class SearchRepository:
    def __init__(self, conn: Connection):
        self.conn = conn

    async def search_receipts(
        self,
        household_id: UUID,
        merchant: Optional[str] = None,
        category_id: Optional[UUID] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        amount_min: Optional[Decimal] = None,
        amount_max: Optional[Decimal] = None,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        clauses = ["r.household_id = $1"]
        params: list = [household_id]
        idx = 2

        if merchant is not None:
            clauses.append(f"r.store_name ILIKE ${idx}")
            params.append(f"%{merchant}%")
            idx += 1

        if category_id is not None:
            clauses.append(
                f"EXISTS (SELECT 1 FROM receipt_items ri "
                f"WHERE ri.receipt_id = r.id "
                f"AND ri.user_confirmed_category_id = ${idx})"
            )
            params.append(category_id)
            idx += 1

        if date_from is not None:
            clauses.append(f"r.receipt_date >= ${idx}")
            params.append(date_from)
            idx += 1

        if date_to is not None:
            clauses.append(f"r.receipt_date <= ${idx}")
            params.append(date_to)
            idx += 1

        if amount_min is not None:
            clauses.append(f"r.total_amount >= ${idx}")
            params.append(amount_min)
            idx += 1

        if amount_max is not None:
            clauses.append(f"r.total_amount <= ${idx}")
            params.append(amount_max)
            idx += 1

        if status is not None:
            clauses.append(f"r.status = ${idx}::receipt_status")
            params.append(status)
            idx += 1

        where = " AND ".join(clauses)

        total = await self.conn.fetchval(
            f"SELECT COUNT(*) FROM receipts r WHERE {where}",
            *params,
        )

        params.append(limit)
        params.append(offset)
        rows = await self.conn.fetch(
            f"""
            SELECT r.id, r.store_name, r.receipt_date, r.total_amount,
                   r.status, r.created_at
            FROM receipts r
            WHERE {where}
            ORDER BY r.receipt_date DESC NULLS LAST, r.created_at DESC
            LIMIT ${idx} OFFSET ${idx + 1}
            """,
            *params,
        )

        return [dict(r) for r in rows], total or 0

    async def search_transactions(
        self,
        household_id: UUID,
        category_id: Optional[UUID] = None,
        type: Optional[str] = None,
        source: Optional[str] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        amount_min: Optional[Decimal] = None,
        amount_max: Optional[Decimal] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        clauses = ["t.household_id = $1"]
        params: list = [household_id]
        idx = 2

        if category_id is not None:
            clauses.append(f"t.category_id = ${idx}")
            params.append(category_id)
            idx += 1

        if type is not None:
            clauses.append(f"t.type = ${idx}::transaction_type")
            params.append(type)
            idx += 1

        if source is not None:
            clauses.append(f"t.source = ${idx}::transaction_source")
            params.append(source)
            idx += 1

        if date_from is not None:
            clauses.append(f"t.effective_date >= ${idx}")
            params.append(date_from)
            idx += 1

        if date_to is not None:
            clauses.append(f"t.effective_date <= ${idx}")
            params.append(date_to)
            idx += 1

        if amount_min is not None:
            clauses.append(f"t.amount >= ${idx}")
            params.append(amount_min)
            idx += 1

        if amount_max is not None:
            clauses.append(f"t.amount <= ${idx}")
            params.append(amount_max)
            idx += 1

        where = " AND ".join(clauses)

        total = await self.conn.fetchval(
            f"SELECT COUNT(*) FROM transactions t WHERE {where}",
            *params,
        )

        params.append(limit)
        params.append(offset)
        rows = await self.conn.fetch(
            f"""
            SELECT t.id, t.type, t.source, t.category_id,
                   c.name AS category_name,
                   t.amount, t.description,
                   t.transaction_date, t.effective_date,
                   r.store_name,
                   t.created_at
            FROM transactions t
            JOIN categories c ON c.id = t.category_id
            LEFT JOIN transaction_groups tg ON tg.id = t.group_id
            LEFT JOIN receipts r ON r.id = tg.receipt_id
            WHERE {where}
            ORDER BY t.effective_date DESC, t.created_at DESC
            LIMIT ${idx} OFFSET ${idx + 1}
            """,
            *params,
        )

        return [dict(r) for r in rows], total or 0
