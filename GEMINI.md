# Budget App - Project Rules

## Purpose
This app is a shared household budgeting system that replaces a manual Excel workflow. It is a budget-first product, not a generic finance tracker.

Core model:
- Income
- Expenses
- Savings

## Product Invariants
- One shared household per app instance.
- One user can belong to only one household.
- v1 supports exactly 2 household members max.
- Currency is DKK only.
- Receipt language is primarily Danish.
- Income entry is manual.
- Savings are first-class entities.
- Categories are custom household categories, not global defaults.

## Architecture Invariants
### Python owns deterministic logic
Python/FastAPI owns:
- budget calculations
- dashboard summaries
- budget vs actual
- month rollover
- onboarding readiness
- category CRUD and rename behavior
- transaction posting
- duplicate detection
- savings calculations and posting
- effective date logic
- late-income shift
- AI output validation
- `requires_review` determination
- search/filter behavior
- all financial writes

### AI owns non-deterministic interpretation only
AI may only:
- read receipt images
- extract line items
- suggest categories
- return confidence scores

AI must never:
- be the source of truth for calculations
- write transactions directly
- decide `requires_review`
- override deterministic rules
- confirm or post receipts

All AI output must be validated by deterministic Python before use.

## Stack
- Database: Supabase-hosted Postgres
- DB access: `asyncpg` directly, no ORM
- Auth: Supabase JWT verification via JWKS
- Storage: Supabase Storage for private receipt files
- Backend: FastAPI with thin routers, heavy services, pure rules
- AI: Anthropic behind interfaces in `ai/base.py`

## Auth Rules
- Verify JWTs via the project's JWKS endpoint.
- Do not reintroduce `SUPABASE_JWT_SECRET` or HS256 shared-secret auth.
- Only two auth dependencies exist:
  - `get_auth_context`
  - `get_user_context`

Use `get_user_context` only for the narrow pre-household corridor. Do not add a third auth dependency without narrow, explicit justification.

## Database and Transaction Rules
- All DB reads/writes go through the `asyncpg` pool.
- Supabase client is for Storage only.
- Multi-step financial writes must run inside DB transactions.
- Repositories must accept a connection or transaction object.
- `transaction_groups.idempotency_key` must prevent double posting.

## Category Rules
- Categories are identified by stable UUIDs, never by name.
- Renaming a category must preserve all history.
- Old names are stored in `category_aliases`.
- Categories with financial history must never be hard-deleted.
- Archive via `archived_at`.

## Onboarding Rules
- Production households start with zero categories.
- `POST /api/v1/households` creates household + settings + owner membership only.
- Do not create starter categories.
- Users create categories manually.
- Seed/demo categories are dev/test only.
- Do not add founder bootstrap shortcuts.
- Do not auto-populate production households with defaults.

## Budget Month Rules
- Budget months are normal calendar months.
- `budget_months.month` is always the first day of the month.
- New month initialization copies prior-month active budget lines and planned amounts.
- Copy applies to income, expense, and savings categories.
- Archived categories are skipped.
- Actual transactions are never copied forward.
- Month creation must be idempotent.
- Late-income shift affects income only.

## Dashboard Rules
- `to_be_allocated = planned_income - planned_expenses - planned_savings`
- `actual_balance = actual_income - actual_expenses - actual_savings`
- `plan_coverage = actual_income - planned_expenses - planned_savings`
- `savings_rate = actual_savings / actual_income * 100`, else `null` if income is zero
- Include categories with budget lines, actuals, or both.
- Unbudgeted actual categories must still appear with `planned = 0`.
- If no budget month exists, return a deterministic empty dashboard response, not 404.
- Money values must serialize with exactly 2 decimal places.

## Receipt Workflow Rules
- Receipt-derived transactions must never auto-post.
- Every receipt requires explicit review before posting.
- `requires_review` is a per-item UI hint, not a posting bypass.
- Receipt items track `suggested_category_id` and `user_confirmed_category_id`.
- Transactions must always be created from `user_confirmed_category_id`, never from AI output.
- Categorization must fail with 422 if the household has zero active expense categories.
- This guard must run before the AI call.
- Re-categorization is a full refresh.
- Re-parse is full replace with preservation on failure from `ocr_complete`.
- Receipt confirm/post must run atomically.

## Invite Rules
- v1 households are capped at 2 members total.
- Do not partially relax this cap.
- Invite flow adds the second member to an existing household only.
- It must never introduce multi-household membership.

## Non-Goals
- no multi-household support
- no household switching
- no production seeding of categories
- no founder-only bootstrap path
- no bank account sync in v1
- no generic finance-app feature creep

## Source of Truth
- `CLAUDE.md` = rules and invariants
- `report.md` = implementation status and handoff details
- `docs/PRODUCT.md` = product vision, user flows, and intended behavior 

If a task depends on intended product behavior rather than current implementation status, consult `docs/PRODUCT.md`.

If they conflict:
- follow `CLAUDE.md` for behavior
- treat `report.md` as implementation reference
- flag the mismatch explicitly