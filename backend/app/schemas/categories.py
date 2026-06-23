from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.enums import TransactionType


class CategoryCreate(BaseModel):
    type: TransactionType
    name: str = Field(min_length=1, max_length=100)
    icon: Optional[str] = Field(default=None, max_length=50)
    sort_order: int = Field(default=0, ge=0, le=10000)


class CategoryUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    icon: Optional[str] = Field(default=None, max_length=50)
    sort_order: Optional[int] = Field(default=None, ge=0, le=10000)


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
    category_ids: list[UUID] = Field(min_length=1, max_length=200)
