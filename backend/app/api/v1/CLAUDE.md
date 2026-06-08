# API Router Rules

## Scope
These rules apply to `backend/app/api/v1/` routers only.

## Router Responsibilities
Routers must stay thin.

Each router should:
- accept request input
- apply the correct auth dependency
- call the service layer
- return the schema response

Routers must not:
- contain business logic
- perform SQL
- manage transactions
- duplicate service validation logic
- implement deterministic financial calculations

## Auth Dependency Rules
Use `get_auth_context` for all normal household-scoped endpoints.

Use `get_user_context` only for:
- `POST /api/v1/households`
- `GET /api/v1/onboarding/status`
- `POST /api/v1/invites/lookup`
- `POST /api/v1/invites/accept`

Do not use `get_user_context` on any other route.

## Endpoint Behavior Rules
- Household-scoped routes must reject users without membership.
- Receipt posting must never bypass review.
- Receipt-derived transactions must never be created from AI output alone.
- Categorization must return 422 when the household has zero active expense categories.
- Dashboard requests with no budget month should return deterministic empty responses, not 404.

## Response Rules
- Prefer schema-driven response shapes.
- Keep response formatting consistent with existing endpoints.
- Do not expose internal storage paths.
- Do not expose hashed invite tokens.
- Do not expose raw invite tokens except in the create-invite response.

## Error Mapping
Use existing domain/service exception patterns.
Do not invent route-local special cases when the service layer should own the rule.

Map behavior consistently:
- 401 for invalid/missing auth
- 403 for authenticated but forbidden access
- 404 for missing resources
- 409 for state conflicts / idempotency conflicts
- 422 for validation failures and business-rule rejections

## Route Design
- Follow existing route naming and grouping conventions.
- Keep new endpoints under the correct domain router.
- Avoid spreading one workflow across unrelated routers.