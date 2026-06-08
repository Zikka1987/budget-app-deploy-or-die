"""Service for searching receipts and transactions."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Optional
from uuid import UUID

from app.core.exceptions import ValidationError
from app.repositories.search import SearchRepository

if TYPE_CHECKING:
    import asyncpg


class SearchService:
    def __init__(self, pool: "asyncpg.Pool"):
        self.pool = pool

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
    ) -> dict:
        _validate_ranges(date_from, date_to, amount_min, amount_max)

        async with self.pool.acquire() as conn:
            repo = SearchRepository(conn)
            rows, total = await repo.search_receipts(
                household_id=household_id,
                merchant=merchant,
                category_id=category_id,
                date_from=date_from,
                date_to=date_to,
                amount_min=amount_min,
                amount_max=amount_max,
                status=status,
                limit=limit,
                offset=offset,
            )
            return {"results": rows, "total": total}

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
    ) -> dict:
        _validate_ranges(date_from, date_to, amount_min, amount_max)

        async with self.pool.acquire() as conn:
            repo = SearchRepository(conn)
            rows, total = await repo.search_transactions(
                household_id=household_id,
                category_id=category_id,
                type=type,
                source=source,
                date_from=date_from,
                date_to=date_to,
                amount_min=amount_min,
                amount_max=amount_max,
                limit=limit,
                offset=offset,
            )
            return {"results": rows, "total": total}


def _validate_ranges(
    date_from: Optional[date],
    date_to: Optional[date],
    amount_min: Optional[Decimal],
    amount_max: Optional[Decimal],
) -> None:
    if date_from is not None and date_to is not None and date_from > date_to:
        raise ValidationError("date_from must be <= date_to")
    if amount_min is not None and amount_max is not None and amount_min > amount_max:
        raise ValidationError("amount_min must be <= amount_max")
