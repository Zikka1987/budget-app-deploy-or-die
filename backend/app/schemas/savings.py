from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel

from app.models.enums import SavingsRuleType, ProposalStatus


class SavingsRuleCreate(BaseModel):
    category_id: UUID
    rule_type: SavingsRuleType
    label: str
    percent_value: Optional[Decimal] = None
    fixed_amount: Optional[Decimal] = None


class SavingsRuleUpdate(BaseModel):
    label: Optional[str] = None
    percent_value: Optional[Decimal] = None
    fixed_amount: Optional[Decimal] = None
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
    amount: Decimal
    transaction_date: date
    description: Optional[str] = None
    details: Optional[str] = None


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
    final_amount: Optional[Decimal] = None
