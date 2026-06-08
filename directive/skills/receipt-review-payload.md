# Skill: Receipt Review Payload Generation

## Purpose
Build the review payload for a parsed+categorized receipt, ready for user review.

## Input
- Receipt record (with status = ocr_complete or reviewed)
- Receipt items with AI suggestions

## Output
- Receipt metadata (store, date, total)
- List of items, each with:
  - description, total_price
  - suggested_category_id + name
  - user_confirmed_category_id + name (if already reviewed)
  - confidence score
  - requires_review flag
  - is_excluded flag
- Validation warnings (e.g., item total != receipt total)

## Rules
- All items with requires_review=True must be resolved before confirmation
- User can override any AI suggestion
- User can exclude items (returns, non-budget items)
- Validate receipt total against sum of item prices (tolerance: 1.00 DKK)
- Nothing is posted until the user confirms
