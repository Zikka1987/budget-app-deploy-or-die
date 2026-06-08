# Skill: Receipt Categorization

## Purpose
Suggest expense categories for parsed receipt line items using AI.

## Input
- List of ParsedLineItem (from receipt parsing)
- List of active expense categories (id, name) for the household

## Output (CategorizationResult)
- Per item: suggested_category_id, confidence (0.0-1.0), requires_review (bool)

## Rules
- AI may only suggest from currently active expense categories
- Confidence threshold for auto-accept: >= 0.85 (configurable)
- Items below threshold: requires_review = True
- Python sets requires_review based on confidence; AI does not decide this
- Category aliases should be included in the prompt context to help AI match historical names
- AI returns JSON; Python validates category IDs exist before saving

## Provider Interface
Implement `CategorizerBase.categorize(items, categories) -> CategorizationResult`
