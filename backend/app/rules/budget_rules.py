"""Pure functions for budget calculations. No DB access."""

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP

TWO_PLACES = Decimal("0.01")


def _q(value: Decimal) -> Decimal:
    """Quantize a Decimal to 2 decimal places."""
    return value.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


@dataclass
class BudgetLine:
    category_id: str
    planned_amount: Decimal
    notes: str | None = None


@dataclass
class BudgetSummary:
    total_planned_income: Decimal
    total_planned_expenses: Decimal
    total_planned_savings: Decimal
    total_actual_income: Decimal
    total_actual_expenses: Decimal
    total_actual_savings: Decimal
    to_be_allocated: Decimal


@dataclass
class CategoryBudgetActualData:
    category_id: str
    category_name: str
    category_type: str
    planned: Decimal
    actual: Decimal
    remaining: Decimal
    is_over_budget: bool


@dataclass
class DashboardData:
    month: str
    total_planned_income: Decimal
    total_planned_expenses: Decimal
    total_planned_savings: Decimal
    total_actual_income: Decimal
    total_actual_expenses: Decimal
    total_actual_savings: Decimal
    to_be_allocated: Decimal
    actual_balance: Decimal
    plan_coverage: Decimal
    savings_rate: Decimal | None
    income_categories: list[CategoryBudgetActualData] = field(default_factory=list)
    expense_categories: list[CategoryBudgetActualData] = field(default_factory=list)
    savings_categories: list[CategoryBudgetActualData] = field(default_factory=list)


def copy_month_structure(
    previous_lines: list[BudgetLine],
) -> list[BudgetLine]:
    """Copy budget lines from previous month to create new month structure.

    Returns new BudgetLine objects with the same category_id and planned_amount.
    """
    return [
        BudgetLine(
            category_id=line.category_id,
            planned_amount=line.planned_amount,
            notes=None,
        )
        for line in previous_lines
    ]


def compute_to_be_allocated(
    total_actual_income: Decimal,
    total_planned_expenses: Decimal,
    total_planned_savings: Decimal,
) -> Decimal:
    """Compute remaining income not yet allocated to expense or savings budgets.

    to_be_allocated = actual_income - planned_expenses - planned_savings
    """
    return total_actual_income - total_planned_expenses - total_planned_savings


def compute_budget_summary(
    planned_income: Decimal,
    planned_expenses: Decimal,
    planned_savings: Decimal,
    actual_income: Decimal,
    actual_expenses: Decimal,
    actual_savings: Decimal,
) -> BudgetSummary:
    """Compute full budget summary for a month."""
    return BudgetSummary(
        total_planned_income=planned_income,
        total_planned_expenses=planned_expenses,
        total_planned_savings=planned_savings,
        total_actual_income=actual_income,
        total_actual_expenses=actual_expenses,
        total_actual_savings=actual_savings,
        to_be_allocated=compute_to_be_allocated(
            actual_income, planned_expenses, planned_savings
        ),
    )


# ── Dashboard pure functions ──


def compute_category_budget_actual(
    category_id: str,
    category_name: str,
    category_type: str,
    planned: Decimal,
    actual: Decimal,
) -> CategoryBudgetActualData:
    """Compute budget-vs-actual for a single category.

    For expense/savings: is_over_budget = actual > planned.
    For income: is_over_budget = False always (exceeding income plan is good).
    remaining = planned - actual for all types.
    """
    planned = _q(planned)
    actual = _q(actual)
    remaining = _q(planned - actual)
    if category_type == "income":
        is_over_budget = False
    else:
        is_over_budget = actual > planned
    return CategoryBudgetActualData(
        category_id=category_id,
        category_name=category_name,
        category_type=category_type,
        planned=planned,
        actual=actual,
        remaining=remaining,
        is_over_budget=is_over_budget,
    )


def compute_planned_to_be_allocated(
    planned_income: Decimal,
    planned_expenses: Decimal,
    planned_savings: Decimal,
) -> Decimal:
    """How much of the plan is unassigned.

    to_be_allocated = planned_income - planned_expenses - planned_savings
    """
    return _q(planned_income - planned_expenses - planned_savings)


