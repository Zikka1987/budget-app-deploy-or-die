from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.core.auth import AuthContext, get_auth_context
from app.core.database import get_pool
from app.models.enums import TransactionType
from app.schemas.categories import (
    CategoryCreate,
    CategoryUpdate,
    CategoryReorder,
    CategoryResponse,
)
from app.services.category_service import CategoryService

router = APIRouter()


def _to_response(cat: dict) -> CategoryResponse:
    return CategoryResponse(**cat)


@router.get("/", response_model=list[CategoryResponse])
async def list_categories(
    type: Optional[TransactionType] = Query(None),
    include_archived: bool = Query(False),
    auth: AuthContext = Depends(get_auth_context),
):
    service = CategoryService(get_pool())
    cats = await service.list_categories(
        auth.household_id,
        type_filter=type.value if type else None,
        include_archived=include_archived,
    )
    return [_to_response(c) for c in cats]


@router.post("/", response_model=CategoryResponse, status_code=201)
async def create_category(
    body: CategoryCreate,
    auth: AuthContext = Depends(get_auth_context),
):
    service = CategoryService(get_pool())
    cat = await service.create_category(
        auth.household_id,
        type=body.type.value,
        name=body.name,
        icon=body.icon,
        sort_order=body.sort_order,
    )
    return _to_response(cat)


# /reorder MUST come before /{category_id} to avoid path collision
@router.put("/reorder", status_code=204)
async def reorder_categories(
    body: CategoryReorder,
    auth: AuthContext = Depends(get_auth_context),
):
    service = CategoryService(get_pool())
    await service.reorder_categories(auth.household_id, body.category_ids)


@router.get("/{category_id}", response_model=CategoryResponse)
async def get_category(
    category_id: UUID,
    auth: AuthContext = Depends(get_auth_context),
):
    service = CategoryService(get_pool())
    cat = await service.get_category(category_id, auth.household_id)
    return _to_response(cat)


@router.put("/{category_id}", response_model=CategoryResponse)
async def update_category(
    category_id: UUID,
    body: CategoryUpdate,
    auth: AuthContext = Depends(get_auth_context),
):
    service = CategoryService(get_pool())
    cat = await service.update_category(
        category_id,
        auth.household_id,
        name=body.name,
        icon=body.icon if body.icon is not None else ...,
        sort_order=body.sort_order,
    )
    return _to_response(cat)


@router.post("/{category_id}/archive", response_model=CategoryResponse)
async def archive_category(
    category_id: UUID,
    auth: AuthContext = Depends(get_auth_context),
):
    service = CategoryService(get_pool())
    cat = await service.archive_category(category_id, auth.household_id)
    return _to_response(cat)
