from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends

from app.core.auth import AuthContext, get_auth_context
from app.core.database import get_pool
from app.schemas.receipts import (
    ReceiptConfirmRequest,
    ReceiptConfirmResponse,
    ReceiptItemResponse,
    ReceiptItemUpdateRequest,
    ReceiptResponse,
)
from app.services.receipt_review_service import ReceiptReviewService
from app.services.receipt_service import ReceiptService

router = APIRouter()


@router.get("/{receipt_id}/payload", response_model=ReceiptResponse)
async def get_review_payload(
    receipt_id: UUID,
    auth: AuthContext = Depends(get_auth_context),
):
    """Get the review payload for an ocr_complete or reviewed receipt.

    Returns the full enriched review view: receipt metadata, items JOINed
    to category names (for both suggested and user-confirmed categories),
    a recomputed list of duplicate_candidates, and a short-lived signed
    URL for the image.

    Returns 409 if the receipt is not in a review-eligible status (must
    be 'ocr_complete' or 'reviewed'). Returns 404 if not found.
    """
    service = ReceiptService(get_pool())
    payload = await service.get_review_payload(receipt_id, auth.household_id)
    return ReceiptResponse(**payload)


@router.put(
    "/{receipt_id}/items/{item_id}", response_model=ReceiptItemResponse
)
async def update_review_item(
    receipt_id: UUID,
    item_id: UUID,
    body: ReceiptItemUpdateRequest,
    auth: AuthContext = Depends(get_auth_context),
):
    """Update a receipt item during review.

    Allows setting/changing user_confirmed_category_id and toggling
    is_excluded. At least one field must be provided. The receipt must
    be in 'ocr_complete' status.
    """
    service = ReceiptReviewService(get_pool())

    kwargs: dict = {"fields_set": body.model_fields_set}
    if "user_confirmed_category_id" in body.model_fields_set:
        kwargs["user_confirmed_category_id"] = body.user_confirmed_category_id
    if "is_excluded" in body.model_fields_set:
        kwargs["is_excluded"] = body.is_excluded

    result = await service.update_item(
        receipt_id, auth.household_id, item_id, **kwargs
    )
    return ReceiptItemResponse(**result)


@router.post("/{receipt_id}/confirm", response_model=ReceiptConfirmResponse)
async def confirm_receipt(
    receipt_id: UUID,
    body: Optional[ReceiptConfirmRequest] = None,
    auth: AuthContext = Depends(get_auth_context),
):
    """Confirm reviewed receipt and create grouped expense transactions.

    Runs ocr_complete → reviewed → posted inside one atomic DB
    transaction. If any step fails, everything rolls back.

    Accepts an optional request body with transaction_date as a fallback
    for when the receipt has no parsed date.
    """
    service = ReceiptReviewService(get_pool())
    transaction_date_override = body.transaction_date if body else None
    result = await service.confirm_receipt(
        receipt_id,
        auth.household_id,
        auth.user_id,
        transaction_date_override,
    )
    return ReceiptConfirmResponse(**result)
