-- ============================================================
-- Budget App - Initial Schema Migration
-- ============================================================
-- Direct Postgres schema. Supabase hosts the DB; asyncpg connects directly.
-- Business logic lives in Python/FastAPI, not in triggers.
-- ============================================================

-- 0. Extensions
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ============================================================
-- 1. ENUM TYPES
-- ============================================================

CREATE TYPE transaction_type AS ENUM ('income', 'expense', 'savings');

CREATE TYPE receipt_status AS ENUM (
    'uploaded',
    'processing',
    'ocr_complete',
    'reviewed',
    'posted',
    'failed'
);

CREATE TYPE savings_rule_type AS ENUM (
    'percent_of_income',
    'fixed_monthly'
);

CREATE TYPE proposal_status AS ENUM (
    'pending',
    'approved',
    'rejected',
    'posted'
);

CREATE TYPE transaction_source AS ENUM (
    'manual_income',
    'manual_expense',
    'manual_savings',
    'receipt',
    'savings_proposal'
);

-- ============================================================
-- 2. HELPER FUNCTION: resolve household for current auth user
-- ============================================================
-- Used by RLS policies. Returns NULL if no membership found.
-- SECURITY DEFINER so it can read household_members regardless of RLS.

CREATE OR REPLACE FUNCTION get_household_id()
RETURNS UUID
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT household_id
    FROM household_members
    WHERE user_id = auth.uid()
    LIMIT 1;
$$;

-- ============================================================
-- 3. TABLES
-- ============================================================

