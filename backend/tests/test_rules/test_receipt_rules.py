from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest

from app.ai.base import (
    CategorySuggestion,
    ItemToCategorize,
    ParsedLineItem,
    ParsedReceipt,
)
from app.rules.receipt_rules import (
    MAX_FILE_SIZE_BYTES,
    _is_item_level_discount,
    _is_summary_discount,
    build_duplicate_candidates,
    build_storage_path,
    build_suggestion_updates,
    detect_duplicate,
    determine_requires_review,
    determine_requires_review_after_edit,
    fold_adjacent_discounts,
    group_items_by_category,
    items_to_categorize_from_rows,
    parsed_receipt_to_item_dicts,
    validate_category_suggestions,
    validate_items_ready_for_confirm,
    validate_receipt_total,
    validate_upload_file,
)


class TestDetermineRequiresReviewAfterEdit:
    def test_excluded_item(self):
        assert determine_requires_review_after_edit(
            user_confirmed_category_id=None, is_excluded=True
        ) is False

    def test_confirmed_category_not_excluded(self):
        cat = UUID("00000000-0000-0000-0000-000000000001")
        assert determine_requires_review_after_edit(
            user_confirmed_category_id=cat, is_excluded=False
        ) is False

    def test_excluded_and_confirmed(self):
        cat = UUID("00000000-0000-0000-0000-000000000001")
        assert determine_requires_review_after_edit(
            user_confirmed_category_id=cat, is_excluded=True
        ) is False

    def test_no_category_not_excluded(self):
        assert determine_requires_review_after_edit(
            user_confirmed_category_id=None, is_excluded=False
        ) is True


class TestValidateItemsReadyForConfirm:
    def test_all_confirmed(self):
        items = [
            {"user_confirmed_category_id": UUID("00000000-0000-0000-0000-000000000001"),
             "is_excluded": False, "description": "A", "line_number": 1},
            {"user_confirmed_category_id": UUID("00000000-0000-0000-0000-000000000002"),
             "is_excluded": False, "description": "B", "line_number": 2},
        ]
        assert validate_items_ready_for_confirm(items) == []

    def test_one_unresolved(self):
        items = [
            {"user_confirmed_category_id": UUID("00000000-0000-0000-0000-000000000001"),
             "is_excluded": False, "description": "A", "line_number": 1},
            {"user_confirmed_category_id": None,
             "is_excluded": False, "description": "B", "line_number": 2},
        ]
        errors = validate_items_ready_for_confirm(items)
        assert len(errors) == 1
        assert "B" in errors[0]
        assert "line 2" in errors[0]

    def test_excluded_without_category_ok(self):
        items = [
            {"user_confirmed_category_id": None,
             "is_excluded": True, "description": "X", "line_number": 1},
        ]
        assert validate_items_ready_for_confirm(items) == []

    def test_all_excluded(self):
        items = [
            {"user_confirmed_category_id": None,
             "is_excluded": True, "description": "X", "line_number": 1},
            {"user_confirmed_category_id": None,
             "is_excluded": True, "description": "Y", "line_number": 2},
        ]
        assert validate_items_ready_for_confirm(items) == []

    def test_empty_list(self):
        assert validate_items_ready_for_confirm([]) == []

    def test_mixed_excluded_and_unresolved(self):
        items = [
            {"user_confirmed_category_id": None,
             "is_excluded": True, "description": "Excluded", "line_number": 1},
            {"user_confirmed_category_id": None,
             "is_excluded": False, "description": "Unresolved", "line_number": 2},
        ]
        errors = validate_items_ready_for_confirm(items)
        assert len(errors) == 1
        assert "Unresolved" in errors[0]

    def test_no_line_number(self):
        items = [
            {"user_confirmed_category_id": None,
             "is_excluded": False, "description": "NoLine"},
        ]
        errors = validate_items_ready_for_confirm(items)
        assert len(errors) == 1
        assert "NoLine" in errors[0]
        assert "line" not in errors[0]


