from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.enums import SavingsRuleType, ProposalStatus


class SavingsRuleCreate(BaseModel):
    category_id: UUID
    rule_type: SavingsRuleType
    label: str = Field(min_length=1, max_length=100)
    percent_value: Optional[Decimal] = Field(default=None, ge=0, max_digits=5, decimal_places=2)
    fixed_amount: Optional[Decimal] = Field(default=None, ge=0, max_digits=12, decimal_places=2)


class SavingsRuleUpdate(BaseModel):
    label: Optional[str] = Field(default=None, min_length=1, max_length=100)
    percent_value: Optional[Decimal] = Field(default=None, ge=0, max_digits=5, decimal_places=2)
    fixed_amount: Optional[Decimal] = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    is_active: Optional[bool] = None


class SavingsRuleResponse(BaseModel):
    id: UUID
    category_id: UUID
    category_name: str
    rule_type: SavingsRuleType
    label: str
    percent_value: Optional[Decimal]
    fixed_amount: Optional[Decimal]
    is_active: bool
    created_at: datetime


class SavingsProposalResponse(BaseModel):
    id: UUID
    savings_rule_id: UUID
    rule_label: str
    budget_month: date
    proposed_amount: Decimal
    final_amount: Optional[Decimal]
    status: ProposalStatus
    calculation_basis: Optional[dict]
    created_at: datetime


class ManualSavingsCreate(BaseModel):
    category_id: UUID
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    transaction_date: date
    description: Optional[str] = Field(default=None, max_length=255)
    details: Optional[str] = Field(default=None, max_length=1000)


class ManualSavingsResponse(BaseModel):
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


class GenerateProposalsRequest(BaseModel):
    budget_month_id: UUID


class ProposalApprove(BaseModel):
    final_amount: Optional[Decimal] = Field(default=None, ge=0, max_digits=12, decimal_places=2)
