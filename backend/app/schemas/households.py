"""Request/response schemas for household and household-settings endpoints."""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class HouseholdCreate(BaseModel):
    household_name: str = Field(..., min_length=1, max_length=100)
    display_name: str = Field(..., min_length=1, max_length=100)


class HouseholdResponse(BaseModel):
    id: UUID
    name: str
    created_at: datetime


class HouseholdMemberResponse(BaseModel):
    id: UUID
    household_id: UUID
    user_id: UUID
    display_name: str
    role: str
    joined_at: datetime


class HouseholdSettingsResponse(BaseModel):
    id: UUID
    household_id: UUID
    currency: str
    shift_late_income: bool
    late_income_cutoff_day: Optional[int]
    created_at: datetime
    updated_at: datetime


class HouseholdSettingsUpdate(BaseModel):
    shift_late_income: Optional[bool] = None
    late_income_cutoff_day: Optional[int] = Field(None, ge=1, le=28)


class HouseholdCreateResponse(BaseModel):
    household: HouseholdResponse
    member: HouseholdMemberResponse
    settings: HouseholdSettingsResponse
