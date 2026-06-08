"""Phase 5 mobile search verification.

Verifies the live backend search endpoints (/api/v1/search/receipts and
/api/v1/search/transactions) against an isolated test user and household.

Workflow:
  - Probe http://127.0.0.1:8000 then :8765 to discover the live backend port.
  - Create a fresh Supabase auth user via the admin API.
  - Mint a JWT, create a fresh household, seed the minimum data needed.
  - Run 23 API scenarios (see plan).
  - Clean up everything in FK dependency order, then delete the auth user.

Exits 0 on GO (all steps pass), 1 on NO-GO.
"""

from __future__ import annotations

import asyncio
import json
import secrets
import sys
from datetime import date
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import asyncpg
import httpx

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / ".smoke"))
from smoke_test import load_env, mint_jwt  # type: ignore

ENV = load_env(REPO_ROOT / ".env")
DATABASE_URL = ENV["DATABASE_URL"]
SUPABASE_URL = ENV["SUPABASE_URL"].rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = ENV["SUPABASE_SERVICE_ROLE_KEY"]

SMOKE_DIR = REPO_ROOT / ".smoke"
TODAY = date.today()
BUDGET_MONTH_DATE = date(TODAY.year, TODAY.month, 1)

ADMIN_HEADERS = {
    "apikey": SUPABASE_SERVICE_ROLE_KEY,
    "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
    "Content-Type": "application/json",
}


# ---------- port discovery ----------

def discover_base_url() -> str:
    candidates = ["http://127.0.0.1:8000", "http://127.0.0.1:8765"]
    for base in candidates:
        try:
            with httpx.Client(timeout=3.0) as c:
                r = c.get(f"{base}/openapi.json")
                if r.status_code == 200:
                    return f"{base}/api/v1"
        except Exception:
            continue
    print("STOP: backend not reachable on :8000 or :8765", file=sys.stderr)
    sys.exit(2)


API_BASE = discover_base_url()


# ---------- report ----------

class Report:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []
        self.failed = False

    def record(self, step: str, method: str, path: str, status, passed: bool, summary: str) -> None:
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


# ---------- HTTP ----------

def http(method: str, path: str, token: str, **kwargs) -> httpx.Response:
    headers = kwargs.pop("headers", {}) or {}
    headers["Authorization"] = f"Bearer {token}"
    with httpx.Client(timeout=30.0) as c:
        return c.request(method, f"{API_BASE}{path}", headers=headers, **kwargs)


def _json(resp: httpx.Response) -> Any:
    try:
        return resp.json()
    except Exception:
        return {"_raw_text": resp.text[:2000], "_status": resp.status_code}


def dump(name: str, data: Any) -> None:
    (SMOKE_DIR / f"search_{name}.json").write_text(json.dumps(data, indent=2, default=str))


# ---------- auth ----------

def create_fresh_user() -> tuple[str, str]:
    email = f"search-verify-{secrets.token_hex(4)}@budget-app-test.local"
    password = secrets.token_urlsafe(24)
    with httpx.Client(timeout=30.0) as c:
        r = c.post(
            f"{SUPABASE_URL}/auth/v1/admin/users",
            headers=ADMIN_HEADERS,
            json={"email": email, "password": password, "email_confirm": True},
        )
    if r.status_code not in (200, 201):
        print(f"STOP: admin/users HTTP {r.status_code}: {r.text[:300]}", file=sys.stderr)
        sys.exit(2)
    return r.json()["id"], email


def delete_auth_user(user_id: str) -> None:
    try:
        with httpx.Client(timeout=30.0) as c:
            c.delete(
                f"{SUPABASE_URL}/auth/v1/admin/users/{user_id}",
                headers=ADMIN_HEADERS,
            )
    except Exception as e:
        print(f"  [cleanup warn] delete user: {e}")


# ---------- seeding ----------

