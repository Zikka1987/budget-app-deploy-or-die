"""Live verification of the second-user invite / join flow.

Walks two fresh Supabase auth users through the invite lifecycle:
create -> list -> lookup -> accept -> post-accept access -> replay ->
wrong-email -> expired -> re-invite after expiry -> revoke.

Exits 0 on GO (all steps pass), 1 on NO-GO.

Assumes backend is running at http://127.0.0.1:8765 (see onboarding_verify.py
for the port-8000 caveat on this developer machine). Migration
00002_household_invites.sql must have been applied to the database.
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

    def record(
        self,
        step: str,
        method: str,
        path: str,
        status: int | str,
        passed: bool,
        summary: str,
    ) -> None:
        self.rows.append({
            "step": step,
            "method": method,
            "path": path,
            "status": status,
            "pass": passed,
            "summary": summary,
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


# ---------- auth user lifecycle ----------

def create_fresh_auth_user(tag: str) -> tuple[str, str, str]:
    email = f"invite-{tag}-{secrets.token_hex(4)}@budget-app-test.local"
    password = secrets.token_urlsafe(24)
    with httpx.Client(timeout=30.0) as c:
        r = c.post(
            f"{SUPABASE_URL}/auth/v1/admin/users",
            headers=ADMIN_HEADERS,
            json={"email": email, "password": password, "email_confirm": True},
        )
    if r.status_code not in (200, 201):
        print(f"STOP: admin/users returned HTTP {r.status_code}", file=sys.stderr)
        print(r.text[:300], file=sys.stderr)
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


async def db_cleanup(
    *, user_ids: list[str], household_id: str | None,
) -> None:
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
                "DELETE FROM households WHERE id = $1", household_id
            )
        for uid in user_ids:
            await conn.execute(
                "DELETE FROM household_members WHERE user_id = $1", uid
            )
    finally:
        await conn.close()


# ---------- step helpers ----------


async def step_1_inviter_creates_household(token: str, rep: Report) -> str | None:
    resp = http_call(
        "POST", f"{API_BASE}/households/", token,
        json={"household_name": "Invite Verify HH", "display_name": "Inviter"},
    )
    body = _safe_json(resp)
    dump_json(SMOKE_DIR / "invite_01_household.json", body)
    if resp.status_code != 201:
        rep.record("1", "POST", "/households/", resp.status_code, False,
                   f"unexpected status {resp.status_code}: {body}")
        return None
    hh_id = body["household"]["id"]
    rep.record("1", "POST", "/households/", 201, True, f"household_id={hh_id}")
    return hh_id


async def step_2_create_invite(
    token: str, rep: Report, email: str
) -> tuple[str | None, str | None]:
    resp = http_call(
        "POST", f"{API_BASE}/invites/", token,
        json={"email": email},
    )
    body = _safe_json(resp)
    dump_json(SMOKE_DIR / "invite_02_create.json", body)
    if resp.status_code != 201:
        rep.record("2", "POST", "/invites/", resp.status_code, False, str(body))
        return None, None
    invite_id = body.get("id")
    token_ = body.get("token")
    passed = (
        invite_id is not None
        and isinstance(token_, str) and len(token_) >= 32
        and body.get("status") == "pending"
    )
    rep.record("2", "POST", "/invites/", 201, passed,
               f"invite_id={invite_id} token_len={len(token_) if token_ else 0}")
    return invite_id, token_


async def step_3_list_invites_no_token_hash(token: str, rep: Report) -> None:
    resp = http_call("GET", f"{API_BASE}/invites/", token)
    body = _safe_json(resp)
    dump_json(SMOKE_DIR / "invite_03_list.json", body)
    invites = body.get("invites") if isinstance(body, dict) else []
    no_secret = all(
        ("token" not in i and "token_hash" not in i) for i in invites
    )
    passed = resp.status_code == 200 and len(invites) >= 1 and no_secret
    rep.record("3", "GET", "/invites/", resp.status_code, passed,
               f"count={len(invites)} no_secret={no_secret}")


async def step_4_invitee_status_pre(token: str, rep: Report) -> None:
    resp = http_call("GET", f"{API_BASE}/onboarding/status", token)
    body = _safe_json(resp)
    passed = resp.status_code == 200 and body.get("has_household") is False
    rep.record("4", "GET", "/onboarding/status (invitee)", resp.status_code, passed,
               f"has_household={body.get('has_household')}")


async def step_5_lookup(invitee_token: str, invite_token: str, rep: Report) -> None:
    resp = http_call(
        "POST", f"{API_BASE}/invites/lookup", invitee_token,
        json={"token": invite_token},
    )
    body = _safe_json(resp)
    dump_json(SMOKE_DIR / "invite_05_lookup.json", body)
    passed = (
        resp.status_code == 200
        and body.get("status") == "pending"
        and body.get("household_name") == "Invite Verify HH"
    )
    rep.record("5", "POST", "/invites/lookup", resp.status_code, passed,
               f"household_name={body.get('household_name')}")


async def step_6_accept(
    invitee_token: str, invite_token: str, rep: Report, household_id: str,
) -> bool:
    resp = http_call(
        "POST", f"{API_BASE}/invites/accept", invitee_token,
        json={"token": invite_token, "display_name": "Invitee User"},
    )
    body = _safe_json(resp)
    dump_json(SMOKE_DIR / "invite_06_accept.json", body)
    if resp.status_code != 201:
        rep.record("6", "POST", "/invites/accept", resp.status_code, False, str(body))
        return False
    member = body.get("member") or {}
    passed = (
        body.get("household", {}).get("id") == household_id
        and member.get("role") == "member"
    )
    rep.record("6", "POST", "/invites/accept", 201, passed,
               f"role={member.get('role')} household={body.get('household', {}).get('id')}")
    return passed


async def step_7_db_probe(
    rep: Report, household_id: str, invite_id: str, invitee_user_id: str,
) -> None:
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        member_count = await conn.fetchval(
            "SELECT count(*) FROM household_members WHERE household_id = $1",
            household_id,
        )
        inv_row = await conn.fetchrow(
            """
            SELECT status, accepted_at, accepted_by_user_id
            FROM household_invites WHERE id = $1
            """,
            invite_id,
        )
    finally:
        await conn.close()
    passed = (
        member_count == 2
        and inv_row is not None
        and inv_row["status"] == "accepted"
        and inv_row["accepted_at"] is not None
        and str(inv_row["accepted_by_user_id"]) == invitee_user_id
    )
    rep.record("7", "-", "db_probe", "ok" if passed else "fail", passed,
               f"members={member_count} status={inv_row and inv_row['status']}")


async def step_8_post_accept_access(token: str, rep: Report, household_id: str) -> None:
    r1 = http_call("GET", f"{API_BASE}/onboarding/status", token)
    b1 = _safe_json(r1)
    p1 = r1.status_code == 200 and b1.get("has_household") is True

    r2 = http_call("GET", f"{API_BASE}/households/me", token)
    b2 = _safe_json(r2)
    p2 = r2.status_code == 200 and b2.get("id") == household_id

    r3 = http_call("GET", f"{API_BASE}/categories/", token)
    p3 = r3.status_code == 200

    passed = p1 and p2 and p3
    rep.record("8", "GET", "(post-accept)", "mix", passed,
               f"status={r1.status_code}/me={r2.status_code}/cats={r3.status_code}")


async def step_9_replay_accept(
    invitee_token: str, invite_token: str, rep: Report,
) -> None:
    resp = http_call(
        "POST", f"{API_BASE}/invites/accept", invitee_token,
        json={"token": invite_token, "display_name": "Invitee User"},
    )
    passed = resp.status_code == 409
    rep.record("9", "POST", "/invites/accept (replay)", resp.status_code, passed,
               "expected 409")


async def step_10_wrong_email(
    invitee_token: str, rep: Report, household_id: str,
) -> None:
    """Insert a pending invite for a DIFFERENT email directly in DB
    (bypasses the 2-seat cap) and verify accept returns 403."""
    import hashlib
    conn = await asyncpg.connect(DATABASE_URL)
    raw = secrets.token_urlsafe(32)
    tok_hash = hashlib.sha256(raw.encode()).hexdigest()
    try:
        owner = await conn.fetchval(
            "SELECT user_id FROM household_members WHERE household_id = $1 AND role = 'owner' LIMIT 1",
            household_id,
        )
        invite_id = await conn.fetchval(
            """
            INSERT INTO household_invites
              (household_id, invited_by_user_id, email, token_hash, expires_at)
            VALUES ($1, $2, $3, $4, now() + interval '1 hour')
            RETURNING id
            """,
            household_id, owner, "someone-else@budget-app-test.local", tok_hash,
        )
    finally:
        await conn.close()
    # Invitee attempts accept — JWT email does NOT match invite email
    resp = http_call(
        "POST", f"{API_BASE}/invites/accept", invitee_token,
        json={"token": raw, "display_name": "x"},
    )
    passed = resp.status_code == 403
    rep.record("10", "POST", "/invites/accept (wrong email)", resp.status_code,
               passed, "expected 403")
    # Clean up: revoke the test row so the pending slot is freed
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        await conn.execute(
            "UPDATE household_invites SET status = 'revoked', revoked_at = now() WHERE id = $1",
            invite_id,
        )
    finally:
        await conn.close()


async def step_11_expired_accept(
    invitee_token: str, rep: Report, household_id: str, invitee_email: str,
) -> str | None:
    """Create a pending invite row directly in DB with expires_at in the past
    and confirm accept returns 410 + the row transitions to expired."""
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        # We need an inviter user_id (any household member will do).
        owner = await conn.fetchval(
            """
            SELECT user_id FROM household_members
            WHERE household_id = $1 AND role = 'owner'
            LIMIT 1
            """,
            household_id,
        )
        # Pick a fresh email for this test row to avoid the pending-email
        # partial unique index on (household, email).
        fresh_email = f"stale-{secrets.token_hex(3)}@budget-app-test.local"
        # Insert a past-expiry pending invite (hash for a known raw token).
        import hashlib
        raw = secrets.token_urlsafe(32)
        tok_hash = hashlib.sha256(raw.encode()).hexdigest()
        invite_id = await conn.fetchval(
            """
            INSERT INTO household_invites
              (household_id, invited_by_user_id, email, token_hash, expires_at)
            VALUES ($1, $2, $3, $4, now() - interval '1 day')
            RETURNING id
            """,
            household_id, owner, fresh_email, tok_hash,
        )
    finally:
        await conn.close()

    # A different user (the existing invitee) attempts accept — should still
    # return 410 even before hitting the email check because lookup/accept
    # detect the stale row first.
    resp = http_call(
        "POST", f"{API_BASE}/invites/accept", invitee_token,
        json={"token": raw, "display_name": "x"},
    )
    # Read the row back to confirm lazy-expire happened
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        row = await conn.fetchrow(
            "SELECT status FROM household_invites WHERE id = $1", invite_id,
        )
    finally:
        await conn.close()
    passed = resp.status_code == 410 and row is not None and row["status"] == "expired"
    rep.record("11", "POST", "/invites/accept (expired)", resp.status_code,
               passed, f"row_status={row and row['status']}")
    return fresh_email


async def step_12_reinvite_after_expiry(
    rep: Report, household_id: str, stale_email: str,
) -> None:
    """After step 11 lazily expired the stale-pending row, a new pending
    invite for the same household must be insertable (the partial unique
    index slot is freed). We insert directly via DB to bypass the 2-seat
    cap and isolate the test to the index behavior."""
    import hashlib
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        owner = await conn.fetchval(
            "SELECT user_id FROM household_members WHERE household_id = $1 AND role = 'owner' LIMIT 1",
            household_id,
        )
        raw = secrets.token_urlsafe(32)
        tok_hash = hashlib.sha256(raw.encode()).hexdigest()
        insert_ok = False
        try:
            await conn.fetchval(
                """
                INSERT INTO household_invites
                  (household_id, invited_by_user_id, email, token_hash, expires_at)
                VALUES ($1, $2, $3, $4, now() + interval '1 hour')
                RETURNING id
                """,
                household_id, owner, stale_email, tok_hash,
            )
            insert_ok = True
        except Exception as e:
            rep.record("12", "-", "db_insert (re-invite)", "fail", False, str(e))
            return

        # Verify exactly one pending + (at least) one expired for this pair
        pending = await conn.fetchval(
            """
            SELECT count(*) FROM household_invites
            WHERE household_id = $1 AND email = $2 AND status = 'pending'
            """,
            household_id, stale_email,
        )
        expired = await conn.fetchval(
            """
            SELECT count(*) FROM household_invites
            WHERE household_id = $1 AND email = $2 AND status = 'expired'
            """,
            household_id, stale_email,
        )
    finally:
        await conn.close()
    passed = insert_ok and pending == 1 and expired >= 1
    rep.record("12", "-", "db_insert (re-invite)", "ok" if passed else "fail",
               passed, f"pending={pending} expired={expired}")
    # Clean up: revoke the test row so the pending slot is freed for step 13
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        await conn.execute(
            """
            UPDATE household_invites SET status = 'revoked', revoked_at = now()
            WHERE household_id = $1 AND email = $2 AND status = 'pending'
            """,
            household_id, stale_email,
        )
    finally:
        await conn.close()


async def step_12b_cap_blocks_second_invite(
    inviter_token: str, rep: Report, household_id: str,
) -> None:
    """After step 6 the household has 2 members. create_invite must 409
    regardless of whether an active pending invite is present. Also verifies
    the DB member count is exactly 2.
    """
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        members = await conn.fetchval(
            "SELECT count(*) FROM household_members WHERE household_id = $1",
            household_id,
        )
    finally:
        await conn.close()

    resp = http_call(
        "POST", f"{API_BASE}/invites/", inviter_token,
        json={"email": f"cap-extra-{secrets.token_hex(3)}@budget-app-test.local"},
    )
    body = _safe_json(resp)
    dump_json(SMOKE_DIR / "invite_12b_cap.json", body)
    msg = (body.get("detail") or "").lower() if isinstance(body, dict) else ""
    passed = (
        members == 2
        and resp.status_code == 409
        and "household is full" in msg
    )
    rep.record(
        "12b", "POST", "/invites/ (cap)", resp.status_code, passed,
        f"members={members} msg_ok={'household is full' in msg}",
    )


async def step_13_revoke(
    inviter_token: str, invitee_token: str, rep: Report, household_id: str,
) -> None:
    """Insert a pending invite directly, revoke it via the API, then confirm
    accept returns 409. DB insert bypasses the 2-seat cap; the revoke
    endpoint is exercised via the real API."""
    import hashlib
    conn = await asyncpg.connect(DATABASE_URL)
    raw = secrets.token_urlsafe(32)
    tok_hash = hashlib.sha256(raw.encode()).hexdigest()
    try:
        owner = await conn.fetchval(
            "SELECT user_id FROM household_members WHERE household_id = $1 AND role = 'owner' LIMIT 1",
            household_id,
        )
        invite_id = await conn.fetchval(
            """
            INSERT INTO household_invites
              (household_id, invited_by_user_id, email, token_hash, expires_at)
            VALUES ($1, $2, $3, $4, now() + interval '1 hour')
            RETURNING id
            """,
            household_id, owner, "to-revoke@budget-app-test.local", tok_hash,
        )
    finally:
        await conn.close()
    r = http_call("DELETE", f"{API_BASE}/invites/{invite_id}", inviter_token)
    if r.status_code != 204:
        rep.record("13", "DELETE", "/invites/{id}", r.status_code, False,
                   "expected 204")
        return
    # Now accept with the invitee — the revoked status check should fire
    # first and return 409.
    a = http_call(
        "POST", f"{API_BASE}/invites/accept", invitee_token,
        json={"token": raw, "display_name": "x"},
    )
    passed = a.status_code == 409
    rep.record("13", "POST", "/invites/accept (revoked)", a.status_code, passed,
               "expected 409")


# ---------- main orchestration ----------

async def main() -> int:
    SMOKE_DIR.mkdir(exist_ok=True)
    print(f"Invite verify starting. Output dir: {SMOKE_DIR}")
    print(f"API base: {API_BASE}")

    rep = Report()
    household_id: str | None = None
    inviter_id, inviter_email, _ = create_fresh_auth_user("inviter")
    invitee_id, invitee_email, _ = create_fresh_auth_user("invitee")
    print("Fresh auth users created.")

    try:
        inviter_token = mint_jwt(inviter_email)
        invitee_token = mint_jwt(invitee_email)
        if not inviter_token or not invitee_token:
            rep.record("0", "-", "mint_jwt", "n/a", False, "tokens missing")
            rep.print_summary()
            return 1

        household_id = await step_1_inviter_creates_household(inviter_token, rep)
        if not household_id:
            rep.print_summary()
            return 1

        invite_id, invite_token = await step_2_create_invite(
            inviter_token, rep, invitee_email
        )
        # 2b: a SECOND pending invite for this household (different email)
        # must be blocked by the one_pending_per_household partial unique.
        if invite_token is not None:
            r2b = http_call(
                "POST", f"{API_BASE}/invites/", inviter_token,
                json={"email": f"second-pending-{secrets.token_hex(3)}@budget-app-test.local"},
            )
            b2b = _safe_json(r2b)
            msg = (b2b.get("detail") or "").lower() if isinstance(b2b, dict) else ""
            passed_2b = r2b.status_code == 409 and "pending invite" in msg
            rep.record("2b", "POST", "/invites/ (2nd pending)", r2b.status_code,
                       passed_2b, f"msg_ok={'pending invite' in msg}")

        await step_3_list_invites_no_token_hash(inviter_token, rep)
        await step_4_invitee_status_pre(invitee_token, rep)

        if invite_id and invite_token:
            await step_5_lookup(invitee_token, invite_token, rep)
            accepted = await step_6_accept(
                invitee_token, invite_token, rep, household_id
            )
            if accepted:
                await step_7_db_probe(rep, household_id, invite_id, invitee_id)
                await step_8_post_accept_access(
                    invitee_token, rep, household_id
                )
                await step_9_replay_accept(invitee_token, invite_token, rep)

        await step_10_wrong_email(invitee_token, rep, household_id)
        stale_email = await step_11_expired_accept(
            invitee_token, rep, household_id, invitee_email
        )
        if stale_email:
            await step_12_reinvite_after_expiry(
                rep, household_id, stale_email
            )
        # 12b: household now has 2 members; any new invite must 409
        # with "Household is full".
        await step_12b_cap_blocks_second_invite(
            inviter_token, rep, household_id
        )
        await step_13_revoke(inviter_token, invitee_token, rep, household_id)

        rep.print_summary()
        verdict = "GO" if not rep.failed else "NO-GO"
        print(f"\nVERDICT: {verdict}")
        return 0 if not rep.failed else 1
    finally:
        try:
            await db_cleanup(
                user_ids=[inviter_id, invitee_id],
                household_id=household_id,
            )
        finally:
            delete_auth_user(invitee_id)
            delete_auth_user(inviter_id)
        print("Cleanup complete.")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
