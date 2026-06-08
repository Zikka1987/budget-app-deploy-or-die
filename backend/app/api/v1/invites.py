"""Household invite endpoints: create, list, revoke (inviter);
lookup, accept (invitee).

Inviter endpoints use AuthContext (household membership required).
Invitee endpoints use UserContext (invitee has no household yet by definition).
"""

from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.core.auth import AuthContext, UserContext, get_auth_context, get_user_context
from app.core.database import get_pool
from app.schemas.households import HouseholdMemberResponse, HouseholdResponse
from app.schemas.invites import (
    InviteAcceptRequest,
    InviteAcceptResponse,
    InviteCreateRequest,
    InviteCreateResponse,
    InviteListResponse,
    InviteLookupRequest,
    InviteLookupResponse,
    InviteSummary,
)
from app.services.invite_service import InviteService

router = APIRouter()


# ── Inviter side ──


@router.post("/", response_model=InviteCreateResponse, status_code=201)
async def create_invite(
    body: InviteCreateRequest,
    auth: AuthContext = Depends(get_auth_context),
):
    service = InviteService(get_pool())
    row = await service.create_invite(auth, body.email)
    return InviteCreateResponse(
        id=row["id"],
        household_id=row["household_id"],
        email=row["email"],
        token=row["token"],
        status=row["status"],
        expires_at=row["expires_at"],
        created_at=row["created_at"],
    )


@router.get("/", response_model=InviteListResponse)
async def list_invites(
    auth: AuthContext = Depends(get_auth_context),
    status_filter: str | None = Query(default=None, alias="status"),
):
    service = InviteService(get_pool())
    rows = await service.list_invites(auth, status_filter)
    return InviteListResponse(
        invites=[
            InviteSummary(
                id=r["id"],
                email=r["email"],
                status=r["status"],
                expires_at=r["expires_at"],
                created_at=r["created_at"],
                accepted_at=r.get("accepted_at"),
                revoked_at=r.get("revoked_at"),
            )
            for r in rows
        ]
    )


@router.delete("/{invite_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_invite(
    invite_id: UUID,
    auth: AuthContext = Depends(get_auth_context),
):
    service = InviteService(get_pool())
    await service.revoke_invite(auth, invite_id)
    return None


# ── Invitee side ──


@router.post("/lookup", response_model=InviteLookupResponse)
async def lookup_invite(
    body: InviteLookupRequest,
    user: UserContext = Depends(get_user_context),
):
    service = InviteService(get_pool())
    data = await service.lookup_invite(user, body.token)
    return InviteLookupResponse(**data)


@router.post("/accept", response_model=InviteAcceptResponse, status_code=201)
async def accept_invite(
    body: InviteAcceptRequest,
    user: UserContext = Depends(get_user_context),
):
    service = InviteService(get_pool())
    result = await service.accept_invite(user, body.token, body.display_name)
    return InviteAcceptResponse(
        household=HouseholdResponse(**result["household"]),
        member=HouseholdMemberResponse(**result["member"]),
    )
