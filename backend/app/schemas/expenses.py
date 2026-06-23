from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class ExpenseCreate(BaseModel):
    category_id: UUID
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    transaction_date: date
    description: Optional[str] = Field(default=None, max_length=255)
    details: Optional[str] = Field(default=None, max_length=1000)


class ExpenseUpdate(BaseModel):
    category_id: Optional[UUID] = None
    amount: Optional[Decimal] = Field(default=None, gt=0, max_digits=12, decimal_places=2)
    transaction_date: Optional[date] = None
    description: Optional[str] = Field(default=None, max_length=255)
    details: Optional[str] = Field(default=None, max_length=1000)


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
