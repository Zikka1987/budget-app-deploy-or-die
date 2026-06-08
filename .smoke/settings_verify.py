"""Phase 6 mobile verification: settings + invite endpoints.

Focus: the *narrow* set of API contracts that mobile Phase 6 newly depends on
which were not already covered by invite_verify.py / onboarding_verify.py:

  - GET /households/me  (used by Settings screen "Household" card)
  - GET /household-settings  (used by Settings screen "Preferences" card)
  - GET /invites?status=accepted  (used by Settings "Members" workaround
    since there is no member-list endpoint)
  - POST /invites/lookup with garbage token -> 404
  - POST /household-settings full-cycle: enable shift+cutoff, then disable

Exits 0 on GO, 1 on NO-GO. Cleans up auth users + DB rows on exit.
"""

from __future__ import annotations

import asyncio
import json
import secrets
import sys
from pathlib import Path
from typing import Any

import asyncpg
import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from smoke_test import load_env, mint_jwt, http_call  # type: ignore

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV = load_env(REPO_ROOT / ".env")

SUPABASE_URL = ENV["SUPABASE_URL"].rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = ENV["SUPABASE_SERVICE_ROLE_KEY"]
DATABASE_URL = ENV["DATABASE_URL"]

SMOKE_DIR = REPO_ROOT / ".smoke"
API_BASE = "http://127.0.0.1:8765/api/v1"

ADMIN_HEADERS = {
    "apikey": SUPABASE_SERVICE_ROLE_KEY,
    "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
    "Content-Type": "application/json",
}


def _safe_json(resp: httpx.Response) -> Any:
    try:
        return resp.json()
    except Exception:
        return {"_raw_text": resp.text[:2000], "_status": resp.status_code}


def dump_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, default=str))


class Report:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []
        self.failed = False

    def record(self, step: str, method: str, path: str, status: int | str,
               passed: bool, summary: str) -> None:
        self.rows.append({
            "step": step, "method": method, "path": path,
            "status": status, "pass": passed, "summary": summary,
        })
        if not passed:
            self.failed = True

    def print_summary(self) -> None:
        print("\n" + "=" * 80)
        print(f"{'Step':<6}{'Method':<7}{'Status':<8}{'Pass':<6}Endpoint")
        print("-" * 80)
        for r in self.rows:
            mark = "OK" if r["pass"] else "FAIL"
            print(f"{r['step']:<6}{r['method']:<7}{str(r['status']):<8}{mark:<6}{r['path']}")
            if r["summary"]:
                print(f"      -> {r['summary']}")
        print("=" * 80)


def create_fresh_auth_user(tag: str) -> tuple[str, str, str]:
    email = f"settings-{tag}-{secrets.token_hex(4)}@budget-app-test.local"
    password = secrets.token_urlsafe(24)
    with httpx.Client(timeout=30.0) as c:
        r = c.post(
            f"{SUPABASE_URL}/auth/v1/admin/users",
            headers=ADMIN_HEADERS,
            json={"email": email, "password": password, "email_confirm": True},
        )
    if r.status_code not in (200, 201):
        print(f"STOP: admin/users returned {r.status_code}: {r.text[:300]}",
              file=sys.stderr)
        sys.exit(2)
    return r.json()["id"], email, password


def delete_auth_user(user_id: str) -> None:
    try:
        with httpx.Client(timeout=30.0) as c:
            c.delete(
                f"{SUPABASE_URL}/auth/v1/admin/users/{user_id}",
                headers=ADMIN_HEADERS,
            )
    except Exception as e:
        print(f"  [cleanup warn] delete auth user failed: {e}")


async def db_cleanup(*, user_ids: list[str], household_id: str | None) -> None:
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        if household_id:
            await conn.execute(
                "DELETE FROM household_invites WHERE household_id = $1",
                household_id,
            )
            await conn.execute(
                "DELETE FROM household_settings WHERE household_id = $1",
                household_id,
            )
            await conn.execute(
                "DELETE FROM household_members WHERE household_id = $1",
                household_id,
            )
            await conn.execute(
                "DELETE FROM households WHERE id = $1", household_id,
            )
        for uid in user_ids:
            await conn.execute(
                "DELETE FROM household_members WHERE user_id = $1", uid,
            )
    finally:
        await conn.close()


