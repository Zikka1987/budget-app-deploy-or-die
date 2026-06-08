from fastapi import APIRouter

from app.api.v1.categories import router as categories_router
from app.api.v1.budgets import router as budgets_router
from app.api.v1.incomes import router as incomes_router
from app.api.v1.expenses import router as expenses_router
from app.api.v1.receipts import router as receipts_router
from app.api.v1.receipt_review import router as receipt_review_router
from app.api.v1.savings import router as savings_router
from app.api.v1.dashboard import router as dashboard_router
from app.api.v1.search import router as search_router
from app.api.v1.households import router as households_router
from app.api.v1.household_settings import router as household_settings_router
from app.api.v1.onboarding import router as onboarding_router
from app.api.v1.invites import router as invites_router

v1_router = APIRouter()

v1_router.include_router(categories_router, prefix="/categories", tags=["categories"])
v1_router.include_router(budgets_router, prefix="/budgets", tags=["budgets"])
v1_router.include_router(incomes_router, prefix="/incomes", tags=["incomes"])
v1_router.include_router(expenses_router, prefix="/expenses", tags=["expenses"])
v1_router.include_router(receipts_router, prefix="/receipts", tags=["receipts"])
v1_router.include_router(receipt_review_router, prefix="/receipt-review", tags=["receipt-review"])
v1_router.include_router(savings_router, prefix="/savings", tags=["savings"])
v1_router.include_router(dashboard_router, prefix="/dashboard", tags=["dashboard"])
v1_router.include_router(search_router, prefix="/search", tags=["search"])
v1_router.include_router(households_router, prefix="/households", tags=["households"])
v1_router.include_router(household_settings_router, prefix="/household-settings", tags=["household-settings"])
v1_router.include_router(onboarding_router, prefix="/onboarding", tags=["onboarding"])
v1_router.include_router(invites_router, prefix="/invites", tags=["invites"])
