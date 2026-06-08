# Budget App - Technical Report

_Last updated: 2026-06-08 (remote server provisioned and SSH-hardened on Hetzner Cloud; application not yet deployed)_

Update this file whenever implemented scope, verification status, or major architecture facts change

## 1. What this document is

This file is the implementation handoff and current-state reference for the budget app.

Use it to understand:
- what is currently implemented
- how the backend is structured
- which flows are verified
- which features are still missing
- what should be built next

This is **not** the primary rules file. `CLAUDE.md` holds project rules and invariants. If this file and `CLAUDE.md` ever conflict, follow `CLAUDE.md` and treat this file as a status document that needs updating.

If a task depends on intended product behavior rather than current implementation status, consult `docs/PRODUCT.md`.

---

## 2. Current product snapshot

The app is a shared household budgeting application built to replace a manual Excel-based monthly budgeting workflow.

It is a **budget-first system**, not a generic finance tracker.

Core model:
- **Income** — manually entered
- **Expenses** — currently entered through receipt upload, review, and posting
- **Savings** — rule CRUD, proposal generation/approval/rejection, and manual savings entry all implemented

Target product model:
- one shared household
- two users max in v1
- DKK only
- Danish receipt handling

### Current user model
The shared-household model is now implemented for v1:
- first user signs in and creates the household
- second user joins through the invite flow
- one user can belong to only one household
- multi-household support does not exist

---

## 3. Current implementation status

### Implemented
- Supabase-backed Postgres schema with RLS
- JWKS-based Supabase JWT verification
- two auth contexts:
  - `AuthContext(user_id, household_id, email)`
  - `UserContext(user_id, email)`
- category CRUD with stable UUID identity and rename aliasing
- budget month initialization from previous month
- budget line upsert/update
- manual income CRUD
- dashboard summary calculations
- receipt upload
- receipt OCR / parse
- receipt categorization
- receipt review payload
- receipt item review editing
- receipt confirm/post
- idempotent receipt posting
- household creation
- household read
- household settings read/update
- onboarding status endpoint
- second-user invite / join flow
- deterministic rule modules for budget/date/receipt/savings
- AI abstractions + Anthropic implementations
- savings rule CRUD, proposal generation/approval/rejection, manual savings entry
- receipt search (merchant, category, date range, amount range, status)
- transaction search (category, type, source, date range, amount range)

### Mobile app — Phase 1+2+3+4+5+6 implemented
- Expo SDK 54, expo-router v6, TypeScript strict mode
- Supabase JS client with AsyncStorage session persistence
- TanStack Query for server state
- plain `fetch` wrapper with automatic Bearer token injection

Phase 1 screens:
- sign in / sign up (Supabase Auth)
- create household
- category setup (income, expense, savings with progress checkmarks)
- initialize budget month
- dashboard with month navigation, summary cards, metrics, category breakdowns

Phase 2 screens:
- budget month detail with editable budget lines (planned amounts per category, grouped by type)
- budget months list (month selection with initialize-month support)
- income list for selected month
- income add/edit/delete form (with category picker, amount, date, description)

Phase 3 screens:
- receipt list with status badges (uploaded, processing, ocr_complete, posted, failed)
- receipt upload (camera/gallery via expo-image-picker, optional store name and date)
- receipt detail/review (status-driven UI: parse → categorize → review items → confirm/post)

Phase 4 screens:
- savings hub with segmented control (Rules / Proposals)
- savings rule create/edit form (percent_of_income or fixed_monthly, immutable category + rule_type after creation)
- savings rule active toggle (Switch on each row)
- proposal generation per budget month
- proposal cards with status badges (pending / posted / rejected)
- approve modal with optional final_amount override
- reject confirmation flow
- manual savings entry (always accessible, not gated by budget month — backend derives month from transaction_date)

Phase 5 screens:
- single Search tab with segmented control toggling between Receipts / Transactions modes
- receipts mode: merchant text search (debounced 250 ms), status chip row (all 6 statuses), single-select expense category chip, date range (YYYY-MM-DD), amount min/max
- transactions mode: type chip row (income / expense / savings), source chip row (5 source values), single-select category chip filtered by active type, date range (effective_date), amount min/max
- result rows: receipt rows pressable → existing `/(main)/receipts/[id]` detail screen; transaction rows read-only with type badge
- "Showing N of M" count line, "Load more" button when more pages remain (`useInfiniteQuery`, page size 50), "Clear filters" resets active mode without affecting the other mode
- each mode owns its own filter state; switching modes preserves both
- write hooks across receipts/savings/incomes invalidate `['search']` so result lists stay fresh after mutations

Phase 6 screens:
- single Settings tab (7th tab) — one screen with stacked cards
- household card (name + created date) sourced from `GET /households/me`
- preferences card — late-income shift toggle + numeric cutoff-day input (1–28), disabled when shift is off, Save button enabled only when form differs from server state, client-side range check + 422 surfaced via `Alert.alert`
- members section — "you (this device) + email of accepted invitee", count rendered as "N/2"
- invites section — inline send-invite form (email input + Send button, hidden once 2/2 members), pending invite list with destructive `Alert.alert`-confirmed Revoke
- token banner — `selectable` Text with "Long-press to copy" hint (no `expo-clipboard` dependency added; OS long-press copy works on iOS + Android)
- sign-out button at bottom calling `useAuth().signOut`
- onboarding `accept-invite` screen — token + display-name inputs, debounced lookup preview ("You'll join {household_name}"), inline error for 403/404/410, post-accept invalidates `['onboarding','status']` + `['household','me']` and `router.replace('/')` so the root gate decides where to land
- "Have an invite? Join an existing household →" link added to `create-household` (and the inverse link on accept-invite)
- root gate updated to allowlist `/(onboarding)/accept-invite` as a valid pre-household route — without this, the gate would yank user B back to `create-household` before they could paste a token

Member-list workaround: backend has no member-list endpoint, so the Members section uses `GET /invites?status=accepted` to read the second member's email. The current user's identity comes from `useAuth().user.email`. This is documented as a known gap rather than worked around with a new backend route.

Phase 2+3+4+5+6 infrastructure:
- shared `MonthContext` for synchronized month state across dashboard, budget, income, and savings tabs
- reusable `MonthSelector` component (extracted from dashboard)
- seven-tab layout: Home (dashboard), Budget, Income, Savings, Receipts, Search, Settings
- stack navigation within Budget, Income, Savings, Receipts, and Settings tabs
- multipart/form-data upload support in API client
- receipt API hooks with processing-status polling (refetchInterval)

The root onboarding gate computes app-level readiness from the three individual category booleans (`has_income_category`, `has_expense_category`, `has_savings_category`). It does **not** use the backend `is_ready` field, which only requires income + expense. The app requires all three types before routing to the main dashboard.

The dashboard intentionally handles the empty/zero state: when no budget month exists or no budget lines are set, all totals render as zero, `savings_rate` renders as null, and category sections show an empty-state message.

Budget detail merges all active categories with existing budget lines, showing un-budgeted categories with planned=0 so users can set planned amounts via upsert. Closed months are displayed as read-only.

Income form handles late-income shift: if the backend assigns an income to a different budget month than the currently selected one (due to `shift_late_income` household setting), the app shows an informational alert and stays on the current month. Edit mode loads existing income data from TanStack Query cache (no single-income GET endpoint exists).

Receipt detail screen adapts UI based on receipt status: `uploaded` shows parse button, `processing` shows spinner with auto-polling, `failed` shows retry, `ocr_complete` shows full review UI (categorize, item category assignment via modal, exclude toggle, post button), `posted` shows read-only summary. Category picker shows only active expense categories. Post button is gated on all non-excluded items having confirmed categories. Date fallback input appears when receipt has no parsed date. Duplicate warning shown when `duplicate_candidates` is non-empty. The detail endpoint returns items=[] for non-review states; the review payload endpoint provides enriched items with category names.

### Mobile hardening pass (2026-04-26)

Post-v1 hardening focused on real-device readiness, cross-cutting UX consistency, and an observability baseline. No new product features, no new backend endpoints, no new native dependencies. 14 changes across three tiers:

**Foundation (api-client / QueryClient / auth):**
- 15s `AbortController` timeout on all `api-client.ts` methods; `AbortError` maps to `ApiError(0, 'Network timeout')`
- `handleResponse` short-circuits 204 / `content-length: 0` before `response.json()`; `del()` now delegates through `handleResponse<void>` so DELETE error bodies surface the same `detail` as other methods
- New `lib/errorLog.ts` — in-memory ring buffer (50 entries) + dev-mode `console.error`; explicit Sentry/PostHog swap-point comment marks the single chokepoint for future provider adoption
- QueryClient gains `QueryCache` + `MutationCache` wired to `logError`; `refetchOnWindowFocus: true` is now backed by an `AppState` → `focusManager.setEventListener` bridge (without the bridge the flag is a silent no-op in React Native). `refetchOnReconnect` is intentionally **not** set — wiring it would require `@react-native-community/netinfo`, a separate native-dep decision
- New `<ErrorBoundary>` wraps `<RootGate />` + `<Slot />`; renders `ErrorView` with reset, logs render errors via `logError`
- `signOut` now clears the React Query cache so a subsequent sign-in (possibly a different user on the same device) cannot see stale household-scoped data

**Cross-cutting UX:**
- New `<KeyboardAwareScreen>` wrapper (KeyboardAvoidingView + ScrollView + `keyboardShouldPersistTaps="handled"` + safe-area bottom padding). Applied to 8 form-heavy screens: sign-in, sign-up, create-household, accept-invite, income/form, savings/rule-form, savings/manual, settings
- `ErrorView` accepts an optional `error: unknown` prop with friendly mapping for `ApiError` (status 0 → "Connection problem", 401 → "Session expired", 5xx → "Server having trouble"); existing `message`-prop callers unchanged
- Email inputs across sign-in, sign-up, settings invite form get full attribute set (`autoComplete="email"`, `textContentType="emailAddress"`, `autoCorrect={false}`, `autoCapitalize="none"`, `keyboardType="email-address"`); password fields get `autoComplete="password"` / `"new-password"` + `textContentType` accordingly
- Money-amount inputs across income/form, savings/rule-form, savings/manual, search switch from `keyboardType="numeric"` to `"decimal-pad"` so the decimal point is visible on Android. Settings cutoff day already used `"number-pad"` + `maxLength={2}`