class TestGroupItemsByCategory:
    def test_groups_by_category(self, sample_receipt_items):
        groups = group_items_by_category(sample_receipt_items)
        assert len(groups) == 2
        # Find the groceries group (cat 001)
        groceries = next(
            g for g in groups
            if g.category_id == UUID("00000000-0000-0000-0000-000000000001")
        )
        assert groceries.total_amount == Decimal("40.50")  # 25.50 + 15.00 (excluded item skipped)
        assert len(groceries.item_descriptions) == 2

    def test_excludes_items(self, sample_receipt_items):
        groups = group_items_by_category(sample_receipt_items)
        # The excluded Smor (10.00) should not be counted
        groceries = next(
            g for g in groups
            if g.category_id == UUID("00000000-0000-0000-0000-000000000001")
        )
        assert "Smor" not in groceries.item_descriptions

    def test_empty_items(self):
        groups = group_items_by_category([])
        assert groups == []


class TestValidateReceiptTotal:
    def test_within_tolerance(self):
        assert validate_receipt_total(Decimal("100.50"), Decimal("100.00")) is True

    def test_exact_match(self):
        assert validate_receipt_total(Decimal("100.00"), Decimal("100.00")) is True

    def test_outside_tolerance(self):
        assert validate_receipt_total(Decimal("102.00"), Decimal("100.00")) is False


class TestDetectDuplicate:
    def test_finds_duplicate(self):
        existing = [
            {"store_name": "Netto", "receipt_date": "2026-04-05", "total_amount": "150.00"},
        ]
        result = detect_duplicate("Netto", "2026-04-05", Decimal("150.00"), existing)
        assert len(result) == 1

    def test_no_duplicate(self):
        existing = [
            {"store_name": "Netto", "receipt_date": "2026-04-05", "total_amount": "150.00"},
        ]
        result = detect_duplicate("Fakta", "2026-04-05", Decimal("150.00"), existing)
        assert len(result) == 0

    def test_missing_fields(self):
        result = detect_duplicate(None, "2026-04-05", Decimal("150.00"), [])
        assert result == []


class TestValidateUploadFile:
    def test_valid_jpeg(self):
        assert validate_upload_file("image/jpeg", 1024) == "jpg"

    def test_valid_png(self):
        assert validate_upload_file("image/png", 1024) == "png"

    def test_valid_webp(self):
        assert validate_upload_file("image/webp", 1024) == "webp"

    def test_valid_pdf(self):
        assert validate_upload_file("application/pdf", 1024) == "pdf"

    def test_unsupported_mime(self):
        with pytest.raises(ValueError, match="Unsupported"):
            validate_upload_file("text/plain", 1024)

    def test_unsupported_mime_gif(self):
        with pytest.raises(ValueError, match="Unsupported"):
            validate_upload_file("image/gif", 1024)

    def test_empty_file(self):
        with pytest.raises(ValueError, match="empty"):
            validate_upload_file("image/jpeg", 0)

    def test_negative_size(self):
        with pytest.raises(ValueError, match="empty"):
            validate_upload_file("image/jpeg", -1)

    def test_file_too_large(self):
        with pytest.raises(ValueError, match="limit"):
            validate_upload_file("image/jpeg", MAX_FILE_SIZE_BYTES + 1)

    def test_exact_size_limit_allowed(self):
        """10 MB exactly is allowed (boundary condition)."""
        assert validate_upload_file("image/jpeg", MAX_FILE_SIZE_BYTES) == "jpg"


