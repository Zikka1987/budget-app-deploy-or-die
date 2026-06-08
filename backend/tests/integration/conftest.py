"""Fixtures for real-Postgres integration tests.

Session-scoped: Docker container, schema bootstrap + migrations, connection pool.
Function-scoped: per-test rollback transaction, pool adapter for services.
"""

import asyncio
import os
import subprocess
from pathlib import Path

import pytest
import pytest_asyncio

import asyncpg

from tests.integration.pool_adapter import SingleConnectionPool


def pytest_configure(config):
    config.addinivalue_line("markers", "integration: real Postgres integration tests")


# Ensure app modules can be imported with dummy env vars (same as unit tests).
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon-key")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")

# ── Configuration ──

_CONTAINER_NAME = "budget_test_pg"
_DEFAULT_DSN = "postgresql://postgres:postgres@localhost:5433/budget_test"
TEST_DATABASE_URL = os.environ.get("INTEGRATION_TEST_DB_URL", _DEFAULT_DSN)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]  # backend/
_REPO_ROOT = _PROJECT_ROOT.parent
_MIGRATIONS_DIR = _REPO_ROOT / "supabase" / "migrations"
_BOOTSTRAP_SQL = Path(__file__).resolve().parent / "bootstrap.sql"

# PgBouncer / Supabase pooler: disable prepared statement cache.
_IS_POOLER = "pooler.supabase.com" in TEST_DATABASE_URL
_CACHE_SIZE = 0 if _IS_POOLER else 100


# ── Session fixture: Docker Postgres lifecycle (sync) ──


@pytest.fixture(scope="session")
def _docker_postgres():
    """Start a Postgres 16 container unless an external DB URL is configured."""
    if os.environ.get("INTEGRATION_TEST_DB_URL"):
        yield
        return

    result = subprocess.run(["docker", "info"], capture_output=True, timeout=15)
    if result.returncode != 0:
        pytest.skip("Docker not available; skipping integration tests")

    subprocess.run(["docker", "rm", "-f", _CONTAINER_NAME], capture_output=True)
    subprocess.run(
        [
            "docker", "run", "-d",
            "--name", _CONTAINER_NAME,
            "-p", "5433:5432",
            "-e", "POSTGRES_USER=postgres",
            "-e", "POSTGRES_PASSWORD=postgres",
            "-e", "POSTGRES_DB=budget_test",
            "postgres:16-alpine",
        ],
        check=True, capture_output=True,
    )

    async def _wait():
        for _ in range(30):
            try:
                conn = await asyncpg.connect(TEST_DATABASE_URL)
                await conn.close()
                return
            except (OSError, asyncpg.PostgresError):
                await asyncio.sleep(0.5)
        raise RuntimeError("Postgres container did not become ready in time")

    asyncio.run(_wait())
    yield
    subprocess.run(["docker", "rm", "-f", _CONTAINER_NAME], capture_output=True)


@pytest.fixture(scope="session")
def _apply_migrations(_docker_postgres):
    """Run bootstrap + migrations if the schema doesn't exist yet (sync)."""
    async def _run():
        conn = await asyncpg.connect(TEST_DATABASE_URL, statement_cache_size=_CACHE_SIZE)
        try:
            has_schema = await conn.fetchval(
                "SELECT EXISTS ("
                "  SELECT 1 FROM information_schema.tables "
                "  WHERE table_schema = 'public' AND table_name = 'households'"
                ")"
            )
            if has_schema:
                return
            await conn.execute(_BOOTSTRAP_SQL.read_text(encoding="utf-8"))
            for mf in sorted(_MIGRATIONS_DIR.glob("*.sql")):
                await conn.execute(mf.read_text(encoding="utf-8"))
        finally:
            await conn.close()

    asyncio.run(_run())


# ── Function fixtures ──
# Each test gets its own pool → connection → transaction, all on the
# pytest-asyncio event loop.  The pool is created per-test and closed at
# teardown.  This avoids cross-event-loop issues with session-scoped
# async fixtures while keeping full rollback isolation.


@pytest_asyncio.fixture
async def db_conn(_apply_migrations):
    """Per-test connection inside a rolled-back transaction."""
    pool = await asyncpg.create_pool(
        TEST_DATABASE_URL, min_size=1, max_size=2,
        statement_cache_size=_CACHE_SIZE,
    )
    conn = await pool.acquire()
    txn = conn.transaction()
    await txn.start()

    yield conn

    await txn.rollback()
    await pool.release(conn)
    await pool.close()


@pytest_asyncio.fixture
async def pool_adapter(db_conn):
    """SingleConnectionPool wrapping the per-test connection."""
    return SingleConnectionPool(db_conn)