**Targeted polish:**
- Receipt detail `<Image>` gains `onError` → "Image unavailable. Tap to reload." fallback that invalidates `['receipts', id]` to fetch a fresh signed URL (Supabase signed URLs have a finite TTL and could expire mid-session)
- Image-picker permission denial (both library and camera) now offers `Linking.openSettings()` from `react-native` (built-in, not `expo-linking`) instead of dead-ending
- Dashboard ScrollView gains `RefreshControl` invalidating `['dashboard']` + `['budgets']` (other tabs deferred — users mostly refresh by changing month selector)

### Mobile — not yet implemented
- (none — v1 mobile feature set complete; remaining work is polish, real-device hardening, and observability)

### Not implemented (product scope)
- multi-household support
- household switching
- starter category templates
- founder-specific bootstrap flow

---

## 4. Architecture summary

### Deterministic logic in Python
Python/FastAPI owns:
- budget calculations
- dashboard math
- month rollover logic
- onboarding readiness checks
- category rename behavior
- transaction posting
- duplicate detection
- effective date logic
- late-income shift
- AI output validation
- `requires_review` determination
- all financial writes

### Non-deterministic logic in AI
AI is used only for:
- receipt OCR
- line-item extraction
- category suggestion
- confidence scoring

AI never:
- writes transactions directly
- decides `requires_review`
- posts receipts
- overrides deterministic financial rules

### Backend stack
- **Database:** Supabase-hosted Postgres
- **DB access:** `asyncpg` directly
- **Auth:** Supabase JWT verification via JWKS
- **Storage:** Supabase Storage for receipt images
- **API:** FastAPI
- **AI:** Anthropic via interfaces in `backend/app/ai/base.py`

### Mobile stack
- **Framework:** Expo SDK 54, expo-router v6
- **Language:** TypeScript (strict mode)
- **Auth:** `@supabase/supabase-js` with AsyncStorage session persistence
- **Server state:** TanStack Query (`@tanstack/react-query`)
- **HTTP:** Plain `fetch` wrapper with automatic Supabase JWT injection
- **UI:** Built-in React Native components + design tokens (no UI framework)

### Layering model
- `api/v1/` — thin routers
- `services/` — business logic and orchestration
- `repositories/` — SQL data access
- `rules/` — pure deterministic logic
- `schemas/` — request/response models
- `ai/` — provider interfaces and implementations

---

## 5. Auth model

There are exactly two auth dependencies in `backend/app/core/auth.py`.

| Dependency | Returns | Requires household? | Intended use |
|---|---|---|---|
| `get_auth_context` | `AuthContext(user_id, household_id, email)` | Yes | All normal household-scoped endpoints |
| `get_user_context` | `UserContext(user_id, email)` | No | Narrow pre-household corridor only |

### Current pre-household corridor
`get_user_context` is used only for:
- `POST /api/v1/households`
- `GET /api/v1/onboarding/status`
- `POST /api/v1/invites/lookup`
- `POST /api/v1/invites/accept`

Everything else remains household-scoped and requires `get_auth_context`.

Additional current auth behavior:
- JWTs are verified against the project's JWKS document
- normalized `email` is extracted from the JWT and treated as required
- `SUPABASE_JWT_SECRET` / shared-secret verification is not used

---

## 6. Core data model

### Main entities
- `households`
- `household_members`
- `household_settings`
- `categories`
- `category_aliases`
- `budget_months`
- `budget_lines`
- `receipts`
- `receipt_items`
- `transaction_groups`
- `transactions`
- `savings_rules`
- `savings_proposals`
- `household_invites`

### Important schema constraints
- UUID primary keys throughout
- one household per user via `UNIQUE(user_id)` on `household_members`
- stable category identity via UUIDs
- positive amounts; transaction `type` determines direction
- idempotency via `UNIQUE(idempotency_key)` on `transaction_groups`
- private receipt storage bucket
- RLS enabled on household-scoped tables

### Invite-specific schema notes
`household_invites` stores:
- normalized invite email
- SHA-256 token hash
- status
- expiry
- accepted/revoked metadata

Key invite constraints:
- unique index on `token_hash`
- partial unique constraint for one pending invite per household
- this supports the v1 two-member cap

---

## 7. Budget and dashboard behavior

### Budget month behavior
- months are calendar months
- `budget_months.month` is always the first day of the month
- new month initialization copies the prior month’s active budget lines and planned amounts
- archived categories are skipped
- actual transactions are never copied forward
- month initialization is idempotent

### Late-income shift
When enabled, income after the configured cutoff day is assigned to the next budget month.

This affects income only.

### Dashboard formulas
- `to_be_allocated = planned_income - planned_expenses - planned_savings`
- `actual_balance = actual_income - actual_expenses - actual_savings`
- `plan_coverage = actual_income - planned_expenses - planned_savings`
- `savings_rate = actual_savings / actual_income * 100`, else `null` if income is zero

Dashboard behavior:
- includes categories with budget lines, actuals, or both
- unbudgeted actual categories still appear with `planned = 0`
- if no budget month exists, returns a deterministic empty response instead of 404

---

## 8. Receipt workflow status

The receipt flow is fully implemented through posting.

### Current flow
1. upload receipt image
2. parse with OCR
3. categorize items
4. load review payload
5. edit item confirmations/exclusions
6. confirm receipt
7. create grouped expense transactions
8. mark receipt as posted

### Important current rules
- receipt-derived transactions are never auto-posted
- explicit user confirmation is always required
- categorization fails with **422** when the household has zero active expense categories
- `requires_review` is determined by Python, not AI
- transactions are created from `user_confirmed_category_id`, never from `suggested_category_id`
- item-level discount lines (RABAT, DISCOUNT, TILBUD with a negative price) are extracted by AI and folded into their preceding product item in Python (`fold_adjacent_discounts` in `receipt_rules.py`); the net price is stored — never the gross
- summary discount lines (RABAT I ALT, TOTAL RABAT, etc.) are dropped by Python before DB insert; they appear only in `ocr_raw_text` and the stored receipt image

### Re-categorization
Re-categorization is a full refresh:
- valid new suggestions replace old ones
- items without valid new suggestions reset to unresolved state

### Re-parse behavior
Successful re-parse replaces OCR data and items atomically.

Failed re-parse from `ocr_complete` preserves the prior OCR data/items and restores `ocr_complete`.

### Confirm/post behavior
`POST /api/v1/receipt-review/{id}/confirm`:
- validates all non-excluded items are resolved
- re-validates active expense categories
- groups items by confirmed category
- creates `transaction_group`
- creates grouped expense transactions
- transitions `ocr_complete → reviewed → posted`
- is idempotent via `receipt:{receipt_id}`

---

## 9. Invite flow status

The second-user invite / join flow is implemented.

### Current inviter-side endpoints
- `POST /api/v1/invites/`
- `GET /api/v1/invites/`
- `DELETE /api/v1/invites/{id}`

These require `get_auth_context`.

### Current invitee-side endpoints
- `POST /api/v1/invites/lookup`
- `POST /api/v1/invites/accept`

These use `get_user_context` because the invitee does not yet belong to a household.

### Current invite behavior
- raw token generated with `secrets.token_urlsafe(32)`
- only SHA-256 token hash stored at rest
- token is returned exactly once on invite creation
- tokens are single-use
- tokens expire after 7 days
- verified JWT email must equal invite email for lookup and accept
- acceptance inserts the membership row and flips invite status atomically

### v1 seat cap
Households are capped at 2 members in v1.

This is enforced by:
1. DB-level one-pending-invite constraint
2. create-invite member-count check
3. accept-invite member-count re-check inside the locked transaction

### Current cap audit status
The v1 2-member cap has been explicitly audited and is currently enforced at three layers:

1. DB-level one-pending-invite-per-household constraint
2. `InviteService.create_invite` member-count rejection when household already has 2+ members
3. `InviteService.accept_invite` member-count re-check inside the locked accept transaction before membership insert

This behavior is covered by automated tests, a smoke harness, and live verification against the running stack (all 14 scenarios pass, including create-side cap enforcement). Accept-side cap enforcement remains covered by automated tests and the service-level audit.

---

## 10. Savings workflow status

### Implemented savings flows

**Savings rule CRUD:**
- `GET /api/v1/savings/rules` — list all rules for household
- `POST /api/v1/savings/rules` — create rule (percent_of_income or fixed_monthly)
- `PUT /api/v1/savings/rules/{id}` — partial update with `model_fields_set` semantics

Rules are validated against savings-type categories. Mutable fields: `label`, `percent_value`, `fixed_amount`, `is_active`. Immutable: `category_id`, `rule_type`.

**Proposal generation:**
- `POST /api/v1/savings/proposals/generate` — generate proposals for a budget month (200, idempotent)
- `GET /api/v1/savings/proposals` — list proposals for a month

Generation uses total actual income for the month and active rules. `build_proposals()` produces audit-friendly `calculation_basis` including rule type, basis values, and total income. Idempotent via `ON CONFLICT (savings_rule_id, budget_month_id) DO NOTHING`.

**Proposal approval and rejection:**
- `POST /api/v1/savings/proposals/{id}/approve` — approve + post atomically (pending → posted)
- `POST /api/v1/savings/proposals/{id}/reject` — reject (pending → rejected)

Approve creates a transaction_group + savings transaction in one DB transaction. Uses `idempotency_key = savings_proposal:{proposal_id}`. User may override `final_amount`. The `approved` enum value is reserved for future use but not used in v1.

**Manual savings entry:**
- `POST /api/v1/savings/manual` — create a manual savings transaction (201)

Creates a transaction_group (source=`manual_savings`) + savings transaction atomically. Validates category is type `savings` and not archived. Resolves budget month from `transaction_date` using normal calendar month (no late-income shift). Auto-creates budget month if it does not exist. Uses `idempotency_key = manual_savings:{uuid4()}`.

