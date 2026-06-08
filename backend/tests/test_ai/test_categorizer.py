"""Tests for pure helper functions in app.ai.categorizer.

No Anthropic client is instantiated here — these tests cover the
index-mapping logic independently of the network call.
"""

from decimal import Decimal
from uuid import UUID

from app.ai.base import CategorizerBase, ItemToCategorize
from app.ai.categorizer import (
    _build_suggestions_from_payload,
    _format_categories,
    _format_items,
)

ITEM_UUID_1 = UUID("11111111-1111-1111-1111-111111111111")
ITEM_UUID_2 = UUID("22222222-2222-2222-2222-222222222222")
CAT_UUID_1 = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
CAT_UUID_2 = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")


def _items():
    return [
        ItemToCategorize(id=ITEM_UUID_1, description="Mælk", total_price=Decimal("10.00")),
        ItemToCategorize(id=ITEM_UUID_2, description="Skumklude", total_price=Decimal("15.00")),
    ]


def _categories():
    return [
        CategorizerBase.CategoryOption(id=CAT_UUID_1, name="Groceries", type="expense"),
        CategorizerBase.CategoryOption(id=CAT_UUID_2, name="Cleaning Products", type="expense"),
    ]


class TestFormatItems:
    def test_uses_bracketed_one_based_index(self):
        result = _format_items(_items())
        assert "[1]" in result
        assert "[2]" in result

    def test_includes_description(self):
        result = _format_items(_items())
        assert "Mælk" in result
        assert "Skumklude" in result

    def test_no_uuids_in_output(self):
        result = _format_items(_items())
        assert str(ITEM_UUID_1) not in result
        assert str(ITEM_UUID_2) not in result

    def test_single_item(self):
        items = [ItemToCategorize(id=ITEM_UUID_1, description="X", total_price=Decimal("1"))]
        result = _format_items(items)
        assert result == "[1] X | total=1"


class TestFormatCategories:
    def test_uses_bracketed_one_based_index(self):
        result = _format_categories(_categories())
        assert "[1]" in result
        assert "[2]" in result

    def test_includes_name(self):
        result = _format_categories(_categories())
        assert "Groceries" in result
        assert "Cleaning Products" in result

    def test_no_uuids_in_output(self):
        result = _format_categories(_categories())
        assert str(CAT_UUID_1) not in result
        assert str(CAT_UUID_2) not in result

    def test_single_category(self):
        cats = [CategorizerBase.CategoryOption(id=CAT_UUID_1, name="Groceries", type="expense")]
        result = _format_categories(cats)
        assert result == "[1] Groceries"


class TestBuildSuggestionsFromPayload:
    def test_valid_mapping(self):
        payload = {"suggestions": [{"item_index": 1, "category_index": 2, "confidence": 0.9}]}
        result = _build_suggestions_from_payload(payload, _items(), _categories())
        assert len(result.suggestions) == 1
        s = result.suggestions[0]
        assert s.receipt_item_id == ITEM_UUID_1
        assert s.suggested_category_id == CAT_UUID_2
        assert s.confidence == 0.9

    def test_second_item_first_category(self):
        payload = {"suggestions": [{"item_index": 2, "category_index": 1, "confidence": 0.85}]}
        result = _build_suggestions_from_payload(payload, _items(), _categories())
        s = result.suggestions[0]
        assert s.receipt_item_id == ITEM_UUID_2
        assert s.suggested_category_id == CAT_UUID_1

    def test_null_category_index_kept_as_no_suggestion(self):
        payload = {"suggestions": [{"item_index": 1, "category_index": None, "confidence": None}]}
        result = _build_suggestions_from_payload(payload, _items(), _categories())
        assert len(result.suggestions) == 1
        assert result.suggestions[0].suggested_category_id is None
        assert result.suggestions[0].receipt_item_id == ITEM_UUID_1

    def test_item_index_out_of_range_dropped(self):
        payload = {"suggestions": [{"item_index": 99, "category_index": 1, "confidence": 0.9}]}
        result = _build_suggestions_from_payload(payload, _items(), _categories())
        assert result.suggestions == []

    def test_item_index_zero_dropped(self):
        # 0 is not a valid 1-based index
        payload = {"suggestions": [{"item_index": 0, "category_index": 1, "confidence": 0.9}]}
        result = _build_suggestions_from_payload(payload, _items(), _categories())
        assert result.suggestions == []

    def test_item_index_negative_dropped(self):
        payload = {"suggestions": [{"item_index": -1, "category_index": 1, "confidence": 0.9}]}
        result = _build_suggestions_from_payload(payload, _items(), _categories())
        assert result.suggestions == []

    def test_category_index_out_of_range_dropped(self):
        payload = {"suggestions": [{"item_index": 1, "category_index": 99, "confidence": 0.9}]}
        result = _build_suggestions_from_payload(payload, _items(), _categories())
        assert result.suggestions == []

    def test_category_index_zero_dropped(self):
        payload = {"suggestions": [{"item_index": 1, "category_index": 0, "confidence": 0.9}]}
        result = _build_suggestions_from_payload(payload, _items(), _categories())
        assert result.suggestions == []

    def test_non_integer_item_index_dropped(self):
        payload = {"suggestions": [{"item_index": "1", "category_index": 1, "confidence": 0.9}]}
        result = _build_suggestions_from_payload(payload, _items(), _categories())
        assert result.suggestions == []

    def test_non_integer_category_index_dropped(self):
        # A non-null, non-int category_index is invalid (not null, not in-range int)
        payload = {"suggestions": [{"item_index": 1, "category_index": "1", "confidence": 0.9}]}
        result = _build_suggestions_from_payload(payload, _items(), _categories())
        assert result.suggestions == []

    def test_non_dict_suggestion_dropped_others_survive(self):
        payload = {
            "suggestions": [
                "not a dict",
                {"item_index": 1, "category_index": 1, "confidence": 0.9},
            ]
        }
        result = _build_suggestions_from_payload(payload, _items(), _categories())
        assert len(result.suggestions) == 1
        assert result.suggestions[0].receipt_item_id == ITEM_UUID_1

    def test_empty_suggestions_returns_empty(self):
        result = _build_suggestions_from_payload({"suggestions": []}, _items(), _categories())
        assert result.suggestions == []

    def test_missing_suggestions_key_returns_empty(self):
        result = _build_suggestions_from_payload({}, _items(), _categories())
        assert result.suggestions == []

    def test_multiple_valid_suggestions(self):
        payload = {
            "suggestions": [
                {"item_index": 1, "category_index": 1, "confidence": 0.95},
                {"item_index": 2, "category_index": 2, "confidence": 0.80},
            ]
        }
        result = _build_suggestions_from_payload(payload, _items(), _categories())
        assert len(result.suggestions) == 2
        assert result.suggestions[0].receipt_item_id == ITEM_UUID_1
        assert result.suggestions[0].suggested_category_id == CAT_UUID_1
        assert result.suggestions[1].receipt_item_id == ITEM_UUID_2
        assert result.suggestions[1].suggested_category_id == CAT_UUID_2
