from datetime import date

from app.rules.date_rules import determine_budget_month, get_month_date_range


class TestDetermineBudgetMonth:
    def test_normal_income(self):
        result = determine_budget_month(date(2026, 4, 15), "income")
        assert result == date(2026, 4, 1)

    def test_normal_expense(self):
        result = determine_budget_month(date(2026, 4, 28), "expense")
        assert result == date(2026, 4, 1)

    def test_late_income_shift_disabled(self):
        result = determine_budget_month(
            date(2026, 4, 28), "income", shift_late_income=False
        )
        assert result == date(2026, 4, 1)

    def test_late_income_shift_before_cutoff(self):
        result = determine_budget_month(
            date(2026, 4, 20), "income", shift_late_income=True, late_income_cutoff_day=25
        )
        assert result == date(2026, 4, 1)

    def test_late_income_shift_after_cutoff(self):
        result = determine_budget_month(
            date(2026, 4, 28), "income", shift_late_income=True, late_income_cutoff_day=25
        )
        assert result == date(2026, 5, 1)

    def test_late_income_shift_december(self):
        result = determine_budget_month(
            date(2026, 12, 28), "income", shift_late_income=True, late_income_cutoff_day=25
        )
        assert result == date(2027, 1, 1)

    def test_expense_ignores_late_income_shift(self):
        result = determine_budget_month(
            date(2026, 4, 28), "expense", shift_late_income=True, late_income_cutoff_day=25
        )
        assert result == date(2026, 4, 1)

    def test_savings_ignores_late_income_shift(self):
        result = determine_budget_month(
            date(2026, 4, 28), "savings", shift_late_income=True, late_income_cutoff_day=25
        )
        assert result == date(2026, 4, 1)


class TestDetermineBudgetMonthEdgeCases:
    def test_late_income_on_cutoff_day_stays_current(self):
        """Income ON the cutoff day stays in current month (only > shifts)."""
        result = determine_budget_month(
            date(2026, 4, 25), "income", shift_late_income=True, late_income_cutoff_day=25
        )
        assert result == date(2026, 4, 1)

    def test_late_income_day_after_cutoff_shifts(self):
        result = determine_budget_month(
            date(2026, 4, 26), "income", shift_late_income=True, late_income_cutoff_day=25
        )
        assert result == date(2026, 5, 1)

    def test_first_of_month_income_no_shift(self):
        result = determine_budget_month(
            date(2026, 1, 1), "income", shift_late_income=True, late_income_cutoff_day=25
        )
        assert result == date(2026, 1, 1)

    def test_last_day_of_feb_income_shifts(self):
        result = determine_budget_month(
            date(2026, 2, 28), "income", shift_late_income=True, late_income_cutoff_day=20
        )
        assert result == date(2026, 3, 1)

    def test_shift_enabled_but_cutoff_none_no_shift(self):
        """If cutoff_day is None, no shift happens even if shift flag is True."""
        result = determine_budget_month(
            date(2026, 4, 28), "income", shift_late_income=True, late_income_cutoff_day=None
        )
        assert result == date(2026, 4, 1)


class TestGetMonthDateRange:
    def test_april(self):
        start, end = get_month_date_range(date(2026, 4, 1))
        assert start == date(2026, 4, 1)
        assert end == date(2026, 4, 30)

    def test_february_non_leap(self):
        start, end = get_month_date_range(date(2026, 2, 1))
        assert start == date(2026, 2, 1)
        assert end == date(2026, 2, 28)

    def test_december(self):
        start, end = get_month_date_range(date(2026, 12, 1))
        assert start == date(2026, 12, 1)
        assert end == date(2026, 12, 31)
