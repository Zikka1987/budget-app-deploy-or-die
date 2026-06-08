from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel

from app.models.enums import ReceiptStatus, TransactionType, TransactionSource


class ReceiptSearchResult(BaseModel):
    id: UUID
    store_name: Optional[str]
    receipt_date: Optional[date]
    total_amount: Optional[Decimal]
    status: ReceiptStatus
    created_at: datetime


class TransactionSearchResult(BaseModel):
    id: UUID
    type: TransactionType
    source: TransactionSource
    category_id: UUID
    category_name: str
    amount: Decimal
    description: Optional[str]
    transaction_date: date
    effective_date: date
    store_name: Optional[str]
    created_at: datetime


class ReceiptSearchResponse(BaseModel):
    results: list[ReceiptSearchResult]
    total: int


class TransactionSearchResponse(BaseModel):
    results: list[TransactionSearchResult]
    total: int
