"""Pure functions for receipt processing. No DB access."""

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Optional
from uuid import UUID

if TYPE_CHECKING:
    from app.ai.base import (
        CategorySuggestion,
        ItemToCategorize,
        ParsedLineItem,
        ParsedReceipt,
    )


ALLOWED_MIME_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "application/pdf",
}

MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB (matches storage bucket limit)

EXTENSION_FOR_MIME = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "application/pdf": "pdf",
}


def validate_upload_file(mime_type: str, size_bytes: int) -> str:
    """Validate an uploaded file.

    Returns the canonical file extension if the file is acceptable.
    Raises ValueError if the MIME type is not allowed, the file is empty,
    or the file exceeds the size limit.
    """
    if mime_type not in ALLOWED_MIME_TYPES:
        raise ValueError(f"Unsupported file type: {mime_type}")
    if size_bytes <= 0:
        raise ValueError("File is empty")
    if size_bytes > MAX_FILE_SIZE_BYTES:
        raise ValueError(f"File exceeds {MAX_FILE_SIZE_BYTES} byte limit")
    return EXTENSION_FOR_MIME[mime_type]


def build_storage_path(household_id: UUID, receipt_id: UUID, extension: str) -> str:
    """Build the storage path for a receipt image.

    Format: {household_id}/{receipt_id}/original.{extension}
    This matches the RLS policy on storage.objects which checks the first
    folder segment against the current user's household_id.
    """
    return f"{household_id}/{receipt_id}/original.{extension}"


@dataclass
class GroupedExpense:
    """Line items grouped by confirmed category for transaction creation."""
    category_id: UUID
    total_amount: Decimal
    item_descriptions: list[str]


def group_items_by_category(
    items: list[dict],
) -> list[GroupedExpense]:
    """Group confirmed receipt items by user_confirmed_category_id.

    Each item dict must have: user_confirmed_category_id, total_price, description, is_excluded.
    Excluded items are skipped. Items with the same category are summed.
    """
    groups: dict[UUID, GroupedExpense] = {}
    for item in items:
        if item.get("is_excluded", False):
            continue
        cat_id = item["user_confirmed_category_id"]
        if cat_id is None:
            continue
        if cat_id not in groups:
            groups[cat_id] = GroupedExpense(
                category_id=cat_id,
                total_amount=Decimal("0"),
                item_descriptions=[],
            )
        groups[cat_id].total_amount += Decimal(str(item["total_price"]))
        groups[cat_id].item_descriptions.append(item["description"])
    return list(groups.values())


def validate_receipt_total(
    item_total: Decimal,
    receipt_total: Decimal,
    tolerance: Decimal = Decimal("1.00"),
) -> bool:
    """Check if the sum of item prices matches the receipt total within tolerance."""
    return abs(item_total - receipt_total) <= tolerance


def detect_duplicate(
    store_name: str | None,
    receipt_date: str | None,
    total_amount: Decimal | None,
    existing_receipts: list[dict],
) -> list[dict]:
    """Find potential duplicate receipts based on store, date, and amount.

    Returns list of existing receipts that match all three fields.
    """
    if not all([store_name, receipt_date, total_amount]):
        return []
    return [
        r for r in existing_receipts
        if (
            r.get("store_name") == store_name
            and str(r.get("receipt_date")) == str(receipt_date)
            and Decimal(str(r.get("total_amount", 0))) == total_amount
        )
    ]


def parsed_receipt_to_item_dicts(parsed: "ParsedReceipt") -> list[dict]:
    """Convert ParsedReceipt.items into dicts ready for receipt_items INSERT.

    For this phase (OCR only, no categorization):
    - suggested_category_id: None (categorization is a separate phase)
    - user_confirmed_category_id: None (review is a separate phase)
    - requires_review: True (user must review before posting)
    - is_excluded: False
    - confidence: carried through from ParsedLineItem.confidence (may be None)
    """
    return [
        {
            "line_number": item.line_number,
            "description": item.description,
            "quantity": item.quantity,
            "unit_price": item.unit_price,
            "total_price": item.total_price,
            "suggested_category_id": None,
            "confidence": item.confidence,
            "requires_review": True,
            "user_confirmed_category_id": None,
            "is_excluded": False,
        }
        for item in parsed.items
    ]


_SUMMARY_DISCOUNT_PHRASES = (
    "rabat i alt",
    "total rabat",
    "total discount",
    "discount total",
)

