from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class ExpenseCreate(BaseModel):
    category_id: UUID
    amount: Decimal
    transaction_date: date
    description: Optional[str] = None
    details: Optional[str] = None


class ExpenseUpdate(BaseModel):
    category_id: Optional[UUID] = None
    amount: Optional[Decimal] = None
    transaction_date: Optional[date] = None
    description: Optional[str] = None
    details: Optional[str] = None


class ExpenseResponse(BaseModel):
    id: UUID
    category_id: UUID
    category_name: str
    amount: Decimal
    transaction_date: date
    effective_date: date
    budget_month: date
    description: Optional[str]
    details: Optional[str]
    created_at: datetime
