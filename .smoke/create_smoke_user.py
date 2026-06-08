"""Create a smoke-test auth user via Supabase admin API + household_members row.

Uses SUPABASE_SERVICE_ROLE_KEY to create a confirmed user, then inserts a
household_members row linking the new user to the placeholder household.
Never prints secrets, email, password, or tokens.
"""

from __future__ import annotations

import asyncio
import secrets
import sys
from pathlib import Path
import asyncpg
import httpx

sys.path.insert(0, ".smoke")
from smoke_test import load_env  # type: ignore

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV = load_env(REPO_ROOT / ".env")

SUPABASE_URL = ENV["SUPABASE_URL"].rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = ENV["SUPABASE_SERVICE_ROLE_KEY"]
DATABASE_URL = ENV["DATABASE_URL"]

PLACEHOLDER_HOUSEHOLD_ID = "00000000-0000-0000-0000-000000000000"
SMOKE_EMAIL = f"smoke-test-{secrets.token_hex(4)}@budget-app-test.local"
SMOKE_PASSWORD = secrets.token_urlsafe(24)


async def main() -> int:
    # 1. Check if a household_members row already exists for the placeholder
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        existing = await conn.fetchrow(
            """
            SELECT hm.user_id, u.email
            FROM household_members hm
            JOIN auth.users u ON u.id = hm.user_id
            WHERE hm.household_id = $1
            LIMIT 1
            """,
            PLACEHOLDER_HOUSEHOLD_ID,
        )
        if existing:
            print(
                f"Smoke user already exists for placeholder household. "
                f"user_id=<redacted> — skipping creation."
            )
            return 0
    finally:
        await conn.close()

    # 2. Create auth user via admin API
    print("Creating smoke-test auth user via admin API...")
    admin_headers = {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
    }
    with httpx.Client(timeout=30.0) as c:
        r = c.post(
            f"{SUPABASE_URL}/auth/v1/admin/users",
            headers=admin_headers,
            json={
                "email": SMOKE_EMAIL,
                "password": SMOKE_PASSWORD,
                "email_confirm": True,
            },
        )
    if r.status_code not in (200, 201):
        print(f"STOP: admin/users returned HTTP {r.status_code}", file=sys.stderr)
        # Print error detail but NOT the request body (contains password)
        try:
            err = r.json()
            # Remove any echoed email/password from error
            print(f"  error: {err.get('msg', err.get('message', str(err)[:200]))}", file=sys.stderr)
        except Exception:
            print(f"  body: {r.text[:200]}", file=sys.stderr)
        return 2

    user_data = r.json()
    user_id = user_data["id"]
    print(f"Auth user created. user_id={user_id}")

    # 3. Insert household_members row
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        await conn.execute(
            """
            INSERT INTO household_members (user_id, household_id, display_name, role)
            VALUES ($1::uuid, $2::uuid, 'Smoke Test User', 'owner')
            ON CONFLICT (user_id, household_id) DO NOTHING
            """,
            user_id,
            PLACEHOLDER_HOUSEHOLD_ID,
        )
        print(f"household_members row inserted (role=owner).")

        # Verify
        count = await conn.fetchval(
            "SELECT count(*) FROM household_members WHERE household_id = $1",
            PLACEHOLDER_HOUSEHOLD_ID,
        )
        print(f"household_members rows for placeholder household: {count}")
    finally:
        await conn.close()

    print("\nBootstrap complete. Ready for smoke test.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