---

## 11. Current backend code map

### Routers
Implemented:
- `categories.py`
- `budgets.py`
- `incomes.py`
- `expenses.py` — manual expense entry CRUD (`GET`, `POST`, `PUT`, `DELETE` under `/expenses`); request/response shapes in `app/schemas/expenses.py`; router included in `app/api/v1/router.py` with `prefix="/expenses"`, `tags=["expenses"]`
- `dashboard.py`
- `receipts.py`
- `receipt_review.py`
- `households.py`
- `household_settings.py`
- `onboarding.py`
- `invites.py`

Implemented:
- `savings.py` — rules CRUD, proposal generation/list/approve/reject, manual savings entry
- `search.py` — receipt search, transaction search

### Services
Implemented:
- `category_service.py`
- `budget_service.py`
- `income_service.py`
- `expense_service.py` — manual expense create/update/delete/list; mirrors `income_service` minus late-income-shift (expenses always use the calendar month of `transaction_date`); writes `source="manual_expense"` with idempotency key `manual_expense:{uuid}`; create/update responses augmented with `category_name` + `budget_month`
- `dashboard_service.py`
- `receipt_service.py`
- `receipt_review_service.py`
- `household_service.py`
- `onboarding_service.py`
- `invite_service.py`
- `savings_service.py` — rules CRUD, proposal generation/approve/reject, manual savings entry
- `search_service.py` — receipt search, transaction search with range validation

### Repositories
Implemented:
- `categories.py`
- `budgets.py`
- `transactions.py`
- `household.py`
- `onboarding.py`
- `receipts.py`
- `invites.py`
- `savings.py`
- `search.py`

---

## 12. API surface summary

### Current implemented domains
- categories
- budgets
- incomes
- expenses
- dashboard
- receipts
- receipt review
- households
- household settings
- onboarding
- invites
- savings
- search

All endpoints are under `/api/v1/`. All endpoints except `/health` require Bearer auth.

---

## 13. Testing and verification status

### Automated tests
The invite test suite includes explicit proof of all three v1 2-seat-cap enforcement layers.
Current count:
- **410 unit tests passing** (mock-based)
- **29 integration tests passing** (real Postgres)

#### Unit test coverage
- JWKS auth
- JWT email extraction and normalization
- category rules
- budget rules
- dashboard rules
- date rules
- receipt rules
- savings rules (pure calculations)
- savings service (rule CRUD, proposal generation/idempotency, approve+post, rejection, manual savings entry)
- expense service (create happy path returns `category_name` + `budget_month`; create rejects non-expense category, archived category, non-positive amount; delete happy path; delete rejects receipt-sourced transactions) — `backend/tests/test_services/test_expense_service.py` (6 tests)
- household service
- onboarding service
- invite service
- receipt service
- receipt review service
- router-level onboarding auth wiring
- router-level invite auth wiring
- search service (receipt search, transaction search, range validation)
- router-level search auth wiring and response shape

#### Real Postgres integration tests (`tests/integration/`)
Added in this phase. Tests run against a real Postgres instance (Docker or Supabase pooler via `INTEGRATION_TEST_DB_URL`). Each test runs inside a rolled-back transaction for full isolation.

Infrastructure:
- `conftest.py` — Docker Postgres lifecycle, migration application, per-test rollback connection
- `pool_adapter.py` — `SingleConnectionPool` wrapping one connection as an asyncpg.Pool
- `bootstrap.sql` — stub `auth`/`storage` schemas for plain Postgres (Docker path)
- `seed_helpers.py` — raw-SQL test data factories

Flows covered (29 tests):
- **Receipt confirm/post** (5 tests) — transaction group + transaction creation, idempotency key dedup, status CAS, auto budget month creation, wrong-status rejection, unconfirmed-item rejection
- **Invite accept** (5 tests) — membership creation + invite status update, wrong-email rejection with no side effects, full-household rejection, one-pending-per-household constraint, lazy expiry transition
- **Savings approve/post + manual savings** (6 tests) — proposal → posted with transaction group + transaction + proposal linkage, idempotency key prevents double post, custom amount override, manual savings auto-creates budget month, rejects expense category, rejects archived category
- **Budget month initialization** (4 tests) — idempotent return of existing month, carry-forward copies previous lines, archived categories skipped, first month creates empty
- **Category rename/alias** (5 tests) — rename creates alias, multiple renames accumulate aliases, name updated correctly, rename to existing name fails with no alias, archived rename fails
- **Search household scoping** (4 tests) — transactions scoped to household, receipts scoped to household (two-household isolation)

Run with: `pytest tests/integration/ -v` (requires `INTEGRATION_TEST_DB_URL` or Docker)
Run unit tests only: `pytest tests/ -m "not integration"`

### Not covered by automated tests
- broad full API end-to-end suite across the whole app
- concurrency stress tests
- full storage integration under automated test

### Live-verified flows
Verified against the running stack:
- receipt upload → parse → categorize → payload (re-verified on emulator 2026-04-30 after UUID→index AI contract fix — food items categorized into Groceries, household items into correct categories)
- receipt review UX — disabled Post button when zero non-excluded items; spinner during parse/categorize; counts update live (emulator-verified 2026-04-30, Android)
- receipt confirm 409 eliminated — removed spurious `['receipt-review', receiptId]` invalidation from `useConfirmReceipt.onSuccess`; review payload query disables itself naturally when status becomes posted (emulator-verified 2026-04-30, Android)
- receipt item-level discount handling — AI now extracts RABAT lines with negative prices; Python `fold_adjacent_discounts` folds each into its preceding product item so category totals reflect the net paid amount, not gross (emulator-verified 2026-04-30, Android)
- receipt item editing
- receipt confirm/post
- onboarding corridor from fresh user to ready state
- invite create → list → lookup → accept → post-accept access
- invite replay (409), wrong-email (403), expired (410 + lazy transition), re-invite after expiry, cap block (409), revoke → accept (409)
- one-pending-per-household constraint
- 2-seat cap enforcement live-verified at create; accept-side enforcement remains covered by automated tests and the service-level audit
- DB probe: 2 members after accept, invite status=accepted with timestamps
- savings: category create → percent rule → fixed rules → add rule later → generate proposals → idempotent re-generate → approve/post → reject → manual savings entry → DB probe (transaction_group, transaction, savings_proposals.transaction_id) → dashboard reflects posted savings
- savings cleanup + second consecutive run: both runs GO
- search: receipt search (merchant, category, date range, amount range, status) + transaction search (category, type, source, date range, amount range) + invalid range validation (422) + no-household 403 + cross-household scoping (200, total=0) + cleanup + second consecutive run: both runs GO
- mobile Phase 5 search: full search/history slice exercised end-to-end via fresh isolated user — 23 API scenarios + 9 code-reviewed scenarios + tsc clean (see Section 13)

### Mobile Phase 1 verification (2026-04-18)

**Scope:** API contract verification + code-level correctness review + TypeScript compile check. This does **not** cover native UI rendering, touch interactions, visual layout, or platform-specific behavior — those require manual testing on a device or simulator.

**Method:** Fresh Supabase auth user created via admin API, walked through the exact API call sequence the mobile app makes against the live backend (port 8765). All test data cleaned up afterward (household-scoped data in dependency order + auth user deletion, verified zero orphaned rows).

| # | Scenario | Method | Result |
|---|----------|--------|--------|
| 1 | Sign-up with fresh email | API-verified | PASS |
| 2 | Onboarding status (no household) | API-verified | PASS |
| 3 | Create household | API-verified | PASS (201) |
| 4 | Onboarding status (household, no categories) | API-verified | PASS |
| 5 | Create categories (income, expense, savings) | API-verified | PASS (3× 201) |
| 6 | Onboarding readiness (all flags true) | API-verified | PASS |
| 7 | Initialize current month | API-verified | PASS (201) |
| 8 | Dashboard zero state (0.00 totals, null savings_rate, empty arrays) | API-verified | PASS |
| 9 | Month navigation (no-data month → deterministic empty, not 404) | API-verified | PASS |
| 10 | Sign back in → onboarding ready → dashboard | API-verified | PASS |
| 11 | Backend-down → connection refused | API-verified | PASS |
| 12 | Root gate navigation logic | Code-reviewed | PASS |
| 13 | API path alignment (mobile ↔ backend) | Code-reviewed | PASS |
| 14 | Loading states (all screens) | Code-reviewed | PASS |
| 15 | Error states with retry | Code-reviewed | PASS |
| 16 | Sign out flow | Code-reviewed | PASS |
| 17 | TypeScript compilation (zero errors) | Compile-verified | PASS |

**Verdict:** GO — Phase 1 mobile is green at the API contract + code correctness + build health level.

**Notes:**
- Backend routes `/households` and `/categories` return 307 redirects to trailing-slash variants; `fetch` follows 307 preserving method/body, so this works but is worth noting.
- Backend confirmed reachable on port 8765 (Windows-specific local bind), not 8000 from root `.env`.

### Mobile Phase 2 verification (2026-04-19)

**Scope:** API contract verification + code-level correctness review + TypeScript compile check. Same framing as Phase 1 — does not cover native UI rendering, touch interactions, or platform-specific behavior.

**Method:** Fresh Supabase auth user created via admin API, fresh household + categories + budget month. All API calls against the live backend (port 8765). All test data cleaned up afterward (transactions → transaction_groups → budget_lines → budget_months → category_aliases → categories → household_settings → household_members → households → auth user, verified zero orphaned rows).

