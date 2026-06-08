from fastapi import APIRouter, Depends, Query

from app.core.auth import AuthContext, get_auth_context
from app.core.database import get_pool
from app.schemas.dashboard import DashboardSummary
from app.services.dashboard_service import DashboardService

router = APIRouter()


@router.get("/summary", response_model=DashboardSummary)
async def get_dashboard_summary(
    year: int = Query(..., ge=2000, le=2100),
    month: int = Query(..., ge=1, le=12),
    auth: AuthContext = Depends(get_auth_context),
):
    """Get monthly dashboard: totals, budget vs actual, savings rate, balance metrics."""
    service = DashboardService(get_pool())
    data = await service.get_summary(auth.household_id, year, month)
    return data