_DISCOUNT_KEYWORDS = ("rabat", "discount", "tilbud")


def _is_summary_discount(description: str) -> bool:
    """True if description contains a known summary/aggregate discount phrase.

    Uses substring matching so trailing amounts or punctuation (e.g.
    "RABAT I ALT 41.80", "RABAT I ALT:") are caught. Whitespace is
    normalized so "RABAT   I   ALT" also matches. Case-insensitive.
    Lines matched here are dropped entirely from receipt_items output.
    """
    normalized = " ".join(description.strip().lower().split())
    return any(phrase in normalized for phrase in _SUMMARY_DISCOUNT_PHRASES)


def _is_item_level_discount(item: "ParsedLineItem") -> bool:
    """True if item looks like an item-level discount eligible for folding.

    All three conditions must hold:
    - total_price is negative
    - description is NOT a summary discount phrase
    - description contains at least one discount keyword
    """
    if item.total_price >= 0:
        return False
    if _is_summary_discount(item.description):
        return False
    desc_lower = item.description.strip().lower()
    return any(kw in desc_lower for kw in _DISCOUNT_KEYWORDS)


def fold_adjacent_discounts(items: list["ParsedLineItem"]) -> list["ParsedLineItem"]:
    """Fold item-level discount lines into their preceding product item.

    Processes items in extracted order (no re-sorting). Matching rule:
    - Positive product item: emitted, becomes the current anchor.
    - Foldable discount (_is_item_level_discount): if an anchor exists, its
      total_price is reduced by the discount amount and the discount row is
      removed. Consecutive foldable discounts fold into the same anchor.
      If no anchor exists, the discount is kept as-is for user review.
    - Summary/meta discount (_is_summary_discount): dropped entirely.
      Resets the anchor so subsequent discounts are not incorrectly attributed.
    - Non-foldable negative (negative price, no discount keyword): emitted
      as-is. Resets the anchor.

    Folded rows and dropped summary rows are never written to receipt_items.
    The audit trail is ocr_raw_text and the receipt image.
    """
    import dataclasses

    result: list["ParsedLineItem"] = []
    anchor_idx: Optional[int] = None

    for item in items:
        if _is_summary_discount(item.description):
            anchor_idx = None
        elif _is_item_level_discount(item):
            if anchor_idx is not None:
                anchor = result[anchor_idx]
                result[anchor_idx] = dataclasses.replace(
                    anchor,
                    total_price=anchor.total_price + item.total_price,
                )
            else:
                result.append(item)
        elif item.total_price >= 0:
            result.append(item)
            anchor_idx = len(result) - 1
        else:
            result.append(item)
            anchor_idx = None

    return result


def build_duplicate_candidates(
    parsed: "ParsedReceipt",
    existing_receipts: list[dict],
) -> list[dict]:
    """Return potential duplicates matching a ParsedReceipt.

    Thin wrapper around detect_duplicate() that accepts a ParsedReceipt
    directly, converting receipt_date to ISO string form.

    The caller is responsible for excluding the receipt currently being
    parsed from existing_receipts.
    """
    return detect_duplicate(
        store_name=parsed.store_name,
        receipt_date=parsed.receipt_date.isoformat() if parsed.receipt_date else None,
        total_amount=parsed.total_amount,
        existing_receipts=existing_receipts,
    )


# ── Review / confirm rules (pure, no DB / no AI) ──


def determine_requires_review_after_edit(
    user_confirmed_category_id: Optional[UUID],
    is_excluded: bool,
) -> bool:
    """Compute requires_review after a user edit on a receipt item.

    Distinct from determine_requires_review() which operates on AI
    suggestion confidence. This function operates on the final item
    state after a user action (setting a confirmed category or toggling
    exclusion).

    Rules:
    - Excluded items don't need attention → False
    - Items with a confirmed category are resolved → False
    - Otherwise the item still needs user action → True
    """
    if is_excluded:
        return False
    if user_confirmed_category_id is not None:
        return False
    return True


def validate_items_ready_for_confirm(items: list[dict]) -> list[str]:
    """Check that every non-excluded item has a confirmed category.

    Returns a list of error strings (one per invalid item). Empty list
    means all items are ready for confirmation.
    """
    errors: list[str] = []
    for item in items:
        if item.get("is_excluded", False):
            continue
        if item.get("user_confirmed_category_id") is None:
            desc = item.get("description", "unknown")
            line = item.get("line_number")
            if line is not None:
                errors.append(
                    f"Item '{desc}' (line {line}) has no confirmed category"
                )
            else:
                errors.append(
                    f"Item '{desc}' has no confirmed category"
                )
    return errors


