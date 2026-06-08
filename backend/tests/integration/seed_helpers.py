"""Raw-SQL helpers for inserting test data.

Each function uses the test connection directly (no repositories, no service
layer) so that test setup is independent of application code under test.
"""

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
from typing import Optional
from uuid import UUID


async def create_test_user(conn, email: str = "test@example.com") -> UUID:
    """Insert a row into auth.users and return the user id."""
    user_id = uuid.uuid4()
    await conn.execute(
        "INSERT INTO auth.users (id, email) VALUES ($1, $2)",
        user_id,
        email,
    )
    return user_id


async def create_test_household(
    conn,
    user_id: UUID,
    name: str = "Test Household",
    display_name: str = "Owner",
) -> dict:
    """Create household + owner membership + settings. Return IDs."""
    household_id = uuid.uuid4()
    await conn.execute(
        "INSERT INTO households (id, name) VALUES ($1, $2)",
        household_id,
        name,
    )
    member_id = uuid.uuid4()
    await conn.execute(
        """INSERT INTO household_members (id, household_id, user_id, display_name, role)
           VALUES ($1, $2, $3, $4, 'owner')""",
        member_id,
        household_id,
        user_id,
        display_name,
    )
    await conn.execute(
        "INSERT INTO household_settings (household_id) VALUES ($1)",
        household_id,
    )
    return {
        "household_id": household_id,
        "member_id": member_id,
        "user_id": user_id,
    }


async def create_test_category(
    conn,
    household_id: UUID,
    type: str = "expense",
    name: str = "Dagligvarer",
    icon: Optional[str] = None,
    sort_order: int = 0,
) -> dict:
    """Insert a category and return it as a dict."""
    cat_id = uuid.uuid4()
    row = await conn.fetchrow(
        """INSERT INTO categories (id, household_id, type, name, icon, sort_order)
           VALUES ($1, $2, $3::transaction_type, $4, $5, $6)
           RETURNING id, household_id, type::text, name, icon, sort_order,
                     archived_at, created_at, updated_at""",
        cat_id,
        household_id,
        type,
        name,
        icon,
        sort_order,
    )
    return dict(row)


async def create_test_budget_month(
    conn,
    household_id: UUID,
    month: date,
) -> dict:
    """Insert a budget month (month must be 1st of month) and return it."""
    month = date(month.year, month.month, 1)
    bm_id = uuid.uuid4()
    row = await conn.fetchrow(
        """INSERT INTO budget_months (id, household_id, month)
           VALUES ($1, $2, $3)
           RETURNING id, household_id, month, notes, is_closed, created_at, updated_at""",
        bm_id,
        household_id,
        month,
    )
    return dict(row)


async def create_test_budget_line(
    conn,
    budget_month_id: UUID,
    category_id: UUID,
    planned_amount: Decimal = Decimal("1000.00"),
) -> dict:
    """Insert a budget line and return it."""
    bl_id = uuid.uuid4()
    row = await conn.fetchrow(
        """INSERT INTO budget_lines (id, budget_month_id, category_id, planned_amount)
           VALUES ($1, $2, $3, $4)
           RETURNING id, budget_month_id, category_id, planned_amount, notes,
                     created_at, updated_at""",
        bl_id,
        budget_month_id,
        category_id,
        planned_amount,
    )
    return dict(row)


async def create_test_receipt(
    conn,
    household_id: UUID,
    user_id: UUID,
    status: str = "ocr_complete",
    store_name: str = "Netto",
    receipt_date: Optional[date] = None,
    total_amount: Optional[Decimal] = None,
) -> dict:
    """Insert a receipt and return it."""
    receipt_id = uuid.uuid4()
    receipt_date = receipt_date or date(2026, 4, 15)
    row = await conn.fetchrow(
        """INSERT INTO receipts
               (id, household_id, uploaded_by, status, store_name,
                receipt_date, total_amount, storage_path)
           VALUES ($1, $2, $3, $4::receipt_status, $5, $6, $7, $8)
           RETURNING id, household_id, uploaded_by, status::text, store_name,
                     receipt_date, total_amount, storage_path,
                     created_at, updated_at""",
        receipt_id,
        household_id,
        user_id,
        status,
        store_name,
        receipt_date,
        total_amount,
        f"{household_id}/test_{receipt_id}.jpg",
    )
    return dict(row)


async def create_test_receipt_item(
    conn,
    receipt_id: UUID,
    description: str = "Maelk",
    total_price: Decimal = Decimal("25.50"),
    user_confirmed_category_id: Optional[UUID] = None,
    suggested_category_id: Optional[UUID] = None,
    is_excluded: bool = False,
    requires_review: bool = False,
    line_number: Optional[int] = None,
) -> dict:
    """Insert a receipt item and return it."""
    item_id = uuid.uuid4()
    row = await conn.fetchrow(
        """INSERT INTO receipt_items
               (id, receipt_id, line_number, description, total_price,
                suggested_category_id, user_confirmed_category_id,
                is_excluded, requires_review)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
           RETURNING id, receipt_id, line_number, description, total_price,
                     suggested_category_id, user_confirmed_category_id,
                     is_excluded, requires_review, created_at, updated_at""",
        item_id,
        receipt_id,
        line_number,
        description,
        total_price,
        suggested_category_id,
        user_confirmed_category_id,
        is_excluded,
        requires_review,
    )
    return dict(row)


