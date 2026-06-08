"""Service for category CRUD with alias management."""

from typing import Optional
from uuid import UUID

import asyncpg

from app.core.exceptions import ConflictError, NotFoundError
from app.repositories.categories import CategoryRepository


class CategoryService:
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def list_categories(
        self,
        household_id: UUID,
        type_filter: Optional[str] = None,
        include_archived: bool = False,
    ) -> list[dict]:
        async with self.pool.acquire() as conn:
            repo = CategoryRepository(conn)
            return await repo.list_by_household(household_id, type_filter, include_archived)

    async def get_category(self, category_id: UUID, household_id: UUID) -> dict:
        async with self.pool.acquire() as conn:
            repo = CategoryRepository(conn)
            cat = await repo.get_by_id(category_id, household_id)
            if not cat:
                raise NotFoundError(f"Category {category_id} not found")
            return cat

    async def create_category(
        self,
        household_id: UUID,
        type: str,
        name: str,
        icon: Optional[str] = None,
        sort_order: int = 0,
    ) -> dict:
        async with self.pool.acquire() as conn:
            repo = CategoryRepository(conn)
            if await repo.name_exists(household_id, type, name):
                raise ConflictError(f"Category '{name}' already exists for type '{type}'")
            return await repo.create(household_id, type, name, icon, sort_order)

    async def update_category(
        self,
        category_id: UUID,
        household_id: UUID,
        name: Optional[str] = None,
        icon: Optional[str] = ...,
        sort_order: Optional[int] = None,
    ) -> dict:
        """Update category fields. If name changes, creates alias. All in one transaction."""
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                repo = CategoryRepository(conn)
                cat = await repo.get_by_id(category_id, household_id)
                if not cat:
                    raise NotFoundError(f"Category {category_id} not found")

                is_rename = name is not None and cat["name"] != name

                if is_rename:
                    if cat["archived_at"] is not None:
                        raise ConflictError("Cannot rename an archived category")
                    if await repo.name_exists(household_id, cat["type"], name, exclude_id=category_id):
                        raise ConflictError(f"Category '{name}' already exists for type '{cat['type']}'")
                    await repo.create_alias(category_id, cat["name"])

                # Apply all field changes in one UPDATE
                updated = await repo.update(
                    category_id,
                    household_id,
                    name=name if is_rename else None,
                    icon=icon,
                    sort_order=sort_order,
                )
                return updated

    async def archive_category(self, category_id: UUID, household_id: UUID) -> dict:
        async with self.pool.acquire() as conn:
            repo = CategoryRepository(conn)
            cat = await repo.archive(category_id, household_id)
            if not cat:
                raise NotFoundError(f"Category {category_id} not found or already archived")
            return cat

    async def reorder_categories(self, household_id: UUID, category_ids: list[UUID]) -> None:
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                repo = CategoryRepository(conn)
                await repo.reorder(household_id, category_ids)
