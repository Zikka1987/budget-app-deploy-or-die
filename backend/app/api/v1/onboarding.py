"""Onboarding status endpoint."""

from fastapi import APIRouter, Depends

from app.core.auth import UserContext, get_user_context
from app.core.database import get_pool
from app.schemas.onboarding import OnboardingStatusResponse
from app.services.onboarding_service import OnboardingService

router = APIRouter()


@router.get("/status", response_model=OnboardingStatusResponse)
async def get_onboarding_status(
    user: UserContext = Depends(get_user_context),
):
    service = OnboardingService(get_pool())
    status = await service.get_status(user.user_id)
    return OnboardingStatusResponse(**status)
