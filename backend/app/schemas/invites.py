"""Request/response schemas for invite endpoints."""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.households import HouseholdMemberResponse, HouseholdResponse


# ── Inviter side ──


class InviteCreateRequest(BaseModel):
    # Email format is validated in the service layer so we avoid the
    # email-validator runtime dependency pulled in by pydantic EmailStr.
    email: str = Field(..., min_length=3, max_length=254)


class InviteCreateResponse(BaseModel):
    id: UUID
    household_id: UUID
    email: str
    token: str
    status: str
    expires_at: datetime
    created_at: datetime


class InviteSummary(BaseModel):
    id: UUID
    email: str
    status: str
    expires_at: datetime
    created_at: datetime
    accepted_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None


class InviteListResponse(BaseModel):
    invites: list[InviteSummary]


# ── Invitee side ──


class InviteLookupRequest(BaseModel):
    token: str = Field(..., min_length=1, max_length=200)


class InviteLookupResponse(BaseModel):
    household_name: str
    email: str
    expires_at: datetime
    status: str


class InviteAcceptRequest(BaseModel):
    token: str = Field(..., min_length=1, max_length=200)
    display_name: str = Field(..., min_length=1, max_length=100)


class InviteAcceptResponse(BaseModel):
    household: HouseholdResponse
    member: HouseholdMemberResponse
