from datetime import date
from decimal import Decimal
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.core.auth import AuthContext, get_auth_context
from app.core.database import get_pool
from app.models.enums import ReceiptStatus, TransactionSource, TransactionType
from app.schemas.search import ReceiptSearchResponse, TransactionSearchResponse
from app.services.search_service import SearchService

router = APIRouter()


@router.get("/receipts", response_model=ReceiptSearchResponse)
async def search_receipts(
    merchant: Optional[str] = Query(None, min_length=1, max_length=200),
    category_id: Optional[UUID] = Query(None),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    amount_min: Optional[Decimal] = Query(None, ge=0),
    amount_max: Optional[Decimal] = Query(None, ge=0),
    status: Optional[ReceiptStatus] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    auth: AuthContext = Depends(get_auth_context),
):
    """Search receipts by merchant, date, amount, category, or status."""
    service = SearchService(get_pool())
    return await service.search_receipts(
        household_id=auth.household_id,
        merchant=merchant,
        category_id=category_id,
        date_from=date_from,
        date_to=date_to,
        amount_min=amount_min,
        amount_max=amount_max,
        status=status.value if status else None,
        limit=limit,
        offset=offset,
    )


@router.get("/transactions", response_model=TransactionSearchResponse)
async def search_transactions(
    category_id: Optional[UUID] = Query(None),
    type: Optional[TransactionType] = Query(None),
    source: Optional[TransactionSource] = Query(None),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    amount_min: Optional[Decimal] = Query(None, ge=0),
    amount_max: Optional[Decimal] = Query(None, ge=0),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    auth: AuthContext = Depends(get_auth_context),
):
    """Search transactions by category, type, source, date, or amount."""
    service = SearchService(get_pool())
    return await service.search_transactions(
        household_id=auth.household_id,
        category_id=category_id,
        type=type.value if type else None,
        source=source.value if source else None,
        date_from=date_from,
        date_to=date_to,
        amount_min=amount_min,
        amount_max=amount_max,
        limit=limit,
        offset=offset,
    )