async def create_test_invite(
    conn,
    household_id: UUID,
    invited_by: UUID,
    email: str,
    token: Optional[str] = None,
    expires_at: Optional[datetime] = None,
) -> tuple[dict, str]:
    """Insert a pending invite. Returns (row_dict, raw_token)."""
    import secrets

    raw_token = token or secrets.token_urlsafe(32)
    token_hash = sha256(raw_token.encode()).hexdigest()
    expires_at = expires_at or (datetime.now(timezone.utc) + timedelta(days=7))
    invite_id = uuid.uuid4()
    row = await conn.fetchrow(
        """INSERT INTO household_invites
               (id, household_id, invited_by_user_id, email, token_hash,
                status, expires_at)
           VALUES ($1, $2, $3, $4, $5, 'pending', $6)
           RETURNING id, household_id, invited_by_user_id, email,
                     token_hash, status::text, expires_at,
                     created_at, accepted_at, accepted_by_user_id, revoked_at""",
        invite_id,
        household_id,
        invited_by,
        email,
        token_hash,
        expires_at,
    )
    return dict(row), raw_token


async def create_test_savings_rule(
    conn,
    household_id: UUID,
    category_id: UUID,
    user_id: UUID,
    rule_type: str = "fixed_monthly",
    label: str = "Test Savings",
    percent_value: Optional[Decimal] = None,
    fixed_amount: Optional[Decimal] = None,
) -> dict:
    """Insert a savings rule and return it."""
    rule_id = uuid.uuid4()
    if rule_type == "fixed_monthly" and fixed_amount is None:
        fixed_amount = Decimal("2000.00")
    if rule_type == "percent_of_income" and percent_value is None:
        percent_value = Decimal("10.00")
    row = await conn.fetchrow(
        """INSERT INTO savings_rules
               (id, household_id, category_id, rule_type, label,
                percent_value, fixed_amount, created_by)
           VALUES ($1, $2, $3, $4::savings_rule_type, $5, $6, $7, $8)
           RETURNING id, household_id, category_id, rule_type::text, label,
                     percent_value, fixed_amount, is_active,
                     created_by, created_at, updated_at""",
        rule_id,
        household_id,
        category_id,
        rule_type,
        label,
        percent_value,
        fixed_amount,
        user_id,
    )
    return dict(row)


async def create_test_savings_proposal(
    conn,
    household_id: UUID,
    savings_rule_id: UUID,
    budget_month_id: UUID,
    proposed_amount: Decimal = Decimal("2000.00"),
    status: str = "pending",
) -> dict:
    """Insert a savings proposal and return it."""
    proposal_id = uuid.uuid4()
    row = await conn.fetchrow(
        """INSERT INTO savings_proposals
               (id, household_id, savings_rule_id, budget_month_id,
                proposed_amount, status)
           VALUES ($1, $2, $3, $4, $5, $6::proposal_status)
           RETURNING id, household_id, savings_rule_id, budget_month_id,
                     proposed_amount, final_amount, status::text,
                     transaction_id, created_at, updated_at""",
        proposal_id,
        household_id,
        savings_rule_id,
        budget_month_id,
        proposed_amount,
        status,
    )
    return dict(row)


async def create_test_transaction(
    conn,
    household_id: UUID,
    user_id: UUID,
    category_id: UUID,
    budget_month_id: UUID,
    amount: Decimal = Decimal("100.00"),
    type: str = "expense",
    source: str = "manual_expense",
    transaction_date: Optional[date] = None,
    description: str = "Test txn",
) -> dict:
    """Insert a transaction_group + transaction. Return the transaction row."""
    transaction_date = transaction_date or date(2026, 4, 15)
    idempotency_key = f"test:{uuid.uuid4()}"

    group_id = uuid.uuid4()
    await conn.execute(
        """INSERT INTO transaction_groups
               (id, household_id, source, idempotency_key, created_by)
           VALUES ($1, $2, $3::transaction_source, $4, $5)""",
        group_id,
        household_id,
        source,
        idempotency_key,
        user_id,
    )

    txn_id = uuid.uuid4()
    row = await conn.fetchrow(
        """INSERT INTO transactions
               (id, group_id, household_id, type, category_id, amount,
                description, transaction_date, effective_date,
                budget_month_id, source, posted_by)
           VALUES ($1, $2, $3, $4::transaction_type, $5, $6, $7, $8, $9, $10,
                   $11::transaction_source, $12)
           RETURNING id, group_id, household_id, type::text, category_id,
                     amount, description, transaction_date, effective_date,
                     budget_month_id, source::text, posted_by,
                     created_at, updated_at""",
        txn_id,
        group_id,
        household_id,
        type,
        category_id,
        amount,
        description,
        transaction_date,
        transaction_date,
        budget_month_id,
        source,
        user_id,
    )
    return dict(row)
