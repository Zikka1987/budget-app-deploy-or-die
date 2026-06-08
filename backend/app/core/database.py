"""Database access: asyncpg pool for queries, Supabase client for Auth + Storage.

asyncpg and supabase are imported lazily inside the functions that use them.
This keeps the module importable in test environments where those packages
are not installed, so service tests can monkeypatch get_supabase() without
triggering a real import.
"""

from typing import Any, Optional

from app.core.config import settings

_pool: Optional[Any] = None
_supabase: Optional[Any] = None


async def init_db_pool() -> Any:
    """Create the asyncpg connection pool. Call once at app startup."""
    import asyncpg

    global _pool
    _pool = await asyncpg.create_pool(
        dsn=settings.database_url,
        min_size=settings.database_pool_min,
        max_size=settings.database_pool_max,
    )
    return _pool


async def close_db_pool() -> None:
    """Close the asyncpg connection pool. Call at app shutdown."""
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


def get_pool() -> Any:
    """Get the asyncpg connection pool. Raises if not initialized."""
    if _pool is None:
        raise RuntimeError("Database pool not initialized. Call init_db_pool() first.")
    return _pool


def get_supabase() -> Any:
    """Get the Supabase client (for Auth + Storage only)."""
    from supabase import create_client

    global _supabase
    if _supabase is None:
        _supabase = create_client(
            settings.supabase_url,
            settings.supabase_service_role_key,
        )
    return _supabase
