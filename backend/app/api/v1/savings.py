from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.core.auth import AuthContext, get_auth_context
from app.core.database import get_pool
from app.schemas.savings import (
    GenerateProposalsRequest,
    ManualSavingsCreate,
    ProposalApprove,
    SavingsRuleCreate,
    SavingsRuleUpdate,
)
from app.services.savings_service import SavingsService

router = APIRouter()


# ── rules ──


@router.get("/rules")
async def list_savings_rules(auth: AuthContext = Depends(get_auth_context)):
    """List all savings rules for the household."""
    service = SavingsService(get_pool())
    rules = await service.list_rules(auth.household_id)
    return {"rules": rules}


@router.post("/rules", status_code=201)
async def create_savings_rule(
    body: SavingsRuleCreate,
    auth: AuthContext = Depends(get_auth_context),
):
    """Create a new savings rule (percent_of_income or fixed_monthly)."""
    service = SavingsService(get_pool())
    rule = await service.create_rule(
        household_id=auth.household_id,
        user_id=auth.user_id,
        category_id=body.category_id,
        rule_type=body.rule_type.value,
        label=body.label,
        percent_value=body.percent_value,
        fixed_amount=body.fixed_amount,
    )
    return rule


@router.put("/rules/{rule_id}")
async def update_savings_rule(
    rule_id: UUID,
    body: SavingsRuleUpdate,
    auth: AuthContext = Depends(get_auth_context),
):
    """Update a savings rule."""
    service = SavingsService(get_pool())
    rule = await service.update_rule(
        household_id=auth.household_id,
        rule_id=rule_id,
        fields_set=body.model_fields_set,
        label=body.label,
        percent_value=body.percent_value,
        fixed_amount=body.fixed_amount,
        is_active=body.is_active,
    )
    return rule


# ── proposals ──


@router.post("/proposals/generate")
async def generate_proposals(
    body: GenerateProposalsRequest,
    auth: AuthContext = Depends(get_auth_context),
):
    """Generate savings proposals for a given month. Idempotent."""
    service = SavingsService(get_pool())
    proposals = await service.generate_proposals(
        household_id=auth.household_id,
        user_id=auth.user_id,
        budget_month_id=body.budget_month_id,
    )
    return {"proposals": proposals}


@router.get("/proposals")
async def list_proposals(
    budget_month_id: UUID = Query(...),
    auth: AuthContext = Depends(get_auth_context),
):
    """List savings proposals for a given month."""
    service = SavingsService(get_pool())
    proposals = await service.list_proposals(auth.household_id, budget_month_id)
    return {"proposals": proposals}


@router.post("/proposals/{proposal_id}/approve")
async def approve_proposal(
    proposal_id: UUID,
    body: ProposalApprove,
    auth: AuthContext = Depends(get_auth_context),
):
    """Approve a savings proposal and post as transaction atomically."""
    service = SavingsService(get_pool())
    result = await service.approve_proposal(
        household_id=auth.household_id,
        user_id=auth.user_id,
        proposal_id=proposal_id,
        final_amount=body.final_amount,
    )
    return result


@router.post("/proposals/{proposal_id}/reject")
async def reject_proposal(
    proposal_id: UUID,
    auth: AuthContext = Depends(get_auth_context),
):
    """Reject a savings proposal."""
    service = SavingsService(get_pool())
    result = await service.reject_proposal(
        household_id=auth.household_id,
        user_id=auth.user_id,
        proposal_id=proposal_id,
    )
    return result


@router.post("/manual", status_code=201)
async def create_manual_savings(
    body: ManualSavingsCreate,
    auth: AuthContext = Depends(get_auth_context),
):
    """Create a manual savings entry (direct transaction, no proposal)."""
    service = SavingsService(get_pool())
    txn = await service.create_manual_savings(
        household_id=auth.household_id,
        user_id=auth.user_id,
        category_id=body.category_id,
        amount=body.amount,
        transaction_date=body.transaction_date,
        description=body.description,
        details=body.details,
    )
    return txn
