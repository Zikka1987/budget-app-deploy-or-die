# Skill: Savings Proposal Generation

## Purpose
Generate savings proposals for a month based on active savings rules.

## Input
- Household ID
- Budget month
- Active savings rules for the household
- Total actual income for the month (from transactions)

## Process
1. For each active savings rule:
   - percent_of_income: calculate `total_income * percent / 100`
   - fixed_monthly: use the fixed_amount directly
2. Create savings_proposal records (status = pending)
3. Skip if proposal already exists for this rule + month (UNIQUE constraint)

## Rules
- Pure deterministic calculation — no AI
- Proposals are NOT transactions; they require user approval first
- Use `savings_rules.build_proposals()` pure function for calculation
- Store calculation_basis JSON for auditability
- Idempotent via UNIQUE(savings_rule_id, budget_month_id)
- User can adjust final_amount before approving
