"""End-to-end receipt smoke test.

Runs from repo root. Uses the real .env (no secrets printed).
Covers:
  1. Mint a real Supabase JWT via admin generate_link + verify flow.
  2. upload -> parse -> categorize -> review payload.
  3. Invariant checks (hard + advisory) from the approved verification plan.
  4. Direct DB inspection via asyncpg.

All outputs go to .smoke/*.json (bodies) and stdout (status + pass/fail).
Never prints: JWT, service role key, anon key, database URL, email.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any
from uuid import UUID

import asyncpg
import httpx

# ---------- config loading ----------

def load_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip()
        # Only treat '#' as inline comment when NOT inside quotes.
        if v and v[0] in ('"', "'"):
            quote = v[0]
            end = v.find(quote, 1)
            if end != -1:
                v = v[1:end]
            else:
                v = v[1:]
        else:
            v = v.split("#", 1)[0].strip()
        out[k] = v
    return out


REPO_ROOT = Path(__file__).resolve().parent.parent
ENV = load_env(REPO_ROOT / ".env")

SUPABASE_URL = ENV["SUPABASE_URL"].rstrip("/")
SUPABASE_ANON_KEY = ENV["SUPABASE_ANON_KEY"]
SUPABASE_SERVICE_ROLE_KEY = ENV["SUPABASE_SERVICE_ROLE_KEY"]
DATABASE_URL = ENV["DATABASE_URL"]
CONFIDENCE_THRESHOLD = float(ENV.get("CATEGORIZATION_CONFIDENCE_THRESHOLD", "0.85"))

SMOKE_DIR = REPO_ROOT / ".smoke"
API_BASE = "http://127.0.0.1:8000/api/v1"
FIXTURE_IMAGE = REPO_ROOT / "backend" / "tests" / "fixtures" / "smoke_receipt.jpeg"

# ---------- tiny helpers ----------

def die(msg: str, *, payload: Any = None) -> None:
    print(f"\nSTOP: {msg}", file=sys.stderr)
    if payload is not None:
        try:
            print(json.dumps(payload, indent=2, default=str)[:4000], file=sys.stderr)
        except Exception:
            print(repr(payload)[:4000], file=sys.stderr)
    sys.exit(2)


def ok(msg: str) -> None:
    print(f"  [ok]   {msg}")


def fail(msg: str) -> None:
    print(f"  [FAIL] {msg}")


def note(msg: str) -> None:
    print(f"  [note] {msg}")


def dump_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, default=str))


# ---------- step 1: resolve smoke user + mint JWT ----------

async def find_smoke_user() -> tuple[UUID, UUID, str]:
    """Query the DB for one existing household member + its auth email."""
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        row = await conn.fetchrow(
            """
            SELECT hm.user_id, hm.household_id, u.email
            FROM household_members hm
            JOIN auth.users u ON u.id = hm.user_id
            WHERE u.email IS NOT NULL
            ORDER BY hm.user_id
            LIMIT 1
            """
        )
    finally:
        await conn.close()
    if row is None:
        die("No household_members row with a valid auth.users email found.")
    return row["user_id"], row["household_id"], row["email"]


def mint_jwt(email: str) -> str:
    """Mint a real Supabase access token for an existing user.

    Strategy: admin generate_link(magiclink) -> POST /auth/v1/verify with
    token_hash. Falls back to GET action_link and parsing the Location
    fragment if the verify endpoint rejects token_hash.
    """
    admin_headers = {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
    }
    with httpx.Client(timeout=30.0, follow_redirects=False) as c:
        r = c.post(
            f"{SUPABASE_URL}/auth/v1/admin/generate_link",
            headers=admin_headers,
            json={"type": "magiclink", "email": email},
        )
        if r.status_code != 200:
            die(f"generate_link failed HTTP {r.status_code}", payload=r.text[:500])
        body = r.json()
        # Supabase nests under "properties" in recent versions; older flat.
        props = body.get("properties") or body
        hashed_token = props.get("hashed_token")
        action_link = props.get("action_link")

        verify_url = f"{SUPABASE_URL}/auth/v1/verify"
        verify_headers = {
            "apikey": SUPABASE_ANON_KEY,
            "Content-Type": "application/json",
        }

        # Attempt A: POST /verify with token_hash
        if hashed_token:
            vr = c.post(
                verify_url,
                headers=verify_headers,
                json={"type": "magiclink", "token_hash": hashed_token},
            )
            if vr.status_code == 200:
                data = vr.json()
                if data.get("access_token"):
                    return data["access_token"]

        # Attempt B: GET action_link, parse Location fragment
        if action_link:
            gr = c.get(action_link)
            if gr.status_code in (301, 302, 303, 307, 308):
                loc = gr.headers.get("Location", "")
                # fragment after # contains access_token=...&refresh_token=...
                if "#" in loc:
                    frag = loc.split("#", 1)[1]
                    params = dict(
                        kv.split("=", 1) for kv in frag.split("&") if "=" in kv
                    )
                    if params.get("access_token"):
                        return params["access_token"]
            die(
                f"Could not extract token from action_link redirect "
                f"(status={gr.status_code}).",
                payload=gr.headers.get("Location", "")[:300],
            )

    die("generate_link response missing both hashed_token and action_link.")
    return ""  # unreachable


# ---------- step 2: HTTP flow helpers ----------

def http_call(method: str, url: str, token: str, **kwargs: Any) -> httpx.Response:
    headers = kwargs.pop("headers", {}) or {}
    headers["Authorization"] = f"Bearer {token}"
    with httpx.Client(timeout=120.0) as c:
        return c.request(method, url, headers=headers, **kwargs)


# ---------- step 3: invariant checks ----------

def run_invariants(review: dict[str, Any]) -> bool:
    print("\nReview payload invariants:")
    passed = True

    # a. HARD: status remains ocr_complete
    st = review.get("status")
    if st == "ocr_complete":
        ok(f"(a) status == ocr_complete")
    else:
        fail(f"(a) status == {st!r}, expected 'ocr_complete'")
        passed = False

    # b. HARD: image_url present and http(s)
    iu = review.get("image_url")
    if isinstance(iu, str) and iu.startswith("http"):
        ok("(b) image_url present (signed URL)")
    else:
        fail(f"(b) image_url missing or not http: {iu!r}")
        passed = False

    # c. HARD: duplicate_candidates is an array
    dc = review.get("duplicate_candidates")
    if isinstance(dc, list):
        ok(f"(c) duplicate_candidates is array (len={len(dc)})")
    else:
        fail(f"(c) duplicate_candidates not array: {type(dc).__name__}")
        passed = False

    items = review.get("items") or []
    total = len(items)
    if total == 0:
        fail("items list is empty — nothing to check")
        return False

    # d. HARD: every item has user_confirmed_category_id == null
    confirmed = [i for i in items if i.get("user_confirmed_category_id") is not None]
    if not confirmed:
        ok(f"(d) all {total} items have user_confirmed_category_id == null")
    else:
        fail(f"(d) {len(confirmed)} items have user_confirmed_category_id set")
        passed = False

    # e. ADVISORY: how many items got a category_name
    named = [i for i in items if i.get("suggested_category_name") is not None]
    note(f"(e) ADVISORY: {len(named)}/{total} items have a suggested_category_name")
    if len(named) == 0:
        note(
            "     all-null category names is allowed for ambiguous receipts; "
            "investigate only if the test image is clean+obviously categorizable"
        )

    # f. HARD: suggested_category_id != null AND confidence == null AND
    #         requires_review == false  => violation
    violators_f = [
        i for i in items
        if i.get("suggested_category_id") is not None
        and i.get("confidence") is None
        and i.get("requires_review") is False
    ]
    if not violators_f:
        ok("(f) no item has suggestion+null-confidence auto-trusted")
    else:
        fail(f"(f) {len(violators_f)} items violate the null-confidence rule")
        passed = False

    # g. HARD: low-confidence items still requires_review == true
    violators_g = [
        i for i in items
        if i.get("confidence") is not None
        and i.get("confidence") < CONFIDENCE_THRESHOLD
        and i.get("requires_review") is False
    ]
    if not violators_g:
        ok(f"(g) no low-confidence item (< {CONFIDENCE_THRESHOLD}) is auto-trusted")
    else:
        fail(f"(g) {len(violators_g)} low-confidence items have requires_review=false")
        passed = False

    # h. ADVISORY: high-confidence split
    hi = [
        i for i in items
        if i.get("confidence") is not None
        and i.get("confidence") >= CONFIDENCE_THRESHOLD
    ]
    hi_auto = [i for i in hi if i.get("requires_review") is False]
    hi_flag = [i for i in hi if i.get("requires_review") is True]
    note(
        f"(h) ADVISORY: high-confidence items (>= {CONFIDENCE_THRESHOLD}): "
        f"total={len(hi)} auto={len(hi_auto)} flagged={len(hi_flag)}"
    )

    # i. HARD: null-suggestion items must have requires_review == true
    violators_i = [
        i for i in items
        if i.get("suggested_category_id") is None
        and i.get("requires_review") is False
    ]
    if not violators_i:
        ok("(i) every null-suggestion item has requires_review=true")
    else:
        fail(f"(i) {len(violators_i)} null-suggestion items have requires_review=false")
        passed = False

    return passed


# ---------- step 4: DB inspection ----------

async def inspect_db(receipt_id: UUID, api_item_count: int) -> bool:
    print("\nDB inspection:")
    passed = True
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        r = await conn.fetchrow(
            """
            SELECT id, status, store_name, receipt_date, total_amount,
                   mime_type, ocr_provider, ocr_confidence,
                   (error_message IS NULL) AS error_is_null,
                   created_at, updated_at
            FROM receipts
            WHERE id = $1
            """,
            receipt_id,
        )
        if r is None:
            fail("receipts row not found")
            return False

        if r["status"] == "ocr_complete":
            ok("receipts.status == ocr_complete")
        else:
            fail(f"receipts.status == {r['status']!r}")
            passed = False

        if r["error_is_null"]:
            ok("receipts.error_message IS NULL")
        else:
            fail("receipts.error_message IS NOT NULL")
            passed = False

        expected_provider = ENV.get("OCR_PROVIDER", "anthropic")
        if r["ocr_provider"] == expected_provider:
            ok(f"receipts.ocr_provider == {expected_provider}")
        else:
            fail(
                f"receipts.ocr_provider == {r['ocr_provider']!r}, "
                f"expected {expected_provider!r}"
            )
            passed = False

        items = await conn.fetch(
            """
            SELECT line_number, description, total_price,
                   (suggested_category_id IS NOT NULL) AS has_suggestion,
                   confidence,
                   requires_review,
                   (user_confirmed_category_id IS NULL) AS user_confirmed_is_null,
                   is_excluded
            FROM receipt_items
            WHERE receipt_id = $1
            ORDER BY line_number
            """,
            receipt_id,
        )
        if len(items) == api_item_count:
            ok(f"receipt_items count ({len(items)}) matches API items")
        else:
            fail(f"receipt_items count {len(items)} != API items {api_item_count}")
            passed = False

        if all(i["user_confirmed_is_null"] for i in items):
            ok("every receipt_item has user_confirmed_category_id IS NULL")
        else:
            bad = sum(1 for i in items if not i["user_confirmed_is_null"])
            fail(f"{bad} receipt_items have user_confirmed_category_id SET")
            passed = False

        group_count = await conn.fetchval(
            "SELECT count(*) FROM transaction_groups WHERE receipt_id = $1",
            receipt_id,
        )
        if group_count == 0:
            ok("transaction_groups for this receipt == 0")
        else:
            fail(f"transaction_groups for this receipt == {group_count}")
            passed = False

        txn_count = await conn.fetchval(
            """
            SELECT count(*) FROM transactions t
            JOIN transaction_groups g ON g.id = t.group_id
            WHERE g.receipt_id = $1
            """,
            receipt_id,
        )
        if txn_count == 0:
            ok("transactions for this receipt == 0")
        else:
            fail(f"transactions for this receipt == {txn_count}")
            passed = False

    finally:
        await conn.close()
    return passed


# ---------- main orchestration ----------

async def main() -> int:
    SMOKE_DIR.mkdir(exist_ok=True)
    print(f"Smoke test starting. Output dir: {SMOKE_DIR}")

    if not FIXTURE_IMAGE.exists():
        die(f"Fixture image missing: {FIXTURE_IMAGE}")
    print(f"Fixture: {FIXTURE_IMAGE.name} ({FIXTURE_IMAGE.stat().st_size} bytes)")

    # --- JWT
    user_id, household_id, email = await find_smoke_user()
    # Do not print email or user_id.
    print(
        f"Smoke user resolved: user_id=<redacted> household_id=<redacted> "
        f"email=<redacted>"
    )
    token = mint_jwt(email)
    if not token or len(token) < 20:
        die("JWT acquisition failed (token too short).")
    print(f"JWT acquired (len={len(token)})")

    # --- Upload
    print("\n[1/4] Upload")
    with open(FIXTURE_IMAGE, "rb") as f:
        files = {"file": (FIXTURE_IMAGE.name, f, "image/jpeg")}
        data = {"store_name": "SmokeTestStore"}
        resp = http_call(
            "POST", f"{API_BASE}/receipts/upload", token,
            files=files, data=data,
        )
    dump_json(SMOKE_DIR / "01_upload.json", _safe_json(resp))
    print(f"  HTTP {resp.status_code}")
    if resp.status_code != 201:
        die("upload failed", payload=_safe_json(resp))
    body = resp.json()
    receipt_id = body["id"]
    if body.get("status") != "uploaded":
        die(f"upload: status != uploaded ({body.get('status')!r})")
    ok(f"status=uploaded  receipt_id={receipt_id}")

    # --- Parse
    print("\n[2/4] Parse")
    resp = http_call("POST", f"{API_BASE}/receipts/{receipt_id}/parse", token)
    dump_json(SMOKE_DIR / "02_parse.json", _safe_json(resp))
    print(f"  HTTP {resp.status_code}")
    if resp.status_code != 200:
        die("parse failed", payload=_safe_json(resp))
    pbody = resp.json()
    if pbody.get("status") != "ocr_complete":
        die(f"parse: status != ocr_complete ({pbody.get('status')!r})")
    item_count = len(pbody.get("items") or [])
    if item_count == 0:
        die("parse: items empty")
    ok(f"status=ocr_complete  items={item_count}")

    # Parse-time assertion: no item should have a suggested_category_id yet
    pre_cat_suggested = [
        i for i in pbody["items"] if i.get("suggested_category_id") is not None
    ]
    if pre_cat_suggested:
        fail(
            f"parse produced {len(pre_cat_suggested)} items with "
            f"suggested_category_id set (parse should not categorize)"
        )

    # --- Categorize
    print("\n[3/4] Categorize")
    resp = http_call("POST", f"{API_BASE}/receipts/{receipt_id}/categorize", token)
    dump_json(SMOKE_DIR / "03_categorize.json", _safe_json(resp))
    print(f"  HTTP {resp.status_code}")
    if resp.status_code != 200:
        die("categorize failed", payload=_safe_json(resp))
    cbody = resp.json()
    if cbody.get("status") != "ocr_complete":
        die(f"categorize: status moved to {cbody.get('status')!r}")
    ok("status still ocr_complete after categorize")

    # --- Review payload
    print("\n[4/4] Review payload")
    resp = http_call(
        "GET", f"{API_BASE}/receipt-review/{receipt_id}/payload", token
    )
    dump_json(SMOKE_DIR / "04_review.json", _safe_json(resp))
    print(f"  HTTP {resp.status_code}")
    if resp.status_code != 200:
        die("review payload failed", payload=_safe_json(resp))
    review = resp.json()

    invariants_passed = run_invariants(review)
    api_item_count = len(review.get("items") or [])
    db_passed = await inspect_db(UUID(receipt_id), api_item_count)

    print("\n" + "=" * 60)
    if invariants_passed and db_passed:
        print("SMOKE TEST PASSED")
        return 0
    print("SMOKE TEST FAILED")
    return 1


def _safe_json(resp: httpx.Response) -> Any:
    try:
        return resp.json()
    except Exception:
        return {"_raw_text": resp.text[:2000], "_status": resp.status_code}


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