class TestBuildStoragePath:
    def test_format(self):
        hh = UUID("11111111-1111-1111-1111-111111111111")
        r = UUID("22222222-2222-2222-2222-222222222222")
        assert build_storage_path(hh, r, "jpg") == (
            "11111111-1111-1111-1111-111111111111/"
            "22222222-2222-2222-2222-222222222222/original.jpg"
        )

    def test_pdf_extension(self):
        hh = UUID("11111111-1111-1111-1111-111111111111")
        r = UUID("22222222-2222-2222-2222-222222222222")
        assert build_storage_path(hh, r, "pdf").endswith("/original.pdf")

    def test_webp_extension(self):
        hh = UUID("11111111-1111-1111-1111-111111111111")
        r = UUID("22222222-2222-2222-2222-222222222222")
        assert build_storage_path(hh, r, "webp").endswith("/original.webp")

    def test_path_starts_with_household_id(self):
        """First segment must match the household_id for RLS storage policies."""
        hh = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
        r = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
        path = build_storage_path(hh, r, "jpg")
        assert path.startswith("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/")


class TestParsedReceiptToItemDicts:
    def test_empty_items(self):
        parsed = ParsedReceipt(items=[])
        assert parsed_receipt_to_item_dicts(parsed) == []

    def test_populates_all_fields(self):
        parsed = ParsedReceipt(items=[
            ParsedLineItem(
                description="Maelk",
                total_price=Decimal("12.50"),
                quantity=Decimal("1"),
                unit_price=Decimal("12.50"),
                line_number=1,
                confidence=0.95,
            ),
        ])
        result = parsed_receipt_to_item_dicts(parsed)
        assert len(result) == 1
        item = result[0]
        assert item["description"] == "Maelk"
        assert item["total_price"] == Decimal("12.50")
        assert item["quantity"] == Decimal("1")
        assert item["unit_price"] == Decimal("12.50")
        assert item["line_number"] == 1
        assert item["confidence"] == 0.95
        assert item["requires_review"] is True
        assert item["suggested_category_id"] is None
        assert item["user_confirmed_category_id"] is None
        assert item["is_excluded"] is False

    def test_requires_review_always_true_in_this_phase(self):
        """Even high-confidence items still require review until categorization phase."""
        parsed = ParsedReceipt(items=[
            ParsedLineItem(
                description="Broed", total_price=Decimal("25"), confidence=0.99,
            ),
        ])
        assert parsed_receipt_to_item_dicts(parsed)[0]["requires_review"] is True

    def test_suggested_category_always_null(self):
        """Categorization is a separate phase; suggested_category_id stays None."""
        parsed = ParsedReceipt(items=[
            ParsedLineItem(description="X", total_price=Decimal("1")),
            ParsedLineItem(description="Y", total_price=Decimal("2")),
        ])
        for item in parsed_receipt_to_item_dicts(parsed):
            assert item["suggested_category_id"] is None
            assert item["user_confirmed_category_id"] is None

    def test_confidence_passes_through_none(self):
        """A ParsedLineItem without confidence yields a dict with None."""
        parsed = ParsedReceipt(items=[
            ParsedLineItem(description="X", total_price=Decimal("1")),
        ])
        assert parsed_receipt_to_item_dicts(parsed)[0]["confidence"] is None

    def test_preserves_item_order(self):
        parsed = ParsedReceipt(items=[
            ParsedLineItem(description="A", total_price=Decimal("1"), line_number=1),
            ParsedLineItem(description="B", total_price=Decimal("2"), line_number=2),
            ParsedLineItem(description="C", total_price=Decimal("3"), line_number=3),
        ])
        result = parsed_receipt_to_item_dicts(parsed)
        assert [i["description"] for i in result] == ["A", "B", "C"]


