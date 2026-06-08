"""Household settings read/update endpoints."""

from fastapi import APIRouter, Depends

from app.core.auth import AuthContext, get_auth_context
from app.core.database import get_pool
from app.schemas.households import HouseholdSettingsResponse, HouseholdSettingsUpdate
from app.services.household_service import HouseholdService

router = APIRouter()


@router.get("/", response_model=HouseholdSettingsResponse)
async def get_household_settings(
    auth: AuthContext = Depends(get_auth_context),
):
    service = HouseholdService(get_pool())
    settings = await service.get_settings(auth.household_id)
    return HouseholdSettingsResponse(**settings)


@router.put("/", response_model=HouseholdSettingsResponse)
async def update_household_settings(
    body: HouseholdSettingsUpdate,
    auth: AuthContext = Depends(get_auth_context),
):
    service = HouseholdService(get_pool())
    settings = await service.update_settings(
        household_id=auth.household_id,
        fields_set=body.model_fields_set,
        shift_late_income=body.shift_late_income,
        late_income_cutoff_day=body.late_income_cutoff_day,
    )
    return HouseholdSettingsResponse(**settings)
