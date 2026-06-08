from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.core.auth import AuthContext, get_auth_context
from app.core.database import get_pool
from app.schemas.expenses import ExpenseCreate, ExpenseUpdate
from app.services.expense_service import ExpenseService

router = APIRouter()


@router.get("/")
async def list_expenses(
    budget_month_id: UUID = Query(...),
    auth: AuthContext = Depends(get_auth_context),
):
    service = ExpenseService(get_pool())
    expenses = await service.list_expenses(auth.household_id, budget_month_id)
    return {"expenses": expenses}


@router.post("/", status_code=201)
async def create_expense(
    body: ExpenseCreate,
    auth: AuthContext = Depends(get_auth_context),
):
    service = ExpenseService(get_pool())
    txn = await service.create_expense(
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
async def update_expense(
    transaction_id: UUID,
    body: ExpenseUpdate,
    auth: AuthContext = Depends(get_auth_context),
):
    service = ExpenseService(get_pool())
    txn = await service.update_expense(
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
async def delete_expense(
    transaction_id: UUID,
    auth: AuthContext = Depends(get_auth_context),
):
    service = ExpenseService(get_pool())
    await service.delete_expense(transaction_id, auth.household_id)