async def seed_data(token: str, user_id: str, household_id: str, rep: Report) -> dict[str, Any]:
    """Seed the minimum data needed for all scenarios."""
    ids: dict[str, Any] = {}
    user_uuid = UUID(user_id)
    hh_uuid = UUID(household_id)

    # Categories
    for ttype, name, slot in [
        ("expense", "Groceries (search)", "expense_a_id"),
        ("expense", "Transport (search)", "expense_b_id"),
        ("income", "Salary (search)", "income_cat_id"),
        ("savings", "Emergency (search)", "savings_cat_id"),
    ]:
        r = http("POST", "/categories/", token, json={"type": ttype, "name": name})
        if r.status_code != 201:
            rep.record(f"setup.cat.{slot}", "POST", "/categories/", r.status_code, False, str(_json(r)))
            return ids
        ids[slot] = UUID(_json(r)["id"])
    rep.record("setup.categories", "POST", "/categories/", 201, True,
               "4 categories created")

    # Initialize current budget month
    r = http("POST", "/budgets/months/initialize", token, json={"month": str(BUDGET_MONTH_DATE)})
    if r.status_code not in (200, 201):
        rep.record("setup.month", "POST", "/budgets/months/initialize", r.status_code, False, str(_json(r)))
        return ids
    ids["budget_month_id"] = UUID(_json(r)["id"])
    rep.record("setup.month", "POST", "/budgets/months/initialize", r.status_code, True,
               f"month_id={ids['budget_month_id']}")

    # Income transaction (manual_income source)
    r = http("POST", "/incomes/", token, json={
        "category_id": str(ids["income_cat_id"]),
        "amount": "30000.00",
        "transaction_date": str(TODAY),
        "description": "Search verify income",
    })
    if r.status_code != 201:
        rep.record("setup.income", "POST", "/incomes/", r.status_code, False, str(_json(r)))
        return ids
    ids["income_txn_id"] = UUID(_json(r)["id"])
    rep.record("setup.income", "POST", "/incomes/", 201, True, f"id={ids['income_txn_id']}")

    # Manual savings (manual_savings source)
    r = http("POST", "/savings/manual", token, json={
        "category_id": str(ids["savings_cat_id"]),
        "amount": 500.00,
        "transaction_date": str(TODAY),
        "description": "Search verify manual savings",
    })
    if r.status_code != 201:
        rep.record("setup.manual_savings", "POST", "/savings/manual", r.status_code, False, str(_json(r)))
        return ids
    ids["manual_savings_id"] = UUID(_json(r)["id"])
    rep.record("setup.manual_savings", "POST", "/savings/manual", 201, True,
               f"id={ids['manual_savings_id']}")

    # Savings rule + proposal + approve (savings_proposal source)
    r = http("POST", "/savings/rules", token, json={
        "category_id": str(ids["savings_cat_id"]),
        "rule_type": "fixed_monthly",
        "label": "Search rule",
        "fixed_amount": 750.00,
    })
    if r.status_code != 201:
        rep.record("setup.rule", "POST", "/savings/rules", r.status_code, False, str(_json(r)))
        return ids
    ids["rule_id"] = UUID(_json(r)["id"])

    r = http("POST", "/savings/proposals/generate", token,
             json={"budget_month_id": str(ids["budget_month_id"])})
    if r.status_code not in (200, 201):
        rep.record("setup.gen", "POST", "/savings/proposals/generate", r.status_code, False, str(_json(r)))
        return ids
    proposals = _json(r).get("proposals", [])
    if not proposals:
        rep.record("setup.gen", "POST", "/savings/proposals/generate", r.status_code, False, "no proposals returned")
        return ids
    ids["proposal_id"] = proposals[0]["id"]

    r = http("POST", f"/savings/proposals/{ids['proposal_id']}/approve", token, json={})
    if r.status_code not in (200, 201):
        rep.record("setup.approve", "POST", "/savings/proposals/approve", r.status_code, False, str(_json(r)))
        return ids
    rep.record("setup.savings_pipeline", "POST", "/savings/*", 200, True,
               f"rule={ids['rule_id']} proposal={ids['proposal_id']} approved")

    # Posted receipt + items + receipt-sourced expense transactions (DB inserts;
    # the OCR confirm flow is tested elsewhere — here we just need a posted receipt).
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        receipt_id = uuid4()
        ids["receipt_id"] = receipt_id
        await conn.execute(
            """
            INSERT INTO receipts (id, household_id, uploaded_by, status,
                store_name, receipt_date, total_amount,
                storage_path, mime_type)
            VALUES ($1, $2, $3, 'posted', 'SearchVerifyMart', $4, 425.00,
                'smoke/search_test.jpg', 'image/jpeg')
            """,
            receipt_id, hh_uuid, user_uuid, TODAY,
        )

        item_a, item_b = uuid4(), uuid4()
        ids["item_ids"] = [item_a, item_b]
        await conn.execute(
            """
            INSERT INTO receipt_items
                (id, receipt_id, line_number, description, total_price,
                 user_confirmed_category_id, requires_review, is_excluded)
            VALUES
                ($1, $2, 1, 'Item A', 275.00, $3, false, false),
                ($4, $2, 2, 'Item B', 150.00, $5, false, false)
            """,
            item_a, receipt_id, ids["expense_a_id"],
            item_b, ids["expense_b_id"],
        )

        group_id = uuid4()
        ids["group_id"] = group_id
        await conn.execute(
            """
            INSERT INTO transaction_groups
                (id, household_id, receipt_id, source, idempotency_key, created_by)
            VALUES ($1, $2, $3, 'receipt', $4, $5)
            """,
            group_id, hh_uuid, receipt_id, f"receipt:{receipt_id}", user_uuid,
        )

        txn_a, txn_b = uuid4(), uuid4()
        ids["receipt_txn_ids"] = [txn_a, txn_b]
        await conn.execute(
            """
            INSERT INTO transactions
                (id, group_id, household_id, type, category_id, amount,
                 description, transaction_date, effective_date,
                 budget_month_id, source, posted_by)
            VALUES
                ($1, $2, $3, 'expense', $4, 275.00,
                 'Item A', $5, $5, $6, 'receipt', $7),
                ($8, $2, $3, 'expense', $9, 150.00,
                 'Item B', $5, $5, $6, 'receipt', $7)
            """,
            txn_a, group_id, hh_uuid, ids["expense_a_id"],
            TODAY, ids["budget_month_id"], user_uuid,
            txn_b, ids["expense_b_id"],
        )
        rep.record("setup.receipt_db", "-", "db_insert receipt+items+txns", "ok", True,
                   f"receipt={receipt_id} group={group_id} txns=2")
    finally:
        await conn.close()

    return ids


