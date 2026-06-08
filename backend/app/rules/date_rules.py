"""Pure functions for date and budget month logic. No DB access."""

from datetime import date


def determine_budget_month(
    effective_date: date,
    transaction_type: str,
    shift_late_income: bool = False,
    late_income_cutoff_day: int | None = None,
) -> date:
    """Determine which budget month a transaction belongs to.

    Returns the 1st of the budget month.

    For income with late-income shift enabled:
    - If effective_date.day > cutoff_day, shifts to next month.
    - Example: cutoff=25, date=Dec 28 -> January 1st (next year).

    For expenses and savings, always uses the calendar month of effective_date.
    """
    if (
        transaction_type == "income"
        and shift_late_income
        and late_income_cutoff_day is not None
        and effective_date.day > late_income_cutoff_day
    ):
        # Shift to next month
        if effective_date.month == 12:
            return date(effective_date.year + 1, 1, 1)
        return date(effective_date.year, effective_date.month + 1, 1)

    return date(effective_date.year, effective_date.month, 1)


def get_month_date_range(month: date) -> tuple[date, date]:
    """Get the start and end dates for a calendar month.

    Args:
        month: First day of the month (e.g., date(2026, 4, 1))

    Returns:
        Tuple of (first_day, last_day) inclusive.
    """
    first_day = date(month.year, month.month, 1)
    if month.month == 12:
        last_day = date(month.year + 1, 1, 1)
    else:
        last_day = date(month.year, month.month + 1, 1)
    # last_day is exclusive; subtract one day for inclusive range
    from datetime import timedelta
    last_day = last_day - timedelta(days=1)
    return first_day, last_day
