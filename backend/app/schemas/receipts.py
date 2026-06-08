from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.enums import ReceiptStatus


class ReceiptItemResponse(BaseModel):
    id: UUID
    line_number: Optional[int] = None
    description: str
    quantity: Optional[Decimal] = None
    unit_price: Optional[Decimal] = None
    total_price: Decimal
    suggested_category_id: Optional[UUID] = None
    suggested_category_name: Optional[str] = None  # populated by categorize / review payload
    user_confirmed_category_id: Optional[UUID] = None
    user_confirmed_category_name: Optional[str] = None  # wired up for the review phase
    confidence: Optional[float] = None
    requires_review: bool = True
    is_excluded: bool = False


class DuplicateCandidate(BaseModel):
    id: UUID
    store_name: Optional[str] = None
    receipt_date: Optional[date] = None
    total_amount: Optional[Decimal] = None


class ReceiptListItem(BaseModel):
    """Light receipt item for list responses. No items array, no OCR text."""
    id: UUID
    status: ReceiptStatus
    store_name: Optional[str]
    receipt_date: Optional[date]
    total_amount: Optional[Decimal]
    file_name: Optional[str]
    created_at: datetime
    # NOTE: storage_path is intentionally NOT exposed to clients. It is an
    # internal backend concern, used only for signed URL generation.
    # NOTE: duplicate_candidates is NOT exposed in list responses. Dedup is
    # computed only at parse time. Clients use the detail endpoint to see them.


class ReceiptResponse(BaseModel):
    """Detail response for a single receipt."""
    id: UUID
    status: ReceiptStatus
    store_name: Optional[str]
    receipt_date: Optional[date]
    total_amount: Optional[Decimal]
    file_name: Optional[str]
    mime_type: Optional[str]
    image_url: Optional[str] = None
    items: list[ReceiptItemResponse] = Field(default_factory=list)
    duplicate_candidates: list[DuplicateCandidate] = Field(default_factory=list)
    created_at: datetime
    # NOTE: storage_path is intentionally NOT exposed to clients. Clients use
    # image_url (a short-lived signed URL) to display the receipt image.
    # duplicate_candidates is populated only by POST /parse. Upload/detail
    # endpoints return an empty list.


class ReceiptItemUpdateRequest(BaseModel):
    """Request body for updating a receipt item during review."""
    user_confirmed_category_id: Optional[UUID] = None
    is_excluded: Optional[bool] = None


class ReceiptConfirmRequest(BaseModel):
    """Optional request body for confirming a receipt.

    transaction_date is a fallback for when receipt_date is None
    (OCR couldn't extract a date). If receipt_date exists on the
    receipt, this field is ignored.
    """
    transaction_date: Optional[date] = None


class ReceiptConfirmResponse(BaseModel):
    """Response from the confirm endpoint."""
    transaction_group_id: UUID
    transactions_created: int
    receipt_id: UUID
    status: str
    total_mismatch: bool = False
