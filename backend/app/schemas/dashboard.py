from datetime import date
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel

from app.models.enums import TransactionType


class CategoryBudgetActual(BaseModel):
    category_id: UUID
    category_name: str
    category_type: TransactionType
    planned: Decimal
    actual: Decimal
    remaining: Decimal
    is_over_budget: bool


class DashboardSummary(BaseModel):
    month: date
    total_planned_income: Decimal
    total_planned_expenses: Decimal
    total_planned_savings: Decimal
    total_actual_income: Decimal
    total_actual_expenses: Decimal
    total_actual_savings: Decimal
    to_be_allocated: Decimal
    actual_balance: Decimal
    plan_coverage: Decimal
    savings_rate: Optional[Decimal]
    income_categories: list[CategoryBudgetActual]
    expense_categories: list[CategoryBudgetActual]
    savings_categories: list[CategoryBudgetActual]