| # | Scenario | Method | Result | Notes |
|---|----------|--------|--------|-------|
| 1 | Budget months list — no `lines` field | API-verified | PASS | Keys: id, household_id, month, notes, is_closed, created_at, updated_at |
| 2 | Budget month detail — includes `lines` array | API-verified | PASS | |
| 3 | Budget line upsert — create | API-verified | PASS | Returns raw row (no category_name) |
| 4 | Budget line upsert — update | API-verified | PASS | planned_amount + notes updated |
| 5 | Budget month detail — reflects updated lines | API-verified | PASS | 3 lines with correct planned/actual |
| 6 | Income create — bare response, budget_month is date string | API-verified | PASS | 201, budget_month = "2026-04-01" |
| 7 | Income list — `{incomes: [...]}` wrapper | API-verified | PASS | |
| 8 | Income update — amount change | API-verified | PASS | |
| 9 | Income delete — 204, removed from list | API-verified | PASS | |
| 10 | Late-income shift — enable via household settings | API-verified | PASS | shift_late_income=true, cutoff=25 |
| 11 | Late-income shift — income after cutoff shifts to next month | API-verified | PASS | date=2026-04-28 → budget_month=2026-05-01 |
| 12 | Late-income shift — disable | API-verified | PASS | |
| 13 | Dashboard — reflects budget lines + income | API-verified | PASS | planned_income=12000, actual_income=25000 |
| 14 | Month isolation — different month has no data | API-verified | PASS | |
| 15 | MonthContext — tabs sync on month change | Code-reviewed | PASS | |
| 16 | Budget detail — categories without lines shown, closed months read-only | Code-reviewed | PASS | |
| 17 | Income form — edit loads from cache, add mode has category picker | Code-reviewed | PASS | |
| 18 | Late-income shift UX — informational alert when budget_month differs | Code-reviewed | PASS | |
| 19 | Navigation — tab switching preserves month, stack nav works | Code-reviewed | PASS | |
| 20 | MonthSelector — reused across all tabs | Code-reviewed | PASS | |
| 21 | TypeScript compilation — zero errors | Compile-verified | PASS | |

**Verdict:** GO — Phase 2 mobile is green at the API contract + code correctness + build health level.

**Notes:**
- Budget endpoints return amounts as numbers (e.g., `12000.0`) not strings — the router doesn't use `response_model`. Dashboard endpoint uses `response_model` and returns strings (`"12000.00"`). The mobile `formatDKK` function handles both.
- Budget line upsert response is a raw repository row without `category_name` or `actual_amount`. The mobile mutation only uses the response for cache invalidation, so this is harmless.
- Backend auto-created May 2026 budget month when the late-income-shifted income was assigned to it.

### Mobile Phase 3 verification (2026-04-20)

**Scope:** API contract verification for full receipt lifecycle + code-level correctness review + TypeScript compile check. Same framing as Phase 1+2.

**Method:** Fresh Supabase auth user created via admin API, fresh household + 2 expense categories + budget month. Used `backend/tests/fixtures/smoke_receipt.jpeg` (known-good receipt from backend smoke tests). All API calls against the live backend (port 8765). All test data cleaned up afterward in FK dependency order. Auth user deleted.

| # | Scenario | Method | Result | Notes |
|---|----------|--------|--------|-------|
| 1 | Upload receipt (smoke_receipt.jpeg) | API-verified | PASS | 201, status=uploaded |
| 2 | List receipts — bare array, no wrapper | API-verified | PASS | Returns ReceiptListItem[] |
| 3 | Get receipt detail — signed image URL | API-verified | PASS | image_url present |
| 4 | Parse receipt | API-verified | PASS | Returned ocr_complete immediately |
| 5 | Poll parse completion — items populated | API-verified | PASS | 7 items, store=365 discount, total=401.80 |
| 6 | Categorize — status stays ocr_complete | API-verified | PASS | 6/7 items got suggestions |
| 7 | Review payload — enriched items with category names | API-verified | PASS | suggested_category_name populated |
| 8 | Update item — confirm category | API-verified | PASS | user_confirmed_category_id set |
| 9 | Update item — exclude | API-verified | PASS | is_excluded=True |
| 10 | Confirm/post receipt | API-verified | PASS | transactions_created=1, total_mismatch=True |
| 11 | Get receipt after confirm — status=posted | API-verified | PASS | |
| 12 | Parse on posted receipt → 409 | API-verified | PASS | |
| 13 | Categorize on uploaded receipt → 409 | API-verified | PASS | |
| 14 | Confirm duplicate → idempotent | API-verified | PASS | Returns 200 with cached response |
| 15 | Upload FormData + image picker permissions | Code-reviewed | PASS | No manual Content-Type |
| 16 | Processing poll — refetchInterval only during processing | Code-reviewed | PASS | |
| 17 | Category picker — active expense categories only | Code-reviewed | PASS | |
| 18 | Post button gated on confirmed categories | Code-reviewed | PASS | |
| 19 | Date fallback when receipt_date is null | Code-reviewed | PASS | |
| 20 | Status-driven UI — all 6 statuses rendered | Code-reviewed | PASS | |
| 21 | Invalidation — confirm invalidates receipts + detail + review + dashboard + budget | Code-reviewed | PASS | |
| 22 | TypeScript compilation — zero errors | Compile-verified | PASS | |

**Verdict:** GO — Phase 3 mobile is green at the API contract + code correctness + build health level.

**Post-fix emulator verification (2026-04-30):** A regression was observed where categorize completed but every item returned "No category / Needs review". Root cause: the AI prompt asked Claude to echo raw database UUIDs verbatim; LLMs reliably misremember them, causing all suggestions to be dropped by server-side validation. Fix: switched `backend/app/ai/categorizer.py` to a 1-based index contract — items and categories are numbered `[1]`, `[2]`, … in the prompt; AI returns integer indices; server maps back to UUIDs. Confirmed working on emulator: food items correctly assigned to Groceries, household items to correct categories. Confidence threshold unchanged at 0.85.

**Receipt UX + stability fixes (emulator-verified 2026-04-30, Android):** Three follow-up fixes applied after Phase 3:
1. **Review screen UX** — Post button disabled when `nonExcludedCount === 0`; loading spinners shown during parse and categorize; item counts update live as exclusions change.
2. **Spurious 409 on confirm** — after a successful confirm/post, `useConfirmReceipt.onSuccess` was invalidating `['receipt-review', receiptId]`, which caused `useReviewPayload` (still enabled during the same render cycle) to immediately refetch and receive 409 from the backend (correct: receipt is now `posted`). Fix: removed the review-payload invalidation; the query disables itself on the next render when `receipt.status` transitions to `posted`.
3. **Item-level discount folding** — AI prompt updated to extract RABAT/DISCOUNT lines as items with negative `total_price` (summary lines like RABAT I ALT still excluded). `fold_adjacent_discounts()` added to `receipt_rules.py`: processes items in extracted order, folds each discount into its immediately preceding positive product item via `dataclasses.replace()`, drops summary lines, and keeps unmatched discounts for user review. Called in `receipt_service.py` after AI parse, before DB insert. 29 new unit tests in `test_receipt_rules.py`. Net result: category totals reflect the paid amount (e.g., JORDBÆR 25,00 − RABAT 7,00 → stored as 18,00).

**Notes:**
- Receipt detail endpoint (`GET /receipts/{id}`) returns `items: []` for all statuses. Items are only populated via the review payload endpoint (`GET /receipt-review/{id}/payload`). The detail screen correctly uses `reviewData?.items ?? receipt.items`.
- Parse returned `ocr_complete` immediately (synchronous AI call, no intermediate `processing` state observed). The mobile polling logic handles both cases correctly.
- `total_mismatch=True` on confirm: the excluded NICORETTE item causes the posted sum to differ from the receipt total. This is expected behavior.
- All 7 items were grouped into 1 transaction (all confirmed as "Groceries" category). The backend groups items by confirmed category.
- The `confirm` endpoint returns 200 on duplicate attempt (idempotent via `receipt:{receipt_id}` key), not 409.

### Mobile Phase 4 verification (2026-04-21)

**Scope:** API contract verification for full savings lifecycle (rule CRUD, proposal generate/approve/reject, manual savings) + code-level correctness review + TypeScript compile check. Same framing as Phase 1+2+3.

**Method:** Two complementary verification scripts against the live backend (port 8765):
- [.smoke/savings_verify.py](.smoke/savings_verify.py) — full savings lifecycle (13 base scenarios), uses the existing smoke user
- [.smoke/savings_phase4_verify.py](.smoke/savings_phase4_verify.py) — Phase 4 mobile gaps (label update, is_active toggle, approve-with-override, 409 re-approve)

Both scripts initialize the budget month + a test income (40k–50k DKK), exercise the full flow, and clean up all artifacts in FK dependency order. No mock data; all amounts checked against deterministic backend math.

| # | Scenario | Method | Result | Notes |
|---|----------|--------|--------|-------|
| 1 | Initialize budget month (idempotent) | API-verified | PASS | 201, month_id returned |
| 2 | Create savings category | API-verified | PASS | 201, type=savings |
| 3 | Create percent_of_income rule (rule A, 10%) | API-verified | PASS | 201, category_name populated |
| 4 | Create fixed_monthly rule (rule B, 1500) | API-verified | PASS | 201 |
| 5 | Create second fixed_monthly rule (rule C, 800) | API-verified | PASS | 201 |
| 6 | List rules — all 3 returned with category_name | API-verified | PASS | `{rules: [...]}` wrapper |
| 7 | Update rule label (PUT) | API-verified | PASS | 200, label changed |
| 8 | Toggle rule inactive (is_active=false) | API-verified | PASS | 200 |
| 9 | Toggle rule active (is_active=true) | API-verified | PASS | 200 |
| 10 | Generate proposals for month — 3 pending | API-verified | PASS | 200, one proposal per active rule |
| 11 | Percent proposal amount = 10% of income | API-verified | PASS | 4000.0 of 40000 (gap script); 5000.0 of 50000 (base script) |
| 12 | Idempotent re-generation — same IDs | API-verified | PASS | base script |
| 13 | Approve A with default amount (no body) | API-verified | PASS | 200, status=posted, final=proposed |
| 14 | Approve B with override final_amount | API-verified | PASS | 200, status=posted, final≠proposed |
| 15 | Reject C | API-verified | PASS | 200, status=rejected |
| 16 | Re-approve already-posted A → 409 | API-verified | PASS | 409, "Proposal status is 'posted', expected 'pending'" |
| 17 | Manual savings entry | API-verified | PASS | 201, type=savings, source=manual_savings |
| 18 | DB probe — savings_proposal txn group + idem key | API-verified | PASS | base script (`savings_proposal:{id}` key) |
| 19 | DB probe — manual_savings txn group + idem key | API-verified | PASS | base script |
| 20 | Dashboard reflects savings totals | API-verified | PASS | total_actual_savings = 6100.0 (4000+1750+350); savings_rate = 11.50 in base script |
| 21 | Segmented control toggles between Rules / Proposals | Code-reviewed | PASS | full-width pills, primary bg when active |
| 22 | Rule form: category picker shows only savings categories, archived filtered | Code-reviewed | PASS | `useCategories('savings')` + `!c.archived_at` |
| 23 | Rule form: rule_type toggle shows correct value field | Code-reviewed | PASS | percent_value vs fixed_amount field swap |
| 24 | Rule form: edit mode disables category + rule_type, shows read-only | Code-reviewed | PASS | loaded from `['savings','rules']` cache |
| 25 | Proposals segment: month selector + budget month lookup | Code-reviewed | PASS | mirrors income index pattern |
| 26 | Approve modal: pre-fills proposed_amount, sends final_amount only when overridden | Code-reviewed | PASS | empty body when default |
| 27 | Manual form: not gated by budgetMonthId, top-level entry button | Code-reviewed | PASS | backend derives month from transaction_date |
| 28 | TypeScript compilation — zero errors | Compile-verified | PASS | `npx tsc --noEmit` |

