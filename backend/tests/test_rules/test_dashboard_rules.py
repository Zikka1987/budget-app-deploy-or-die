from decimal import Decimal

from app.rules.budget_rules import (
    compute_category_budget_actual,
    compute_planned_to_be_allocated,
    compute_actual_balance,
    compute_plan_coverage,
    compute_savings_rate,
    build_dashboard_data,
)


# ── compute_category_budget_actual ──


class TestCategoryBudgetActualExpense:
    def test_under_budget(self):
        r = compute_category_budget_actual("c1", "Groceries", "expense", Decimal("5000"), Decimal("3000"))
        assert r.remaining == Decimal("2000")
        assert r.is_over_budget is False

    def test_exactly_on_budget(self):
        r = compute_category_budget_actual("c1", "Groceries", "expense", Decimal("5000"), Decimal("5000"))
        assert r.remaining == Decimal("0")
        assert r.is_over_budget is False

    def test_over_budget(self):
        r = compute_category_budget_actual("c1", "Groceries", "expense", Decimal("5000"), Decimal("6000"))
        assert r.remaining == Decimal("-1000")
        assert r.is_over_budget is True

    def test_unbudgeted_spend(self):
        """Actual > 0 with no budget line (planned=0)."""
        r = compute_category_budget_actual("c1", "Surprise", "expense", Decimal("0"), Decimal("200"))
        assert r.planned == Decimal("0")
        assert r.actual == Decimal("200")
        assert r.remaining == Decimal("-200")
        assert r.is_over_budget is True

    def test_planned_with_zero_actual(self):
        r = compute_category_budget_actual("c1", "Vacation", "expense", Decimal("3000"), Decimal("0"))
        assert r.remaining == Decimal("3000")
        assert r.is_over_budget is False


class TestCategoryBudgetActualIncome:
    def test_income_below_plan(self):
        """Remaining is positive = still below plan."""
        r = compute_category_budget_actual("c2", "Salary", "income", Decimal("45000"), Decimal("40000"))
        assert r.remaining == Decimal("5000")
        assert r.is_over_budget is False

    def test_income_matched_plan(self):
        r = compute_category_budget_actual("c2", "Salary", "income", Decimal("45000"), Decimal("45000"))
        assert r.remaining == Decimal("0")
        assert r.is_over_budget is False

    def test_income_exceeded_plan(self):
        """Remaining is negative = exceeded plan. is_over_budget stays False."""
        r = compute_category_budget_actual("c2", "Salary", "income", Decimal("45000"), Decimal("50000"))
        assert r.remaining == Decimal("-5000")
        assert r.is_over_budget is False

    def test_unbudgeted_income(self):
        """Income with no budget line."""
        r = compute_category_budget_actual("c2", "Bonus", "income", Decimal("0"), Decimal("10000"))
        assert r.remaining == Decimal("-10000")
        assert r.is_over_budget is False


class TestCategoryBudgetActualSavings:
    def test_savings_under_plan(self):
        r = compute_category_budget_actual("c3", "Emergency", "savings", Decimal("2000"), Decimal("1500"))
        assert r.remaining == Decimal("500")
        assert r.is_over_budget is False

    def test_savings_over_plan(self):
        """Saving more than planned is flagged as over_budget (same as expense)."""
        r = compute_category_budget_actual("c3", "Emergency", "savings", Decimal("2000"), Decimal("2500"))
        assert r.remaining == Decimal("-500")
        assert r.is_over_budget is True


# ── Balance metrics ──


class TestPlannedToBeAllocated:
    def test_positive(self):
        assert compute_planned_to_be_allocated(Decimal("50000"), Decimal("30000"), Decimal("5000")) == Decimal("15000")

    def test_zero(self):
        assert compute_planned_to_be_allocated(Decimal("50000"), Decimal("40000"), Decimal("10000")) == Decimal("0")

    def test_over_allocated(self):
        assert compute_planned_to_be_allocated(Decimal("50000"), Decimal("42000"), Decimal("10000")) == Decimal("-2000")


class TestActualBalance:
    def test_positive(self):
        assert compute_actual_balance(Decimal("45000"), Decimal("30000"), Decimal("5000")) == Decimal("10000")

    def test_negative(self):
        assert compute_actual_balance(Decimal("45000"), Decimal("40000"), Decimal("10000")) == Decimal("-5000")

    def test_zero(self):
        assert compute_actual_balance(Decimal("45000"), Decimal("40000"), Decimal("5000")) == Decimal("0")


