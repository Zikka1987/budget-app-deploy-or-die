"""Anthropic implementation of receipt parsing."""

import base64
import json
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from app.ai.base import ParsedLineItem, ParsedReceipt, ReceiptParserBase


PROMPT = """You are a receipt parser. The receipt is in Danish.

Return TWO things in your response, in this exact order:

1. A plain-text transcription of the receipt, preserving line breaks as they
   appear on the receipt. This goes between `<raw_text>` and `</raw_text>` tags.
   Transcribe exactly what is printed - do NOT summarize, reformat, or omit
   subtotals/VAT lines/store metadata. This is the canonical OCR output used
   for search and audit.

2. A structured JSON block inside a ```json code fence with these fields:
   - store_name (string or null)
   - receipt_date (ISO YYYY-MM-DD or null)
   - total_amount (string decimal like "123.45" or null)
   - confidence (float 0.0-1.0, your overall parse confidence)
   - items: array of {description, total_price (string decimal),
     quantity (string decimal or null), unit_price (string decimal or null),
     line_number (int), confidence (float 0.0-1.0)}

Rules for the JSON structured output:
- Use Danish currency conventions (comma as decimal separator on receipts;
  normalize to dot in output).
- INCLUDE individual item discount lines as items with a negative total_price.
  These are RABAT or discount lines that immediately follow a specific product
  line on the receipt (e.g. "RABAT -7,00" directly after "JORDBÆR 25,00").
- EXCLUDE the following — they must NOT appear in items, only in raw_text:
    - RABAT I ALT (total discount summary)
    - TOTAL RABAT or similar aggregate discount lines
    - AT BETALE / total-to-pay lines
    - VISA / Mastercard / Dankort / payment method lines
    - MOMS / VAT subtotals
    - Any other subtotal or running-total line
- If a field is unreadable or missing, return null.
- Return ONLY the two sections described above, no other explanation text.
"""


class AnthropicReceiptParser(ReceiptParserBase):
    """Parse receipt images using Anthropic's Claude vision model."""

    def __init__(self, api_key: str, model: str, max_tokens: int):
        # Import lazily so the module can be imported without the anthropic
        # package being installed (e.g. in pure-function tests).
        from anthropic import AsyncAnthropic

        self._client = AsyncAnthropic(api_key=api_key)
        self._model = model
        self._max_tokens = max_tokens

    async def parse(self, image_bytes: bytes, mime_type: str) -> ParsedReceipt:
        encoded = base64.standard_b64encode(image_bytes).decode("ascii")

        if mime_type == "application/pdf":
            content_block: dict[str, Any] = {
                "type": "document",
                "source": {
                    "type": "base64",
                    "media_type": mime_type,
                    "data": encoded,
                },
            }
        else:
            content_block = {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": mime_type,
                    "data": encoded,
                },
            }

        message = await self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            messages=[
                {
                    "role": "user",
                    "content": [content_block, {"type": "text", "text": PROMPT}],
                }
            ],
        )

        response_text = "".join(
            block.text
            for block in message.content
            if getattr(block, "type", "") == "text"
        )
        raw_text = _extract_raw_text(response_text)
        payload = _extract_json(response_text)
        return _parsed_receipt_from_payload(payload, raw_text)


# ── Pure helpers (module-level, independently testable) ──


def _extract_raw_text(response: str) -> Optional[str]:
    """Extract the plain receipt transcription from between <raw_text> tags.

    This is the actual printed receipt text, NOT the model's response wrapper
    or the JSON block. Stored in receipts.ocr_raw_text for search and audit.
    Returns None if the tags are missing (fallback behavior - the receipt
    will still be marked ocr_complete since ocr_raw_text is nullable).
    """
    match = re.search(r"<raw_text>\s*(.*?)\s*</raw_text>", response, re.DOTALL)
    if not match:
        return None
    return match.group(1).strip()


def _extract_json(text: str) -> dict[str, Any]:
    """Extract the JSON payload from the model response.

    Looks for a ```json code fence first, falls back to parsing the entire
    text as JSON. Raises ValueError if nothing valid is found.
    """
    match = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        return json.loads(match.group(1))
    return json.loads(text.strip())


def _to_decimal(value: Any) -> Optional[Decimal]:
    """Convert a string/number to Decimal, tolerating Danish comma decimals."""
    if value is None:
        return None
    try:
        return Decimal(str(value).replace(",", "."))
    except (InvalidOperation, ValueError):
        return None


def _to_date(value: Any) -> Optional[date]:
    """Convert an ISO date string to date, tolerating missing/malformed input."""
    if value is None:
        return None
    try:
        return date.fromisoformat(str(value))
    except (ValueError, TypeError):
        return None


def _to_confidence(value: Any) -> Optional[float]:
    """Convert a numeric confidence to float, tolerating missing/malformed input."""
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _parsed_receipt_from_payload(
    payload: dict[str, Any], raw_text: Optional[str]
) -> ParsedReceipt:
    """Build a ParsedReceipt from the JSON payload returned by Claude.

    Tolerates missing or malformed fields - the caller will still mark the
    receipt ocr_complete and the user can fix things in review.
    """
    items_raw = payload.get("items") or []
    items: list[ParsedLineItem] = []
    for i, item in enumerate(items_raw):
        if not isinstance(item, dict):
            continue
        total = _to_decimal(item.get("total_price"))
        description = item.get("description")
        if total is None or not description:
            continue  # skip unusable items
        line_number = item.get("line_number")
        items.append(
            ParsedLineItem(
                description=str(description).strip(),
                total_price=total,
                quantity=_to_decimal(item.get("quantity")),
                unit_price=_to_decimal(item.get("unit_price")),
                line_number=line_number if isinstance(line_number, int) else i + 1,
                confidence=_to_confidence(item.get("confidence")),
            )
        )

    return ParsedReceipt(
        store_name=payload.get("store_name") or None,
        receipt_date=_to_date(payload.get("receipt_date")),
        total_amount=_to_decimal(payload.get("total_amount")),
        items=items,
        raw_text=raw_text,
        confidence=_to_confidence(payload.get("confidence")),
    )