# ---------- scenario helpers ----------

def assert_status(rep: Report, step: str, label: str, r: httpx.Response,
                  expected: int, summary: str) -> bool:
    passed = r.status_code == expected
    rep.record(step, "GET", label, r.status_code, passed,
               summary if passed else f"{summary} | body={r.text[:200]}")
    return passed


def all_in(items, key, allowed) -> bool:
    return all(it.get(key) in allowed for it in items)


# ---------- scenario suite ----------

def run_scenarios(token: str, ids: dict[str, Any], rep: Report) -> None:
    receipt_id = str(ids["receipt_id"])
    expense_cat_a = str(ids["expense_a_id"])

    # 1: receipts no filters → total >= 1, our receipt present
    r = http("GET", "/search/receipts", token)
    body = _json(r)
    dump("01_receipts_all", body)
    found = any(x["id"] == receipt_id for x in body.get("results", []))
    rep.record("1", "GET", "/search/receipts", r.status_code,
               r.status_code == 200 and body.get("total", 0) >= 1 and found,
               f"total={body.get('total')} found_our={found}")

    # 2: merchant substring
    r = http("GET", "/search/receipts?merchant=searchverify", token)
    body = _json(r)
    dump("02_receipts_merchant", body)
    found = any(x["id"] == receipt_id for x in body.get("results", []))
    rep.record("2", "GET", "/search/receipts?merchant=searchverify", r.status_code,
               r.status_code == 200 and found,
               f"total={body.get('total')} found_our={found}")

    # 3: status=posted
    r = http("GET", "/search/receipts?status=posted", token)
    body = _json(r)
    dump("03_receipts_status_posted", body)
    all_posted = all_in(body.get("results", []), "status", {"posted"})
    rep.record("3", "GET", "/search/receipts?status=posted", r.status_code,
               r.status_code == 200 and all_posted and body.get("total", 0) >= 1,
               f"total={body.get('total')} all_posted={all_posted}")

    # 4: date range
    r = http("GET", f"/search/receipts?date_from={TODAY}&date_to={TODAY}", token)
    body = _json(r)
    dump("04_receipts_date", body)
    found = any(x["id"] == receipt_id for x in body.get("results", []))
    rep.record("4", "GET", "/search/receipts?date_from/to", r.status_code,
               r.status_code == 200 and found,
               f"total={body.get('total')} found_our={found}")

    # 5: amount range (our receipt total is 425.00)
    r = http("GET", "/search/receipts?amount_min=400&amount_max=500", token)
    body = _json(r)
    dump("05_receipts_amount", body)
    found = any(x["id"] == receipt_id for x in body.get("results", []))
    rep.record("5", "GET", "/search/receipts?amount_min/max", r.status_code,
               r.status_code == 200 and found,
               f"total={body.get('total')} found_our={found}")

    # 6: by category
    r = http("GET", f"/search/receipts?category_id={expense_cat_a}", token)
    body = _json(r)
    dump("06_receipts_category", body)
    found = any(x["id"] == receipt_id for x in body.get("results", []))
    rep.record("6", "GET", "/search/receipts?category_id=...", r.status_code,
               r.status_code == 200 and found,
               f"total={body.get('total')} found_our={found}")

    # 7: pagination — limit=1 offset=0 then offset=1, no overlap (we only have 1
    # receipt for this fresh user, so first page has 1 row, second page has 0)
    r1 = http("GET", "/search/receipts?limit=1&offset=0", token)
    r2 = http("GET", "/search/receipts?limit=1&offset=1", token)
    b1, b2 = _json(r1), _json(r2)
    dump("07_receipts_paginate", {"page1": b1, "page2": b2})
    ids1 = {x["id"] for x in b1.get("results", [])}
    ids2 = {x["id"] for x in b2.get("results", [])}
    no_overlap = ids1.isdisjoint(ids2)
    rep.record("7", "GET", "/search/receipts pagination",
               f"{r1.status_code}/{r2.status_code}",
               r1.status_code == 200 and r2.status_code == 200 and len(ids1) == 1 and no_overlap,
               f"p1={len(ids1)} p2={len(ids2)} no_overlap={no_overlap}")

    # 8: transactions no filters
    r = http("GET", "/search/transactions", token)
    body = _json(r)
    dump("08_txn_all", body)
    rep.record("8", "GET", "/search/transactions", r.status_code,
               r.status_code == 200 and body.get("total", 0) >= 4,
               f"total={body.get('total')} (expect >=4)")

    # 9: type=income
    r = http("GET", "/search/transactions?type=income", token)
    body = _json(r)
    dump("09_txn_income", body)
    all_income = all_in(body.get("results", []), "type", {"income"})
    rep.record("9", "GET", "/search/transactions?type=income", r.status_code,
               r.status_code == 200 and all_income and body.get("total", 0) >= 1,
               f"total={body.get('total')} all_income={all_income}")

    # 10: type=expense
    r = http("GET", "/search/transactions?type=expense", token)
    body = _json(r)
    dump("10_txn_expense", body)
    all_expense = all_in(body.get("results", []), "type", {"expense"})
    rep.record("10", "GET", "/search/transactions?type=expense", r.status_code,
               r.status_code == 200 and all_expense and body.get("total", 0) >= 2,
               f"total={body.get('total')} all_expense={all_expense}")

    # 11: type=savings (covers manual_savings and savings_proposal)
    r = http("GET", "/search/transactions?type=savings", token)
    body = _json(r)
    dump("11_txn_savings", body)
    sources = {x["source"] for x in body.get("results", [])}
    all_savings = all_in(body.get("results", []), "type", {"savings"})
    has_both = "manual_savings" in sources and "savings_proposal" in sources
    rep.record("11", "GET", "/search/transactions?type=savings", r.status_code,
               r.status_code == 200 and all_savings and has_both,
               f"total={body.get('total')} all_savings={all_savings} both_sources={has_both} sources={sources}")

    # 12: source=receipt (all rows have store_name)
    r = http("GET", "/search/transactions?source=receipt", token)
    body = _json(r)
    dump("12_txn_source_receipt", body)
    results = body.get("results", [])
    all_receipt = all_in(results, "source", {"receipt"})
    has_store = all(x.get("store_name") for x in results)
    rep.record("12", "GET", "/search/transactions?source=receipt", r.status_code,
               r.status_code == 200 and all_receipt and has_store and len(results) >= 2,
               f"n={len(results)} all_receipt={all_receipt} has_store={has_store}")

    # 13: source=savings_proposal — all are savings type
    r = http("GET", "/search/transactions?source=savings_proposal", token)
    body = _json(r)
    dump("13_txn_source_proposal", body)
    results = body.get("results", [])
    all_savings = all_in(results, "type", {"savings"})
    rep.record("13", "GET", "/search/transactions?source=savings_proposal", r.status_code,
               r.status_code == 200 and all_savings and len(results) >= 1,
               f"n={len(results)} all_savings={all_savings}")

    # 14: date range
    r = http("GET", f"/search/transactions?date_from={TODAY}&date_to={TODAY}", token)
    body = _json(r)
    dump("14_txn_date", body)
    rep.record("14", "GET", "/search/transactions?date_from/to", r.status_code,
               r.status_code == 200 and body.get("total", 0) >= 4,
               f"total={body.get('total')}")

    # 15: amount range (manual savings is 500, expense items 150 and 275)
    r = http("GET", "/search/transactions?amount_min=100&amount_max=300", token)
    body = _json(r)
    dump("15_txn_amount", body)
    in_range = all(100 <= float(x["amount"]) <= 300 for x in body.get("results", []))
    rep.record("15", "GET", "/search/transactions?amount_min/max", r.status_code,
               r.status_code == 200 and in_range and body.get("total", 0) >= 2,
               f"total={body.get('total')} in_range={in_range}")

    # 16: category_id
    r = http("GET", f"/search/transactions?category_id={expense_cat_a}", token)
    body = _json(r)
    dump("16_txn_category", body)
    in_cat = all(x["category_id"] == expense_cat_a for x in body.get("results", []))
    rep.record("16", "GET", "/search/transactions?category_id=...", r.status_code,
               r.status_code == 200 and in_cat and body.get("total", 0) >= 1,
               f"total={body.get('total')} in_cat={in_cat}")

    # 17: pagination — limit=2 offset=0 then offset=2, no overlap
    r1 = http("GET", "/search/transactions?limit=2&offset=0", token)
    r2 = http("GET", "/search/transactions?limit=2&offset=2", token)
    b1, b2 = _json(r1), _json(r2)
    dump("17_txn_paginate", {"page1": b1, "page2": b2})
    s1 = {x["id"] for x in b1.get("results", [])}
    s2 = {x["id"] for x in b2.get("results", [])}
    no_overlap = s1.isdisjoint(s2)
    rep.record("17", "GET", "/search/transactions pagination",
               f"{r1.status_code}/{r2.status_code}",
               r1.status_code == 200 and r2.status_code == 200 and no_overlap and len(s1) == 2,
               f"p1={len(s1)} p2={len(s2)} no_overlap={no_overlap}")

    # 18: combined — type=expense + date_from=TODAY + amount_min=200 should match Item A only
    r = http("GET",
             f"/search/transactions?type=expense&date_from={TODAY}&amount_min=200", token)
    body = _json(r)
    dump("18_txn_combined", body)
    results = body.get("results", [])
    all_expense_in_range = all(x["type"] == "expense" and float(x["amount"]) >= 200 for x in results)
    rep.record("18", "GET", "/search/transactions combined",
               r.status_code,
               r.status_code == 200 and all_expense_in_range and body.get("total", 0) >= 1,
               f"total={body.get('total')} all_match={all_expense_in_range}")

    # 19: empty result
    r = http("GET", "/search/transactions?amount_min=99999999", token)
    body = _json(r)
    dump("19_txn_empty", body)
    rep.record("19", "GET", "/search/transactions empty", r.status_code,
               r.status_code == 200 and body.get("total") == 0 and body.get("results") == [],
               f"total={body.get('total')} results_len={len(body.get('results', []))}")

    # 20-23: invalid range validation -> expect 422
    r = http("GET", "/search/receipts?date_from=2026-12-31&date_to=2026-01-01", token)
    rep.record("20", "GET", "/search/receipts bad date range", r.status_code,
               r.status_code == 422, f"expected 422 got {r.status_code}")

    r = http("GET", "/search/receipts?amount_min=1000&amount_max=10", token)
    rep.record("21", "GET", "/search/receipts bad amount range", r.status_code,
               r.status_code == 422, f"expected 422 got {r.status_code}")

    r = http("GET", "/search/transactions?date_from=2026-12-31&date_to=2026-01-01", token)
    rep.record("22", "GET", "/search/transactions bad date range", r.status_code,
               r.status_code == 422, f"expected 422 got {r.status_code}")

    r = http("GET", "/search/transactions?amount_min=1000&amount_max=10", token)
    rep.record("23", "GET", "/search/transactions bad amount range", r.status_code,
               r.status_code == 422, f"expected 422 got {r.status_code}")