**Verdict:** GO — Phase 4 mobile is green at the API contract + code correctness + build health level.

**Notes:**
- Savings endpoints return amounts as JSON numbers (e.g., `5000.0`), not strings — the savings router does NOT use `response_model`. Mobile types model amounts as `number`. `formatDKK` accepts `string | number`.
- `calculation_basis` is returned as a JSON string (e.g., `"{\"percent\": \"10.00\", ...}"`), not as an object. Mobile types it as `string | null`; the UI doesn't decode it currently.
- Backend `SavingsRuleUpdate` does not accept `category_id` or `rule_type`. Edit mode in mobile reflects this by showing read-only category name + rule type, and only sending `label`, `percent_value`, `fixed_amount`, `is_active`.
- Manual savings is **not** gated on an existing budget month — backend derives/auto-creates the month from `transaction_date`. The "Manual Savings Entry" button in the index sits above the segmented control so it's always reachable.
- Re-approve attempt returns 409 with detail `"Proposal status is 'posted', expected 'pending'"`. The mobile UI hides Approve/Reject when status is not pending, so this path is not user-reachable, but the backend safety remains.

### Mobile Phase 5 verification (2026-04-24)

**Scope:** API contract verification for both search endpoints (receipts + transactions) including filter combinations, pagination, and range-validation 422s + code-level correctness review + TypeScript compile check. Same framing as Phase 1+2+3+4.

**Method:** [.smoke/search_verify.py](.smoke/search_verify.py) creates a fresh isolated Supabase auth user per run (no reuse of prior smoke data), discovers the backend port by probing `/openapi.json` on 127.0.0.1:8000 then :8765, seeds the minimum data needed (4 categories, budget month, 1 manual income, 1 manual savings, 1 savings rule + 1 generated proposal + 1 approved → savings_proposal-source txn, 1 receipt + items inserted via DB to produce 2 receipt-source expense transactions), runs all 23 API scenarios, then cleans up everything in FK dependency order and deletes the auth user. The script is rerun-safe and leaves zero residue.

| # | Scenario | Method | Result | Notes |
|---|----------|--------|--------|-------|
| 1 | Search receipts: no filters | API-verified | PASS | total=1, our seeded receipt found |
| 2 | Search receipts by merchant substring (case-insensitive) | API-verified | PASS | substring matches `store_name` ILIKE |
| 3 | Search receipts by status=`posted` | API-verified | PASS | all returned rows have status=posted |
| 4 | Search receipts by date range | API-verified | PASS | filters on `receipt_date` |
| 5 | Search receipts by amount range | API-verified | PASS | inclusive on `total_amount` |
| 6 | Search receipts by category_id | API-verified | PASS | matches receipts whose items have a confirmed category match |
| 7 | Search receipts pagination (`limit=2&offset=0` then `offset=2`) | API-verified | PASS | no overlap between pages |
| 8 | Search transactions: no filters | API-verified | PASS | total=5 (1 income + 1 manual_savings + 1 savings_proposal + 2 receipt-sourced expenses) |
| 9 | Search transactions by `type=income` | API-verified | PASS | all rows type=income |
| 10 | Search transactions by `type=expense` | API-verified | PASS | total=2, all rows type=expense |
| 11 | Search transactions by `type=savings` | API-verified | PASS | sources={manual_savings, savings_proposal} both present |
| 12 | Search transactions by `source=receipt` | API-verified | PASS | all rows have `store_name` populated |
| 13 | Search transactions by `source=savings_proposal` | API-verified | PASS | all rows are type=savings |
| 14 | Search transactions by date range (effective_date) | API-verified | PASS | |
| 15 | Search transactions by amount range | API-verified | PASS | |
| 16 | Search transactions by category_id | API-verified | PASS | |
| 17 | Search transactions pagination (`limit=3&offset=0` then `offset=3`) | API-verified | PASS | no overlap between pages |
| 18 | Combined filters: `type=expense&date_from=...&amount_min=...` | API-verified | PASS | returns subset of #10 |
| 19 | Empty result: `amount_min=99999999` | API-verified | PASS | `{ results: [], total: 0 }` |
| 20 | Receipts: invalid date range (`date_from > date_to`) → 422 | API-verified | PASS | backend rejects, not silent empty |
| 21 | Receipts: invalid amount range (`amount_min > amount_max`) → 422 | API-verified | PASS | |
| 22 | Transactions: invalid date range → 422 | API-verified | PASS | |
| 23 | Transactions: invalid amount range → 422 | API-verified | PASS | |
| 24 | Segmented control switches modes; each mode owns its own filter state | Code-reviewed | PASS | two `useState` filter objects, never reset on mode switch |
| 25 | Receipt rows navigate to `/(main)/receipts/[id]` on tap | Code-reviewed | PASS | `Pressable` wrapping ReceiptRow → `router.push` |
| 26 | Filter chips highlight when active (primary bg + textInverse text) | Code-reviewed | PASS | shared FilterChip + CategoryChips |
| 27 | Category chips bind to `useCategories('expense')` in receipts mode and to selected type in transactions mode | Code-reviewed | PASS | transactions mode passes `filters.type` |
| 28 | "Load more" button shown only when `hasNextPage`; tapping appends | Code-reviewed | PASS | wired to `query.fetchNextPage` |
| 29 | "Clear filters" resets active mode's filter state without touching the other mode | Code-reviewed | PASS | mode-scoped reset |
| 30 | Merchant input debounced 250 ms via `useDebouncedValue` | Code-reviewed | PASS | new helper at `mobile/src/lib/useDebouncedValue.ts` |
| 31 | Empty/loading/error states render correctly | Code-reviewed | PASS | LoadingSpinner / ErrorView / EmptyState |
| 32 | After a write (post receipt, approve/reject proposal, manual savings, income CUD) the relevant search query is invalidated | Code-reviewed | PASS | `['search']` added to receipts/savings/incomes mutation onSuccess |
| 33 | TypeScript compilation — zero errors | Compile-verified | PASS | `npx tsc --noEmit` |

**Verdict:** GO — Phase 5 mobile is green at the API contract + code correctness + build health level.

**Notes:**
- Backend rejects nonsensical date/amount ranges with 422 (validated for both endpoints, both range types — scenarios 20–23). The plan flagged this would be flagged as a finding if it passed silently; it does not — backend behaves as specified.
- Receipt-search `category_id` filter matches receipts whose items have **at least one** item with a confirmed category equal to the filter (not all items). The seeded receipt with two distinct categories satisfies the filter for either category.
- Transaction-search has **no text search** by design — only structured filters. The mobile UI reflects this (no merchant text input in transactions mode).
- v1 has no user-facing manual-expense endpoint — expenses come exclusively from the receipt-posting flow. The verify script creates the two expense transactions by inserting the receipt + items + transactions directly via asyncpg (the receipt is already in `posted` state in DB), avoiding the AI call path while still producing legitimate `source=receipt` rows.
- `useInfiniteQuery` page size is 50 to match the backend default. The mobile UI does not auto-trigger next page on scroll — explicit "Load more" tap.
- Switching modes preserves both filter states. "Clear filters" only resets the currently active mode.

### Mobile Phase 6 verification (2026-04-24)

**Scope:** API contract verification for the mobile-Phase-6 surface (settings + invites) + code-level correctness review of the new screens + TypeScript compile check + the root-gate allowlist needed to make the accept-invite screen reachable.

**Method:** Three layers:
1. **Phase-6-specific smoke** — [.smoke/settings_verify.py](.smoke/settings_verify.py) creates two fresh isolated Supabase users (owner + invitee), exercises `GET /households/me`, `GET /household-settings`, the full `PUT /household-settings` enable/disable cycle + 422 validations, `POST /invites`, `POST /invites/lookup` (garbage-token 404), `POST /invites/accept`, and the `GET /invites?status=accepted` workaround the mobile Members section depends on. Tears down both users + household + settings + invites in FK order on exit.
2. **Existing smoke replay** — [.smoke/invite_verify.py](.smoke/invite_verify.py) re-run end-to-end (15 steps including create/list/lookup/accept/db-probe/replay 409/wrong-email 403/expired 410/re-invite/cap 409/revoke 409). All green.
3. **Code-reviewed** UI scenarios for the new screens, plus `npx tsc --noEmit`.