async def main() -> int:
    SMOKE_DIR.mkdir(exist_ok=True)
    print(f"Settings verify starting. API base: {API_BASE}")

    rep = Report()
    household_id: str | None = None
    owner_id, owner_email, _ = create_fresh_auth_user("owner")
    invitee_id, invitee_email, _ = create_fresh_auth_user("invitee")
    print("Fresh auth users created.")

    try:
        owner_token = mint_jwt(owner_email)
        invitee_token = mint_jwt(invitee_email)
        if not owner_token or not invitee_token:
            rep.record("0", "-", "mint_jwt", "n/a", False, "tokens missing")
            rep.print_summary()
            return 1

        # 1. Create household
        r = http_call(
            "POST", f"{API_BASE}/households/", owner_token,
            json={"household_name": "Phase6 Settings HH", "display_name": "Owner"},
        )
        body = _safe_json(r)
        if r.status_code != 201:
            rep.record("1", "POST", "/households/", r.status_code, False, str(body))
            rep.print_summary()
            return 1
        household_id = body["household"]["id"]
        rep.record("1", "POST", "/households/", 201, True, f"hh={household_id}")

        # 2. GET /households/me
        r = http_call("GET", f"{API_BASE}/households/me", owner_token)
        b = _safe_json(r)
        passed = (
            r.status_code == 200
            and b.get("id") == household_id
            and b.get("name") == "Phase6 Settings HH"
            and "created_at" in b
        )
        rep.record("2", "GET", "/households/me", r.status_code, passed,
                   f"name={b.get('name')}")

        # 3. GET /household-settings — defaults present
        r = http_call("GET", f"{API_BASE}/household-settings/", owner_token)
        b = _safe_json(r)
        passed = (
            r.status_code == 200
            and b.get("currency") == "DKK"
            and "shift_late_income" in b
        )
        rep.record("3", "GET", "/household-settings", r.status_code, passed,
                   f"currency={b.get('currency')} shift={b.get('shift_late_income')}")

        # 4. PUT enable shift + cutoff=25
        r = http_call(
            "PUT", f"{API_BASE}/household-settings/", owner_token,
            json={"shift_late_income": True, "late_income_cutoff_day": 25},
        )
        b = _safe_json(r)
        passed = (
            r.status_code == 200
            and b.get("shift_late_income") is True
            and b.get("late_income_cutoff_day") == 25
        )
        rep.record("4", "PUT", "/household-settings (enable)", r.status_code,
                   passed, f"shift={b.get('shift_late_income')} cutoff={b.get('late_income_cutoff_day')}")

        # 5. GET reflects #4
        r = http_call("GET", f"{API_BASE}/household-settings/", owner_token)
        b = _safe_json(r)
        passed = (
            r.status_code == 200
            and b.get("shift_late_income") is True
            and b.get("late_income_cutoff_day") == 25
        )
        rep.record("5", "GET", "/household-settings (re-read)", r.status_code,
                   passed, f"shift={b.get('shift_late_income')} cutoff={b.get('late_income_cutoff_day')}")

        # 6. PUT cutoff=29 -> 422
        r = http_call(
            "PUT", f"{API_BASE}/household-settings/", owner_token,
            json={"late_income_cutoff_day": 29},
        )
        passed = r.status_code == 422
        rep.record("6", "PUT", "/household-settings (cutoff=29)", r.status_code,
                   passed, "expected 422")

        # 7. PUT cutoff=0 -> 422
        r = http_call(
            "PUT", f"{API_BASE}/household-settings/", owner_token,
            json={"late_income_cutoff_day": 0},
        )
        passed = r.status_code == 422
        rep.record("7", "PUT", "/household-settings (cutoff=0)", r.status_code,
                   passed, "expected 422")

        # 8. PUT disable shift -> 200 (any cutoff value accepted when shift=false)
        r = http_call(
            "PUT", f"{API_BASE}/household-settings/", owner_token,
            json={"shift_late_income": False},
        )
        b = _safe_json(r)
        passed = r.status_code == 200 and b.get("shift_late_income") is False
        rep.record("8", "PUT", "/household-settings (disable)", r.status_code,
                   passed, f"shift={b.get('shift_late_income')}")

        # 9. POST /invites — for invitee
        r = http_call(
            "POST", f"{API_BASE}/invites/", owner_token,
            json={"email": invitee_email},
        )
        b = _safe_json(r)
        invite_token = None
        invite_id = None
        if r.status_code == 201:
            invite_token = b.get("token")
            invite_id = b.get("id")
            passed = isinstance(invite_token, str) and len(invite_token) >= 32
        else:
            passed = False
        rep.record("9", "POST", "/invites/", r.status_code, passed,
                   f"token_len={len(invite_token) if invite_token else 0}")

        # 10. POST /invites/lookup garbage -> 404
        r = http_call(
            "POST", f"{API_BASE}/invites/lookup", invitee_token,
            json={"token": "garbage-not-a-real-token-xyz123"},
        )
        passed = r.status_code == 404
        rep.record("10", "POST", "/invites/lookup (garbage)", r.status_code,
                   passed, "expected 404")

        # 11. POST /invites/accept -> 201
        if invite_token:
            r = http_call(
                "POST", f"{API_BASE}/invites/accept", invitee_token,
                json={"token": invite_token, "display_name": "Invitee"},
            )
            passed = r.status_code == 201
            rep.record("11", "POST", "/invites/accept", r.status_code, passed,
                       "expected 201")

        # 12. GET /invites?status=accepted — mobile member-list workaround
        r = http_call(
            "GET", f"{API_BASE}/invites/", owner_token,
            params={"status": "accepted"},
        )
        b = _safe_json(r)
        invites = b.get("invites") if isinstance(b, dict) else []
        accepted_emails = [i.get("email") for i in invites]
        passed = (
            r.status_code == 200
            and any(e == invitee_email for e in accepted_emails)
            and all(("token" not in i and "token_hash" not in i) for i in invites)
        )
        rep.record("12", "GET", "/invites?status=accepted", r.status_code,
                   passed, f"emails={accepted_emails}")

        rep.print_summary()
        verdict = "GO" if not rep.failed else "NO-GO"
        print(f"\nVERDICT: {verdict}")
        return 0 if not rep.failed else 1
    finally:
        try:
            await db_cleanup(
                user_ids=[owner_id, invitee_id],
                household_id=household_id,
            )
        finally:
            delete_auth_user(invitee_id)
            delete_auth_user(owner_id)
        print("Cleanup complete.")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
