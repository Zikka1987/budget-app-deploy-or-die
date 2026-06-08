from decimal import Decimal

from app.rules.budget_rules import (
    copy_month_structure,
    compute_to_be_allocated,
    compute_budget_summary,
    BudgetLine,
)


class TestCopyMonthStructure:
    def test_copies_lines(self, sample_budget_lines):
        result = copy_month_structure(sample_budget_lines)
        assert len(result) == 3
        assert result[0].category_id == "cat-1"
        assert result[0].planned_amount == Decimal("5000.00")

    def test_clears_notes(self, sample_budget_lines):
        result = copy_month_structure(sample_budget_lines)
        for line in result:
            assert line.notes is None

    def test_empty_input(self):
        result = copy_month_structure([])
        assert result == []


class TestComputeToBeAllocated:
    def test_positive_remainder(self):
        result = compute_to_be_allocated(
            Decimal("45000"), Decimal("30000"), Decimal("5000")
        )
        assert result == Decimal("10000")

    def test_zero_remainder(self):
        result = compute_to_be_allocated(
            Decimal("45000"), Decimal("40000"), Decimal("5000")
        )
        assert result == Decimal("0")

    def test_negative_remainder(self):
        result = compute_to_be_allocated(
            Decimal("45000"), Decimal("42000"), Decimal("5000")
        )
        assert result == Decimal("-2000")


class TestCopyMonthStructureAdvanced:
    def test_preserves_planned_amounts_exactly(self):
        lines = [
            BudgetLine(category_id="a", planned_amount=Decimal("1234.56")),
            BudgetLine(category_id="b", planned_amount=Decimal("0.01")),
        ]
        result = copy_month_structure(lines)
        assert result[0].planned_amount == Decimal("1234.56")
        assert result[1].planned_amount == Decimal("0.01")

    def test_does_not_share_references(self, sample_budget_lines):
        """Copied lines must be independent objects."""
        result = copy_month_structure(sample_budget_lines)
        result[0].planned_amount = Decimal("9999")
        assert sample_budget_lines[0].planned_amount == Decimal("5000.00")

    def test_zero_amount_lines_are_copied(self):
        lines = [BudgetLine(category_id="z", planned_amount=Decimal("0"))]
        result = copy_month_structure(lines)
        assert len(result) == 1
        assert result[0].planned_amount == Decimal("0")


class TestComputeBudgetSummary:
    def test_summary(self):
        result = compute_budget_summary(
            planned_income=Decimal("50000"),
            planned_expenses=Decimal("35000"),
            planned_savings=Decimal("5000"),
            actual_income=Decimal("45000"),
            actual_expenses=Decimal("32000"),
            actual_savings=Decimal("4500"),
        )
        assert result.total_actual_income == Decimal("45000")
        assert result.to_be_allocated == Decimal("5000")

    def test_to_be_allocated_uses_actual_income_not_planned(self):
        """to_be_allocated = actual_income - planned_expenses - planned_savings"""
        result = compute_budget_summary(
            planned_income=Decimal("50000"),
            planned_expenses=Decimal("20000"),
            planned_savings=Decimal("10000"),
            actual_income=Decimal("60000"),
            actual_expenses=Decimal("18000"),
            actual_savings=Decimal("8000"),
        )
        # 60000 - 20000 - 10000 = 30000
        assert result.to_be_allocated == Decimal("30000")

    def test_all_zeroes(self):
        result = compute_budget_summary(
            planned_income=Decimal("0"),
            planned_expenses=Decimal("0"),
            planned_savings=Decimal("0"),
            actual_income=Decimal("0"),
            actual_expenses=Decimal("0"),
            actual_savings=Decimal("0"),
        )
        assert result.to_be_allocated == Decimal("0")