class TestBuildDuplicateCandidates:
    def test_exact_match(self):
        parsed = ParsedReceipt(
            store_name="Netto",
            receipt_date=date(2026, 4, 5),
            total_amount=Decimal("150.00"),
        )
        existing = [
            {"store_name": "Netto", "receipt_date": "2026-04-05", "total_amount": "150.00"},
        ]
        result = build_duplicate_candidates(parsed, existing)
        assert len(result) == 1

    def test_no_match_different_store(self):
        parsed = ParsedReceipt(
            store_name="Netto",
            receipt_date=date(2026, 4, 5),
            total_amount=Decimal("150.00"),
        )
        existing = [
            {"store_name": "Fakta", "receipt_date": "2026-04-05", "total_amount": "150.00"},
        ]
        assert build_duplicate_candidates(parsed, existing) == []

    def test_no_match_different_date(self):
        parsed = ParsedReceipt(
            store_name="Netto",
            receipt_date=date(2026, 4, 5),
            total_amount=Decimal("150.00"),
        )
        existing = [
            {"store_name": "Netto", "receipt_date": "2026-04-06", "total_amount": "150.00"},
        ]
        assert build_duplicate_candidates(parsed, existing) == []

    def test_no_match_different_amount(self):
        parsed = ParsedReceipt(
            store_name="Netto",
            receipt_date=date(2026, 4, 5),
            total_amount=Decimal("150.00"),
        )
        existing = [
            {"store_name": "Netto", "receipt_date": "2026-04-05", "total_amount": "150.50"},
        ]
        assert build_duplicate_candidates(parsed, existing) == []

    def test_empty_existing_returns_empty(self):
        parsed = ParsedReceipt(
            store_name="Netto",
            receipt_date=date(2026, 4, 5),
            total_amount=Decimal("150.00"),
        )
        assert build_duplicate_candidates(parsed, []) == []

    def test_parsed_without_fields_returns_empty(self):
        """A ParsedReceipt with no store/date/total cannot match anything."""
        parsed = ParsedReceipt()
        existing = [
            {"store_name": "Netto", "receipt_date": "2026-04-05", "total_amount": "150.00"},
        ]
        assert build_duplicate_candidates(parsed, existing) == []


# ── Categorization pure functions ──


CAT_A = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
CAT_B = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
CAT_ARCHIVED = UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
ITEM_1 = UUID("11111111-1111-1111-1111-111111111111")
ITEM_2 = UUID("22222222-2222-2222-2222-222222222222")
ITEM_3 = UUID("33333333-3333-3333-3333-333333333333")


class TestDetermineRequiresReview:
    def test_suggestion_above_threshold_is_not_flagged(self):
        assert determine_requires_review(CAT_A, confidence=0.95, threshold=0.85) is False

    def test_suggestion_below_threshold_is_flagged(self):
        assert determine_requires_review(CAT_A, confidence=0.70, threshold=0.85) is True

    def test_confidence_exactly_at_threshold_is_not_flagged(self):
        """Boundary: confidence == threshold counts as trusted."""
        assert determine_requires_review(CAT_A, confidence=0.85, threshold=0.85) is False

    def test_no_suggestion_is_flagged(self):
        assert determine_requires_review(None, confidence=0.99, threshold=0.85) is True

    def test_none_confidence_is_flagged(self):
        assert determine_requires_review(CAT_A, confidence=None, threshold=0.85) is True

    def test_no_suggestion_and_no_confidence_is_flagged(self):
        assert determine_requires_review(None, confidence=None, threshold=0.85) is True


