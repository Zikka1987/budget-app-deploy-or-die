"""Apply the initial schema migration via asyncpg.

Reads supabase/migrations/00001_initial_schema.sql and executes it as a
single multi-statement query through the session pooler. Run from repo root.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import asyncpg

sys.path.insert(0, ".smoke")
from smoke_test import load_env  # type: ignore

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV = load_env(REPO_ROOT / ".env")
MIGRATION = REPO_ROOT / "supabase" / "migrations" / "00001_initial_schema.sql"


async def main() -> int:
    if not MIGRATION.exists():
        print(f"STOP: migration file missing: {MIGRATION}", file=sys.stderr)
        return 2

    sql = MIGRATION.read_text()
    print(f"Loaded migration: {MIGRATION.name} ({len(sql)} bytes)")

    conn = await asyncpg.connect(ENV["DATABASE_URL"])
    try:
        # The migration creates get_household_id() (a SQL-language function)
        # BEFORE household_members exists. Postgres validates SQL function
        # bodies at creation time, so we must turn that check off for this
        # session. The function still works correctly at call time because
        # household_members is created later in the same transaction.
        #
        # We also wrap the whole migration in a single transaction so a
        # partial apply rolls back cleanly.
        async with conn.transaction():
            await conn.execute("SET LOCAL check_function_bodies = off;")
            await conn.execute(sql)
        print("Migration executed without raising.")

        # Sanity: count app tables in public schema
        n = await conn.fetchval(
            """
            SELECT count(*) FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_name IN (
                'households','household_members','household_settings',
                'categories','category_aliases',
                'budget_months','budget_lines',
                'receipts','receipt_items',
                'transaction_groups','transactions',
                'savings_rules','savings_proposals'
              )
            """
        )
        print(f"Public app tables present after migration: {n}/13")
        if n != 13:
            print("STOP: not all expected tables were created.", file=sys.stderr)
            return 2
    finally:
        await conn.close()

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
