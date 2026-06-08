"""Request/response schemas for onboarding status endpoint."""

from pydantic import BaseModel


class OnboardingStatusResponse(BaseModel):
    has_household: bool
    has_income_category: bool
    has_expense_category: bool
    has_savings_category: bool
    is_ready: bool
