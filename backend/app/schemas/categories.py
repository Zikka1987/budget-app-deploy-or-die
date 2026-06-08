from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel

from app.models.enums import TransactionType


class CategoryCreate(BaseModel):
    type: TransactionType
    name: str
    icon: Optional[str] = None
    sort_order: int = 0


class CategoryUpdate(BaseModel):
    name: Optional[str] = None
    icon: Optional[str] = None
    sort_order: Optional[int] = None


class CategoryResponse(BaseModel):
    id: UUID
    household_id: UUID
    type: TransactionType
    name: str
    icon: Optional[str]
    sort_order: int
    archived_at: Optional[datetime]
    created_at: datetime


class CategoryReorder(BaseModel):
    category_ids: list[UUID]
