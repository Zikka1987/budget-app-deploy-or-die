"""Phase 4 mobile-specific gap verification.

Covers scenarios from the mobile Phase 4 plan that are NOT exercised by
`savings_verify.py`:

  10  Update rule label              PUT /savings/rules/{id}
  11  Toggle rule inactive then on   PUT /savings/rules/{id} (is_active toggle)
  15  Approve with override amount   POST /savings/proposals/{id}/approve {final_amount}
  17  Re-approve already-posted -> 409

Uses the existing smoke user. Cleans up after itself.
Exits 0 on GO, 1 on NO-GO.
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any
from uuid import UUID

import asyncpg
import httpx

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / ".smoke"))
from smoke_test import load_env, find_smoke_user, mint_jwt  # type: ignore

ENV = load_env(REPO_ROOT / ".env")
DATABASE_URL = ENV["DATABASE_URL"]
SMOKE_DIR = REPO_ROOT / ".smoke"
API_BASE = "http://127.0.0.1:8765/api/v1"

TODAY = date.today()
BUDGET_MONTH_DATE = date(TODAY.year, TODAY.month, 1)


class Report:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []
        self.failed = False

    def record(self, step: str, method: str, path: str, status, passed: bool, summary: str) -> None:
        self.rows.append({"step": step, "method": method, "path": path,
                          "status": status, "pass": passed, "summary": summary})
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
    (SMOKE_DIR / f"savings_phase4_{name}.json").write_text(json.dumps(data, indent=2, default=str))


async def setup_month_and_income(token: str, rep: Report) -> str | None:
    r = http("POST", "/budgets/months/initialize", token,
             json={"month": str(BUDGET_MONTH_DATE)})
    body = _json(r)
    if r.status_code not in (200, 201):
        rep.record("setup.month", "POST", "/budgets/months/initialize",
                   r.status_code, False, str(body))
        return None
    month_id = body.get("id")
    rep.record("setup.month", "POST", "/budgets/months/initialize",
               r.status_code, True, f"month_id={month_id}")

    # Ensure an income category + income posted
    r = http("GET", "/categories/?type=income", token)
    cats = _json(r)
    income_cat_id = cats[0]["id"] if isinstance(cats, list) and cats else None
    if not income_cat_id:
        r2 = http("POST", "/categories/", token,
                  json={"type": "income", "name": "Salary (phase4)"})
        if r2.status_code == 201:
            income_cat_id = r2.json()["id"]
    if not income_cat_id:
        rep.record("setup.income_cat", "-", "income setup", "fail", False,
                   "no income category")
        return None

    r = http("POST", "/incomes/", token, json={
        "category_id": income_cat_id,
        "amount": "40000.00",
        "transaction_date": str(BUDGET_MONTH_DATE),
        "description": "Phase4 verify income",
    })
    rep.record("setup.income", "POST", "/incomes/", r.status_code,
               r.status_code in (200, 201, 409),
               f"income posted (status={r.status_code})")
    return month_id


def step_create_rules(token: str, rep: Report, cat_id: str) -> dict[str, str]:
    """Create 3 rules: A=percent, B=fixed, C=fixed."""
    rules = {}

    r = http("POST", "/savings/rules", token, json={
        "category_id": cat_id, "rule_type": "percent_of_income",
        "label": "Phase4 A (10%)", "percent_value": "10.00",
    })
    body = _json(r)
    if r.status_code == 201:
        rules["A"] = body["id"]
        rep.record("rule.A", "POST", "/savings/rules", 201, True,
                   f"id={body['id']} label={body['label']}")
    else:
        rep.record("rule.A", "POST", "/savings/rules", r.status_code, False, str(body))

    r = http("POST", "/savings/rules", token, json={
        "category_id": cat_id, "rule_type": "fixed_monthly",
        "label": "Phase4 B (1500)", "fixed_amount": "1500.00",
    })
    body = _json(r)
    if r.status_code == 201:
        rules["B"] = body["id"]
        rep.record("rule.B", "POST", "/savings/rules", 201, True,
                   f"id={body['id']} label={body['label']}")
    else:
        rep.record("rule.B", "POST", "/savings/rules", r.status_code, False, str(body))

    r = http("POST", "/savings/rules", token, json={
        "category_id": cat_id, "rule_type": "fixed_monthly",
        "label": "Phase4 C (800)", "fixed_amount": "800.00",
    })
    body = _json(r)
    if r.status_code == 201:
        rules["C"] = body["id"]
        rep.record("rule.C", "POST", "/savings/rules", 201, True,
                   f"id={body['id']} label={body['label']}")
    else:
        rep.record("rule.C", "POST", "/savings/rules", r.status_code, False, str(body))

    return rules


def step_update_label(token: str, rep: Report, rule_a_id: str) -> None:
    """Scenario 10: Update rule label."""
    new_label = "Phase4 A (renamed)"
    r = http("PUT", f"/savings/rules/{rule_a_id}", token, json={"label": new_label})
    body = _json(r)
    dump("update_label", body)
    if r.status_code != 200:
        rep.record("10", "PUT", f"/savings/rules/.../", r.status_code, False, str(body))
        return
    passed = body.get("label") == new_label
    rep.record("10", "PUT", "/savings/rules/.../ (label)", 200, passed,
               f"label={body.get('label')}")


def step_toggle_active(token: str, rep: Report, rule_b_id: str) -> None:
    """Scenario 11: Toggle inactive then back on."""
    # Toggle off
    r = http("PUT", f"/savings/rules/{rule_b_id}", token, json={"is_active": False})
    body = _json(r)
    dump("toggle_off", body)
    if r.status_code != 200 or body.get("is_active") is not False:
        rep.record("11.off", "PUT", "/savings/rules/.../ (is_active=false)",
                   r.status_code, False, f"is_active={body.get('is_active')}")
        return
    rep.record("11.off", "PUT", "/savings/rules/.../ (is_active=false)", 200,
               True, "is_active=False")

    # Toggle back on
    r = http("PUT", f"/savings/rules/{rule_b_id}", token, json={"is_active": True})
    body = _json(r)
    dump("toggle_on", body)
    passed = r.status_code == 200 and body.get("is_active") is True
    rep.record("11.on", "PUT", "/savings/rules/.../ (is_active=true)",
               r.status_code, passed, f"is_active={body.get('is_active')}")


def step_generate_proposals(token: str, rep: Report, budget_month_id: str,
                            rules: dict[str, str]) -> dict[str, dict]:
    """Scenario 12+13: Generate proposals; verify the 3 rules each get one."""
    r = http("POST", "/savings/proposals/generate", token,
             json={"budget_month_id": budget_month_id})
    body = _json(r)
    dump("generate", body)
    proposals = body.get("proposals", []) if isinstance(body, dict) else []
    if r.status_code != 200:
        rep.record("12", "POST", "/savings/proposals/generate", r.status_code,
                   False, str(body))
        return {}

    # Map proposals to rule keys
    by_rule: dict[str, dict] = {}
    for p in proposals:
        for key, rid in rules.items():
            if p.get("savings_rule_id") == rid:
                by_rule[key] = p

    expected_keys = {"A", "B", "C"}
    found_keys = set(by_rule.keys())
    passed = expected_keys.issubset(found_keys)
    rep.record("12", "POST", "/savings/proposals/generate", 200, passed,
               f"proposals={len(proposals)} found_for_rules={sorted(found_keys)}")

    # Scenario 13: amount sanity check
    if "A" in by_rule:
        amt = float(by_rule["A"].get("proposed_amount", 0))
        rep.record("13.A", "-", "(amount A: 10% of 40000)",
                   "ok" if abs(amt - 4000.0) < 0.01 else "fail",
                   abs(amt - 4000.0) < 0.01,
                   f"proposed_amount={amt} (expect 4000.0)")
    if "B" in by_rule:
        amt = float(by_rule["B"].get("proposed_amount", 0))
        rep.record("13.B", "-", "(amount B: 1500 fixed)",
                   "ok" if abs(amt - 1500.0) < 0.01 else "fail",
                   abs(amt - 1500.0) < 0.01,
                   f"proposed_amount={amt}")
    if "C" in by_rule:
        amt = float(by_rule["C"].get("proposed_amount", 0))
        rep.record("13.C", "-", "(amount C: 800 fixed)",
                   "ok" if abs(amt - 800.0) < 0.01 else "fail",
                   abs(amt - 800.0) < 0.01,
                   f"proposed_amount={amt}")

    return by_rule


def step_approve_default(token: str, rep: Report, proposal_a: dict) -> None:
    """Scenario 14: Approve A with default amount (no body)."""
    pid = proposal_a["id"]
    proposed = float(proposal_a.get("proposed_amount", 0))
    r = http("POST", f"/savings/proposals/{pid}/approve", token, json={})
    body = _json(r)
    dump("approve_A_default", body)
    if r.status_code != 200:
        rep.record("14", "POST", "/savings/proposals/.../approve (default)",
                   r.status_code, False, str(body))
        return
    final = float(body.get("final_amount", 0))
    passed = (
        body.get("status") == "posted"
        and abs(final - proposed) < 0.01
    )
    rep.record("14", "POST", "/savings/proposals/.../approve (default)", 200,
               passed, f"status={body.get('status')} final={final} proposed={proposed}")


def step_approve_override(token: str, rep: Report, proposal_b: dict) -> None:
    """Scenario 15: Approve B with override final_amount differing from proposed."""
    pid = proposal_b["id"]
    proposed = float(proposal_b.get("proposed_amount", 0))
    override = proposed + 250.0
    r = http("POST", f"/savings/proposals/{pid}/approve", token,
             json={"final_amount": override})
    body = _json(r)
    dump("approve_B_override", body)
    if r.status_code != 200:
        rep.record("15", "POST", "/savings/proposals/.../approve (override)",
                   r.status_code, False, str(body))
        return
    final = float(body.get("final_amount", 0))
    passed = (
        body.get("status") == "posted"
        and abs(final - override) < 0.01
        and abs(final - proposed) > 0.01
    )
    rep.record("15", "POST", "/savings/proposals/.../approve (override)", 200,
               passed, f"status={body.get('status')} final={final} (proposed was {proposed})")


def step_reject(token: str, rep: Report, proposal_c: dict) -> None:
    """Scenario 16: Reject C."""
    pid = proposal_c["id"]
    r = http("POST", f"/savings/proposals/{pid}/reject", token, json={})
    body = _json(r)
    dump("reject_C", body)
    if r.status_code != 200:
        rep.record("16", "POST", "/savings/proposals/.../reject", r.status_code,
                   False, str(body))
        return
    passed = body.get("status") == "rejected"
    rep.record("16", "POST", "/savings/proposals/.../reject", 200, passed,
               f"status={body.get('status')}")


def step_reapprove_409(token: str, rep: Report, proposal_a: dict) -> None:
    """Scenario 17: Re-approve already-posted proposal A -> expect 409."""
    pid = proposal_a["id"]
    r = http("POST", f"/savings/proposals/{pid}/approve", token, json={})
    body = _json(r)
    dump("reapprove_409", body)
    passed = r.status_code == 409
    rep.record("17", "POST", "/savings/proposals/.../approve (already posted)",
               r.status_code, passed,
               f"expect 409, got {r.status_code}: {body.get('detail') if isinstance(body, dict) else body}")


def step_manual_savings(token: str, rep: Report, cat_id: str) -> dict | None:
    """Scenario 18: Manual savings entry."""
    r = http("POST", "/savings/manual", token, json={
        "category_id": cat_id,
        "amount": "350.00",
        "transaction_date": str(TODAY),
        "description": "Phase4 manual savings",
    })
    body = _json(r)
    dump("manual", body)
    if r.status_code != 201:
        rep.record("18", "POST", "/savings/manual", r.status_code, False, str(body))
        return None
    passed = (
        body.get("type") == "savings"
        and body.get("source") == "manual_savings"
        and abs(float(body.get("amount", 0)) - 350.0) < 0.01
    )
    rep.record("18", "POST", "/savings/manual", 201, passed,
               f"id={body.get('id')} amount={body.get('amount')}")
    return body


def step_dashboard(token: str, rep: Report) -> None:
    """Scenario 19: Dashboard reflects savings totals."""
    r = http("GET", f"/dashboard/summary?year={TODAY.year}&month={TODAY.month}",
             token)
    body = _json(r)
    dump("dashboard", body)
    if r.status_code != 200:
        rep.record("19", "GET", "/dashboard/summary", r.status_code, False, str(body))
        return
    actual = float(body.get("total_actual_savings", 0))
    # Expect: 4000 (A approved default) + 1750 (B override) + 350 (manual) = 6100
    passed = abs(actual - 6100.0) < 0.01
    rep.record("19", "GET", "/dashboard/summary", 200, passed,
               f"total_actual_savings={actual} (expect 6100.0)")


async def cleanup(rep: Report, household_id: UUID, cat_id: str | None) -> None:
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        if cat_id:
            cu = UUID(cat_id)
            await conn.execute(
                "DELETE FROM transactions WHERE category_id=$1 AND household_id=$2",
                cu, household_id)
            await conn.execute(
                """
                DELETE FROM transaction_groups tg
                WHERE tg.household_id=$1
                AND tg.source IN ('savings_proposal','manual_savings')
                AND NOT EXISTS (SELECT 1 FROM transactions t WHERE t.group_id=tg.id)
                """, household_id)
            await conn.execute(
                """
                DELETE FROM savings_proposals
                WHERE savings_rule_id IN (SELECT id FROM savings_rules WHERE category_id=$1)
                """, cu)
            await conn.execute(
                "DELETE FROM savings_rules WHERE category_id=$1", cu)
            await conn.execute(
                "DELETE FROM categories WHERE id=$1 AND household_id=$2",
                cu, household_id)

        await conn.execute(
            """
            DELETE FROM transactions
            WHERE household_id=$1 AND source='manual_income'
            AND description='Phase4 verify income'
            """, household_id)
        await conn.execute(
            """
            DELETE FROM transaction_groups tg
            WHERE tg.household_id=$1 AND tg.source='manual_income'
            AND NOT EXISTS (SELECT 1 FROM transactions t WHERE t.group_id=tg.id)
            """, household_id)
        rep.record("cleanup", "-", "cleanup", "ok", True, "phase4 data removed")
    except Exception as e:
        rep.record("cleanup", "-", "cleanup", "fail", False, str(e))
    finally:
        await conn.close()


async def main() -> int:
    SMOKE_DIR.mkdir(exist_ok=True)
    print("=" * 60)
    print("PHASE 4 GAP VERIFICATION")
    print(f"Budget month: {TODAY.year}-{TODAY.month:02d}")
    print("=" * 60)

    rep = Report()
    print("\n[Setup] Acquiring JWT...")
    user_id, household_id, email = await find_smoke_user()
    token = mint_jwt(email)
    if not token:
        print("STOP: JWT mint failed", file=sys.stderr)
        return 1
    print(f"  JWT acquired (len={len(token)})")

    cat_id: str | None = None
    try:
        budget_month_id = await setup_month_and_income(token, rep)
        if not budget_month_id:
            rep.print_summary()
            return 1

        print("\n[1] Create savings category")
        r = http("POST", "/categories/", token,
                 json={"type": "savings", "name": "Phase4 Fund"})
        body = _json(r)
        if r.status_code != 201:
            rep.record("cat", "POST", "/categories/", r.status_code, False, str(body))
            rep.print_summary()
            return 1
        cat_id = body["id"]
        rep.record("cat", "POST", "/categories/", 201, True, f"cat_id={cat_id}")

        print("\n[2] Create 3 rules (A=percent, B=fixed, C=fixed)")
        rules = step_create_rules(token, rep, cat_id)
        if len(rules) != 3:
            rep.print_summary()
            return 1

        print("\n[10] Update rule A label")
        step_update_label(token, rep, rules["A"])

        print("\n[11] Toggle rule B inactive then re-activate")
        step_toggle_active(token, rep, rules["B"])

        print("\n[12-13] Generate proposals + amount checks")
        by_rule = step_generate_proposals(token, rep, budget_month_id, rules)
        if not all(k in by_rule for k in ("A", "B", "C")):
            rep.print_summary()
            return 1

        print("\n[14] Approve A with default amount")
        step_approve_default(token, rep, by_rule["A"])

        print("\n[15] Approve B with override amount")
        step_approve_override(token, rep, by_rule["B"])

        print("\n[16] Reject C")
        step_reject(token, rep, by_rule["C"])

        print("\n[17] Re-approve A -> 409")
        step_reapprove_409(token, rep, by_rule["A"])

        print("\n[18] Manual savings entry")
        step_manual_savings(token, rep, cat_id)

        print("\n[19] Dashboard reflects savings totals")
        step_dashboard(token, rep)

        rep.print_summary()
        verdict = "GO" if not rep.failed else "NO-GO"
        print(f"\nVERDICT: {verdict}")

    finally:
        print("\n[cleanup]")
        await cleanup(rep, household_id, cat_id)
        print("Cleanup complete.")

    return 0 if not rep.failed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