class TestPlanCoverage:
    def test_income_covers_plan(self):
        assert compute_plan_coverage(Decimal("50000"), Decimal("30000"), Decimal("5000")) == Decimal("15000")

    def test_income_short_of_plan(self):
        assert compute_plan_coverage(Decimal("40000"), Decimal("35000"), Decimal("10000")) == Decimal("-5000")


# ── Savings rate ──


class TestSavingsRate:
    def test_normal(self):
        result = compute_savings_rate(Decimal("4500"), Decimal("45000"))
        assert result == Decimal("10.00")

    def test_zero_income(self):
        result = compute_savings_rate(Decimal("4500"), Decimal("0"))
        assert result is None

    def test_zero_savings(self):
        result = compute_savings_rate(Decimal("0"), Decimal("45000"))
        assert result == Decimal("0.00")

    def test_rounding(self):
        result = compute_savings_rate(Decimal("3333"), Decimal("45000"))
        assert result == Decimal("7.41")

    def test_result_is_decimal(self):
        result = compute_savings_rate(Decimal("4500"), Decimal("45000"))
        assert isinstance(result, Decimal)


# ── build_dashboard_data ──


class TestBuildDashboardData:
    def _make_budget_line(self, cat_id, name, cat_type, planned):
        return {
            "category_id": cat_id,
            "category_name": name,
            "category_type": cat_type,
            "planned_amount": planned,
        }

    def _make_actual(self, cat_id, name, cat_type, total):
        return {
            "category_id": cat_id,
            "category_name": name,
            "type": cat_type,
            "total": total,
        }

    def test_mixed_types(self):
        lines = [
            self._make_budget_line("c1", "Salary", "income", Decimal("45000")),
            self._make_budget_line("c2", "Groceries", "expense", Decimal("5000")),
            self._make_budget_line("c3", "Emergency", "savings", Decimal("2000")),
        ]
        actuals = [
            self._make_actual("c1", "Salary", "income", Decimal("45000")),
            self._make_actual("c2", "Groceries", "expense", Decimal("4000")),
            self._make_actual("c3", "Emergency", "savings", Decimal("2000")),
        ]
        d = build_dashboard_data("2026-04-01", lines, actuals)
        assert len(d.income_categories) == 1
        assert len(d.expense_categories) == 1
        assert len(d.savings_categories) == 1
        assert d.total_actual_income == Decimal("45000")
        assert d.total_actual_expenses == Decimal("4000")
        assert d.total_actual_savings == Decimal("2000")

    def test_unbudgeted_actual_appears(self):
        """A category with actuals but no budget line shows planned=0."""
        lines = [
            self._make_budget_line("c1", "Salary", "income", Decimal("45000")),
        ]
        actuals = [
            self._make_actual("c1", "Salary", "income", Decimal("45000")),
            self._make_actual("c99", "Gift", "income", Decimal("5000")),
        ]
        d = build_dashboard_data("2026-04-01", lines, actuals)
        assert len(d.income_categories) == 2
        gift = next(c for c in d.income_categories if c.category_name == "Gift")
        assert gift.planned == Decimal("0")
        assert gift.actual == Decimal("5000")

    def test_budgeted_with_no_actual(self):
        """A budgeted category with no transactions shows actual=0."""
        lines = [
            self._make_budget_line("c1", "Rent", "expense", Decimal("8000")),
        ]
        actuals = []
        d = build_dashboard_data("2026-04-01", lines, actuals)
        assert len(d.expense_categories) == 1
        assert d.expense_categories[0].actual == Decimal("0")
        assert d.expense_categories[0].remaining == Decimal("8000")

    def test_to_be_allocated(self):
        """to_be_allocated = planned_income - planned_expenses - planned_savings"""
        lines = [
            self._make_budget_line("c1", "Salary", "income", Decimal("50000")),
            self._make_budget_line("c2", "Groceries", "expense", Decimal("5000")),
            self._make_budget_line("c3", "Rent", "expense", Decimal("10000")),
            self._make_budget_line("c4", "Savings", "savings", Decimal("5000")),
        ]
        d = build_dashboard_data("2026-04-01", lines, [])
        # 50000 - 15000 - 5000 = 30000
        assert d.to_be_allocated == Decimal("30000")

    def test_actual_balance(self):
        """actual_balance = actual_income - actual_expenses - actual_savings"""
        lines = []
        actuals = [
            self._make_actual("c1", "Salary", "income", Decimal("45000")),
            self._make_actual("c2", "Groceries", "expense", Decimal("12000")),
            self._make_actual("c3", "Savings", "savings", Decimal("3000")),
        ]
        d = build_dashboard_data("2026-04-01", lines, actuals)
        # 45000 - 12000 - 3000 = 30000
        assert d.actual_balance == Decimal("30000")

    def test_plan_coverage(self):
        """plan_coverage = actual_income - planned_expenses - planned_savings"""
        lines = [
            self._make_budget_line("c1", "Salary", "income", Decimal("50000")),
            self._make_budget_line("c2", "Groceries", "expense", Decimal("15000")),
            self._make_budget_line("c3", "Savings", "savings", Decimal("5000")),
        ]
        actuals = [
            self._make_actual("c1", "Salary", "income", Decimal("48000")),
        ]
        d = build_dashboard_data("2026-04-01", lines, actuals)
        # 48000 - 15000 - 5000 = 28000
        assert d.plan_coverage == Decimal("28000")

    def test_savings_rate_computed(self):
        lines = []
        actuals = [
            self._make_actual("c1", "Salary", "income", Decimal("45000")),
            self._make_actual("c2", "Emergency", "savings", Decimal("4500")),
        ]
        d = build_dashboard_data("2026-04-01", lines, actuals)
        assert d.savings_rate == Decimal("10.00")

    def test_savings_rate_none_when_no_income(self):
        lines = [
            self._make_budget_line("c1", "Groceries", "expense", Decimal("5000")),
        ]
        d = build_dashboard_data("2026-04-01", lines, [])
        assert d.savings_rate is None

    def test_no_budget_month_returns_empty_dashboard(self):
        """When no budget month exists, service passes empty lists.
        The pure function must return the exact empty response shape."""
        d = build_dashboard_data("2026-04-01", [], [])
        assert d.month == "2026-04-01"
        assert d.total_planned_income == Decimal("0")
        assert d.total_planned_expenses == Decimal("0")
        assert d.total_planned_savings == Decimal("0")
        assert d.total_actual_income == Decimal("0")
        assert d.total_actual_expenses == Decimal("0")
        assert d.total_actual_savings == Decimal("0")
        assert d.to_be_allocated == Decimal("0")
        assert d.actual_balance == Decimal("0")
        assert d.plan_coverage == Decimal("0")
        assert d.savings_rate is None
        assert d.income_categories == []
        assert d.expense_categories == []
        assert d.savings_categories == []

    def test_all_values_are_decimal(self):
        lines = [
            self._make_budget_line("c1", "Salary", "income", Decimal("45000")),
        ]
        actuals = [
            self._make_actual("c1", "Salary", "income", Decimal("45000")),
        ]
        d = build_dashboard_data("2026-04-01", lines, actuals)
        assert isinstance(d.total_actual_income, Decimal)
        assert isinstance(d.to_be_allocated, Decimal)
        assert isinstance(d.actual_balance, Decimal)
        assert isinstance(d.plan_coverage, Decimal)

    def test_all_money_fields_have_two_decimal_places(self):
        """All money fields must serialize with exactly 2 decimal places."""
        lines = [
            self._make_budget_line("c1", "Salary", "income", Decimal("45000")),
            self._make_budget_line("c2", "Groceries", "expense", Decimal("5000")),
        ]
        actuals = [
            self._make_actual("c1", "Salary", "income", Decimal("48000")),
            self._make_actual("c2", "Groceries", "expense", Decimal("4333.5")),
        ]
        d = build_dashboard_data("2026-04-01", lines, actuals)
        # Top-level totals
        assert str(d.total_planned_income) == "45000.00"
        assert str(d.total_planned_expenses) == "5000.00"
        assert str(d.total_actual_income) == "48000.00"
        assert str(d.total_actual_expenses) == "4333.50"
        assert str(d.to_be_allocated) == "40000.00"
        assert str(d.actual_balance) == "43666.50"
        assert str(d.plan_coverage) == "43000.00"
        # Per-category fields
        grocery = d.expense_categories[0]
        assert str(grocery.planned) == "5000.00"
        assert str(grocery.actual) == "4333.50"
        assert str(grocery.remaining) == "666.50"

    def test_empty_dashboard_money_fields_have_two_decimal_places(self):
        d = build_dashboard_data("2026-04-01", [], [])
        assert str(d.total_planned_income) == "0.00"
        assert str(d.total_actual_income) == "0.00"
        assert str(d.to_be_allocated) == "0.00"
        assert str(d.actual_balance) == "0.00"
        assert str(d.plan_coverage) == "0.00"