-- 3a. households
CREATE TABLE households (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 3b. household_members
-- UNIQUE(user_id) enforces one household per user (v1 constraint).
CREATE TABLE household_members (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    household_id    UUID NOT NULL REFERENCES households(id) ON DELETE CASCADE,
    user_id         UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    display_name    TEXT NOT NULL,
    role            TEXT NOT NULL DEFAULT 'member'
                        CHECK (role IN ('owner', 'member')),
    joined_at       TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (user_id),
    UNIQUE (household_id, user_id)
);

CREATE INDEX idx_hm_user_id ON household_members(user_id);
CREATE INDEX idx_hm_household_id ON household_members(household_id);

-- 3c. household_settings
CREATE TABLE household_settings (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    household_id            UUID NOT NULL UNIQUE REFERENCES households(id) ON DELETE CASCADE,
    currency                TEXT NOT NULL DEFAULT 'DKK' CHECK (currency = 'DKK'),
    shift_late_income       BOOLEAN NOT NULL DEFAULT FALSE,
    late_income_cutoff_day  INT CHECK (late_income_cutoff_day BETWEEN 1 AND 28),
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- If shift is enabled, cutoff day must be set
    CHECK (
        (shift_late_income = FALSE)
        OR
        (shift_late_income = TRUE AND late_income_cutoff_day IS NOT NULL)
    )
);

-- 3d. categories
CREATE TABLE categories (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    household_id    UUID NOT NULL REFERENCES households(id) ON DELETE CASCADE,
    type            transaction_type NOT NULL,
    name            TEXT NOT NULL,
    icon            TEXT,
    sort_order      INT NOT NULL DEFAULT 0,
    archived_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (household_id, type, name)
);

-- Active categories by household and type (most common query)
CREATE INDEX idx_cat_household_type ON categories(household_id, type)
    WHERE archived_at IS NULL;

-- 3e. category_aliases
-- Historical names created when a category is renamed.
CREATE TABLE category_aliases (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    category_id     UUID NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
    alias           TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_cat_alias_category ON category_aliases(category_id);
CREATE INDEX idx_cat_alias_text ON category_aliases(alias text_pattern_ops);

-- 3f. budget_months
-- One per household per calendar month. Month is always the 1st.
CREATE TABLE budget_months (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    household_id    UUID NOT NULL REFERENCES households(id) ON DELETE CASCADE,
    month           DATE NOT NULL,
    notes           TEXT,
    is_closed       BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (household_id, month),
    CHECK (EXTRACT(DAY FROM month) = 1)
);

CREATE INDEX idx_bm_household_month ON budget_months(household_id, month);

-- 3g. budget_lines
-- Planned amount per category per budget month.
CREATE TABLE budget_lines (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    budget_month_id UUID NOT NULL REFERENCES budget_months(id) ON DELETE CASCADE,
    category_id     UUID NOT NULL REFERENCES categories(id) ON DELETE RESTRICT,
    planned_amount  NUMERIC(12,2) NOT NULL DEFAULT 0 CHECK (planned_amount >= 0),
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (budget_month_id, category_id)
);

CREATE INDEX idx_bl_budget_month ON budget_lines(budget_month_id);
CREATE INDEX idx_bl_category ON budget_lines(category_id);

-- 3h. receipts
CREATE TABLE receipts (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    household_id    UUID NOT NULL REFERENCES households(id) ON DELETE CASCADE,
    uploaded_by     UUID NOT NULL REFERENCES auth.users(id),
    status          receipt_status NOT NULL DEFAULT 'uploaded',

    -- Extracted / manual metadata
    store_name      TEXT,
    receipt_date    DATE,
    total_amount    NUMERIC(12,2),
    ocr_raw_text    TEXT,

    -- Storage reference
    storage_path    TEXT NOT NULL,
    file_name       TEXT,
    mime_type       TEXT,

    -- Processing metadata
    ocr_provider    TEXT,
    ocr_confidence  NUMERIC(5,4),
    error_message   TEXT,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_receipt_household ON receipts(household_id);
CREATE INDEX idx_receipt_household_status ON receipts(household_id, status);
CREATE INDEX idx_receipt_household_date ON receipts(household_id, receipt_date);
CREATE INDEX idx_receipt_store_name ON receipts(household_id, store_name)
    WHERE store_name IS NOT NULL;

-- Full-text search on OCR text + store name
CREATE INDEX idx_receipt_ocr_search ON receipts
    USING gin(to_tsvector('simple', COALESCE(ocr_raw_text, '') || ' ' || COALESCE(store_name, '')));

-- 3i. receipt_items
-- Line items extracted by AI. Tracks both AI suggestion and user-confirmed category.
CREATE TABLE receipt_items (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    receipt_id                  UUID NOT NULL REFERENCES receipts(id) ON DELETE CASCADE,
    line_number                 INT,
    description                 TEXT NOT NULL,
    quantity                    NUMERIC(10,3) DEFAULT 1,
    unit_price                  NUMERIC(12,2),
    total_price                 NUMERIC(12,2) NOT NULL,

    -- AI suggestion (set after categorization)
    suggested_category_id       UUID REFERENCES categories(id) ON DELETE SET NULL,
    confidence                  NUMERIC(5,4),
    requires_review             BOOLEAN NOT NULL DEFAULT TRUE,

    -- User-confirmed (set during review, used for transaction creation)
    user_confirmed_category_id  UUID REFERENCES categories(id) ON DELETE SET NULL,

    is_excluded                 BOOLEAN NOT NULL DEFAULT FALSE,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_ri_receipt ON receipt_items(receipt_id);

-- 3j. transaction_groups
-- Groups transactions from a single event. One receipt = one group = N transactions.
-- Manual entry = one group = one transaction.
CREATE TABLE transaction_groups (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    household_id    UUID NOT NULL REFERENCES households(id) ON DELETE CASCADE,
    receipt_id      UUID REFERENCES receipts(id) ON DELETE SET NULL,
    source          transaction_source NOT NULL,
    description     TEXT,
    idempotency_key TEXT NOT NULL,
    created_by      UUID NOT NULL REFERENCES auth.users(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (idempotency_key)
);

CREATE INDEX idx_tg_household ON transaction_groups(household_id);
CREATE INDEX idx_tg_receipt ON transaction_groups(receipt_id) WHERE receipt_id IS NOT NULL;
CREATE INDEX idx_tg_source ON transaction_groups(household_id, source);

-- 3k. transactions
-- The ledger. Amounts are always positive; type indicates direction.
CREATE TABLE transactions (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    group_id            UUID NOT NULL REFERENCES transaction_groups(id) ON DELETE CASCADE,
    household_id        UUID NOT NULL REFERENCES households(id) ON DELETE CASCADE,
    type                transaction_type NOT NULL,
    category_id         UUID NOT NULL REFERENCES categories(id) ON DELETE RESTRICT,
    amount              NUMERIC(12,2) NOT NULL CHECK (amount > 0),
    description         TEXT,
    details             TEXT,
    transaction_date    DATE NOT NULL,
    effective_date      DATE NOT NULL,
    budget_month_id     UUID REFERENCES budget_months(id) ON DELETE SET NULL,
    source              transaction_source NOT NULL,
    posted_by           UUID NOT NULL REFERENCES auth.users(id),

    savings_proposal_id UUID,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_txn_household_date ON transactions(household_id, effective_date);
CREATE INDEX idx_txn_household_type ON transactions(household_id, type);
CREATE INDEX idx_txn_household_budget ON transactions(household_id, budget_month_id);
CREATE INDEX idx_txn_category ON transactions(category_id);
CREATE INDEX idx_txn_group ON transactions(group_id);
CREATE INDEX idx_txn_source ON transactions(household_id, source);
CREATE INDEX idx_txn_savings_proposal ON transactions(savings_proposal_id)
    WHERE savings_proposal_id IS NOT NULL;

-- 3l. savings_rules
-- Automatable savings behaviors only (percent_of_income, fixed_monthly).
-- Manual savings goes through normal transaction flow.
CREATE TABLE savings_rules (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    household_id    UUID NOT NULL REFERENCES households(id) ON DELETE CASCADE,
    category_id     UUID NOT NULL REFERENCES categories(id) ON DELETE RESTRICT,
    rule_type       savings_rule_type NOT NULL,
    label           TEXT NOT NULL,

    percent_value   NUMERIC(5,2) CHECK (percent_value > 0 AND percent_value <= 100),
    fixed_amount    NUMERIC(12,2) CHECK (fixed_amount > 0),

    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_by      UUID NOT NULL REFERENCES auth.users(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    CHECK (
        (rule_type = 'percent_of_income' AND percent_value IS NOT NULL AND fixed_amount IS NULL)
        OR
        (rule_type = 'fixed_monthly' AND fixed_amount IS NOT NULL AND percent_value IS NULL)
    )
);

CREATE INDEX idx_sr_household ON savings_rules(household_id) WHERE is_active = TRUE;

-- 3m. savings_proposals
-- Generated monthly by Python. User reviews, approves/rejects. Approved ones become transactions.
CREATE TABLE savings_proposals (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    household_id        UUID NOT NULL REFERENCES households(id) ON DELETE CASCADE,
    savings_rule_id     UUID NOT NULL REFERENCES savings_rules(id) ON DELETE CASCADE,
    budget_month_id     UUID NOT NULL REFERENCES budget_months(id) ON DELETE CASCADE,

    proposed_amount     NUMERIC(12,2) NOT NULL CHECK (proposed_amount > 0),
    final_amount        NUMERIC(12,2) CHECK (final_amount > 0),
    status              proposal_status NOT NULL DEFAULT 'pending',

    calculation_basis   JSONB,

    reviewed_by         UUID REFERENCES auth.users(id),
    reviewed_at         TIMESTAMPTZ,
    transaction_id      UUID,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (savings_rule_id, budget_month_id)
);

CREATE INDEX idx_sp_household_status ON savings_proposals(household_id, status);
CREATE INDEX idx_sp_budget_month ON savings_proposals(budget_month_id);

-- Deferred foreign keys (circular references)
ALTER TABLE transactions
    ADD CONSTRAINT fk_txn_savings_proposal
    FOREIGN KEY (savings_proposal_id) REFERENCES savings_proposals(id)
    ON DELETE SET NULL;

ALTER TABLE savings_proposals
    ADD CONSTRAINT fk_sp_transaction
    FOREIGN KEY (transaction_id) REFERENCES transactions(id)
    ON DELETE SET NULL;

-- ============================================================
-- 4. ROW LEVEL SECURITY
-- ============================================================

ALTER TABLE households ENABLE ROW LEVEL SECURITY;
ALTER TABLE household_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE household_settings ENABLE ROW LEVEL SECURITY;
ALTER TABLE categories ENABLE ROW LEVEL SECURITY;
ALTER TABLE category_aliases ENABLE ROW LEVEL SECURITY;
ALTER TABLE budget_months ENABLE ROW LEVEL SECURITY;
ALTER TABLE budget_lines ENABLE ROW LEVEL SECURITY;
ALTER TABLE receipts ENABLE ROW LEVEL SECURITY;
ALTER TABLE receipt_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE transaction_groups ENABLE ROW LEVEL SECURITY;
ALTER TABLE transactions ENABLE ROW LEVEL SECURITY;
ALTER TABLE savings_rules ENABLE ROW LEVEL SECURITY;
ALTER TABLE savings_proposals ENABLE ROW LEVEL SECURITY;

-- households
CREATE POLICY "Users can view their household"
    ON households FOR SELECT USING (id = get_household_id());
CREATE POLICY "Users can update their household"
    ON households FOR UPDATE USING (id = get_household_id());

-- household_members
CREATE POLICY "Members can view co-members"
    ON household_members FOR SELECT USING (household_id = get_household_id());
CREATE POLICY "Members can insert into their household"
    ON household_members FOR INSERT WITH CHECK (household_id = get_household_id());
CREATE POLICY "Members can delete from their household"
    ON household_members FOR DELETE USING (household_id = get_household_id());

-- household_settings
CREATE POLICY "Members can view household settings"
    ON household_settings FOR SELECT USING (household_id = get_household_id());
CREATE POLICY "Members can update household settings"
    ON household_settings FOR UPDATE USING (household_id = get_household_id());
CREATE POLICY "Members can insert household settings"
    ON household_settings FOR INSERT WITH CHECK (household_id = get_household_id());

-- categories
CREATE POLICY "Household categories select"
    ON categories FOR SELECT USING (household_id = get_household_id());
CREATE POLICY "Household categories insert"
    ON categories FOR INSERT WITH CHECK (household_id = get_household_id());
CREATE POLICY "Household categories update"
    ON categories FOR UPDATE USING (household_id = get_household_id());

-- category_aliases (via join to category)
CREATE POLICY "Household category_aliases select"
    ON category_aliases FOR SELECT USING (
        EXISTS (SELECT 1 FROM categories c WHERE c.id = category_aliases.category_id AND c.household_id = get_household_id())
    );
CREATE POLICY "Household category_aliases insert"
    ON category_aliases FOR INSERT WITH CHECK (
        EXISTS (SELECT 1 FROM categories c WHERE c.id = category_aliases.category_id AND c.household_id = get_household_id())
    );

-- budget_months
CREATE POLICY "Household budget_months select"
    ON budget_months FOR SELECT USING (household_id = get_household_id());
CREATE POLICY "Household budget_months insert"
    ON budget_months FOR INSERT WITH CHECK (household_id = get_household_id());
CREATE POLICY "Household budget_months update"
    ON budget_months FOR UPDATE USING (household_id = get_household_id());

-- budget_lines (via join to budget_months)
CREATE POLICY "Household budget_lines select"
    ON budget_lines FOR SELECT USING (
        EXISTS (SELECT 1 FROM budget_months bm WHERE bm.id = budget_lines.budget_month_id AND bm.household_id = get_household_id())
    );
CREATE POLICY "Household budget_lines insert"
    ON budget_lines FOR INSERT WITH CHECK (
        EXISTS (SELECT 1 FROM budget_months bm WHERE bm.id = budget_lines.budget_month_id AND bm.household_id = get_household_id())
    );
CREATE POLICY "Household budget_lines update"
    ON budget_lines FOR UPDATE USING (
        EXISTS (SELECT 1 FROM budget_months bm WHERE bm.id = budget_lines.budget_month_id AND bm.household_id = get_household_id())
    );

-- receipts
CREATE POLICY "Household receipts select"
    ON receipts FOR SELECT USING (household_id = get_household_id());
CREATE POLICY "Household receipts insert"
    ON receipts FOR INSERT WITH CHECK (household_id = get_household_id());
CREATE POLICY "Household receipts update"
    ON receipts FOR UPDATE USING (household_id = get_household_id());

-- receipt_items (via join to receipt)
CREATE POLICY "Household receipt_items select"
    ON receipt_items FOR SELECT USING (
        EXISTS (SELECT 1 FROM receipts r WHERE r.id = receipt_items.receipt_id AND r.household_id = get_household_id())
    );
CREATE POLICY "Household receipt_items insert"
    ON receipt_items FOR INSERT WITH CHECK (
        EXISTS (SELECT 1 FROM receipts r WHERE r.id = receipt_items.receipt_id AND r.household_id = get_household_id())
    );
CREATE POLICY "Household receipt_items update"
    ON receipt_items FOR UPDATE USING (
        EXISTS (SELECT 1 FROM receipts r WHERE r.id = receipt_items.receipt_id AND r.household_id = get_household_id())
    );

-- transaction_groups
CREATE POLICY "Household transaction_groups select"
    ON transaction_groups FOR SELECT USING (household_id = get_household_id());
CREATE POLICY "Household transaction_groups insert"
    ON transaction_groups FOR INSERT WITH CHECK (household_id = get_household_id());

-- transactions
CREATE POLICY "Household transactions select"
    ON transactions FOR SELECT USING (household_id = get_household_id());
CREATE POLICY "Household transactions insert"
    ON transactions FOR INSERT WITH CHECK (household_id = get_household_id());
CREATE POLICY "Household transactions update"
    ON transactions FOR UPDATE USING (household_id = get_household_id());
CREATE POLICY "Household transactions delete"
    ON transactions FOR DELETE USING (household_id = get_household_id());

-- savings_rules
CREATE POLICY "Household savings_rules select"
    ON savings_rules FOR SELECT USING (household_id = get_household_id());
CREATE POLICY "Household savings_rules insert"
    ON savings_rules FOR INSERT WITH CHECK (household_id = get_household_id());
CREATE POLICY "Household savings_rules update"
    ON savings_rules FOR UPDATE USING (household_id = get_household_id());

-- savings_proposals
CREATE POLICY "Household savings_proposals select"
    ON savings_proposals FOR SELECT USING (household_id = get_household_id());
CREATE POLICY "Household savings_proposals insert"
    ON savings_proposals FOR INSERT WITH CHECK (household_id = get_household_id());
CREATE POLICY "Household savings_proposals update"
    ON savings_proposals FOR UPDATE USING (household_id = get_household_id());

-- ============================================================
-- 5. STORAGE BUCKET
-- ============================================================

INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
VALUES (
    'receipts',
    'receipts',
    FALSE,
    10485760,  -- 10 MB
    ARRAY['image/jpeg', 'image/png', 'image/webp', 'application/pdf']
);

CREATE POLICY "Household members can upload receipts"
    ON storage.objects FOR INSERT WITH CHECK (
        bucket_id = 'receipts'
        AND (storage.foldername(name))[1]::UUID = get_household_id()
    );

CREATE POLICY "Household members can view receipts"
    ON storage.objects FOR SELECT USING (
        bucket_id = 'receipts'
        AND (storage.foldername(name))[1]::UUID = get_household_id()
    );

CREATE POLICY "Household members can delete receipts"
    ON storage.objects FOR DELETE USING (
        bucket_id = 'receipts'
        AND (storage.foldername(name))[1]::UUID = get_household_id()
    );

-- ============================================================
-- 6. UPDATED_AT TRIGGER (infrastructure, not business logic)
-- ============================================================

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

CREATE TRIGGER set_updated_at BEFORE UPDATE ON households
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER set_updated_at BEFORE UPDATE ON household_settings
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER set_updated_at BEFORE UPDATE ON categories
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER set_updated_at BEFORE UPDATE ON budget_months
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER set_updated_at BEFORE UPDATE ON budget_lines
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER set_updated_at BEFORE UPDATE ON receipts
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER set_updated_at BEFORE UPDATE ON receipt_items
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER set_updated_at BEFORE UPDATE ON transactions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER set_updated_at BEFORE UPDATE ON savings_rules
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER set_updated_at BEFORE UPDATE ON savings_proposals
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
