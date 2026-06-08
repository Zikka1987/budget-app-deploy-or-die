"""Household creation and read endpoints."""

from fastapi import APIRouter, Depends

from app.core.auth import AuthContext, UserContext, get_auth_context, get_user_context
from app.core.database import get_pool
from app.schemas.households import (
    HouseholdCreate,
    HouseholdCreateResponse,
    HouseholdMemberResponse,
    HouseholdResponse,
    HouseholdSettingsResponse,
)
from app.services.household_service import HouseholdService

router = APIRouter()


@router.post("/", response_model=HouseholdCreateResponse, status_code=201)
async def create_household(
    body: HouseholdCreate,
    user: UserContext = Depends(get_user_context),
):
    service = HouseholdService(get_pool())
    result = await service.create_household(
        user_id=user.user_id,
        household_name=body.household_name,
        display_name=body.display_name,
    )
    return HouseholdCreateResponse(
        household=HouseholdResponse(**result["household"]),
        member=HouseholdMemberResponse(**result["member"]),
        settings=HouseholdSettingsResponse(**result["settings"]),
    )


@router.get("/me", response_model=HouseholdResponse)
async def get_my_household(
    auth: AuthContext = Depends(get_auth_context),
):
    service = HouseholdService(get_pool())
    household = await service.get_my_household(auth.household_id)
    return HouseholdResponse(**household)
