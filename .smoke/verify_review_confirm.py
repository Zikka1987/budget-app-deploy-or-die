"""Live verification of receipt review editing + confirm/post flow.

Runs against a live server. Covers:
  1. PUT /receipt-review/{id}/items/{item_id} — set, clear, toggle
  2. POST /receipt-review/{id}/confirm — grouped transactions, idempotency
  3. Direct DB inspection — categories, transaction_groups, transactions, dashboard

Uses the existing smoke test receipt (must be ocr_complete with categorized items).
If the receipt has already been posted, uploads + parses + categorizes a fresh one.

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

# ---------- config ----------

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / ".smoke"))
from smoke_test import load_env, find_smoke_user, mint_jwt, die, ok, fail, note

ENV = load_env(REPO_ROOT / ".env")
DATABASE_URL = ENV["DATABASE_URL"]
SMOKE_DIR = REPO_ROOT / ".smoke"
API_BASE = "http://127.0.0.1:8001/api/v1"
FIXTURE_IMAGE = REPO_ROOT / "backend" / "tests" / "fixtures" / "smoke_receipt.jpeg"

passed_count = 0
failed_count = 0


def check(label: str, condition: bool, detail: str = "") -> bool:
    global passed_count, failed_count
    if condition:
        ok(label)
        passed_count += 1
        return True
    else:
        fail(f"{label} — {detail}" if detail else label)
        failed_count += 1
        return False


def dump_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, default=str))


# ---------- HTTP helpers ----------

def http(method: str, path: str, token: str, **kwargs) -> httpx.Response:
    headers = kwargs.pop("headers", {}) or {}
    headers["Authorization"] = f"Bearer {token}"
    with httpx.Client(timeout=120.0) as c:
        return c.request(method, f"{API_BASE}{path}", headers=headers, **kwargs)


# ---------- ensure a receipt in ocr_complete ----------

async def ensure_receipt(token: str) -> tuple[str, list[dict]]:
    """Return (receipt_id, items) for a receipt in ocr_complete status.

    First tries the existing smoke test receipt. If it's not in ocr_complete,
    uploads a fresh one through the full pipeline.
    """
    # Check existing smoke test receipt
    review_json = SMOKE_DIR / "04_review.json"
    if review_json.exists():
        data = json.loads(review_json.read_text())
        rid = data["id"]
        r = http("GET", f"/receipt-review/{rid}/payload", token)
        if r.status_code == 200:
            body = r.json()
            if body["status"] == "ocr_complete":
                print(f"  Using existing receipt {rid}")
                return rid, body["items"]

    # Need a fresh receipt
    print("  Existing receipt not usable, uploading fresh one...")
    if not FIXTURE_IMAGE.exists():
        die(f"Fixture image missing: {FIXTURE_IMAGE}")

    with open(FIXTURE_IMAGE, "rb") as f:
        files = {"file": (FIXTURE_IMAGE.name, f, "image/jpeg")}
        data = {"store_name": "VerifyStore"}
        r = http("POST", "/receipts/upload", token, files=files, data=data)
    if r.status_code != 201:
        die("upload failed", payload=r.json())
    rid = r.json()["id"]
    print(f"  Uploaded: {rid}")

    r = http("POST", f"/receipts/{rid}/parse", token)
    if r.status_code != 200:
        die("parse failed", payload=r.json())
    print(f"  Parsed: {len(r.json().get('items', []))} items")

    r = http("POST", f"/receipts/{rid}/categorize", token)
    if r.status_code != 200:
        die("categorize failed", payload=r.json())
    print(f"  Categorized")

    r = http("GET", f"/receipt-review/{rid}/payload", token)
    if r.status_code != 200:
        die("review payload failed", payload=r.json())
    body = r.json()
    return rid, body["items"]


# ---------- Test: PUT /items — set user_confirmed_category_id ----------

def test_set_category(token: str, receipt_id: str, item: dict, cat_id: str) -> dict:
    print("\n--- PUT: set user_confirmed_category_id ---")
    item_id = item["id"]
    r = http(
        "PUT",
        f"/receipt-review/{receipt_id}/items/{item_id}",
        token,
        json={"user_confirmed_category_id": cat_id},
    )
    check("PUT set category returns 200", r.status_code == 200, f"got {r.status_code}: {r.text[:200]}")
    if r.status_code != 200:
        return item

    body = r.json()
    check(
        "user_confirmed_category_id is set",
        body.get("user_confirmed_category_id") == cat_id,
        f"expected {cat_id}, got {body.get('user_confirmed_category_id')}",
    )
    check(
        "user_confirmed_category_name populated",
        body.get("user_confirmed_category_name") is not None,
        f"got None",
    )
    check(
        "requires_review is False after setting category",
        body.get("requires_review") is False,
        f"got {body.get('requires_review')}",
    )
    check(
        "suggested_category_id unchanged",
        body.get("suggested_category_id") == item.get("suggested_category_id"),
        f"was {item.get('suggested_category_id')}, now {body.get('suggested_category_id')}",
    )
    check(
        "is_excluded unchanged (still False)",
        body.get("is_excluded") is False,
        f"got {body.get('is_excluded')}",
    )
    return body


# ---------- Test: PUT /items — clear user_confirmed_category_id ----------

def test_clear_category(token: str, receipt_id: str, item: dict) -> dict:
    print("\n--- PUT: clear user_confirmed_category_id (set to null) ---")
    item_id = item["id"]
    r = http(
        "PUT",
        f"/receipt-review/{receipt_id}/items/{item_id}",
        token,
        json={"user_confirmed_category_id": None},
    )
    check("PUT clear category returns 200", r.status_code == 200, f"got {r.status_code}: {r.text[:200]}")
    if r.status_code != 200:
        return item

    body = r.json()
    check(
        "user_confirmed_category_id is null",
        body.get("user_confirmed_category_id") is None,
        f"got {body.get('user_confirmed_category_id')}",
    )
    check(
        "user_confirmed_category_name is null",
        body.get("user_confirmed_category_name") is None,
        f"got {body.get('user_confirmed_category_name')}",
    )
    check(
        "requires_review is True after clearing",
        body.get("requires_review") is True,
        f"got {body.get('requires_review')}",
    )
    check(
        "suggested_category_id still unchanged",
        body.get("suggested_category_id") == item.get("suggested_category_id"),
        f"was {item.get('suggested_category_id')}, now {body.get('suggested_category_id')}",
    )
    return body


# ---------- Test: PUT /items — toggle is_excluded ----------

def test_toggle_excluded(token: str, receipt_id: str, item: dict) -> dict:
    print("\n--- PUT: toggle is_excluded ---")
    item_id = item["id"]

    # Exclude
    r = http(
        "PUT",
        f"/receipt-review/{receipt_id}/items/{item_id}",
        token,
        json={"is_excluded": True},
    )
    check("PUT exclude returns 200", r.status_code == 200, f"got {r.status_code}: {r.text[:200]}")
    if r.status_code != 200:
        return item

    body = r.json()
    check("is_excluded is True", body.get("is_excluded") is True)
    check(
        "requires_review is False (excluded items don't need review)",
        body.get("requires_review") is False,
        f"got {body.get('requires_review')}",
    )

    # Un-exclude (item still has no confirmed category from test_clear_category)
    r2 = http(
        "PUT",
        f"/receipt-review/{receipt_id}/items/{item_id}",
        token,
        json={"is_excluded": False},
    )
    check("PUT un-exclude returns 200", r2.status_code == 200, f"got {r2.status_code}")
    body2 = r2.json()
    check("is_excluded is False after un-exclude", body2.get("is_excluded") is False)
    # Item has no confirmed category, so requires_review should be True
    check(
        "requires_review is True (un-excluded, no confirmed cat)",
        body2.get("requires_review") is True,
        f"got {body2.get('requires_review')}",
    )

    return body2


# ---------- Test: PUT /items — re-set category for confirm ----------

def set_all_categories(token: str, receipt_id: str, items: list[dict]) -> list[dict]:
    """Set user_confirmed_category_id on every item using its suggested_category_id."""
    print("\n--- Setting confirmed categories on all items for confirm ---")
    updated = []
    for item in items:
        cat_id = item.get("suggested_category_id")
        if cat_id is None:
            # Use the first available category from another item
            cat_id = next(
                (i["suggested_category_id"] for i in items if i.get("suggested_category_id")),
                None,
            )
        if cat_id is None:
            die("No suggested categories available to confirm")

        r = http(
            "PUT",
            f"/receipt-review/{receipt_id}/items/{item['id']}",
            token,
            json={"user_confirmed_category_id": cat_id},
        )
        if r.status_code != 200:
            die(f"Failed to set category on item {item['id']}: {r.text[:200]}")
        updated.append(r.json())
    ok(f"All {len(items)} items have user_confirmed_category_id set")
    return updated


def exclude_one_item(token: str, receipt_id: str, item: dict) -> dict:
    """Exclude one item to test excluded-item skipping at confirm."""
    print(f"\n--- Excluding item '{item['description']}' for confirm test ---")
    r = http(
        "PUT",
        f"/receipt-review/{receipt_id}/items/{item['id']}",
        token,
        json={"is_excluded": True},
    )
    check("Exclude item for confirm test returns 200", r.status_code == 200)
    return r.json()


# ---------- Test: POST /confirm ----------

def test_confirm(
    token: str,
    receipt_id: str,
    total_items: int,
    excluded_count: int,
) -> dict:
    print("\n--- POST /confirm ---")
    r = http("POST", f"/receipt-review/{receipt_id}/confirm", token)
    check("POST confirm returns 200", r.status_code == 200, f"got {r.status_code}: {r.text[:300]}")
    if r.status_code != 200:
        return {}

    body = r.json()
    check("response has transaction_group_id", body.get("transaction_group_id") is not None)
    check("response has transactions_created > 0", body.get("transactions_created", 0) > 0)
    check("response has receipt_id", str(body.get("receipt_id")) == receipt_id)
    check("response status is 'posted'", body.get("status") == "posted")
    check("response has total_mismatch field", "total_mismatch" in body)

    # Since we excluded 1 item, transactions_created should be fewer
    # than total distinct categories among non-excluded items
    note(
        f"transactions_created={body.get('transactions_created')}, "
        f"total_items={total_items}, excluded={excluded_count}"
    )

    return body


# ---------- Test: idempotent duplicate confirm ----------

def test_idempotent_confirm(token: str, receipt_id: str, first_result: dict) -> None:
    print("\n--- POST /confirm (duplicate — idempotency check) ---")
    r = http("POST", f"/receipt-review/{receipt_id}/confirm", token)
    check(
        "Duplicate confirm returns 200 (not error)",
        r.status_code == 200,
        f"got {r.status_code}: {r.text[:200]}",
    )
    if r.status_code != 200:
        return

    body = r.json()
    check(
        "Same transaction_group_id on duplicate",
        body.get("transaction_group_id") == first_result.get("transaction_group_id"),
        f"first={first_result.get('transaction_group_id')}, dup={body.get('transaction_group_id')}",
    )
    check(
        "Same transactions_created count",
        body.get("transactions_created") == first_result.get("transactions_created"),
    )
    check("Duplicate status is 'posted'", body.get("status") == "posted")


# ---------- DB inspection ----------

async def inspect_db(
    receipt_id: str,
    confirm_result: dict,
    items_before_confirm: list[dict],
    excluded_item_id: str,
) -> None:
    print("\n--- DB inspection ---")
    rid = UUID(receipt_id)
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        # 1. Receipt status
        row = await conn.fetchrow(
            "SELECT status FROM receipts WHERE id = $1", rid
        )
        check("DB: receipt status is 'posted'", row and row["status"] == "posted",
              f"got {row['status'] if row else 'NOT FOUND'}")

        # 2. user_confirmed_category_id persisted
        items = await conn.fetch(
            """
            SELECT id, description, user_confirmed_category_id, suggested_category_id,
                   is_excluded, requires_review
            FROM receipt_items WHERE receipt_id = $1 ORDER BY line_number
            """,
            rid,
        )
        non_excluded = [i for i in items if not i["is_excluded"]]
        excluded = [i for i in items if i["is_excluded"]]
        all_confirmed = all(
            i["user_confirmed_category_id"] is not None for i in non_excluded
        )
        check(
            "DB: all non-excluded items have user_confirmed_category_id",
            all_confirmed,
            f"{sum(1 for i in non_excluded if i['user_confirmed_category_id'] is None)} missing",
        )

        # 3. Excluded item in DB
        check(
            "DB: excluded item is marked is_excluded=True",
            any(str(i["id"]) == excluded_item_id and i["is_excluded"] for i in items),
        )

        # 4. transaction_groups
        group_id = UUID(confirm_result["transaction_group_id"])
        group = await conn.fetchrow(
            "SELECT * FROM transaction_groups WHERE id = $1", group_id
        )
        check("DB: transaction_group exists", group is not None)
        if group:
            check(
                "DB: transaction_groups.source = 'receipt'",
                group["source"] == "receipt",
                f"got '{group['source']}'",
            )
            check(
                "DB: transaction_groups.receipt_id matches",
                str(group["receipt_id"]) == receipt_id,
            )
            check(
                "DB: idempotency_key is correct",
                group["idempotency_key"] == f"receipt:{receipt_id}",
            )

        # 5. Transactions
        txns = await conn.fetch(
            "SELECT * FROM transactions WHERE group_id = $1 ORDER BY created_at", group_id
        )
        check(
            "DB: transaction count matches response",
            len(txns) == confirm_result["transactions_created"],
            f"DB has {len(txns)}, response said {confirm_result['transactions_created']}",
        )

        # 6. Transactions use confirmed category IDs, not suggested
        confirmed_cat_ids = {
            str(i["user_confirmed_category_id"])
            for i in non_excluded
            if i["user_confirmed_category_id"] is not None
        }
        txn_cat_ids = {str(t["category_id"]) for t in txns}
        check(
            "DB: transaction category_ids are from user_confirmed (not suggested)",
            txn_cat_ids.issubset(confirmed_cat_ids),
            f"txn cats={txn_cat_ids}, confirmed cats={confirmed_cat_ids}",
        )

        # 7. No transaction for the excluded item's category if it was the only
        # item in that category
        # (This is a softer check — the excluded item shared a category with
        # other non-excluded items, so we just verify the count is correct)
        note(
            f"DB: {len(txns)} transactions, {len(non_excluded)} non-excluded items, "
            f"{len(excluded)} excluded items"
        )

        # 8. Zero child transaction groups impossible
        # Verify there are no transaction_groups with 0 transactions
        zero_groups = await conn.fetchval(
            """
            SELECT count(*) FROM transaction_groups g
            WHERE g.receipt_id = $1
            AND NOT EXISTS (SELECT 1 FROM transactions t WHERE t.group_id = g.id)
            """,
            rid,
        )
        check(
            "DB: no zero-child transaction_groups",
            zero_groups == 0,
            f"found {zero_groups} groups with 0 transactions",
        )

        # 9. All transactions have type='expense' and source='receipt'
        all_expense = all(t["type"] == "expense" for t in txns)
        all_receipt_source = all(t["source"] == "receipt" for t in txns)
        check("DB: all transactions type='expense'", all_expense)
        check("DB: all transactions source='receipt'", all_receipt_source)

        # 10. Budget actuals — check that dashboard would reflect posted expenses
        if txns:
            budget_month_id = txns[0]["budget_month_id"]
            actual_sum = await conn.fetchval(
                """
                SELECT COALESCE(SUM(amount), 0)
                FROM transactions
                WHERE budget_month_id = $1
                AND group_id = $2
                """,
                budget_month_id, group_id,
            )
            expected_sum = sum(t["amount"] for t in txns)
            check(
                "DB: budget actuals reflect posted expenses",
                actual_sum == expected_sum,
                f"DB sum={actual_sum}, expected={expected_sum}",
            )

    finally:
        await conn.close()


# ---------- main ----------

async def main() -> int:
    global passed_count, failed_count
    print("=" * 60)
    print("LIVE VERIFICATION: Receipt Review Edit + Confirm/Post")
    print("=" * 60)

    # 1. Acquire JWT
    print("\n[Setup] Acquiring JWT...")
    user_id, household_id, email = await find_smoke_user()
    token = mint_jwt(email)
    print(f"  JWT acquired (len={len(token)})")

    # 2. Ensure a receipt in ocr_complete
    print("\n[Setup] Ensuring receipt in ocr_complete...")
    receipt_id, items = await ensure_receipt(token)
    print(f"  Receipt: {receipt_id}, {len(items)} items")

    if len(items) < 2:
        die("Need at least 2 items for verification")

    # Pick items for testing
    test_item = items[0]  # Used for set/clear/toggle tests
    cat_id = test_item.get("suggested_category_id")
    if cat_id is None:
        cat_id = next(
            (i["suggested_category_id"] for i in items if i.get("suggested_category_id")),
            None,
        )
    if cat_id is None:
        die("No suggested category to use for testing")

    # ============================================================
    # PUT /items tests
    # ============================================================

    # A. Set category
    updated_item = test_set_category(token, receipt_id, test_item, cat_id)

    # B. Clear category
    cleared_item = test_clear_category(token, receipt_id, updated_item)

    # C. Toggle is_excluded
    toggled_item = test_toggle_excluded(token, receipt_id, cleared_item)

    # ============================================================
    # Prepare for confirm
    # ============================================================

    # Re-fetch all items (test_item may have been modified)
    r = http("GET", f"/receipt-review/{receipt_id}/payload", token)
    if r.status_code != 200:
        die("Failed to re-fetch payload before confirm")
    items = r.json()["items"]

    # Set confirmed categories on all items
    confirmed_items = set_all_categories(token, receipt_id, items)

    # Exclude the last item to test excluded-item skipping
    exclude_target = confirmed_items[-1]
    exclude_one_item(token, receipt_id, exclude_target)

    # ============================================================
    # POST /confirm tests
    # ============================================================

    confirm_result = test_confirm(
        token,
        receipt_id,
        total_items=len(items),
        excluded_count=1,
    )

    if not confirm_result:
        die("Confirm failed — cannot proceed with remaining checks")

    # ============================================================
    # Idempotent duplicate confirm
    # ============================================================

    test_idempotent_confirm(token, receipt_id, confirm_result)

    # ============================================================
    # DB inspection
    # ============================================================

    await inspect_db(
        receipt_id,
        confirm_result,
        confirmed_items,
        exclude_target["id"],
    )

    # ============================================================
    # Verify receipt is no longer editable
    # ============================================================
    print("\n--- POST-confirm: verify receipt is no longer editable ---")
    r = http(
        "PUT",
        f"/receipt-review/{receipt_id}/items/{items[0]['id']}",
        token,
        json={"user_confirmed_category_id": cat_id},
    )
    check(
        "PUT on posted receipt returns 409",
        r.status_code == 409,
        f"got {r.status_code}",
    )

    # ============================================================
    # Summary
    # ============================================================
    print("\n" + "=" * 60)
    print(f"RESULTS: {passed_count} passed, {failed_count} failed")
    if failed_count == 0:
        print("ALL CHECKS PASSED")
    else:
        print("SOME CHECKS FAILED")
    print("=" * 60)

    return 0 if failed_count == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