class TestValidateCategorySuggestions:
    def _suggestion(self, item_id=ITEM_1, cat_id=CAT_A, confidence=0.9):
        return CategorySuggestion(
            receipt_item_id=item_id,
            suggested_category_id=cat_id,
            confidence=confidence,
        )

    def test_valid_suggestion_kept(self):
        result = validate_category_suggestions(
            [self._suggestion()],
            item_ids_in_receipt={ITEM_1},
            active_expense_category_ids={CAT_A},
        )
        assert len(result) == 1

    def test_unknown_item_id_dropped(self):
        unknown = UUID("99999999-9999-9999-9999-999999999999")
        result = validate_category_suggestions(
            [self._suggestion(item_id=unknown)],
            item_ids_in_receipt={ITEM_1},
            active_expense_category_ids={CAT_A},
        )
        assert result == []

    def test_unknown_category_id_dropped(self):
        unknown_cat = UUID("88888888-8888-8888-8888-888888888888")
        result = validate_category_suggestions(
            [self._suggestion(cat_id=unknown_cat)],
            item_ids_in_receipt={ITEM_1},
            active_expense_category_ids={CAT_A},
        )
        assert result == []

    def test_archived_category_dropped(self):
        """Archived categories are absent from the active set → dropped."""
        result = validate_category_suggestions(
            [self._suggestion(cat_id=CAT_ARCHIVED)],
            item_ids_in_receipt={ITEM_1},
            active_expense_category_ids={CAT_A},
        )
        assert result == []

    def test_confidence_above_one_dropped(self):
        result = validate_category_suggestions(
            [self._suggestion(confidence=1.5)],
            item_ids_in_receipt={ITEM_1},
            active_expense_category_ids={CAT_A},
        )
        assert result == []

    def test_confidence_below_zero_dropped(self):
        result = validate_category_suggestions(
            [self._suggestion(confidence=-0.1)],
            item_ids_in_receipt={ITEM_1},
            active_expense_category_ids={CAT_A},
        )
        assert result == []

    def test_none_confidence_kept(self):
        """Confidence=None is a valid signal meaning 'AI had none'."""
        result = validate_category_suggestions(
            [self._suggestion(confidence=None)],
            item_ids_in_receipt={ITEM_1},
            active_expense_category_ids={CAT_A},
        )
        assert len(result) == 1

    def test_none_suggested_category_kept(self):
        """suggested_category_id=None is a valid 'no suggestion' signal."""
        result = validate_category_suggestions(
            [self._suggestion(cat_id=None)],
            item_ids_in_receipt={ITEM_1},
            active_expense_category_ids={CAT_A},
        )
        assert len(result) == 1


class TestBuildSuggestionUpdates:
    def _item(self, item_id):
        return {"id": item_id, "description": "x", "total_price": Decimal("1")}

    def test_output_length_matches_input_length(self):
        items = [self._item(ITEM_1), self._item(ITEM_2), self._item(ITEM_3)]
        updates = build_suggestion_updates(items, [], threshold=0.85)
        assert len(updates) == 3

    def test_item_with_valid_suggestion_above_threshold(self):
        items = [self._item(ITEM_1)]
        suggestions = [
            CategorySuggestion(
                receipt_item_id=ITEM_1,
                suggested_category_id=CAT_A,
                confidence=0.95,
            ),
        ]
        updates = build_suggestion_updates(items, suggestions, threshold=0.85)
        assert updates[0]["id"] == ITEM_1
        assert updates[0]["suggested_category_id"] == CAT_A
        assert updates[0]["confidence"] == 0.95
        assert updates[0]["requires_review"] is False

    def test_item_with_valid_suggestion_below_threshold(self):
        items = [self._item(ITEM_1)]
        suggestions = [
            CategorySuggestion(
                receipt_item_id=ITEM_1,
                suggested_category_id=CAT_A,
                confidence=0.50,
            ),
        ]
        updates = build_suggestion_updates(items, suggestions, threshold=0.85)
        assert updates[0]["suggested_category_id"] == CAT_A
        assert updates[0]["confidence"] == 0.50
        assert updates[0]["requires_review"] is True

    def test_item_without_suggestion_is_reset(self):
        """Full-refresh: an item with no suggestion in this run is reset."""
        items = [self._item(ITEM_1)]
        updates = build_suggestion_updates(items, [], threshold=0.85)
        assert updates[0]["id"] == ITEM_1
        assert updates[0]["suggested_category_id"] is None
        assert updates[0]["confidence"] is None
        assert updates[0]["requires_review"] is True

    def test_suggestion_with_null_category_is_reset(self):
        """A suggestion whose suggested_category_id is None counts as no suggestion."""
        items = [self._item(ITEM_1)]
        suggestions = [
            CategorySuggestion(
                receipt_item_id=ITEM_1,
                suggested_category_id=None,
                confidence=0.99,
            ),
        ]
        updates = build_suggestion_updates(items, suggestions, threshold=0.85)
        assert updates[0]["suggested_category_id"] is None
        assert updates[0]["confidence"] is None
        assert updates[0]["requires_review"] is True

    def test_regression_stale_suggestion_cleared_on_reparse(self):
        """Item had a suggestion from a prior run; new run has no suggestion for it.

        The output dict must reset the fields. This is the regression guard
        for the full-refresh rule.
        """
        # Item carries a stale suggestion in the DB row; caller ignores that
        # and the output dict still resets it.
        items = [{
            "id": ITEM_1,
            "description": "x",
            "total_price": Decimal("1"),
            "suggested_category_id": CAT_A,  # stale data from a prior run
            "confidence": 0.95,
            "requires_review": False,
        }]
        updates = build_suggestion_updates(items, [], threshold=0.85)
        assert updates[0]["suggested_category_id"] is None
        assert updates[0]["confidence"] is None
        assert updates[0]["requires_review"] is True

    def test_mixed_items(self):
        """Three items: one with high-conf suggestion, one low-conf, one none."""
        items = [self._item(ITEM_1), self._item(ITEM_2), self._item(ITEM_3)]
        suggestions = [
            CategorySuggestion(
                receipt_item_id=ITEM_1,
                suggested_category_id=CAT_A,
                confidence=0.95,
            ),
            CategorySuggestion(
                receipt_item_id=ITEM_2,
                suggested_category_id=CAT_B,
                confidence=0.55,
            ),
        ]
        updates = build_suggestion_updates(items, suggestions, threshold=0.85)
        by_id = {u["id"]: u for u in updates}
        assert by_id[ITEM_1]["requires_review"] is False
        assert by_id[ITEM_2]["requires_review"] is True
        assert by_id[ITEM_3]["suggested_category_id"] is None
        assert by_id[ITEM_3]["requires_review"] is True


