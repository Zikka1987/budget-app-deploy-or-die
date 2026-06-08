# Skill: Month Rollover (Budget Month Initialization)

## Purpose
Initialize a new budget month by copying the previous month's structure and planned amounts.

## Input
- Household ID
- Target month (date, 1st of month)

## Process
1. Check if target month already exists (idempotent — return existing if found)
2. Find the most recent previous budget month
3. Copy all budget_lines from previous month with their planned_amounts
4. Create budget_month record
5. Create budget_line records for each copied line

## Rules
- Idempotent: running twice for the same month must not create duplicates
- If no previous month exists, create an empty month (no budget lines)
- Only copy active categories (archived_at IS NULL)
- Do not copy notes from previous month's lines
- This is pure deterministic logic — no AI involved
- Use a DB transaction to create month + all lines atomically
