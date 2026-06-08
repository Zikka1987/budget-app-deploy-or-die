"""Shared pytest fixtures.

IMPORTANT: Dummy environment variables MUST be set here (at module import
time, before any test module is collected) so that `app.core.config.Settings()`
can instantiate without a real .env file. The service tests import the
service module, which transitively imports config.py and instantiates
settings at module load.
"""

import os

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon-key")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")

import pytest
from decimal import Decimal


@pytest.fixture
def sample_budget_lines():
    """Sample budget lines for testing month rollover."""
    from app.rules.budget_rules import BudgetLine
    return [
        BudgetLine(category_id="cat-1", planned_amount=Decimal("5000.00")),
        BudgetLine(category_id="cat-2", planned_amount=Decimal("3000.00")),
        BudgetLine(category_id="cat-3", planned_amount=Decimal("1500.00"), notes="old note"),
    ]


@pytest.fixture
def sample_savings_rules():
    """Sample savings rules for testing proposal generation."""
    return [
        {
            "id": "rule-1",
            "category_id": "cat-savings-1",
            "rule_type": "percent_of_income",
            "percent_value": Decimal("10"),
            "fixed_amount": None,
        },
        {
            "id": "rule-2",
            "category_id": "cat-savings-2",
            "rule_type": "fixed_monthly",
            "percent_value": None,
            "fixed_amount": Decimal("2000.00"),
        },
    ]


@pytest.fixture
def sample_receipt_items():
    """Sample receipt items for testing grouping."""
    from uuid import UUID
    return [
        {
            "user_confirmed_category_id": UUID("00000000-0000-0000-0000-000000000001"),
            "total_price": Decimal("25.50"),
            "description": "Maelk",
            "is_excluded": False,
        },
        {
            "user_confirmed_category_id": UUID("00000000-0000-0000-0000-000000000001"),
            "total_price": Decimal("15.00"),
            "description": "Broed",
            "is_excluded": False,
        },
        {
            "user_confirmed_category_id": UUID("00000000-0000-0000-0000-000000000002"),
            "total_price": Decimal("45.00"),
            "description": "Vanish",
            "is_excluded": False,
        },
        {
            "user_confirmed_category_id": UUID("00000000-0000-0000-0000-000000000001"),
            "total_price": Decimal("10.00"),
            "description": "Smor",
            "is_excluded": True,
        },
    ]