class TestItemsToCategorizeFromRows:
    def test_basic_shape(self):
        rows = [
            {
                "id": ITEM_1,
                "description": "Maelk",
                "total_price": Decimal("12.50"),
                "quantity": Decimal("1"),  # extra field, ignored
            },
            {
                "id": ITEM_2,
                "description": "Broed",
                "total_price": Decimal("25.00"),
            },
        ]
        result = items_to_categorize_from_rows(rows)
        assert len(result) == 2
        assert isinstance(result[0], ItemToCategorize)
        assert result[0].id == ITEM_1
        assert result[0].description == "Maelk"
        assert result[0].total_price == Decimal("12.50")

    def test_empty(self):
        assert items_to_categorize_from_rows([]) == []


class TestIsSummaryDiscount:
    def test_rabat_i_alt(self):
        assert _is_summary_discount("RABAT I ALT") is True

    def test_rabat_i_alt_with_amount(self):
        assert _is_summary_discount("RABAT I ALT 41.80") is True

    def test_rabat_i_alt_with_colon(self):
        assert _is_summary_discount("RABAT I ALT:") is True

    def test_extra_internal_whitespace_still_matches(self):
        assert _is_summary_discount("RABAT   I   ALT") is True

    def test_case_insensitive(self):
        assert _is_summary_discount("rabat i alt") is True

    def test_total_rabat(self):
        assert _is_summary_discount("TOTAL RABAT") is True

    def test_total_discount(self):
        assert _is_summary_discount("total discount") is True

    def test_plain_rabat_is_not_summary(self):
        assert _is_summary_discount("RABAT") is False

    def test_product_name_with_rabat_is_not_summary(self):
        assert _is_summary_discount("RABAT JORDBÆR") is False


class TestIsItemLevelDiscount:
    def test_plain_rabat_negative(self):
        item = ParsedLineItem(description="RABAT", total_price=Decimal("-7.00"))
        assert _is_item_level_discount(item) is True

    def test_positive_rabat_is_not_discount(self):
        item = ParsedLineItem(description="RABAT", total_price=Decimal("7.00"))
        assert _is_item_level_discount(item) is False

    def test_summary_rabat_is_not_foldable(self):
        item = ParsedLineItem(description="RABAT I ALT", total_price=Decimal("-41.80"))
        assert _is_item_level_discount(item) is False

    def test_tilbud_negative(self):
        item = ParsedLineItem(description="TILBUD JORDBÆR", total_price=Decimal("-5.00"))
        assert _is_item_level_discount(item) is True

    def test_negative_non_discount_description(self):
        item = ParsedLineItem(description="RETUR", total_price=Decimal("-10.00"))
        assert _is_item_level_discount(item) is False

    def test_discount_keyword_case_insensitive(self):
        item = ParsedLineItem(description="Rabat", total_price=Decimal("-3.00"))
        assert _is_item_level_discount(item) is True


