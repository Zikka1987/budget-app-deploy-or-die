from datetime import date
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile

from app.core.auth import AuthContext, get_auth_context
from app.core.database import get_pool
from app.schemas.receipts import ReceiptListItem, ReceiptResponse
from app.services.receipt_service import ReceiptService

router = APIRouter()


@router.post("/upload", response_model=ReceiptResponse, status_code=201)
async def upload_receipt(
    file: UploadFile = File(...),
    store_name: Optional[str] = Form(None),
    receipt_date: Optional[date] = Form(None),
    auth: AuthContext = Depends(get_auth_context),
):
    """Upload a receipt image and create a draft record.

    Accepts JPEG, PNG, WebP, or PDF up to 10 MB. The file is stored in a
    private Supabase Storage bucket scoped to the household, and a receipts
    row is created with status='uploaded'.
    """
    file_bytes = await file.read()
    service = ReceiptService(get_pool())
    receipt = await service.upload_receipt(
        household_id=auth.household_id,
        user_id=auth.user_id,
        file_bytes=file_bytes,
        mime_type=file.content_type or "",
        file_name=file.filename,
        store_name=store_name,
        receipt_date=receipt_date,
    )
    # Pydantic drops storage_path because it is not declared in ReceiptResponse.
    return ReceiptResponse(**receipt)


@router.get("/", response_model=list[ReceiptListItem])
async def list_receipts(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    auth: AuthContext = Depends(get_auth_context),
):
    """List receipts for the current household, paginated."""
    service = ReceiptService(get_pool())
    receipts = await service.list_receipts(
        auth.household_id, limit=limit, offset=offset
    )
    return [ReceiptListItem(**r) for r in receipts]


@router.get("/{receipt_id}", response_model=ReceiptResponse)
async def get_receipt(
    receipt_id: UUID,
    auth: AuthContext = Depends(get_auth_context),
):
    """Get receipt details with a short-lived signed URL for image viewing."""
    service = ReceiptService(get_pool())
    receipt = await service.get_receipt(receipt_id, auth.household_id)
    return ReceiptResponse(**receipt)


@router.post("/{receipt_id}/parse", response_model=ReceiptResponse)
async def parse_receipt(
    receipt_id: UUID,
    auth: AuthContext = Depends(get_auth_context),
):
    """Parse an uploaded receipt with the configured AI provider.

    Downloads the stored image, calls Claude vision (or configured provider),
    persists extracted metadata and line items, and transitions status to
    'ocr_complete'.

    Failure handling depends on the prior status:
    - If the receipt was previously 'uploaded' or 'failed' and parsing fails,
      the receipt transitions to 'failed' with an error_message and returns 502.
    - If the receipt was previously 'ocr_complete' (re-parse case) and parsing
      fails, the last good OCR data and items are preserved, status is
      reverted to 'ocr_complete', and 502 is returned so the caller knows the
      re-parse attempt failed.

    Returns 409 if the receipt is in 'processing', 'reviewed', or 'posted'.
    """
    service = ReceiptService(get_pool())
    receipt = await service.parse_receipt(receipt_id, auth.household_id)
    return ReceiptResponse(**receipt)


@router.post("/{receipt_id}/categorize", response_model=ReceiptResponse)
async def categorize_receipt(
    receipt_id: UUID,
    auth: AuthContext = Depends(get_auth_context),
):
    """Run AI categorization on an ocr_complete receipt's items.

    Loads the household's active expense categories, sends them to the AI
    along with the receipt's items, validates the output, and persists a
    full refresh of (suggested_category_id, confidence, requires_review)
    across every item on the receipt. Items without a valid suggestion
    in the new run are reset to (NULL, NULL, True) so no stale data from
    a previous run survives.

    Status must be 'ocr_complete' (else 409). Receipt status is NOT
    changed by this endpoint — it stays 'ocr_complete'. User review and
    the transition to 'reviewed'/'posted' belong to the next phase.

    Even when every item ends up with requires_review=False, the receipt
    still requires user review before any transactions are posted.
    requires_review is a per-item UI hint, not a global review bypass.
    """
    service = ReceiptService(get_pool())
    receipt = await service.categorize_receipt(receipt_id, auth.household_id)
    return ReceiptResponse(**receipt)
