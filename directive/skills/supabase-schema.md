# Skill: Supabase Schema Work

## Purpose
Guide schema changes for the Supabase-hosted Postgres database.

## Architecture
- Supabase hosts Postgres; backend connects via asyncpg directly
- Supabase client used only for Auth and Storage
- All schema lives in `supabase/migrations/` as numbered SQL files

## Migration conventions
- File naming: `NNNNN_description.sql` (e.g., `00002_add_merchant_memory.sql`)
- Each migration is a single SQL file, applied in order
- Migrations must be idempotent where possible (use IF NOT EXISTS)
- Never drop columns in production without a deprecation migration

## Schema rules
- UUID primary keys everywhere (gen_random_uuid())
- Foreign keys with appropriate ON DELETE behavior
- RLS enabled on all tables, policies use get_household_id()
- Business logic stays in Python, NOT in triggers or functions
- Only infrastructure triggers allowed (e.g., updated_at)
- Enums for fixed value sets; CHECK constraints for simple validation
- Indexes justified by specific query patterns

## RLS pattern
All tables scoped to household. Use helper function:
```sql
CREATE POLICY "policy_name" ON table_name
    FOR operation USING (household_id = get_household_id());
```
For child tables (budget_lines, receipt_items), join to parent to check household.