class TestFoldAdjacentDiscounts:

    def _item(self, desc: str, price: str, line: int | None = None) -> ParsedLineItem:
        return ParsedLineItem(
            description=desc,
            total_price=Decimal(price),
            line_number=line,
        )

    # ── Core receipt pattern from the reported issue ──────────────────────────

    def test_concrete_receipt_pattern(self):
        """JORDBÆR+RABAT, MILKSHAKE+RABAT, JORDBÆR+RABAT all fold correctly."""
        items = [
            self._item("JORDBÆR", "25.00", 1),
            self._item("RABAT", "-7.00", 2),
            self._item("MILKSHAKE JORDBÆR", "51.80", 3),
            self._item("RABAT", "-27.80", 4),
            self._item("JORDBÆR", "25.00", 5),
            self._item("RABAT", "-7.00", 6),
        ]
        result = fold_adjacent_discounts(items)
        assert len(result) == 3
        assert result[0].description == "JORDBÆR"
        assert result[0].total_price == Decimal("18.00")
        assert result[1].description == "MILKSHAKE JORDBÆR"
        assert result[1].total_price == Decimal("24.00")
        assert result[2].description == "JORDBÆR"
        assert result[2].total_price == Decimal("18.00")

    def test_net_total_matches_at_betale(self):
        """Sum of net items equals 254.70 (AT BETALE), not 296.50 (gross).
        Non-discounted items sum to 194.70 (254.70 − 60.00)."""
        items = [
            self._item("JORDBÆR", "25.00", 1),
            self._item("RABAT", "-7.00", 2),
            self._item("MILKSHAKE JORDBÆR", "51.80", 3),
            self._item("RABAT", "-27.80", 4),
            self._item("JORDBÆR", "25.00", 5),
            self._item("RABAT", "-7.00", 6),
            self._item("OTHER ITEMS", "194.70", 7),
        ]
        result = fold_adjacent_discounts(items)
        total = sum(i.total_price for i in result)
        assert total == Decimal("254.70")

    # ── Summary discount handling (drop, not emit) ─────────────────────────────

    def test_rabat_i_alt_dropped(self):
        """RABAT I ALT is dropped entirely — not folded, not kept as review item."""
        items = [
            self._item("JORDBÆR", "25.00", 1),
            self._item("RABAT I ALT", "-41.80", 2),
        ]
        result = fold_adjacent_discounts(items)
        assert len(result) == 1
        assert result[0].total_price == Decimal("25.00")

    def test_rabat_i_alt_with_trailing_amount_dropped(self):
        items = [
            self._item("JORDBÆR", "25.00", 1),
            self._item("RABAT I ALT 41.80", "-41.80", 2),
        ]
        result = fold_adjacent_discounts(items)
        assert len(result) == 1
        assert result[0].total_price == Decimal("25.00")

    def test_summary_line_resets_anchor(self):
        """Summary line between product and RABAT drops and resets anchor;
        the subsequent RABAT has no anchor and is kept for user review."""
        items = [
            self._item("JORDBÆR", "25.00", 1),
            self._item("RABAT I ALT", "-41.80", 2),
            self._item("RABAT", "-7.00", 3),
        ]
        result = fold_adjacent_discounts(items)
        assert len(result) == 2
        assert result[0].total_price == Decimal("25.00")
        assert result[1].total_price == Decimal("-7.00")

    # ── Non-discount negatives ─────────────────────────────────────────────────

    def test_non_discount_negative_not_folded(self):
        items = [
            self._item("JORDBÆR", "25.00", 1),
            self._item("RETUR", "-5.00", 2),
        ]
        result = fold_adjacent_discounts(items)
        assert len(result) == 2
        assert result[0].total_price == Decimal("25.00")
        assert result[1].total_price == Decimal("-5.00")

    def test_non_discount_negative_resets_anchor(self):
        """Non-discount negative resets anchor; subsequent RABAT is not folded."""
        items = [
            self._item("JORDBÆR", "25.00", 1),
            self._item("RETUR", "-5.00", 2),
            self._item("RABAT", "-3.00", 3),
        ]
        result = fold_adjacent_discounts(items)
        assert len(result) == 3
        assert result[0].total_price == Decimal("25.00")
        assert result[2].total_price == Decimal("-3.00")

    # ── Extracted order (line_number=None) ────────────────────────────────────

    def test_none_line_numbers_fold_by_extracted_order(self):
        """Items without line_number fold if discount immediately follows product
        in extracted order."""
        items = [
            ParsedLineItem(description="A", total_price=Decimal("10.00"), line_number=None),
            ParsedLineItem(description="RABAT", total_price=Decimal("-2.00"), line_number=None),
        ]
        result = fold_adjacent_discounts(items)
        assert len(result) == 1
        assert result[0].total_price == Decimal("8.00")

    def test_none_line_numbers_do_not_fold_across_positive_item(self):
        """RABAT after a second product only folds into the second product."""
        items = [
            ParsedLineItem(description="A", total_price=Decimal("10.00"), line_number=None),
            ParsedLineItem(description="B", total_price=Decimal("20.00"), line_number=None),
            ParsedLineItem(description="RABAT", total_price=Decimal("-3.00"), line_number=None),
        ]
        result = fold_adjacent_discounts(items)
        assert len(result) == 2
        assert result[0].total_price == Decimal("10.00")
        assert result[1].total_price == Decimal("17.00")

    # ── Consecutive discounts ──────────────────────────────────────────────────

    def test_consecutive_rabats_both_fold_into_same_item(self):
        items = [
            self._item("JORDBÆR", "25.00", 1),
            self._item("RABAT", "-5.00", 2),
            self._item("RABAT", "-3.00", 3),
        ]
        result = fold_adjacent_discounts(items)
        assert len(result) == 1
        assert result[0].total_price == Decimal("17.00")

    # ── Edge cases ─────────────────────────────────────────────────────────────

    def test_unmatched_rabat_no_preceding_item_kept(self):
        items = [
            self._item("RABAT", "-5.00", 1),
            self._item("MÆLK", "20.00", 2),
        ]
        result = fold_adjacent_discounts(items)
        assert len(result) == 2
        assert result[0].total_price == Decimal("-5.00")
        assert result[1].total_price == Decimal("20.00")

    def test_no_discounts_unchanged(self):
        items = [
            self._item("MÆLK", "15.00", 1),
            self._item("BRØD", "25.00", 2),
        ]
        result = fold_adjacent_discounts(items)
        assert len(result) == 2
        assert result[0].total_price == Decimal("15.00")
        assert result[1].total_price == Decimal("25.00")

    def test_empty_items(self):
        assert fold_adjacent_discounts([]) == []

    # ── Integration with posting ───────────────────────────────────────────────

    def test_posted_total_uses_net_after_fold(self):
        """After folding, group_items_by_category sums net amounts."""
        cat_id = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
        items = [
            self._item("JORDBÆR", "25.00", 1),
            self._item("RABAT", "-7.00", 2),
        ]
        folded = fold_adjacent_discounts(items)
        item_dicts = [
            {
                "description": folded[0].description,
                "total_price": folded[0].total_price,
                "user_confirmed_category_id": cat_id,
                "is_excluded": False,
            }
        ]
        groups = group_items_by_category(item_dicts)
        assert len(groups) == 1
        assert groups[0].total_amount == Decimal("18.00")