# ---------- cleanup ----------

async def cleanup(rep: Report, household_id: str | None,
                  user_id: str | None, ids: dict[str, Any]) -> None:
    if not household_id:
        if user_id:
            delete_auth_user(user_id)
        return

    hh_uuid = UUID(household_id)
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        # Receipt-sourced txns + group + receipt
        if ids.get("group_id"):
            await conn.execute("DELETE FROM transactions WHERE group_id = $1", ids["group_id"])
            await conn.execute("DELETE FROM transaction_groups WHERE id = $1", ids["group_id"])
        if ids.get("receipt_id"):
            await conn.execute("DELETE FROM receipt_items WHERE receipt_id = $1", ids["receipt_id"])
            await conn.execute("DELETE FROM receipts WHERE id = $1", ids["receipt_id"])

        # All remaining transactions (income, manual savings, savings_proposal)
        # belong to this household — wipe by household.
        await conn.execute(
            "DELETE FROM transactions WHERE household_id = $1", hh_uuid,
        )
        await conn.execute(
            "DELETE FROM transaction_groups WHERE household_id = $1", hh_uuid,
        )

        # Savings proposals + rules
        await conn.execute(
            "DELETE FROM savings_proposals WHERE household_id = $1", hh_uuid,
        )
        await conn.execute(
            "DELETE FROM savings_rules WHERE household_id = $1", hh_uuid,
        )

        # Budget lines + months
        await conn.execute(
            "DELETE FROM budget_lines WHERE budget_month_id IN "
            "(SELECT id FROM budget_months WHERE household_id = $1)",
            hh_uuid,
        )
        await conn.execute(
            "DELETE FROM budget_months WHERE household_id = $1", hh_uuid,
        )

        # Categories (no aliases for fresh categories)
        await conn.execute(
            "DELETE FROM category_aliases WHERE category_id IN "
            "(SELECT id FROM categories WHERE household_id = $1)",
            hh_uuid,
        )
        await conn.execute(
            "DELETE FROM categories WHERE household_id = $1", hh_uuid,
        )

        # Membership + settings + household
        await conn.execute(
            "DELETE FROM household_settings WHERE household_id = $1", hh_uuid,
        )
        await conn.execute(
            "DELETE FROM household_members WHERE household_id = $1", hh_uuid,
        )
        await conn.execute(
            "DELETE FROM households WHERE id = $1", hh_uuid,
        )
        rep.record("cleanup", "-", "DB cleanup", "ok", True, "household removed")
    except Exception as e:
        rep.record("cleanup", "-", "DB cleanup", "fail", False, str(e))
    finally:
        await conn.close()

    if user_id:
        delete_auth_user(user_id)


