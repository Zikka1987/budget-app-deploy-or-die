from uuid import UUID

from fastapi import APIRouter, Depends

from app.core.auth import AuthContext, get_auth_context
from app.core.database import get_pool
from app.schemas.budgets import (
    BudgetMonthInitialize,
    BudgetLineUpdate,
)
from app.services.budget_service import BudgetService

router = APIRouter()


@router.get("/months")
async def list_budget_months(auth: AuthContext = Depends(get_auth_context)):
    service = BudgetService(get_pool())
    months = await service.list_months(auth.household_id)
    return {"months": months}


@router.post("/months/initialize", status_code=201)
async def initialize_month(
    body: BudgetMonthInitialize,
    auth: AuthContext = Depends(get_auth_context),
):
    service = BudgetService(get_pool())
    month = await service.initialize_month(auth.household_id, body.month)
    return month


@router.get("/months/{month_id}")
async def get_budget_month(
    month_id: UUID,
    auth: AuthContext = Depends(get_auth_context),
):
    service = BudgetService(get_pool())
    return await service.get_month_detail(month_id, auth.household_id)


@router.put("/months/{month_id}/lines/{category_id}")
async def upsert_budget_line(
    month_id: UUID,
    category_id: UUID,
    body: BudgetLineUpdate,
    auth: AuthContext = Depends(get_auth_context),
):
    service = BudgetService(get_pool())
    line = await service.upsert_budget_line(
        month_id, auth.household_id, category_id, body.planned_amount, body.notes,
    )
    return line


@router.put("/lines/{line_id}")
async def update_budget_line(
    line_id: UUID,
    body: BudgetLineUpdate,
    auth: AuthContext = Depends(get_auth_context),
):
    service = BudgetService(get_pool())
    line = await service.update_budget_line(
        line_id, auth.household_id, body.planned_amount, body.notes,
    )
    return line
