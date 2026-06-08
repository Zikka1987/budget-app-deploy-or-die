-- ============================================================
-- Budget App - Household Invites Migration
-- ============================================================
-- Second-user invite / join flow. Verified JWT email must equal the
-- invite email at accept time; the invite token is stored as a
-- SHA-256 hex digest (raw token is never persisted).
-- ============================================================

-- 1. Status enum
CREATE TYPE household_invite_status AS ENUM (
    'pending',
    'accepted',
    'revoked',
    'expired'
);

-- 2. Invites table
CREATE TABLE household_invites (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    household_id         UUID NOT NULL REFERENCES households(id) ON DELETE CASCADE,
    invited_by_user_id   UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    email                TEXT NOT NULL,
    token_hash           TEXT NOT NULL,
    status               household_invite_status NOT NULL DEFAULT 'pending',
    expires_at           TIMESTAMPTZ NOT NULL,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    accepted_at          TIMESTAMPTZ,
    accepted_by_user_id  UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    revoked_at           TIMESTAMPTZ,

    CONSTRAINT chk_hi_email_normalized CHECK (email = lower(email)),
    CONSTRAINT chk_hi_email_length     CHECK (char_length(email) BETWEEN 3 AND 254),
    -- `accepted_at` is set exactly when status becomes `accepted` and is never
    -- modified after. Safe against auth.users deletion.
    CONSTRAINT chk_hi_accepted_pair    CHECK ((status = 'accepted') = (accepted_at IS NOT NULL)),
    CONSTRAINT chk_hi_revoked_pair     CHECK ((status = 'revoked')  = (revoked_at  IS NOT NULL))
    -- NOTE: `accepted_by_user_id` is informational-only and may become NULL
    -- if the accepting auth user is later deleted. We deliberately do NOT
    -- bind it to status='accepted' via a CHECK because the FK has ON DELETE
    -- SET NULL. The authoritative acceptance record is in `household_members`.
);

-- 3. Indexes

-- Unique token lookup
CREATE UNIQUE INDEX household_invites_token_hash_uniq
    ON household_invites (token_hash);

-- v1 households have a hard 2-seat cap (owner + one invitee). That means
-- the household has at most ONE remaining seat, which means at most ONE
-- live pending invite can exist per household at any given time. This
-- partial unique index enforces that at the DB level. Pending invites that
-- cross `expires_at` are lazily transitioned to status='expired' so a
-- fresh invite can be created without manual revocation.
CREATE UNIQUE INDEX household_invites_one_pending_per_household
    ON household_invites (household_id)
    WHERE status = 'pending';

CREATE INDEX idx_hi_household    ON household_invites (household_id);
CREATE INDEX idx_hi_email_status ON household_invites (email, status);

-- 4. Row Level Security (defense-in-depth; backend uses asyncpg service role)
ALTER TABLE household_invites ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Household invites select"
    ON household_invites FOR SELECT
    USING (household_id = get_household_id());
-- No INSERT/UPDATE/DELETE policies: all writes go through the backend
-- via asyncpg, bypassing RLS.
