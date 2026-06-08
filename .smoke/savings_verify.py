"""Live verification of the full savings system.

Covers:
  1.  Create a savings category
  2.  Create a percent_of_income savings rule
  3.  Create multiple fixed_monthly savings rules
  4.  Add a new fixed_monthly rule later
  5.  Generate proposals for a budget month
  6.  Verify proposal generation is idempotent
  7.  Approve/post a proposal
  8.  Reject a proposal
  9.  Create a manual savings entry
  10. DB probe: transaction_group, transaction, savings_proposals.transaction_id
  11. Verify dashboard reflects posted savings
  12. Cleanup
  13. Second consecutive run result (handled by re-running the script)

Uses the existing smoke user (must have a household + at least one income
category and a budget month with income).

Exits 0 on GO (all steps pass), 1 on NO-GO.
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

# ---------- config ----------

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / ".smoke"))
from smoke_test import load_env, find_smoke_user, mint_jwt  # type: ignore

ENV = load_env(REPO_ROOT / ".env")
DATABASE_URL = ENV["DATABASE_URL"]
SMOKE_DIR = REPO_ROOT / ".smoke"
API_BASE = "http://127.0.0.1:8765/api/v1"

# Budget month to use for verification (current month)
TODAY = date.today()
VERIFY_YEAR = TODAY.year
VERIFY_MONTH = TODAY.month
BUDGET_MONTH_DATE = date(VERIFY_YEAR, VERIFY_MONTH, 1)


# ---------- report ----------

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


# ---------- HTTP helpers ----------

def http(method: str, path: str, token: str, **kwargs) -> httpx.Response:
    headers = kwargs.pop("headers", {}) or {}
    headers["Authorization"] = f"Bearer {token}"
    with httpx.Client(timeout=30.0) as c:
        return c.request(method, f"{API_BASE}{path}", headers=headers, **kwargs)


def _safe_json(resp: httpx.Response) -> Any:
    try:
        return resp.json()
    except Exception:
        return {"_raw_text": resp.text[:2000], "_status": resp.status_code}


def dump_json(name: str, data: Any) -> None:
    path = SMOKE_DIR / f"savings_{name}.json"
    path.write_text(json.dumps(data, indent=2, default=str))


# ---------- setup: ensure income exists for proposal generation ----------

async def ensure_income_for_month(
    token: str, household_id: UUID, rep: Report,
) -> UUID | None:
    """Ensure a budget month exists with at least some actual income.

    Returns the budget_month_id if successful.
    """
    # Initialize the budget month (idempotent)
    r = http("POST", "/budgets/months/initialize", token,
             json={"month": str(BUDGET_MONTH_DATE)})
    body = _safe_json(r)
    if r.status_code not in (200, 201):
        rep.record("0a", "POST", "/budgets/months/initialize", r.status_code,
                   False, f"failed: {body}")
        return None
    month_id = body.get("id")
    rep.record("0a", "POST", "/budgets/months/initialize", r.status_code,
               True, f"month_id={month_id}")

    # Check if income category exists; create one if needed
    r = http("GET", "/categories/?type=income", token)
    cats = _safe_json(r)
    income_cat_id = None
    if isinstance(cats, list) and len(cats) > 0:
        income_cat_id = cats[0]["id"]
    else:
        r2 = http("POST", "/categories/", token,
                  json={"type": "income", "name": "Salary (smoke)"})
        if r2.status_code == 201:
            income_cat_id = r2.json()["id"]

    if not income_cat_id:
        rep.record("0b", "-", "income setup", "fail", False, "no income category")
        return None

    # Post a small income entry so proposals have a basis
    r = http("POST", "/incomes/", token, json={
        "category_id": income_cat_id,
        "amount": "50000.00",
        "transaction_date": str(BUDGET_MONTH_DATE),
        "description": "Savings verify income",
    })
    if r.status_code == 201:
        rep.record("0b", "POST", "/incomes/", 201, True,
                   f"income posted, cat={income_cat_id}")
    else:
        # May already exist or fail — not fatal for proposal generation
        rep.record("0b", "POST", "/incomes/", r.status_code, True,
                   f"income post returned {r.status_code} (may already exist)")

    return UUID(month_id) if month_id else None


# ---------- step 1: create savings category ----------

def step_1_create_savings_category(token: str, rep: Report) -> str | None:
    r = http("POST", "/categories/", token,
             json={"type": "savings", "name": "Emergency Fund (smoke)"})
    body = _safe_json(r)
    dump_json("01_category", body)
    if r.status_code != 201:
        rep.record("1", "POST", "/categories/", r.status_code, False, str(body))
        return None
    cat_id = body["id"]
    passed = body.get("type") == "savings" and body.get("name") == "Emergency Fund (smoke)"
    rep.record("1", "POST", "/categories/", 201, passed,
               f"cat_id={cat_id} type={body.get('type')}")
    return cat_id


# ---------- step 2: create percent_of_income rule ----------

def step_2_create_percent_rule(
    token: str, rep: Report, cat_id: str,
) -> str | None:
    r = http("POST", "/savings/rules", token, json={
        "category_id": cat_id,
        "rule_type": "percent_of_income",
        "label": "10% emergency fund",
        "percent_value": "10.00",
    })
    body = _safe_json(r)
    dump_json("02_percent_rule", body)
    if r.status_code != 201:
        rep.record("2", "POST", "/savings/rules", r.status_code, False, str(body))
        return None
    rule_id = body.get("id")
    passed = (
        body.get("rule_type") == "percent_of_income"
        and body.get("category_name") == "Emergency Fund (smoke)"
        and body.get("is_active") is True
    )
    rep.record("2", "POST", "/savings/rules", 201, passed,
               f"rule_id={rule_id} type={body.get('rule_type')}")
    return rule_id


# ---------- step 3: create multiple fixed_monthly rules ----------

def step_3_create_fixed_rules(
    token: str, rep: Report, cat_id: str,
) -> list[str]:
    rule_ids = []
    for i, (label, amount) in enumerate([
        ("Vacation fund", "2000.00"),
        ("Car repair fund", "1500.00"),
    ], start=1):
        r = http("POST", "/savings/rules", token, json={
            "category_id": cat_id,
            "rule_type": "fixed_monthly",
            "label": label,
            "fixed_amount": amount,
        })
        body = _safe_json(r)
        dump_json(f"03_fixed_rule_{i}", body)
        if r.status_code != 201:
            rep.record(f"3.{i}", "POST", "/savings/rules", r.status_code,
                       False, str(body))
            continue
        rule_ids.append(body["id"])
        passed = (
            body.get("rule_type") == "fixed_monthly"
            and body.get("is_active") is True
        )
        rep.record(f"3.{i}", "POST", "/savings/rules", 201, passed,
                   f"rule_id={body['id']} label={label}")

    # Verify list returns all rules
    r = http("GET", "/savings/rules", token)
    body = _safe_json(r)
    rules = body.get("rules", []) if isinstance(body, dict) else []
    # Count only our smoke rules (there might be others)
    smoke_rules = [
        rl for rl in rules
        if rl.get("category_name") == "Emergency Fund (smoke)"
    ]
    passed = len(smoke_rules) >= 3  # 1 percent + 2 fixed
    rep.record("3.list", "GET", "/savings/rules", r.status_code, passed,
               f"total_rules={len(rules)} smoke_rules={len(smoke_rules)}")
    return rule_ids


# ---------- step 4: add another fixed rule later ----------

def step_4_add_another_rule(
    token: str, rep: Report, cat_id: str,
) -> str | None:
    r = http("POST", "/savings/rules", token, json={
        "category_id": cat_id,
        "rule_type": "fixed_monthly",
        "label": "New appliance fund",
        "fixed_amount": "500.00",
    })
    body = _safe_json(r)
    dump_json("04_extra_rule", body)
    if r.status_code != 201:
        rep.record("4", "POST", "/savings/rules", r.status_code, False, str(body))
        return None
    rule_id = body["id"]
    rep.record("4", "POST", "/savings/rules", 201, True,
               f"rule_id={rule_id} label={body.get('label')}")
    return rule_id


# ---------- step 5: generate proposals ----------

def step_5_generate_proposals(
    token: str, rep: Report, budget_month_id: str,
) -> list[dict]:
    r = http("POST", "/savings/proposals/generate", token, json={
        "budget_month_id": budget_month_id,
    })
    body = _safe_json(r)
    dump_json("05_proposals", body)
    proposals = body.get("proposals", []) if isinstance(body, dict) else []
    if r.status_code != 200:
        rep.record("5", "POST", "/savings/proposals/generate", r.status_code,
                   False, str(body))
        return []
    # Should have 4 proposals (1 percent + 3 fixed)
    passed = len(proposals) >= 4
    rep.record("5", "POST", "/savings/proposals/generate", 200, passed,
               f"proposals={len(proposals)}")

    # Verify one is percent-based with calculated amount
    def _parse_basis(p: dict) -> dict:
        cb = p.get("calculation_basis")
        if isinstance(cb, str):
            try:
                return json.loads(cb)
            except Exception:
                return {}
        return cb if isinstance(cb, dict) else {}

    percent_proposals = [
        p for p in proposals
        if _parse_basis(p).get("rule_type") == "percent_of_income"
    ]
    if percent_proposals:
        pp = percent_proposals[0]
        expected = 5000.0  # 10% of 50000
        actual = float(pp["proposed_amount"])
        amount_ok = abs(actual - expected) < 0.01
        rep.record("5.pct", "-", "(percent check)", "ok" if amount_ok else "fail",
                   amount_ok, f"expected ~{expected}, got {actual}")
    else:
        rep.record("5.pct", "-", "(percent check)", "fail", False,
                   "no percent_of_income proposal found")

    return proposals


# ---------- step 6: idempotent proposal generation ----------

def step_6_idempotent_generation(
    token: str, rep: Report, budget_month_id: str, first_proposals: list[dict],
) -> None:
    r = http("POST", "/savings/proposals/generate", token, json={
        "budget_month_id": budget_month_id,
    })
    body = _safe_json(r)
    dump_json("06_idempotent", body)
    proposals = body.get("proposals", []) if isinstance(body, dict) else []
    # Same count as first generation
    same_count = len(proposals) == len(first_proposals)
    # Same IDs
    first_ids = sorted(p["id"] for p in first_proposals)
    second_ids = sorted(p["id"] for p in proposals)
    same_ids = first_ids == second_ids
    passed = r.status_code == 200 and same_count and same_ids
    rep.record("6", "POST", "/savings/proposals/generate (idem)", r.status_code,
               passed, f"count={len(proposals)} same_ids={same_ids}")


# ---------- step 7: approve a proposal ----------

def step_7_approve_proposal(
    token: str, rep: Report, proposals: list[dict],
) -> dict | None:
    # Pick the percent-based proposal to approve
    def _parse_basis(p: dict) -> dict:
        cb = p.get("calculation_basis")
        if isinstance(cb, str):
            try:
                return json.loads(cb)
            except Exception:
                return {}
        return cb if isinstance(cb, dict) else {}

    target = None
    for p in proposals:
        if p.get("status") == "pending":
            basis = _parse_basis(p)
            if basis.get("rule_type") == "percent_of_income":
                target = p
                break
    if not target:
        # Fall back to any pending
        for p in proposals:
            if p.get("status") == "pending":
                target = p
                break
    if not target:
        rep.record("7", "-", "(no pending)", "fail", False, "no pending proposal")
        return None

    r = http("POST", f"/savings/proposals/{target['id']}/approve", token,
             json={})
    body = _safe_json(r)
    dump_json("07_approve", body)
    if r.status_code != 200:
        rep.record("7", "POST", f"/savings/proposals/.../approve", r.status_code,
                   False, str(body))
        return None

    passed = body.get("status") == "posted" and body.get("final_amount") is not None
    rep.record("7", "POST", "/savings/proposals/.../approve", 200, passed,
               f"status={body.get('status')} amount={body.get('final_amount')}")
    return body


# ---------- step 8: reject a proposal ----------

def step_8_reject_proposal(
    token: str, rep: Report, proposals: list[dict], approved_id: str | None,
) -> dict | None:
    # Pick a different pending proposal
    target = None
    for p in proposals:
        if p.get("status") == "pending" and p["id"] != approved_id:
            target = p
            break
    if not target:
        rep.record("8", "-", "(no pending)", "fail", False,
                   "no second pending proposal to reject")
        return None

    r = http("POST", f"/savings/proposals/{target['id']}/reject", token, json={})
    body = _safe_json(r)
    dump_json("08_reject", body)
    if r.status_code != 200:
        rep.record("8", "POST", "/savings/proposals/.../reject", r.status_code,
                   False, str(body))
        return None
    passed = body.get("status") == "rejected"
    rep.record("8", "POST", "/savings/proposals/.../reject", 200, passed,
               f"status={body.get('status')}")
    return body


# ---------- step 9: manual savings entry ----------

def step_9_manual_savings(
    token: str, rep: Report, cat_id: str,
) -> dict | None:
    r = http("POST", "/savings/manual", token, json={
        "category_id": cat_id,
        "amount": "750.00",
        "transaction_date": str(TODAY),
        "description": "Manual savings smoke test",
    })
    body = _safe_json(r)
    dump_json("09_manual", body)
    if r.status_code != 201:
        rep.record("9", "POST", "/savings/manual", r.status_code, False, str(body))
        return None

    passed = (
        body.get("category_name") == "Emergency Fund (smoke)"
        and body.get("budget_month") is not None
        and float(body.get("amount", 0)) == 750.0
        and body.get("type") == "savings"
        and body.get("source") == "manual_savings"
    )
    rep.record("9", "POST", "/savings/manual", 201, passed,
               f"txn_id={body.get('id')} amount={body.get('amount')} "
               f"type={body.get('type')} source={body.get('source')}")
    return body


# ---------- step 10: DB probe ----------

async def step_10_db_probe(
    rep: Report,
    approved_result: dict | None,
    manual_result: dict | None,
    household_id: UUID,
) -> None:
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        # 10a: Check transaction_group for approved proposal
        if approved_result:
            proposal_id = approved_result.get("id")
            if proposal_id:
                row = await conn.fetchrow(
                    """
                    SELECT sp.transaction_id, sp.status, sp.final_amount,
                           tg.source AS group_source, tg.idempotency_key,
                           t.type AS txn_type, t.source AS txn_source, t.amount
                    FROM savings_proposals sp
                    LEFT JOIN transactions t ON t.id = sp.transaction_id
                    LEFT JOIN transaction_groups tg ON tg.id = t.group_id
                    WHERE sp.id = $1
                    """,
                    UUID(proposal_id),
                )
                if row:
                    checks = (
                        row["transaction_id"] is not None
                        and row["status"] == "posted"
                        and row["group_source"] == "savings_proposal"
                        and row["txn_type"] == "savings"
                        and row["txn_source"] == "savings_proposal"
                        and row["idempotency_key"] == f"savings_proposal:{proposal_id}"
                    )
                    rep.record("10a", "-", "db_probe (approved proposal)", "ok" if checks else "fail",
                               checks,
                               f"txn_id={row['transaction_id']} group_source={row['group_source']} "
                               f"idem_key={row['idempotency_key']}")
                else:
                    rep.record("10a", "-", "db_probe (approved proposal)", "fail", False,
                               "proposal row not found")
        else:
            rep.record("10a", "-", "db_probe (approved proposal)", "skip", True,
                       "no approved proposal to probe")

        # 10b: Check transaction_group for manual savings
        if manual_result:
            txn_id = manual_result.get("id")
            if txn_id:
                row = await conn.fetchrow(
                    """
                    SELECT t.type, t.source, t.amount,
                           tg.source AS group_source, tg.idempotency_key
                    FROM transactions t
                    JOIN transaction_groups tg ON tg.id = t.group_id
                    WHERE t.id = $1
                    """,
                    UUID(txn_id),
                )
                if row:
                    checks = (
                        row["type"] == "savings"
                        and row["source"] == "manual_savings"
                        and row["group_source"] == "manual_savings"
                        and str(row["idempotency_key"]).startswith("manual_savings:")
                    )
                    rep.record("10b", "-", "db_probe (manual savings)", "ok" if checks else "fail",
                               checks,
                               f"type={row['type']} source={row['source']} "
                               f"group_source={row['group_source']}")
                else:
                    rep.record("10b", "-", "db_probe (manual savings)", "fail", False,
                               "transaction row not found")
        else:
            rep.record("10b", "-", "db_probe (manual savings)", "skip", True,
                       "no manual savings to probe")

    finally:
        await conn.close()


# ---------- step 11: dashboard reflects savings ----------

def step_11_dashboard(token: str, rep: Report) -> None:
    r = http("GET", f"/dashboard/summary?year={VERIFY_YEAR}&month={VERIFY_MONTH}",
             token)
    body = _safe_json(r)
    dump_json("11_dashboard", body)
    if r.status_code != 200:
        rep.record("11", "GET", "/dashboard/summary", r.status_code, False,
                   str(body))
        return

    actual_savings = float(body.get("total_actual_savings", 0))
    planned_savings = float(body.get("total_planned_savings", 0))
    savings_rate = body.get("savings_rate")
    # We posted at least 750 (manual) + ~5000 (proposal) = ~5750
    has_savings = actual_savings > 0
    rep.record("11", "GET", "/dashboard/summary", 200, has_savings,
               f"total_actual_savings={actual_savings} total_planned_savings={planned_savings} "
               f"savings_rate={savings_rate}")


# ---------- step 12: cleanup ----------

async def step_12_cleanup(
    rep: Report,
    household_id: UUID,
    cat_id: str | None,
    income_txn_ids: list[str] | None,
) -> None:
    """Clean up smoke test artifacts from the database."""
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        if cat_id:
            cat_uuid = UUID(cat_id)

            # Delete transactions linked to our savings category
            await conn.execute(
                """
                DELETE FROM transactions
                WHERE category_id = $1 AND household_id = $2
                """,
                cat_uuid, household_id,
            )

            # Delete transaction_groups that are now childless
            await conn.execute(
                """
                DELETE FROM transaction_groups tg
                WHERE tg.household_id = $1
                AND tg.source IN ('savings_proposal', 'manual_savings')
                AND NOT EXISTS (
                    SELECT 1 FROM transactions t WHERE t.group_id = tg.id
                )
                """,
                household_id,
            )

            # Delete savings proposals for our category's rules
            await conn.execute(
                """
                DELETE FROM savings_proposals
                WHERE savings_rule_id IN (
                    SELECT id FROM savings_rules WHERE category_id = $1
                )
                """,
                cat_uuid,
            )

            # Delete savings rules for our category
            await conn.execute(
                "DELETE FROM savings_rules WHERE category_id = $1", cat_uuid,
            )

            # Delete the category itself
            await conn.execute(
                "DELETE FROM categories WHERE id = $1 AND household_id = $2",
                cat_uuid, household_id,
            )

        # Delete smoke income entry
        await conn.execute(
            """
            DELETE FROM transactions
            WHERE household_id = $1
            AND source = 'manual_income'
            AND description = 'Savings verify income'
            """,
            household_id,
        )
        # Clean up childless income groups
        await conn.execute(
            """
            DELETE FROM transaction_groups tg
            WHERE tg.household_id = $1
            AND tg.source = 'manual_income'
            AND NOT EXISTS (
                SELECT 1 FROM transactions t WHERE t.group_id = tg.id
            )
            """,
            household_id,
        )

        rep.record("12", "-", "cleanup", "ok", True, "smoke data removed")
    except Exception as e:
        rep.record("12", "-", "cleanup", "fail", False, str(e))
    finally:
        await conn.close()


# ---------- main ----------

async def main() -> int:
    SMOKE_DIR.mkdir(exist_ok=True)
    print("=" * 60)
    print("LIVE VERIFICATION: Savings System (full flow)")
    print(f"Budget month: {VERIFY_YEAR}-{VERIFY_MONTH:02d}")
    print("=" * 60)

    rep = Report()

    # Acquire JWT
    print("\n[Setup] Acquiring JWT...")
    user_id, household_id, email = await find_smoke_user()
    token = mint_jwt(email)
    if not token or len(token) < 20:
        print("STOP: JWT acquisition failed", file=sys.stderr)
        return 1
    print(f"  JWT acquired (len={len(token)})")

    cat_id: str | None = None

    try:
        # Setup: ensure budget month + income
        print("\n[Setup] Ensuring budget month with income...")
        budget_month_id = await ensure_income_for_month(token, household_id, rep)
        if not budget_month_id:
            rep.print_summary()
            return 1
        bm_id_str = str(budget_month_id)

        # Step 1: Create savings category
        print("\n[1] Create savings category")
        cat_id = step_1_create_savings_category(token, rep)
        if not cat_id:
            rep.print_summary()
            return 1

        # Step 2: Create percent_of_income rule
        print("\n[2] Create percent_of_income rule")
        percent_rule_id = step_2_create_percent_rule(token, rep, cat_id)

        # Step 3: Create multiple fixed_monthly rules
        print("\n[3] Create fixed_monthly rules")
        fixed_rule_ids = step_3_create_fixed_rules(token, rep, cat_id)

        # Step 4: Add another fixed rule later
        print("\n[4] Add another fixed rule")
        extra_rule_id = step_4_add_another_rule(token, rep, cat_id)

        # Step 5: Generate proposals
        print("\n[5] Generate proposals")
        proposals = step_5_generate_proposals(token, rep, bm_id_str)

        # Step 6: Idempotent proposal generation
        print("\n[6] Verify idempotent generation")
        step_6_idempotent_generation(token, rep, bm_id_str, proposals)

        # Step 7: Approve a proposal
        print("\n[7] Approve proposal")
        approved = step_7_approve_proposal(token, rep, proposals)
        approved_id = approved["id"] if approved else None

        # Step 8: Reject a proposal
        print("\n[8] Reject proposal")
        rejected = step_8_reject_proposal(token, rep, proposals, approved_id)

        # Step 9: Manual savings entry
        print("\n[9] Manual savings entry")
        manual = step_9_manual_savings(token, rep, cat_id)

        # Step 10: DB probe
        print("\n[10] DB probe")
        await step_10_db_probe(rep, approved, manual, household_id)

        # Step 11: Dashboard
        print("\n[11] Dashboard savings check")
        step_11_dashboard(token, rep)

        # Print summary before cleanup
        rep.print_summary()
        verdict = "GO" if not rep.failed else "NO-GO"
        print(f"\nVERDICT: {verdict}")

    finally:
        # Step 12: Cleanup
        print("\n[12] Cleanup")
        await step_12_cleanup(rep, household_id, cat_id, None)
        print("Cleanup complete.")

    return 0 if not rep.failed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
