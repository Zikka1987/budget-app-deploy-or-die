"""Pure functions for savings calculations. No DB access."""

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP


@dataclass
class SavingsProposal:
    savings_rule_id: str
    category_id: str
    proposed_amount: Decimal
    calculation_basis: dict


def calculate_percent_savings(
    total_income: Decimal,
    percent_value: Decimal,
) -> Decimal:
    """Calculate savings amount as a percentage of total income.

    Example: total_income=45000, percent_value=10 -> 4500.00
    """
    return (total_income * percent_value / Decimal("100")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


def calculate_fixed_savings(fixed_amount: Decimal) -> Decimal:
    """Fixed monthly savings — just returns the amount (identity, for consistency)."""
    return fixed_amount


def build_proposals(
    rules: list[dict],
    total_income: Decimal,
) -> list[SavingsProposal]:
    """Build savings proposals from active rules and total income for the month.

    Each rule dict must have: id, category_id, rule_type, percent_value, fixed_amount.
    Returns one SavingsProposal per rule.
    """
    proposals = []
    for rule in rules:
        rule_type = rule["rule_type"]
        if rule_type == "percent_of_income":
            amount = calculate_percent_savings(total_income, rule["percent_value"])
            basis = {
                "rule_type": rule_type,
                "total_income": str(total_income),
                "percent": str(rule["percent_value"]),
            }
        elif rule_type == "fixed_monthly":
            amount = calculate_fixed_savings(rule["fixed_amount"])
            basis = {
                "rule_type": rule_type,
                "fixed_amount": str(rule["fixed_amount"]),
            }
        else:
            continue

        if amount > 0:
            proposals.append(
                SavingsProposal(
                    savings_rule_id=rule["id"],
                    category_id=rule["category_id"],
                    proposed_amount=amount,
                    calculation_basis=basis,
                )
            )
    return proposals