| # | Scenario | Method | Result | Notes |
|---|----------|--------|--------|-------|
| 1 | `POST /households/` returns 201 with `household.id` | API-verified | PASS | settings_verify step 1 |
| 2 | `GET /households/me` returns `{ id, name, created_at }` | API-verified | PASS | mobile household card source |
| 3 | `GET /household-settings` returns `currency=DKK` + defaults | API-verified | PASS | |
| 4 | `PUT /household-settings` enable shift + cutoff=25 → 200 | API-verified | PASS | |
| 5 | `GET /household-settings` reflects #4 | API-verified | PASS | |
| 6 | `PUT /household-settings` cutoff=29 → 422 | API-verified | PASS | |
| 7 | `PUT /household-settings` cutoff=0 → 422 | API-verified | PASS | |
| 8 | `PUT /household-settings` disable shift → 200 | API-verified | PASS | |
| 9 | `POST /invites/` → 201 with `token` (≥32 chars) | API-verified | PASS | mobile token banner source |
| 10 | `POST /invites/lookup` with garbage token → 404 | API-verified | PASS | mobile inline error path |
| 11 | `POST /invites/accept` → 201 | API-verified | PASS | |
| 12 | `GET /invites?status=accepted` returns invitee email + no token leak | API-verified | PASS | member-list workaround |
| 13 | `invite_verify.py` replay — full invite lifecycle (15 steps) | API-verified | PASS | no regression from prior phases |
| 14 | Settings tab renders household name + created_at | Code-reviewed | PASS | uses `useHousehold()` |
| 15 | Late-income switch toggles cutoff input enabled state | Code-reviewed | PASS | `editable={shiftLate}` on TextInput |
| 16 | Save button disabled when no field changed; enabled after edit | Code-reviewed | PASS | `settingsDirty` memo compares form vs server |
| 17 | 422 from `PUT /household-settings` surfaces as `Alert.alert` | Code-reviewed | PASS | mutation `onError` wrapped |
| 18 | Send-invite success shows token in `selectable` Text with "Long-press to copy" hint (no `expo-clipboard` dependency) | Code-reviewed | PASS | banner visible until cleared |
| 19 | Revoke invite triggers `Alert.alert` confirm before DELETE | Code-reviewed | PASS | mirrors income/index.tsx pattern |
| 20 | Members section shows "You — {email}" + accepted invitee email; count "N/2" | Code-reviewed | PASS | `1 + accepted.length` |
| 21 | When 2/2 members reached, send-invite form is hidden | Code-reviewed | PASS | conditional render on `memberCount < 2` |
| 22 | Root gate allows pre-household user to remain on `/(onboarding)/accept-invite` (allowlist set with both pareth and non-pareth pathname forms) | Code-reviewed | PASS | `PRE_HOUSEHOLD_ALLOWED.has(pathname)` early return |
| 23 | Post-accept routing — invalidate `['onboarding','status']` + `['household','me']` then `router.replace('/')`; root gate decides target (`/(main)` if categories ready, otherwise `/(onboarding)/categories`) | Code-reviewed | PASS | accept-invite never hard-routes |
| 24 | "Have an invite?" link on create-household routes to accept-invite (and inverse link on accept-invite) | Code-reviewed | PASS | both screens use `router.replace` between them |
| 25 | Sign-out at bottom of settings calls `useAuth().signOut` after Alert confirm | Code-reviewed | PASS | |
| 26 | Lookup preview is debounced (400 ms) and only fires when token length ≥ 8 | Code-reviewed | PASS | `setTimeout` cleanup on token change |
| 27 | TypeScript compilation — zero errors | Compile-verified | PASS | `npx tsc --noEmit` clean |

**Verdict:** GO — Phase 6 mobile is green at the API contract + code correctness + build health level.

