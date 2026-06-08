"""Repository for categories and category_aliases tables."""

from typing import Optional
from uuid import UUID

from app.repositories.base import Connection


class CategoryRepository:
    def __init__(self, conn: Connection):
        self.conn = conn

    async def list_by_household(
        self,
        household_id: UUID,
        type_filter: Optional[str] = None,
        include_archived: bool = False,
    ) -> list[dict]:
        query = """
            SELECT id, household_id, type, name, icon, sort_order,
                   archived_at, created_at, updated_at
            FROM categories
            WHERE household_id = $1
        """
        params: list = [household_id]
        idx = 2
        if type_filter:
            query += f" AND type = ${idx}::transaction_type"
            params.append(type_filter)
            idx += 1
        if not include_archived:
            query += " AND archived_at IS NULL"
        query += " ORDER BY type, sort_order, name"
        rows = await self.conn.fetch(query, *params)
        return [dict(r) for r in rows]

    async def get_by_id(self, category_id: UUID, household_id: UUID) -> Optional[dict]:
        row = await self.conn.fetchrow(
            """
            SELECT id, household_id, type, name, icon, sort_order,
                   archived_at, created_at, updated_at
            FROM categories
            WHERE id = $1 AND household_id = $2
            """,
            category_id, household_id,
        )
        return dict(row) if row else None

    async def name_exists(
        self, household_id: UUID, type: str, name: str, exclude_id: Optional[UUID] = None
    ) -> bool:
        query = """
            SELECT 1 FROM categories
            WHERE household_id = $1 AND type = $2::transaction_type AND name = $3
                  AND archived_at IS NULL
        """
        params: list = [household_id, type, name]
        if exclude_id:
            query += " AND id != $4"
            params.append(exclude_id)
        row = await self.conn.fetchval(query, *params)
        return row is not None

    async def create(
        self,
        household_id: UUID,
        type: str,
        name: str,
        icon: Optional[str] = None,
        sort_order: int = 0,
    ) -> dict:
        row = await self.conn.fetchrow(
            """
            INSERT INTO categories (household_id, type, name, icon, sort_order)
            VALUES ($1, $2::transaction_type, $3, $4, $5)
            RETURNING id, household_id, type, name, icon, sort_order,
                      archived_at, created_at, updated_at
            """,
            household_id, type, name, icon, sort_order,
        )
        return dict(row)

    async def update(
        self,
        category_id: UUID,
        household_id: UUID,
        name: Optional[str] = None,
        icon: Optional[str] = ...,
        sort_order: Optional[int] = None,
    ) -> Optional[dict]:
        # Build SET clause dynamically
        sets = []
        params: list = []
        idx = 1
        if name is not None:
            sets.append(f"name = ${idx}")
            params.append(name)
            idx += 1
        if icon is not ...:
            sets.append(f"icon = ${idx}")
            params.append(icon)
            idx += 1
        if sort_order is not None:
            sets.append(f"sort_order = ${idx}")
            params.append(sort_order)
            idx += 1
        if not sets:
            return await self.get_by_id(category_id, household_id)

        params.append(category_id)
        params.append(household_id)
        query = f"""
            UPDATE categories SET {', '.join(sets)}
            WHERE id = ${idx} AND household_id = ${idx + 1}
            RETURNING id, household_id, type, name, icon, sort_order,
                      archived_at, created_at, updated_at
        """
        row = await self.conn.fetchrow(query, *params)
        return dict(row) if row else None

    async def archive(self, category_id: UUID, household_id: UUID) -> Optional[dict]:
        row = await self.conn.fetchrow(
            """
            UPDATE categories SET archived_at = now()
            WHERE id = $1 AND household_id = $2 AND archived_at IS NULL
            RETURNING id, household_id, type, name, icon, sort_order,
                      archived_at, created_at, updated_at
            """,
            category_id, household_id,
        )
        return dict(row) if row else None

    async def reorder(
        self, household_id: UUID, category_ids: list[UUID]
    ) -> None:
        for idx, cat_id in enumerate(category_ids):
            await self.conn.execute(
                """
                UPDATE categories SET sort_order = $1
                WHERE id = $2 AND household_id = $3
                """,
                idx, cat_id, household_id,
            )

    async def create_alias(self, category_id: UUID, alias: str) -> dict:
        row = await self.conn.fetchrow(
            """
            INSERT INTO category_aliases (category_id, alias)
            VALUES ($1, $2)
            RETURNING id, category_id, alias, created_at
            """,
            category_id, alias,
        )
        return dict(row)

    async def list_aliases(self, category_id: UUID) -> list[dict]:
        rows = await self.conn.fetch(
            "SELECT id, category_id, alias, created_at FROM category_aliases WHERE category_id = $1",
            category_id,
        )
        return [dict(r) for r in rows]
