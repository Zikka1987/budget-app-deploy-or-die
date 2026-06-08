from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.core.auth import AuthContext, get_auth_context
from app.core.database import get_pool
from app.schemas.incomes import IncomeCreate, IncomeUpdate
from app.services.income_service import IncomeService

router = APIRouter()


@router.get("/")
async def list_incomes(
    budget_month_id: UUID = Query(...),
    auth: AuthContext = Depends(get_auth_context),
):
    service = IncomeService(get_pool())
    incomes = await service.list_incomes(auth.household_id, budget_month_id)
    return {"incomes": incomes}


@router.post("/", status_code=201)
async def create_income(
    body: IncomeCreate,
    auth: AuthContext = Depends(get_auth_context),
):
    service = IncomeService(get_pool())
    txn = await service.create_income(
        household_id=auth.household_id,
        user_id=auth.user_id,
        category_id=body.category_id,
        amount=body.amount,
        transaction_date=body.transaction_date,
        description=body.description,
        details=body.details,
    )
    return txn


@router.put("/{transaction_id}")
async def update_income(
    transaction_id: UUID,
    body: IncomeUpdate,
    auth: AuthContext = Depends(get_auth_context),
):
    service = IncomeService(get_pool())
    txn = await service.update_income(
        txn_id=transaction_id,
        household_id=auth.household_id,
        category_id=body.category_id,
        amount=body.amount,
        transaction_date=body.transaction_date,
        description=body.description if body.description is not None else ...,
        details=body.details if body.details is not None else ...,
    )
    return txn


@router.delete("/{transaction_id}", status_code=204)
async def delete_income(
    transaction_id: UUID,
    auth: AuthContext = Depends(get_auth_context),
):
    service = IncomeService(get_pool())
    await service.delete_income(transaction_id, auth.household_id)