# ── Categorization rules (pure, no DB / no AI) ──


def determine_requires_review(
    suggested_category_id: Optional[UUID],
    confidence: Optional[float],
    threshold: float,
) -> bool:
    """Decide whether an item still requires manual attention in the UI.

    This is a per-item UI hint, NOT a global review-bypass flag. The
    receipt itself still requires user review before posting regardless
    of what this returns for individual items.

    Rules (first match wins):
    - suggested_category_id is None  → True  (no suggestion at all)
    - confidence is None              → True  (AI gave us nothing usable)
    - confidence < threshold          → True  (below trust threshold)
    - otherwise                       → False (trusted suggestion)

    Note: confidence exactly equal to the threshold counts as trusted.
    """
    if suggested_category_id is None:
        return True
    if confidence is None:
        return True
    if confidence < threshold:
        return True
    return False


def validate_category_suggestions(
    suggestions: list["CategorySuggestion"],
    item_ids_in_receipt: set[UUID],
    active_expense_category_ids: set[UUID],
) -> list["CategorySuggestion"]:
    """Filter AI suggestions down to ones the service can safely persist.

    A suggestion is dropped if:
    - receipt_item_id is not one of the receipt's own items
    - confidence is outside [0.0, 1.0] (a confidence of None is kept —
      that is a valid "no confidence" signal that Python will turn into
      requires_review=True downstream)
    - suggested_category_id is set but is not one of the household's
      active expense categories (suggested_category_id=None is kept —
      that means "AI has no suggestion for this item")

    This is the only place the service trusts the AI output. After this
    returns, build_suggestion_updates() applies the deterministic
    requires_review rule to every item.
    """
    validated: list["CategorySuggestion"] = []
    for s in suggestions:
        if s.receipt_item_id not in item_ids_in_receipt:
            continue
        if s.confidence is not None and not (0.0 <= s.confidence <= 1.0):
            continue
        if s.suggested_category_id is not None and s.suggested_category_id not in active_expense_category_ids:
            continue
        validated.append(s)
    return validated


def build_suggestion_updates(
    items: list[dict],
    validated_suggestions: list["CategorySuggestion"],
    threshold: float,
) -> list[dict]:
    """Build a FULL-REFRESH update list: one dict per receipt item.

    For each item:
    - If a validated suggestion exists AND has a non-None suggested_category_id,
      the item is updated with the suggestion's values and requires_review
      is computed by determine_requires_review(...).
    - Otherwise (no suggestion, or the suggestion had no category), the
      item is RESET: suggested_category_id=None, confidence=None,
      requires_review=True.

    This guarantees no stale data from a previous categorization run
    survives into the new one. Callers must persist every returned dict
    in a single transaction.

    Each item dict in the input must have an 'id' key (the receipt_item_id).
    The output dicts have keys: id, suggested_category_id, confidence,
    requires_review.
    """
    by_item_id: dict[UUID, "CategorySuggestion"] = {}
    for s in validated_suggestions:
        # Only keep suggestions with an actual category — a suggestion whose
        # suggested_category_id is None should be treated as "no suggestion"
        # so the item resets to NULL fields and requires_review=True.
        if s.suggested_category_id is not None:
            by_item_id[s.receipt_item_id] = s

    updates: list[dict] = []
    for item in items:
        item_id: UUID = item["id"]
        suggestion = by_item_id.get(item_id)
        if suggestion is None:
            updates.append({
                "id": item_id,
                "suggested_category_id": None,
                "confidence": None,
                "requires_review": True,
            })
        else:
            updates.append({
                "id": item_id,
                "suggested_category_id": suggestion.suggested_category_id,
                "confidence": suggestion.confidence,
                "requires_review": determine_requires_review(
                    suggestion.suggested_category_id,
                    suggestion.confidence,
                    threshold,
                ),
            })
    return updates


def items_to_categorize_from_rows(
    item_rows: list[dict],
) -> list["ItemToCategorize"]:
    """Adapter: DB receipt_item rows → AI input dataclasses.

    Keeps the service code tidy and pure-function testable.
    """
    from app.ai.base import ItemToCategorize

    return [
        ItemToCategorize(
            id=row["id"],
            description=row["description"],
            total_price=row["total_price"],
        )
        for row in item_rows
    ]