**Notes / known limitations (deliberate, not blockers):**
- **No member-list endpoint on backend.** Mobile uses `GET /invites?status=accepted` to surface the second member's email. If a future household ever has multiple historical accepted invites, the Members section would list all of them; in v1 this can never happen because the cap is 2 (verified by `invite_verify.py` step 12b — second invite after acceptance returns 409 "Household is full").
- **No `/me` member endpoint.** Mobile shows the current user via `useAuth().user.email`; we never display the member's `display_name` in v1 (it is only set during onboarding and not editable).
- **Root gate change was required.** The pre-existing gate at [mobile/app/_layout.tsx:43-44](mobile/app/_layout.tsx#L43-L44) unconditionally redirected any session without a household to `/(onboarding)/create-household`, which would have made the new accept-invite screen structurally unreachable. The fix adds a `PRE_HOUSEHOLD_ALLOWED` set containing both parenthesised and unparenthesised pathname forms (`/(onboarding)/accept-invite` and `/onboarding/accept-invite`) so the allowlist works regardless of which form `usePathname()` emits in this Expo Router version.
- **No `expo-clipboard` dependency added.** The token banner uses `<Text selectable>` with a "Long-press to copy" hint — OS long-press copy works on both iOS and Android without a native dependency.
- **Lookup is debounced 400 ms** to avoid spamming `POST /invites/lookup` on every keystroke. Token must be ≥8 chars before lookup fires.

### Mobile hardening verification (2026-04-26)

**Scope:** Type-check, smoke regression, and code-review verification of the 14 hardening changes. Real-device walkthrough is required for keyboard / safe-area / pull-to-refresh / permission-denial / signed-URL-expiry / timeout / AppState-refetch / cache-clear scenarios — listed as D-rows below for the next person on a device.

**Method:** Three layers:
1. **TypeScript compile** — `npx tsc --noEmit` against `mobile/`.
2. **Backend smoke regression** — three `.smoke/*_verify.py` scripts re-run end-to-end. The hardening pass touches no backend code; this confirms shared environment + smoke fixtures still work.
3. **Code-reviewed** the 14 changes against the per-file diff.

| # | Item | Method | Result | Notes |
|---|------|--------|--------|-------|
| 1 | `api-client.ts` uses `fetchWithTimeout` for get/post/put/del/upload (15s `AbortController`) | Code-reviewed | PASS | `AbortError` → `ApiError(0, 'Network timeout')` |
| 2 | `handleResponse` short-circuits 204 / `content-length: 0` before `response.json()` | Code-reviewed | PASS | additive — JSON-returning paths untouched |
| 3 | `del()` delegates through `handleResponse<void>` so error bodies surface `detail` | Code-reviewed | PASS | parity with get/post/put |
| 4 | `lib/errorLog.ts` exports `logError` + `getRecentErrors`; ring buffer = 50; dev `console.error`; Sentry swap-point comment present | Code-reviewed | PASS | no Sentry/PostHog dep added |
| 5 | `_layout.tsx` QueryClient has `QueryCache` + `MutationCache` wired to `logError` | Code-reviewed | PASS | `refetchOnWindowFocus: true` set; `refetchOnReconnect` intentionally NOT set with documented reason |
| 6 | `_layout.tsx` bridges `AppState` change events to `focusManager.setEventListener` | Code-reviewed | PASS | guards `Platform.OS !== 'web'`; subscribed at module scope |
| 7 | `_layout.tsx` mounts `<ErrorBoundary>` around `<RootGate />` + `<Slot />` inside the providers | Code-reviewed | PASS | renders `ErrorView` with reset on render errors |
| 8 | `auth-context.tsx` `signOut` calls `queryClient.clear()` after Supabase signOut succeeds | Code-reviewed | PASS | uses `useQueryClient()` (provider runs inside QueryClientProvider) |
| 9 | `<KeyboardAwareScreen>` applied to all 8 listed screens (sign-in, sign-up, create-household, accept-invite, income/form, savings/rule-form, savings/manual, settings) | Code-reviewed | PASS | KAV behavior=`'padding'` on iOS; ScrollView `keyboardShouldPersistTaps="handled"` + `keyboardDismissMode="on-drag"`; safe-area bottom padding |
| 10 | `ErrorView` accepts new `error: unknown` prop with friendly `ApiError` mapping; existing `message` callers unbroken | Code-reviewed | PASS | additive — non-breaking |
| 11 | Email inputs (sign-in, sign-up, settings invite) have full attribute set: `autoComplete`, `textContentType`, `autoCorrect={false}`, `autoCapitalize="none"`, `keyboardType="email-address"` | Code-reviewed | PASS | accept-invite token field correctly skipped (not an email) |
| 12 | Money inputs use `keyboardType="decimal-pad"` (income/form, savings/rule-form percent + fixed, savings/manual, search amount min/max ×4); settings cutoff uses `number-pad` + `maxLength={2}` | Code-reviewed | PASS | settings cutoff already correct from Phase 6 |
| 13 | Receipt detail `<Image>` has `onError` → fallback view with "Tap to reload" → `invalidateQueries(['receipts', id])` | Code-reviewed | PASS | local `imageFailed` state resets on reload |
| 14 | Receipts upload permission denial (library + camera) shows `Alert.alert` with "Open Settings" calling `Linking.openSettings()` from `react-native` (not `expo-linking`) | Code-reviewed | PASS | both code paths patched |
| 15 | Dashboard ScrollView has `RefreshControl` with `refreshing={isRefetching}` and `onRefresh` invalidating `['dashboard']` + `['budgets']` | Code-reviewed | PASS | `useCallback` memoised |
| 16 | TypeScript compile — `npx tsc --noEmit` clean | Compile-verified | PASS | one initial KeyboardAwareScreen prop typing fixed (`React.ReactElement<RefreshControlProps>`) before clean |
| 17 | `.smoke/invite_verify.py` — full invite lifecycle (15 steps) | API-verified | PASS | VERDICT: GO |
| 18 | `.smoke/settings_verify.py` — household/settings/invite contract (12 steps) | API-verified | PASS | VERDICT: GO |
| 19 | `.smoke/search_verify.py` — receipts + transactions search contract (23 steps) | API-verified | PASS | VERDICT: GO |

**Device-walkthrough rows (must be done on at least one iOS + one Android device — not done in this pass):**
| # | Check |
|---|-------|
| D1 | Sign-in: email field shows `@`/`.com` keyboard + saved-email autocomplete |
| D2 | Income form: amount field shows decimal point; tap outside dismisses; Save reachable above keyboard |
| D3 | Savings rule form: percent + fixed both show decimal-pad |
| D4 | Settings cutoff: number-pad keyboard; can't type past 2 chars |
| D5 | Tab bar: bottom safe-area respected on iPhone home indicator + Android nav bar |
| D6 | Receipt upload: deny camera permission → "Open Settings" actually opens app's permission page |
| D7 | Receipt detail with manually-stale image URL → "Image unavailable. Tap to reload" → image restores after invalidate |
| D8 | Dashboard pull-to-refresh shows spinner; stops on refetch completion |
| D9 | Airplane mode + tap any action → after 15s a friendly "Connection problem" surfaces, not an indefinite spinner |
| D10 | Background app for 30s → return to foreground → confirm dashboard / current screen refetches (validates AppState→focusManager bridge) |
| D11 | Sign out then sign in as a different test user → no flash of previous user's data |
| D12 | (Synthetic) temporarily throw in dashboard render → ErrorBoundary catches; "Try again" restores |
| D13 | DELETE path: revoke a pending invite → 204 handled silently with no JSON-parse error in Metro logs; UI updates correctly |

**Verdict:** GO at the type-check + smoke + code-review level. Real-device verification (D1–D13) is the remaining gate before claiming end-to-end device readiness.

**Notes / known limitations (deliberate, not blockers):**
- **No Sentry / PostHog SDK added.** `lib/errorLog.ts` is the single chokepoint for that future swap (one diff, no scattered call sites). Adopting an observability provider requires a dev-build rebuild — separate decision.
- **`refetchOnReconnect` not enabled.** React Query's `onlineManager` is unwired in this repo; toggling the flag would need `@react-native-community/netinfo`, a new native module. Out of scope for this hardening pass.
- **Modal text inputs (savings approve, receipt category picker) not wrapped in `KeyboardAwareScreen`.** They use `Modal` + `Cancel` button; converting them is more disruptive than the value warrants. Promote to a follow-up only if device testing shows obstruction.
- **Other tabs not given pull-to-refresh.** Dashboard is the highest-leverage; other tabs (incomes, receipts, budget months) typically refetch via month-selector changes. Add per-tab if device testing surfaces demand.
- **Receipt upload not wrapped in `KeyboardAwareScreen`.** It's image-picker driven — the optional store-name / receipt-date inputs are short and don't sit near the bottom. Skip rather than add the wrapper preemptively.
- **`useCreateIncome`, `useUploadReceipt` invalidation audit.** Earlier exploration flagged these as missing dashboard / budget invalidation; a direct read of `mobile/src/api/incomes.ts:28-33` and `mobile/src/api/receipts.ts:48-50` confirmed they already invalidate correctly. No change required.
- **Post-hardening Android fix (verified on emulator):** the auth-screen "Sign up" / "Sign in" links were unresponsive. Two causes: (1) `<Link>` wrapping a nested `<Text>` is not recognised by `ScrollView`'s `keyboardShouldPersistTaps="handled"` and Android has flaky press-routing on nested Text — fixed by `<Link asChild>` + `<Pressable hitSlop={12}>` in [(auth)/sign-in.tsx](mobile/app/(auth)/sign-in.tsx) and [(auth)/sign-up.tsx](mobile/app/(auth)/sign-up.tsx); (2) `RootGate` in [_layout.tsx](mobile/app/_layout.tsx) unconditionally redirected `!session` users to sign-in, bouncing them back after navigation — fixed with an `AUTH_ALLOWED` set (`/sign-in`, `/sign-up`) consulted before redirecting. Inspecting the installed expo-router 6.0.23 source ([routeInfo.js:90-94](mobile/node_modules/expo-router/build/global-state/routeInfo.js#L90-L94)) confirmed `usePathname()` strips route-group segments unconditionally; the existing `PRE_HOUSEHOLD_ALLOWED` set was using stale parens'd forms that could never match and was corrected to `/create-household`, `/accept-invite` in the same edit.
- **Post-hardening Android fix #2 — tab bar hijacked by RootGate:** after a fully-onboarded user reached the dashboard, every bottom-tab tap appeared dead — visually a brief flicker, then back on Home. Cause: `RootGate`'s final branch in [_layout.tsx](mobile/app/_layout.tsx) unconditionally returned `<Redirect href="/(main)" />` for any signed-in, fully-onboarded user. Since the root layout re-renders on every route change, every tab navigation triggered the gate, which immediately redirected the group to its default screen (`index`/Home), undoing the tab tap. Fixed by adding a `REDIRECT_TO_MAIN_FROM` allowlist (`/sign-in`, `/sign-up`, `/create-household`, `/accept-invite`, `/categories`, `/initialize-month`) and only emitting the redirect when the user is currently on one of those routes; otherwise return `null` so `<Slot />` renders the tapped tab. The redirect is still required for the post-sign-in / post-onboarding hand-off — the auth context's `signIn` doesn't navigate.
- **Post-hardening fixes #3 + #4 — income edit (mobile + backend):** (a) mobile [(main)/income/form.tsx](mobile/app/(main)/income/form.tsx) crashed in edit mode with `amount.trim is not a function (it is undefined)` because `setAmount(existing.amount)` accepted whatever shape the cached object had; coerced to string on seed and routed all four `.trim()` call sites through a single `trimmedAmount` derived value. Same file also showed a false-positive "Late-Income Shift — Invalid Date" alert on every edit; the shift comparison was rewritten to compare YYYY-MM only, validate the response field with a regex, and build the label from parsed integers (cannot produce `Invalid Date`). (b) The underlying backend gap that fed the false positive: [backend/app/services/income_service.py](backend/app/services/income_service.py) `update_income` returned `txn_repo.update_transaction(...)` with no `budget_month` augmentation — the `transactions` table only stores `budget_month_id`. Mirrored the `create_income` augmentation by looking up the resolved budget month via `BudgetRepository.get_month_by_id(...)` after the update and setting `updated["budget_month"] = bm_row["month"]`. New mock-based tests in [backend/tests/test_services/test_income_service.py](backend/tests/test_services/test_income_service.py) pin the contract for no-shift, month-shifting, and category-change edits. Follow-up patch in the same service also added `category_name` to the update response (reuses the name already loaded by `get_transaction`'s JOIN, or the one fetched during validation when the category changes — zero extra DB reads), bringing create/update response parity for both fields the mobile client consumes.

---

## 14. Known constraints and caveats

### Product constraints
- one household per user
- exactly two members max in v1
- DKK only
- Danish receipt focus
- manual income only
- no bank account tracking
- no multi-household support

### Current onboarding behavior
- production households start with zero categories
- there is no category seeding in production
- users must create categories manually
- receipt categorization will return 422 until at least one active expense category exists

### Technical caveats
- no ORM
- AI calls are currently blocking
- no retry/backoff around AI calls yet
- `storage_path` is internal only and must not be exposed
- dashboard savings fields currently use `total_actual_savings` / `total_planned_savings` naming

---

## 15. Mobile app code map

### Routing (`mobile/app/`)
- `_layout.tsx` — root layout: providers + auth/onboarding routing gate (with `PRE_HOUSEHOLD_ALLOWED` allowlist so `/(onboarding)/accept-invite` is reachable for users without a household)
- `(auth)/` — sign-in, sign-up (Stack navigator)
- `(onboarding)/` — create-household, accept-invite, categories, initialize-month (Stack navigator)
- `(main)/_layout.tsx` — tab navigator (Home, Budget, Income, Savings, Receipts, Search, Settings) wrapped in MonthProvider
- `(main)/index.tsx` — dashboard
- `(main)/budget/_layout.tsx` — stack navigator for budget tab
- `(main)/budget/index.tsx` — budget month detail with editable lines
- `(main)/budget/months.tsx` — budget months list / selection
- `(main)/income/_layout.tsx` — stack navigator for income tab
- `(main)/income/index.tsx` — income list for selected month
- `(main)/income/form.tsx` — add/edit income entry
- `(main)/savings/_layout.tsx` — stack navigator for savings tab
- `(main)/savings/index.tsx` — savings hub: segmented Rules/Proposals + manual savings entry button + approve modal
- `(main)/savings/rule-form.tsx` — create/edit savings rule (immutable category + rule_type after creation)
- `(main)/savings/manual.tsx` — manual savings entry (not gated by budget month)
- `(main)/receipts/_layout.tsx` — stack navigator for receipts tab
- `(main)/receipts/index.tsx` — receipt list with status badges; header shows primary `Upload Receipt` button + secondary (ghost-variant) `+ Manual entry` button → `/(main)/receipts/manual`
- `(main)/receipts/upload.tsx` — receipt upload (camera/gallery + optional metadata)
- `(main)/receipts/manual.tsx` — manual expense entry (add-only for v1, parallels `savings/manual.tsx`): expense category picker, amount (`decimal-pad`), transaction date, optional description; Save → `router.back()`
- `(main)/receipts/[id].tsx` — receipt detail/review (status-driven: parse → categorize → review → post)
- `(main)/search/_layout.tsx` — stack navigator for search tab
- `(main)/search/index.tsx` — search/history screen: segmented Receipts/Transactions modes, always-visible filter section, infinite-query result list with "Load more"
- `(main)/settings/_layout.tsx` — stack navigator for settings tab
- `(main)/settings/index.tsx` — settings screen: household card, late-income preferences form, **Categories navigation row → `/(main)/settings/categories`**, members section, invites section (send/list/revoke), sign-out
- `(main)/settings/categories.tsx` — post-onboarding category management: three sections (Income / Expense / Savings), each row tap-to-rename inline (Save disabled when blank or unchanged), per-row Archive with confirm; **last-active-of-type archive blocked** with a clear "add another first" alert

### Foundation (`mobile/src/`)
- `lib/supabase.ts` — Supabase client singleton
- `lib/api-client.ts` — typed fetch wrapper with token injection + multipart upload; **15 s `AbortController` timeout on every method (get/post/put/del/upload), aborts mapped to `ApiError(0, 'Network timeout')`; `handleResponse` short-circuits 204 / `content-length: 0` before JSON parse; `del()` now delegates through `handleResponse` for unified error-body parsing**
- `lib/format.ts` — DKK formatting, date formatting
- `lib/constants.ts` — env var reads
- `lib/useDebouncedValue.ts` — generic debounce hook used by search merchant input
- `lib/errorLog.ts` — in-memory ring-buffer error logger (`logError(scope, error, context?)` + `getRecentErrors()`); single chokepoint with a labelled Sentry/PostHog swap-point comment
- `theme/tokens.ts` — colors, spacing, typography, border radii
- `types/api.ts` — TypeScript interfaces mirroring backend schemas
- `contexts/auth-context.tsx` — AuthProvider + useAuth hook; **`signOut` calls `queryClient.clear()` after Supabase sign-out succeeds to prevent prior-user data from flashing into a new session**
- `contexts/month-context.tsx` — MonthProvider + useSelectedMonth hook (shared month state)

### API hooks (`mobile/src/api/`)
- `onboarding.ts` — `useOnboardingStatus`
- `households.ts` — `useCreateHousehold`, `useHousehold`
- `categories.ts` — `useCategories`, `useCreateCategory`, `useUpdateCategory` (rename), `useArchiveCategory` (soft-archive); rename + archive invalidate the 8-key set that carries denormalised `category_name` (`['categories']`, `['budgets', 'month']`, `['dashboard']`, `['incomes']`, `['savings', 'rules']`, `['receipts']`, `['receipt-review']`, `['search']`); archive additionally invalidates `['onboarding', 'status']` defensively
- `budgets.ts` — `useBudgetMonths`, `useBudgetMonth`, `useInitializeMonth`, `useUpsertBudgetLine`
- `dashboard.ts` — `useDashboardSummary`
- `incomes.ts` — `useIncomes`, `useCreateIncome`, `useUpdateIncome`, `useDeleteIncome`
- `expenses.ts` — `useCreateExpense` (v1 add-only); invalidates `['budgets', 'month']` + `['dashboard']` + `['search']` (the three surfaces where a new manual expense becomes visible). Backend supports full CRUD; update/delete hooks deferred until a manual-expenses list view is added.
- `receipts.ts` — `useReceipts`, `useReceipt`, `useReviewPayload`, `useUploadReceipt`, `useParseReceipt`, `useCategorizeReceipt`, `useUpdateReceiptItem`, `useConfirmReceipt`
- `savings.ts` — `useSavingsRules`, `useSavingsProposals`, `useCreateSavingsRule`, `useUpdateSavingsRule`, `useGenerateProposals`, `useApproveProposal`, `useRejectProposal`, `useCreateManualSavings`
- `search.ts` — `useSearchReceipts`, `useSearchTransactions` (both `useInfiniteQuery`, page size 50)
- `settings.ts` — `useHouseholdSettings`, `useUpdateHouseholdSettings` (invalidates `['settings']` + `['budgets', 'month']` + `['dashboard']`)
- `invites.ts` — `useInvites`, `useCreateInvite`, `useRevokeInvite`, `useLookupInvite`, `useAcceptInvite` (accept invalidates `['onboarding','status']` + `['household','me']` + `['invites']`)

### UI components (`mobile/src/components/`)
- `MonthSelector.tsx` — shared month navigation arrows + label
- `ErrorBoundary.tsx` — class-component error boundary mounted in `_layout.tsx` around `<RootGate />` and `<Slot />`; logs to `errorLog` and renders `ErrorView` with reset
- `KeyboardAwareScreen.tsx` — shared `KeyboardAvoidingView` + `ScrollView` wrapper (`keyboardShouldPersistTaps="handled"`, `keyboardDismissMode="on-drag"`, safe-area bottom padding); applied to all 8 form-heavy screens
- `ui/` — Button, TextInput, Card, LoadingSpinner, EmptyState, ErrorView (now accepts `error: unknown` and maps `ApiError` → friendly text for status 0/401/5xx; legacy `message` prop still works), AmountDisplay

---

## 16. Recommended next implementation steps

The v1 mobile feature set is now complete (Phases 1–6), the post-v1 hardening pass (2026-04-26) has shipped foundation/UX/targeted polish, post-onboarding category management is in place (Settings → Categories: add / rename / archive, with last-active-of-type guard; manually verified on Android), and manual expense entry is in place under the Receipts tab (secondary "+ Manual entry" button → add-only form; backend exposes full CRUD at `/api/v1/expenses`; manually verified on Android). Remaining work is non-feature:

1. **Observability provider** — `mobile/src/lib/errorLog.ts` is the single chokepoint and labelled swap-point. Choose Sentry or PostHog, install the native SDK (requires a dev-build rebuild), and wire `captureException` inside `logError`. Until then, the in-memory ring buffer + `__DEV__` console output is the only surface.
2. **Real-device walkthrough (D1–D14)** — the device verification table in §13 is still pending. CLI verification (tsc + smoke) is GREEN, but keyboard overlap, pull-to-refresh, AppState→focusManager refetch, image-`onError` reload, permission `Linking.openSettings`, and `signOut` cache-clear must each be exercised on physical iOS + Android before shipping. Reconnect refetch is intentionally out of scope (no `@react-native-community/netinfo`).
3. **CI** — wire `npx tsc --noEmit` and the `.smoke/*_verify.py` scripts into a PR check so regressions are caught automatically.
4. **Native delivery** — TestFlight + Play Internal Testing build pipelines.

---

## 17. Quick orientation for future work

When making changes:
- use `CLAUDE.md` for rules and invariants
- use this file for current implementation state
- check whether a feature is truly implemented or only modeled in schema/stubs
- update this file when implemented scope changes materially

Current state:
- backend is fully implemented across all v1 domains (budgets, receipts, savings, search, invites)
- real Postgres integration tests cover the highest-risk transactional flows (29 tests)
- mobile Phase 1 delivers the first usable vertical slice: sign-up through empty dashboard
- mobile Phase 2 adds budget month management and income CRUD
- mobile Phase 3 adds the full receipts flow: upload, parse, categorize, review, and post
- mobile Phase 4 adds the full savings flow: rule CRUD, proposal generate/approve/reject, manual savings entry
- mobile Phase 5 adds the search/history slice: receipts + transactions search with structured filters, infinite-query pagination, and write-side cache invalidation
- mobile Phase 6 adds the settings + invite management slice: household card, late-income preferences, member visibility, send/list/revoke invites, accept-invite onboarding screen, sign-out — completing the v1 mobile feature set
- post-v1 mobile hardening (2026-04-26): foundation (15 s fetch timeout, 204-safe response handling, global QueryCache/MutationCache error wiring, AppState→focusManager bridge, ErrorBoundary, sign-out cache clear, errorLog ring buffer), UX (KeyboardAwareScreen across 8 screens, friendly ErrorView, email/password autocomplete, decimal-pad/number-pad), targeted (image `onError` + reload, `Linking.openSettings` on permission deny, dashboard pull-to-refresh)
- mobile is hardened for real-device use; observability surface is in place but not wired to a third-party provider yet — `mobile/src/lib/errorLog.ts` is the single swap-point when Sentry/PostHog is chosen
- post-onboarding category management shipped under Settings → Categories (add / rename / archive; last-active-of-type archive blocked); rename + archive invalidate every cache that carries denormalised `category_name`
- manual expense entry shipped under the Receipts tab (secondary "+ Manual entry" button → `(main)/receipts/manual.tsx`); v1 mobile is add-only, backend exposes full CRUD at `/api/v1/expenses` (`expense_service.py` mirrors `income_service` minus late-shift; writes `source="manual_expense"`)
- v1 mobile feature set is complete; remaining work is the device walkthrough (D1–D14), an observability provider decision, CI, and native delivery

---

## 18. Remote server and deployment preparation

_Status as of 2026-06-08 — application not yet deployed_

### Server

| Property | Value |
|---|---|
| Provider | Hetzner Cloud |
| Location | Falkenstein, EU-central |
| Type | CPX22 — 2 vCPU, 4 GB RAM, 80 GB disk, 20 TB traffic |
| OS | Ubuntu 24.04 LTS |
| Public IPv4 | 168.119.51.12 |
| Public IPv6 | 2a01:4f8:c012:f37d::1 |
| Hostname | ubuntu-4gb-fsn1-2 (default, not yet changed) |

### Completed steps

**Provisioning and verification**
- server created on Hetzner Cloud
- hostname, IP configuration (`ip a`), and OS release (`/etc/os-release`) confirmed on first login
- OS confirmed as Ubuntu 24.04 LTS

**Package update**
- `apt update && apt upgrade -y` applied; server remained reachable after update

**Admin user setup**
- non-root user `andreas` created, added to `sudo` group
- SSH `authorized_keys` copied from root to `/home/andreas/.ssh/authorized_keys`
- permissions: `/home/andreas/.ssh` → 700, `authorized_keys` → 600
- SSH login as `andreas` verified; `sudo whoami` returns `root`

**SSH key access**
- local ed25519 key pair created on Windows
- public key registered with Hetzner Cloud at provisioning time
- private key remains local only, protected with a passphrase
- initial root login confirmed; subsequent logins use `andreas`

**SSH hardening**
`/etc/ssh/sshd_config.d/99-deploy-hardening.conf` created with:

```
PermitRootLogin no
PasswordAuthentication no
PubkeyAuthentication yes
KbdInteractiveAuthentication no
```

Config validated with `sudo sshd -t` before restart. Post-restart session as `andreas` confirmed working.

Current SSH state:
- key-based auth: enabled
- non-root `andreas` login: working
- `sudo` for `andreas`: working
- direct root SSH: disabled
- password auth: disabled

### Current deployment status

The application is not deployed. The server is at OS baseline only.

Not yet present on the server:
- no Docker or docker-compose
- no NGINX
- no DNS configuration
- no HTTPS/TLS
- no application code
- no GitHub repository connected or cloned

### Pending deployment work

1. verify `.gitignore` coverage before creating the GitHub repository — confirm `.env`, `mobile/.env`, private keys, `node_modules/`, `.venv/`, `.expo/`, build artifacts, and cache directories are excluded
2. create and push the GitHub repository
3. build a Dockerfile for the backend
4. compose the backend container with any required services
5. configure NGINX as a reverse proxy
6. point DNS to `168.119.51.12` and configure HTTPS