# ---------- main ----------

async def main() -> int:
    SMOKE_DIR.mkdir(exist_ok=True)
    print("=" * 60)
    print("LIVE VERIFICATION: Phase 5 Search (fresh isolated user)")
    print(f"BASE_URL: {API_BASE}")
    print(f"Date: {TODAY}")
    print("=" * 60)

    rep = Report()

    # Fresh user
    print("\n[setup] creating fresh auth user...")
    user_id, email = create_fresh_user()
    print(f"  user_id={user_id}")
    token = mint_jwt(email)
    if not token or len(token) < 20:
        print("STOP: JWT mint failed", file=sys.stderr)
        delete_auth_user(user_id)
        return 1

    # Fresh household
    r = http("POST", "/households/", token, json={
        "household_name": "Search Verify HH", "display_name": "Searcher",
    })
    body = _json(r)
    if r.status_code != 201:
        print(f"STOP: household creation failed: {body}", file=sys.stderr)
        delete_auth_user(user_id)
        return 1
    household_id = body["household"]["id"]
    print(f"  household_id={household_id}")

    ids: dict[str, Any] = {}
    try:
        print("\n[setup] seeding data...")
        ids = await seed_data(token, user_id, household_id, rep)
        if rep.failed:
            rep.print_summary()
            return 1

        print("\n[scenarios] running 23 search scenarios...")
        run_scenarios(token, ids, rep)

        rep.print_summary()
        verdict = "GO" if not rep.failed else "NO-GO"
        print(f"\nVERDICT: {verdict}")
    finally:
        print("\n[cleanup] removing test data + user...")
        await cleanup(rep, household_id, user_id, ids)
        print("Cleanup complete.")

    return 0 if not rep.failed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
