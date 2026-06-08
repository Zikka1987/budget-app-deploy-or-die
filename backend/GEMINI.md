# Backend Rules

## Scope
These rules apply to backend code only.

## Backend Architecture
- Use FastAPI with thin routers, heavy services, thin repositories, and pure rule modules.
- Do not introduce an ORM.
- Use `asyncpg` directly for all DB access.
- Keep deterministic financial logic out of routers and out of AI providers.
- Rule modules must be pure functions with no DB access.

## Layer Responsibilities
### Routers
Routers should only:
- parse request input
- apply auth dependency
- call a service
- return the response

Routers must not:
- contain business logic
- run SQL
- perform multi-step state transitions

### Services
Services own:
- business rules orchestration
- transaction boundaries
- repository coordination
- deterministic validation
- idempotency behavior
- mapping domain errors to API-safe exceptions

### Repositories
Repositories should:
- be thin wrappers around parameterized SQL
- accept a connection or transaction object
- avoid embedding business policy
- avoid cross-layer orchestration

### Rules
Rule modules should:
- be deterministic
- be fully testable without DB access
- contain calculation and validation logic only

## Auth Rules
Only two auth dependencies exist:
- `get_auth_context`
- `get_user_context`

Use:
- `get_auth_context` for all normal household-scoped backend endpoints
- `get_user_context` only for the narrow pre-household corridor

Do not add a third auth dependency without a narrow, explicit reason.

JWT rules:
- verify with JWKS
- require normalized `email`
- do not reintroduce shared-secret JWT verification

## Transaction Rules
All multi-step financial writes must be atomic.

This includes:
- household creation
- receipt parse persistence
- receipt suggestion refresh
- receipt confirm/post
- savings posting
- invite acceptance

If a flow can leave financial or membership state half-written, it must be wrapped in a DB transaction.

## Idempotency Rules
Use `transaction_groups.idempotency_key` to prevent duplicate posting.

Required keys:
- receipt posting: `receipt:{receipt_id}`
- savings proposal posting: `savings_proposal:{proposal_id}`
- manual income: `manual_income:{uuid}`

Do not add posting flows without an idempotency strategy.

## Receipt Rules
- Never create transactions from AI suggestions directly.
- Posted receipt transactions must come from `user_confirmed_category_id`.
- `requires_review` is determined by Python, not AI.
- Re-categorization is a full refresh.
- Re-parse is full replace with preservation on failure from `ocr_complete`.
- Receipt confirm/post must be atomic.

## Invite Rules
- v1 households are capped at 2 members total.
- This cap is enforced at 3 layers and they must stay aligned:
  1. DB: at most one pending invite per household
  2. `create_invite`: reject when household member count is already 2+
  3. `accept_invite`: re-check member count inside the locked accept transaction before insert
- Do not relax only one layer of the cap.
- Raw invite tokens must never be stored.
- Store only SHA-256 hashes of invite tokens.
- Invite acceptance must be atomic.
- `UNIQUE(user_id)` on `household_members` remains in force.

## Data Rules
- Categories are stable UUID entities.
- Renames preserve history and create aliases.
- Categories with financial history are archived, not hard-deleted.
- Amounts are positive; transaction `type` determines direction.
- `budget_months.month` is always the first day of the month.

## Testing Expectations
Add or update tests when changing:
- auth behavior
- transaction flows
- receipt rules
- invite rules
- dashboard math
- category rename behavior
- date/budget-month logic

Prefer:
- pure rule tests for deterministic logic
- service tests for orchestration
- router tests for auth wiring and response shape