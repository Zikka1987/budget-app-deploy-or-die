"""Create the placeholder household + apply seed_categories.sql verbatim.

The seed file scopes 23 categories to household_id
'00000000-0000-0000-0000-000000000000'. To run the seed unmodified, we
first INSERT a household + household_settings row with that exact UUID,
then execute the seed file as-is. The whole thing runs in one transaction.
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
SEED = REPO_ROOT / "supabase" / "seed" / "seed_categories.sql"

PLACEHOLDER_HOUSEHOLD_ID = "00000000-0000-0000-0000-000000000000"


async def main() -> int:
    if not SEED.exists():
        print(f"STOP: seed file missing: {SEED}", file=sys.stderr)
        return 2

    seed_sql = SEED.read_text()
    print(f"Loaded seed: {SEED.name} ({len(seed_sql)} bytes)")

    conn = await asyncpg.connect(ENV["DATABASE_URL"])
    try:
        async with conn.transaction():
            # Create placeholder household + settings (idempotent on repeat
            # runs via ON CONFLICT — useful if the seed half fails and we
            # need to re-run after a fix without DROPing tables).
            await conn.execute(
                """
                INSERT INTO households (id, name)
                VALUES ($1, 'Smoke Test Household')
                ON CONFLICT (id) DO NOTHING
                """,
                PLACEHOLDER_HOUSEHOLD_ID,
            )
            await conn.execute(
                """
                INSERT INTO household_settings (household_id, currency)
                VALUES ($1, 'DKK')
                ON CONFLICT (household_id) DO NOTHING
                """,
                PLACEHOLDER_HOUSEHOLD_ID,
            )

            # Apply the seed verbatim. The placeholder UUID inside the seed
            # matches the household we just inserted.
            await conn.execute(seed_sql)

        # Verify category counts by type
        rows = await conn.fetch(
            """
            SELECT type::text AS t, count(*) AS n
            FROM categories
            WHERE household_id = $1
            GROUP BY type
            ORDER BY type
            """,
            PLACEHOLDER_HOUSEHOLD_ID,
        )
        print("Category counts for placeholder household:")
        total = 0
        for r in rows:
            print(f"  {r['t']:<8} {r['n']}")
            total += r["n"]
        print(f"  TOTAL    {total}")
        # Expected from seed file: 3 income + 17 expense + 3 savings = 23
        if total != 23:
            print(
                f"STOP: expected 23 categories, got {total}",
                file=sys.stderr,
            )
            return 2

        print(f"\nPlaceholder household_id: {PLACEHOLDER_HOUSEHOLD_ID}")
    finally:
        await conn.close()

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
