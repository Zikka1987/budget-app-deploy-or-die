"""Verify post-bootstrap DB state.

Checks:
  1. All 13 expected app tables exist in public schema (with RLS enabled).
  2. Required ENUMs exist.
  3. The receipts storage bucket exists with the expected configuration.
  4. The placeholder household + household_settings rows exist.
  5. Counts categories per type for the placeholder household.
  6. Confirms household_members is empty (so we know what's missing).
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

EXPECTED_TABLES = [
    "households",
    "household_members",
    "household_settings",
    "categories",
    "category_aliases",
    "budget_months",
    "budget_lines",
    "receipts",
    "receipt_items",
    "transaction_groups",
    "transactions",
    "savings_rules",
    "savings_proposals",
]

EXPECTED_ENUMS = [
    "transaction_type",
    "receipt_status",
    "savings_rule_type",
    "proposal_status",
    "transaction_source",
]

PLACEHOLDER_HOUSEHOLD_ID = "00000000-0000-0000-0000-000000000000"


async def main() -> int:
    conn = await asyncpg.connect(ENV["DATABASE_URL"])
    failed = False
    try:
        # 1. Tables + RLS
        rows = await conn.fetch(
            """
            SELECT c.relname AS name, c.relrowsecurity AS rls
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public'
              AND c.relkind = 'r'
              AND c.relname = ANY($1::text[])
            ORDER BY c.relname
            """,
            EXPECTED_TABLES,
        )
        present = {r["name"]: r["rls"] for r in rows}
        print("App tables (public schema):")
        for t in EXPECTED_TABLES:
            if t in present:
                print(f"  [ok]   {t:<22} rls={'on' if present[t] else 'OFF'}")
                if not present[t]:
                    failed = True
            else:
                print(f"  [FAIL] {t:<22} MISSING")
                failed = True

        # 2. ENUMs
        enum_rows = await conn.fetch(
            """
            SELECT typname FROM pg_type
            WHERE typtype = 'e' AND typname = ANY($1::text[])
            ORDER BY typname
            """,
            EXPECTED_ENUMS,
        )
        present_enums = {r["typname"] for r in enum_rows}
        print("\nEnum types:")
        for e in EXPECTED_ENUMS:
            if e in present_enums:
                print(f"  [ok]   {e}")
            else:
                print(f"  [FAIL] {e} MISSING")
                failed = True

        # 3. Storage bucket
        bucket = await conn.fetchrow(
            """
            SELECT id, name, public, file_size_limit, allowed_mime_types
            FROM storage.buckets WHERE id = 'receipts'
            """
        )
        print("\nStorage bucket 'receipts':")
        if bucket is None:
            print("  [FAIL] not found in storage.buckets")
            failed = True
        else:
            print(f"  [ok]   id={bucket['id']} name={bucket['name']}")
            print(
                f"         public={bucket['public']} "
                f"size_limit={bucket['file_size_limit']} "
                f"mimes={bucket['allowed_mime_types']}"
            )
            if bucket["public"]:
                print("  [WARN] bucket is public; should be private")
                failed = True

        # 4. Placeholder household
        h = await conn.fetchrow(
            "SELECT id, name FROM households WHERE id = $1",
            PLACEHOLDER_HOUSEHOLD_ID,
        )
        print("\nPlaceholder household:")
        if h is None:
            print(f"  [FAIL] {PLACEHOLDER_HOUSEHOLD_ID} not found")
            failed = True
        else:
            print(f"  [ok]   {h['id']} name='{h['name']}'")

        hs = await conn.fetchrow(
            """
            SELECT currency, shift_late_income, late_income_cutoff_day
            FROM household_settings WHERE household_id = $1
            """,
            PLACEHOLDER_HOUSEHOLD_ID,
        )
        if hs is None:
            print("  [FAIL] household_settings missing for placeholder")
            failed = True
        else:
            print(
                f"  [ok]   household_settings currency={hs['currency']} "
                f"shift_late_income={hs['shift_late_income']}"
            )

        # 5. Categories per type
        cats = await conn.fetch(
            """
            SELECT type::text AS t, count(*) AS n
            FROM categories
            WHERE household_id = $1 AND archived_at IS NULL
            GROUP BY type ORDER BY type
            """,
            PLACEHOLDER_HOUSEHOLD_ID,
        )
        print("\nActive categories for placeholder household:")
        for c in cats:
            print(f"  [ok]   {c['t']:<8} {c['n']}")

        # 6. household_members count (expected 0 — user must add this)
        hm_count = await conn.fetchval(
            "SELECT count(*) FROM household_members WHERE household_id = $1",
            PLACEHOLDER_HOUSEHOLD_ID,
        )
        print(
            f"\nhousehold_members rows for placeholder: {hm_count} "
            f"(0 expected — needs an auth user link)"
        )

    finally:
        await conn.close()

    print()
    if failed:
        print("VERIFY: FAIL — one or more checks above failed")
        return 1
    print("VERIFY: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
