"""Live verification of the production onboarding corridor.

Walks a brand-new Supabase auth user (zero household, zero categories) through
the 10 verification steps described in the approved plan. Reuses helpers from
.smoke/smoke_test.py. Writes payload captures to .smoke/onboarding_*.json.

Exits 0 on GO (all steps pass), 1 on NO-GO.

Port note: local backend is reachable at 127.0.0.1:8765 on this machine
(port 8000 is blocked by an OS-level reservation).
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

# Reuse helpers from the existing smoke test (load_env, mint_jwt, http_call).
sys.path.insert(0, str(Path(__file__).resolve().parent))
from smoke_test import load_env, mint_jwt, http_call  # type: ignore

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV = load_env(REPO_ROOT / ".env")

SUPABASE_URL = ENV["SUPABASE_URL"].rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = ENV["SUPABASE_SERVICE_ROLE_KEY"]
DATABASE_URL = ENV["DATABASE_URL"]
SUPABASE_RECEIPTS_BUCKET = ENV.get("SUPABASE_RECEIPTS_BUCKET", "receipts")

SMOKE_DIR = REPO_ROOT / ".smoke"
API_BASE = "http://127.0.0.1:8765/api/v1"
FIXTURE_IMAGE = REPO_ROOT / "backend" / "tests" / "fixtures" / "smoke_receipt.jpeg"

ADMIN_HEADERS = {
    "apikey": SUPABASE_SERVICE_ROLE_KEY,
    "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
    "Content-Type": "application/json",
}


# ---------- helpers ----------

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

def create_fresh_auth_user() -> tuple[str, str, str]:
    """Create a Supabase auth user via admin API. NO household_members insert.

    Returns (user_id, email, password). Password is set for belt-and-suspenders;
    mint_jwt() uses the magiclink flow which does not require a password.
    """
    email = f"onboarding-verify-{secrets.token_hex(4)}@budget-app-test.local"
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
    user_id = r.json()["id"]
    return user_id, email, password


def delete_auth_user(user_id: str) -> None:
    try:
        with httpx.Client(timeout=30.0) as c:
            c.delete(
                f"{SUPABASE_URL}/auth/v1/admin/users/{user_id}",
                headers=ADMIN_HEADERS,
            )
    except Exception as e:
        print(f"  [cleanup warn] delete auth user failed: {e}")


# ---------- storage + DB cleanup ----------

def delete_storage_paths(paths: list[str]) -> None:
    if not paths:
        return
    try:
        with httpx.Client(timeout=30.0) as c:
            c.request(
                "DELETE",
                f"{SUPABASE_URL}/storage/v1/object/{SUPABASE_RECEIPTS_BUCKET}",
                headers={
                    "apikey": SUPABASE_SERVICE_ROLE_KEY,
                    "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
                    "Content-Type": "application/json",
                },
                json={"prefixes": paths},
            )
    except Exception as e:
        print(f"  [cleanup warn] storage delete failed: {e}")


async def db_cleanup(user_id: str, household_id: str | None) -> None:
    """Idempotent DB cleanup scoped to the created household + user."""
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        if household_id:
            # Capture storage paths before deleting rows.
            storage_paths = [
                r["storage_path"]
                for r in await conn.fetch(
                    "SELECT storage_path FROM receipts WHERE household_id = $1",
                    household_id,
                )
                if r["storage_path"]
            ]
            delete_storage_paths(storage_paths)

            await conn.execute(
                """
                DELETE FROM receipt_items
                 WHERE receipt_id IN (
                     SELECT id FROM receipts WHERE household_id = $1
                 )
                """,
                household_id,
            )
            await conn.execute(
                "DELETE FROM receipts WHERE household_id = $1", household_id
            )
            await conn.execute(
                "DELETE FROM categories WHERE household_id = $1", household_id
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
        # Catch-all for any orphaned household_members rows keyed on user.
        await conn.execute(
            "DELETE FROM household_members WHERE user_id = $1", user_id
        )
    finally:
        await conn.close()


# ---------- step executors ----------

async def step_2_onboarding_status_pre(token: str, rep: Report) -> None:
    resp = http_call("GET", f"{API_BASE}/onboarding/status", token)
    body = _safe_json(resp)
    dump_json(SMOKE_DIR / "onboarding_02_status_pre.json", body)
    expected = {
        "has_household": False,
        "has_income_category": False,
        "has_expense_category": False,
        "has_savings_category": False,
        "is_ready": False,
    }
    passed = resp.status_code == 200 and all(
        body.get(k) == v for k, v in expected.items()
    )
    rep.record(
        "2", "GET", "/onboarding/status", resp.status_code, passed,
        f"flags={ {k: body.get(k) for k in expected} }",
    )


async def step_2b_normal_endpoints_reject(token: str, rep: Report) -> None:
    """GET /households/me, /household-settings, /categories, /dashboard/summary
    with a pre-household JWT must all return 403."""
    endpoints = [
        ("/households/me", None),
        ("/household-settings/", None),
        ("/categories/", None),
        ("/dashboard/summary", {"year": 2026, "month": 4}),
    ]
    all_ok = True
    outputs: dict[str, Any] = {}
    for ep, params in endpoints:
        kwargs = {"params": params} if params else {}
        resp = http_call("GET", f"{API_BASE}{ep}", token, **kwargs)
        outputs[ep] = {"status": resp.status_code, "body": _safe_json(resp)}
        if resp.status_code != 403:
            all_ok = False
    dump_json(SMOKE_DIR / "onboarding_02b_endpoints_reject.json", outputs)
    summary = "; ".join(f"{ep}->{outputs[ep]['status']}" for ep, _ in endpoints)
    rep.record("2b", "GET", "(4 endpoints)", "403x4" if all_ok else "mix", all_ok, summary)


async def step_3_create_household(token: str, rep: Report) -> str | None:
    body = {"household_name": "Verify HH", "display_name": "Verifier"}
    resp = http_call("POST", f"{API_BASE}/households/", token, json=body)
    dump_json(SMOKE_DIR / "onboarding_03_create_household.json", _safe_json(resp))
    if resp.status_code != 201:
        rep.record(
            "3", "POST", "/households", resp.status_code, False,
            f"expected 201, got {resp.status_code}: {_safe_json(resp)}",
        )
        return None
    payload = resp.json()
    hh_id = payload.get("household", {}).get("id")
    has_shape = all(k in payload for k in ("household", "member", "settings"))

    # DB probe: 0 categories in the new household.
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        cat_count = await conn.fetchval(
            "SELECT count(*) FROM categories WHERE household_id = $1", hh_id
        )
    finally:
        await conn.close()

    passed = has_shape and hh_id is not None and cat_count == 0
    rep.record(
        "3", "POST", "/households", resp.status_code, passed,
        f"household_id={hh_id} shape_ok={has_shape} category_count={cat_count}",
    )
    return hh_id


async def step_4_onboarding_status_post_hh(token: str, rep: Report) -> None:
    resp = http_call("GET", f"{API_BASE}/onboarding/status", token)
    body = _safe_json(resp)
    dump_json(SMOKE_DIR / "onboarding_04_status_post_hh.json", body)
    expected = {
        "has_household": True,
        "has_income_category": False,
        "has_expense_category": False,
        "has_savings_category": False,
        "is_ready": False,
    }
    passed = resp.status_code == 200 and all(
        body.get(k) == v for k, v in expected.items()
    )
    rep.record(
        "4", "GET", "/onboarding/status", resp.status_code, passed,
        f"flags={ {k: body.get(k) for k in expected} }",
    )


async def step_5_household_reads(token: str, rep: Report, household_id: str) -> None:
    r1 = http_call("GET", f"{API_BASE}/households/me", token)
    b1 = _safe_json(r1)
    dump_json(SMOKE_DIR / "onboarding_05a_households_me.json", b1)
    p1 = r1.status_code == 200 and b1.get("id") == household_id
    rep.record(
        "5a", "GET", "/households/me", r1.status_code, p1,
        f"id={b1.get('id')} matches_step3={p1}",
    )

    r2 = http_call("GET", f"{API_BASE}/household-settings/", token)
    b2 = _safe_json(r2)
    dump_json(SMOKE_DIR / "onboarding_05b_household_settings.json", b2)
    p2 = (
        r2.status_code == 200
        and b2.get("shift_late_income") is False
        and b2.get("late_income_cutoff_day") is None
    )
    rep.record(
        "5b", "GET", "/household-settings", r2.status_code, p2,
        f"shift_late_income={b2.get('shift_late_income')} "
        f"cutoff={b2.get('late_income_cutoff_day')}",
    )


async def step_6_receipt_block_without_categories(
    token: str, rep: Report
) -> tuple[str | None, dict | None]:
    # 6a: upload
    with open(FIXTURE_IMAGE, "rb") as f:
        files = {"file": (FIXTURE_IMAGE.name, f, "image/jpeg")}
        data = {"store_name": "OnboardingVerifyStore"}
        r_up = http_call(
            "POST", f"{API_BASE}/receipts/upload", token, files=files, data=data,
        )
    up_body = _safe_json(r_up)
    dump_json(SMOKE_DIR / "onboarding_06a_upload.json", up_body)
    up_ok = r_up.status_code == 201 and up_body.get("status") == "uploaded"
    rep.record(
        "6a", "POST", "/receipts/upload", r_up.status_code, up_ok,
        f"status={up_body.get('status')} id={up_body.get('id')}",
    )
    if not up_ok:
        return None, None
    receipt_id = up_body["id"]

    # 6b: parse
    r_pr = http_call("POST", f"{API_BASE}/receipts/{receipt_id}/parse", token)
    pr_body = _safe_json(r_pr)
    dump_json(SMOKE_DIR / "onboarding_06b_parse.json", pr_body)
    items = pr_body.get("items") or []
    pr_ok = (
        r_pr.status_code == 200
        and pr_body.get("status") == "ocr_complete"
        and len(items) > 0
    )
    rep.record(
        "6b", "POST", f"/receipts/{{id}}/parse", r_pr.status_code, pr_ok,
        f"status={pr_body.get('status')} items={len(items)}",
    )
    if not pr_ok:
        return receipt_id, None

    # Snapshot items from post-parse state for invariant check after 6c.
    pre_items_snapshot = {
        i["id"]: {
            "suggested_category_id": i.get("suggested_category_id"),
            "confidence": i.get("confidence"),
            "requires_review": i.get("requires_review"),
            "description": i.get("description"),
            "total_price": i.get("total_price"),
            "is_excluded": i.get("is_excluded"),
        }
        for i in items
    }

    # 6c: categorize — expect 422
    r_cat = http_call(
        "POST", f"{API_BASE}/receipts/{receipt_id}/categorize", token
    )
    cat_body = _safe_json(r_cat)
    dump_json(SMOKE_DIR / "onboarding_06c_categorize_blocked.json", cat_body)

    # Hard pass conditions for 6c:
    #  (a) 422 with "no active expense categories" message
    #  (b) receipt status still ocr_complete
    #  (c) receipt items unchanged (no suggestions written)
    msg = (cat_body.get("detail") or "").lower() if isinstance(cat_body, dict) else ""
    cond_a = r_cat.status_code == 422 and "no active expense categories" in msg

    # Fetch receipt + items directly via review payload endpoint for (b)/(c).
    r_chk = http_call(
        "GET", f"{API_BASE}/receipt-review/{receipt_id}/payload", token
    )
    chk_body = _safe_json(r_chk)
    dump_json(SMOKE_DIR / "onboarding_06c_post_check.json", chk_body)
    cond_b = r_chk.status_code == 200 and chk_body.get("status") == "ocr_complete"
    post_items = chk_body.get("items") or []
    unchanged = True
    for it in post_items:
        before = pre_items_snapshot.get(it["id"])
        if before is None:
            unchanged = False
            break
        for k in ("suggested_category_id", "confidence", "requires_review",
                  "description", "total_price", "is_excluded"):
            if before[k] != it.get(k):
                unchanged = False
                break
        if not unchanged:
            break
    cond_c = unchanged

    passed = cond_a and cond_b and cond_c
    rep.record(
        "6c", "POST", f"/receipts/{{id}}/categorize", r_cat.status_code, passed,
        f"msg_ok={cond_a} status_unchanged={cond_b} items_unchanged={cond_c}",
    )
    return receipt_id, pre_items_snapshot


async def step_7_create_categories(token: str, rep: Report) -> None:
    r1 = http_call(
        "POST", f"{API_BASE}/categories/", token,
        json={"type": "income", "name": "Salary"},
    )
    dump_json(SMOKE_DIR / "onboarding_07a_cat_income.json", _safe_json(r1))
    p1 = r1.status_code == 201
    rep.record(
        "7a", "POST", "/categories/ (income)", r1.status_code, p1,
        f"id={r1.json().get('id') if p1 else 'n/a'}",
    )

    r2 = http_call(
        "POST", f"{API_BASE}/categories/", token,
        json={"type": "expense", "name": "Groceries"},
    )
    dump_json(SMOKE_DIR / "onboarding_07b_cat_expense.json", _safe_json(r2))
    p2 = r2.status_code == 201
    rep.record(
        "7b", "POST", "/categories/ (expense)", r2.status_code, p2,
        f"id={r2.json().get('id') if p2 else 'n/a'}",
    )


async def step_8_onboarding_status_ready(token: str, rep: Report) -> None:
    resp = http_call("GET", f"{API_BASE}/onboarding/status", token)
    body = _safe_json(resp)
    dump_json(SMOKE_DIR / "onboarding_08_status_ready.json", body)
    expected = {
        "has_household": True,
        "has_income_category": True,
        "has_expense_category": True,
        "has_savings_category": False,
        "is_ready": True,
    }
    passed = resp.status_code == 200 and all(
        body.get(k) == v for k, v in expected.items()
    )
    rep.record(
        "8", "GET", "/onboarding/status", resp.status_code, passed,
        f"flags={ {k: body.get(k) for k in expected} }",
    )


async def step_9_recategorize(token: str, rep: Report, receipt_id: str) -> None:
    resp = http_call(
        "POST", f"{API_BASE}/receipts/{receipt_id}/categorize", token
    )
    body = _safe_json(resp)
    dump_json(SMOKE_DIR / "onboarding_09_categorize_ok.json", body)
    status_stayed = body.get("status") == "ocr_complete"
    items = body.get("items") or []
    # Per CLAUDE.md categorize rules: every item either has a
    # suggested_category_id OR requires_review=true with null suggestion.
    invariant_ok = all(
        (i.get("suggested_category_id") is not None)
        or (
            i.get("suggested_category_id") is None
            and i.get("requires_review") is True
        )
        for i in items
    )
    passed = resp.status_code == 200 and status_stayed and invariant_ok
    named = sum(1 for i in items if i.get("suggested_category_id") is not None)
    rep.record(
        "9", "POST", f"/receipts/{{id}}/categorize", resp.status_code, passed,
        f"status={body.get('status')} items={len(items)} "
        f"with_suggestion={named} invariant_ok={invariant_ok}",
    )


async def step_10_settings(token: str, rep: Report) -> None:
    # 10a: {"shift_late_income": true} — cutoff omitted, expect 422
    r_a = http_call(
        "PUT", f"{API_BASE}/household-settings/", token,
        json={"shift_late_income": True},
    )
    b_a = _safe_json(r_a)
    dump_json(SMOKE_DIR / "onboarding_10a_settings_omit_cutoff.json", b_a)
    msg_a = (b_a.get("detail") or "").lower() if isinstance(b_a, dict) else ""
    pass_a = (
        r_a.status_code == 422
        and "late_income_cutoff_day" in msg_a
        and "required" in msg_a
    )
    rep.record(
        "10a", "PUT", "/household-settings", r_a.status_code, pass_a,
        f"422+message_match={pass_a} detail={b_a.get('detail') if isinstance(b_a, dict) else b_a!r}",
    )

    # 10b: valid update — shift_late_income=true + cutoff=25 → 200
    r_b = http_call(
        "PUT", f"{API_BASE}/household-settings/", token,
        json={"shift_late_income": True, "late_income_cutoff_day": 25},
    )
    b_b = _safe_json(r_b)
    dump_json(SMOKE_DIR / "onboarding_10b_settings_ok.json", b_b)
    pass_b = (
        r_b.status_code == 200
        and b_b.get("shift_late_income") is True
        and b_b.get("late_income_cutoff_day") == 25
    )
    rep.record(
        "10b", "PUT", "/household-settings", r_b.status_code, pass_b,
        f"shift={b_b.get('shift_late_income')} cutoff={b_b.get('late_income_cutoff_day')}",
    )

    # 10c: {"late_income_cutoff_day": null} with shift still true → 422
    r_c = http_call(
        "PUT", f"{API_BASE}/household-settings/", token,
        json={"late_income_cutoff_day": None},
    )
    b_c = _safe_json(r_c)
    dump_json(SMOKE_DIR / "onboarding_10c_settings_null_cutoff.json", b_c)
    msg_c = (b_c.get("detail") or "").lower() if isinstance(b_c, dict) else ""
    pass_c = r_c.status_code == 422 and "late_income_cutoff_day" in msg_c
    rep.record(
        "10c", "PUT", "/household-settings", r_c.status_code, pass_c,
        f"422+message_match={pass_c} detail={b_c.get('detail') if isinstance(b_c, dict) else b_c!r}",
    )


# ---------- main orchestration ----------

async def main() -> int:
    SMOKE_DIR.mkdir(exist_ok=True)
    if not FIXTURE_IMAGE.exists():
        print(f"STOP: fixture missing: {FIXTURE_IMAGE}", file=sys.stderr)
        return 2
    print(f"Onboarding verify starting. Output dir: {SMOKE_DIR}")
    print(f"API base: {API_BASE}")

    rep = Report()
    household_id: str | None = None
    user_id, email, _pw = create_fresh_auth_user()
    print(f"Fresh auth user created. user_id=<redacted>")

    try:
        token = mint_jwt(email)
        if not token or len(token) < 20:
            rep.record("1", "-", "mint_jwt", "n/a", False, "token missing")
            rep.print_summary()
            return 1
        rep.record("1", "-", "mint_jwt", "ok", True, f"jwt_len={len(token)}")

        # Step 2: pre-household onboarding status
        await step_2_onboarding_status_pre(token, rep)

        # Step 2b: normal household-scoped endpoints must 403
        await step_2b_normal_endpoints_reject(token, rep)

        # Step 3: create household (captures household_id for cleanup)
        household_id = await step_3_create_household(token, rep)

        if household_id:
            # Step 4: onboarding status post-household
            await step_4_onboarding_status_post_hh(token, rep)
            # Step 5: household reads
            await step_5_household_reads(token, rep, household_id)
            # Step 6: receipt categorize-blocked guard
            receipt_id, _pre_snap = await step_6_receipt_block_without_categories(token, rep)
            # Step 7: create categories manually
            await step_7_create_categories(token, rep)
            # Step 8: onboarding status ready
            await step_8_onboarding_status_ready(token, rep)
            # Step 9: re-categorize now succeeds
            if receipt_id:
                await step_9_recategorize(token, rep, receipt_id)
            else:
                rep.record("9", "-", "/categorize", "skipped", False,
                           "no receipt_id from step 6")
            # Step 10: household-settings validation cases
            await step_10_settings(token, rep)
        else:
            print("STOP: household creation failed — skipping remaining steps.")

        rep.print_summary()
        verdict = "GO" if not rep.failed else "NO-GO"
        print(f"\nVERDICT: {verdict}")
        return 0 if not rep.failed else 1
    finally:
        try:
            await db_cleanup(user_id, household_id)
        finally:
            delete_auth_user(user_id)
        print("Cleanup complete.")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