def compute_actual_balance(
    actual_income: Decimal,
    actual_expenses: Decimal,
    actual_savings: Decimal,
) -> Decimal:
    """What actually remains.

    actual_balance = actual_income - actual_expenses - actual_savings
    """
    return _q(actual_income - actual_expenses - actual_savings)


def compute_plan_coverage(
    actual_income: Decimal,
    planned_expenses: Decimal,
    planned_savings: Decimal,
) -> Decimal:
    """Can actual income cover the plan?

    plan_coverage = actual_income - planned_expenses - planned_savings
    """
    return _q(actual_income - planned_expenses - planned_savings)


def compute_savings_rate(
    total_savings: Decimal,
    total_income: Decimal,
) -> Decimal | None:
    """Savings as a percentage of income. None if income is zero.

    Returns Decimal percentage (e.g. Decimal("10.00") for 10%).
    """
    if total_income == 0:
        return None
    return (total_savings / total_income * Decimal("100")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


def build_dashboard_data(
    month: str,
    budget_lines: list[dict],
    actuals_by_category: list[dict],
) -> DashboardData:
    """Assemble full dashboard from budget lines and actual transaction sums.

    budget_lines: list of dicts with category_id, category_name, category_type, planned_amount
    actuals_by_category: list of dicts with type, category_id, category_name, total

    Categories appear if they have a budget line OR actuals (or both).
    """
    # Index budget lines by category_id
    planned_map: dict[str, dict] = {}
    for line in budget_lines:
        cid = str(line["category_id"])
        planned_map[cid] = {
            "category_name": line["category_name"],
            "category_type": str(line["category_type"]),
            "planned": Decimal(str(line["planned_amount"])),
        }

    # Index actuals by category_id
    actual_map: dict[str, dict] = {}
    for row in actuals_by_category:
        cid = str(row["category_id"])
        actual_map[cid] = {
            "category_name": row["category_name"],
            "category_type": str(row["type"]),
            "actual": Decimal(str(row["total"])),
        }

    # Merge: all category_ids from both sources
    all_ids = set(planned_map.keys()) | set(actual_map.keys())

    categories: list[CategoryBudgetActualData] = []
    for cid in all_ids:
        p = planned_map.get(cid)
        a = actual_map.get(cid)
        cat_name = (p or a)["category_name"]
        cat_type = (p or a)["category_type"]
        planned = p["planned"] if p else Decimal("0")
        actual = a["actual"] if a else Decimal("0")
        categories.append(
            compute_category_budget_actual(cid, cat_name, cat_type, planned, actual)
        )

    # Split by type
    income_cats = [c for c in categories if c.category_type == "income"]
    expense_cats = [c for c in categories if c.category_type == "expense"]
    savings_cats = [c for c in categories if c.category_type == "savings"]

    # Compute totals (already 2dp from compute_category_budget_actual, but _q for safety)
    total_planned_income = _q(sum((c.planned for c in income_cats), Decimal("0")))
    total_planned_expenses = _q(sum((c.planned for c in expense_cats), Decimal("0")))
    total_planned_savings = _q(sum((c.planned for c in savings_cats), Decimal("0")))
    total_actual_income = _q(sum((c.actual for c in income_cats), Decimal("0")))
    total_actual_expenses = _q(sum((c.actual for c in expense_cats), Decimal("0")))
    total_actual_savings = _q(sum((c.actual for c in savings_cats), Decimal("0")))

    return DashboardData(
        month=month,
        total_planned_income=total_planned_income,
        total_planned_expenses=total_planned_expenses,
        total_planned_savings=total_planned_savings,
        total_actual_income=total_actual_income,
        total_actual_expenses=total_actual_expenses,
        total_actual_savings=total_actual_savings,
        to_be_allocated=compute_planned_to_be_allocated(
            total_planned_income, total_planned_expenses, total_planned_savings
        ),
        actual_balance=compute_actual_balance(
            total_actual_income, total_actual_expenses, total_actual_savings
        ),
        plan_coverage=compute_plan_coverage(
            total_actual_income, total_planned_expenses, total_planned_savings
        ),
        savings_rate=compute_savings_rate(total_actual_savings, total_actual_income),
        income_categories=income_cats,
        expense_categories=expense_cats,
        savings_categories=savings_cats,
    )
