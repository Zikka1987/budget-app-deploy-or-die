from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class BudgetMonthInitialize(BaseModel):
    month: date


class BudgetLineUpdate(BaseModel):
    planned_amount: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    notes: Optional[str] = Field(default=None, max_length=1000)


class BudgetLineResponse(BaseModel):
    id: UUID
    category_id: UUID
    category_name: str
    planned_amount: Decimal
    actual_amount: Decimal
    notes: Optional[str]


class BudgetMonthResponse(BaseModel):
    id: UUID
    month: date
    is_closed: bool
    lines: list[BudgetLineResponse]
    created_at: datetime
