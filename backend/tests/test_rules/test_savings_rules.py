from decimal import Decimal

from app.rules.savings_rules import (
    calculate_percent_savings,
    calculate_fixed_savings,
    build_proposals,
)


class TestCalculatePercentSavings:
    def test_basic(self):
        result = calculate_percent_savings(Decimal("45000"), Decimal("10"))
        assert result == Decimal("4500.00")

    def test_rounding(self):
        result = calculate_percent_savings(Decimal("33333"), Decimal("7"))
        assert result == Decimal("2333.31")

    def test_zero_income(self):
        result = calculate_percent_savings(Decimal("0"), Decimal("10"))
        assert result == Decimal("0.00")


class TestCalculateFixedSavings:
    def test_returns_amount(self):
        result = calculate_fixed_savings(Decimal("2000.00"))
        assert result == Decimal("2000.00")


class TestBuildProposals:
    def test_generates_proposals(self, sample_savings_rules):
        proposals = build_proposals(sample_savings_rules, Decimal("45000"))
        assert len(proposals) == 2
        assert proposals[0].proposed_amount == Decimal("4500.00")
        assert proposals[1].proposed_amount == Decimal("2000.00")

    def test_empty_rules(self):
        proposals = build_proposals([], Decimal("45000"))
        assert proposals == []

    def test_stores_calculation_basis(self, sample_savings_rules):
        proposals = build_proposals(sample_savings_rules, Decimal("45000"))
        assert proposals[0].calculation_basis["rule_type"] == "percent_of_income"
        assert proposals[0].calculation_basis["total_income"] == "45000"
