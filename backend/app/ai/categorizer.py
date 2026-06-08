"""Anthropic implementation of receipt item categorization."""

import json
import re
from typing import Any, Optional

from app.ai.base import (
    CategorizationResult,
    CategorizerBase,
    CategorySuggestion,
    ItemToCategorize,
)


PROMPT_TEMPLATE = """You are a receipt categorizer for a household budget app.

The receipt line items are in Danish. You will be given a list of numbered line
items and a list of numbered valid expense categories. Pick the single best
category for each item.

Rules:
- Return ONLY a fenced ```json code block with your result. No explanation.
- For each item, emit an object with:
    - item_index: the item's 1-based number (integer)
    - category_index: the category's 1-based number (integer), or null if
      no category is a reasonable match
    - confidence: a float between 0.0 and 1.0 reflecting how sure you are
      (or null if you did not suggest anything)
- Return null for category_index rather than guessing.
- You may only use category numbers from the provided list.
- Category names may be in Danish or English; match semantically.

Items:
{items_block}

Valid categories:
{categories_block}

Respond with JSON in this exact shape:
```json
{{
  "suggestions": [
    {{"item_index": 1, "category_index": 1, "confidence": 0.95}},
    {{"item_index": 2, "category_index": 2, "confidence": 0.88}},
    {{"item_index": 3, "category_index": null, "confidence": null}}
  ]
}}
```
"""


class AnthropicCategorizer(CategorizerBase):
    """Suggest categories for receipt line items using Anthropic Claude."""

    def __init__(self, api_key: str, model: str, max_tokens: int):
        # Lazy import so the module can be imported in test environments
        # without the anthropic package installed.
        from anthropic import AsyncAnthropic

        self._client = AsyncAnthropic(api_key=api_key)
        self._model = model
        self._max_tokens = max_tokens

    async def categorize(
        self,
        items: list[ItemToCategorize],
        categories: list[CategorizerBase.CategoryOption],
    ) -> CategorizationResult:
        if not items or not categories:
            return CategorizationResult(suggestions=[])

        prompt = PROMPT_TEMPLATE.format(
            items_block=_format_items(items),
            categories_block=_format_categories(categories),
        )

        message = await self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            messages=[{"role": "user", "content": [{"type": "text", "text": prompt}]}],
        )

        response_text = "".join(
            block.text
            for block in message.content
            if getattr(block, "type", "") == "text"
        )
        payload = _extract_json(response_text)
        return _build_suggestions_from_payload(payload, items, categories)


# ── Pure helpers (module-level, independently testable) ──


def _format_items(items: list[ItemToCategorize]) -> str:
    return "\n".join(
        f"[{i}] {item.description} | total={item.total_price}"
        for i, item in enumerate(items, start=1)
    )


def _format_categories(
    categories: list[CategorizerBase.CategoryOption],
) -> str:
    return "\n".join(f"[{i}] {cat.name}" for i, cat in enumerate(categories, start=1))


def _extract_json(text: str) -> dict[str, Any]:
    """Extract a JSON payload from a fenced ```json block.

    Falls back to parsing the whole text as JSON if no fenced block is found.
    Raises json.JSONDecodeError / ValueError on malformed input — callers
    convert these to AppError.
    """
    match = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        return json.loads(match.group(1))
    return json.loads(text.strip())


def _to_float_confidence(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _build_suggestions_from_payload(
    payload: dict[str, Any],
    items: list[ItemToCategorize],
    categories: list[CategorizerBase.CategoryOption],
) -> CategorizationResult:
    """Convert a validated JSON payload into a CategorizationResult.

    Maps 1-based item_index / category_index back to actual UUIDs using the
    ordered input lists. Suggestions with an out-of-range or wrong-type index
    are dropped. category_index=null is kept and passed to the service as "no
    suggestion", which will mark the item requires_review.
    """
    raw_suggestions = payload.get("suggestions") or []
    suggestions: list[CategorySuggestion] = []
    for raw in raw_suggestions:
        if not isinstance(raw, dict):
            continue

        item_index = raw.get("item_index")
        if not isinstance(item_index, int) or not (1 <= item_index <= len(items)):
            continue
        receipt_item_id = items[item_index - 1].id

        cat_index = raw.get("category_index")
        if cat_index is None:
            suggested_category_id = None
        elif isinstance(cat_index, int) and 1 <= cat_index <= len(categories):
            suggested_category_id = categories[cat_index - 1].id
        else:
            continue  # out-of-range or wrong type; drop

        suggestions.append(
            CategorySuggestion(
                receipt_item_id=receipt_item_id,
                suggested_category_id=suggested_category_id,
                confidence=_to_float_confidence(raw.get("confidence")),
            )
        )
    return CategorizationResult(suggestions=suggestions)
