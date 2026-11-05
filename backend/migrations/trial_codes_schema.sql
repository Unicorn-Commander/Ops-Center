-- ==============================================================================
-- Trial Codes Schema  (Ops-Center, unicorn_db)
-- ==============================================================================
-- Purpose: handout codes that grant an app entitlement (feature_key) to the
-- redeemer's ORG for a trial window. Two modes:
--   free  -> grants immediately, no payment (a $0 trial code)
--   paid  -> routes to a small Stripe charge ($1 default); the grant lands via
--            the existing /api/v1/webhooks/stripe handler on payment success.
--
-- The grant is written to org_features (org_id, feature_key, enabled, expires_at),
-- which is exactly what GET /api/v1/entitlements reads (tier_features UNION
-- org_features). So a redeemed code is honored by every app that gates on that
-- endpoint (e.g. Project-Ops -> feature_key 'project_ops_access').
--
-- Idempotent (CREATE ... IF NOT EXISTS / ADD COLUMN IF NOT EXISTS). Applied at
-- startup by migrations_runner.py via manifest.json. NO $$ dollar-quoting.
-- ==============================================================================

-- 1) Give org_features an OPTIONAL expiry so trials auto-lapse. Existing rows
--    keep expires_at = NULL (permanent) and are unaffected.
ALTER TABLE org_features ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_org_features_expires_at
    ON org_features (expires_at) WHERE expires_at IS NOT NULL;

-- 2) The codes an admin hands out.
CREATE TABLE IF NOT EXISTS trial_codes (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code          VARCHAR(64) NOT NULL UNIQUE,
    -- App entitlement(s) this code grants, e.g. {'project_ops_access'}.
    feature_keys  TEXT[] NOT NULL DEFAULT '{}',
    -- 'free' = $0 comp trial, 'paid' = small Stripe charge first.
    mode          VARCHAR(16) NOT NULL DEFAULT 'free',
    -- Charge for a paid code, in cents (100 = $1). Ignored for free.
    price_cents   INTEGER NOT NULL DEFAULT 0,
    -- How many days the granted access lasts before it auto-lapses.
    trial_days    INTEGER NOT NULL DEFAULT 14,
    -- Redemption cap across all orgs (a code can be single- or multi-use).
    max_uses      INTEGER NOT NULL DEFAULT 1,
    uses_count    INTEGER NOT NULL DEFAULT 0,
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    note          TEXT,
    campaign      VARCHAR(255),
    created_by    VARCHAR(255),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at    TIMESTAMPTZ,   -- optional code validity window (not the grant)
    CONSTRAINT trial_codes_mode_chk CHECK (mode IN ('free', 'paid'))
);

CREATE INDEX IF NOT EXISTS idx_trial_codes_active ON trial_codes (is_active);

-- 3) One row per (code, org) redemption -- a trial is per-organization.
CREATE TABLE IF NOT EXISTS trial_code_redemptions (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code_id               UUID NOT NULL REFERENCES trial_codes(id) ON DELETE CASCADE,
    org_id                UUID NOT NULL,
    user_sub              VARCHAR(255),
    user_email            VARCHAR(255),
    feature_keys          TEXT[] NOT NULL DEFAULT '{}',
    grant_expires_at      TIMESTAMPTZ,
    -- 'granted'  = free code applied; access live.
    -- 'pending'  = paid code, awaiting Stripe payment (no grant yet).
    -- 'active'   = paid code, payment cleared, access live.
    -- 'revoked'  = manually pulled.
    status                VARCHAR(32) NOT NULL DEFAULT 'granted',
    stripe_customer_id    VARCHAR(255),
    stripe_session_id     VARCHAR(255),
    redeemed_at           TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    activated_at          TIMESTAMPTZ,
    CONSTRAINT trial_code_redemptions_uniq UNIQUE (code_id, org_id)
);

CREATE INDEX IF NOT EXISTS idx_trial_redemptions_org ON trial_code_redemptions (org_id);
CREATE INDEX IF NOT EXISTS idx_trial_redemptions_session ON trial_code_redemptions (stripe_session_id);

-- 2b) tier grant (comp) support (added 2026-07-15)
ALTER TABLE trial_codes ADD COLUMN IF NOT EXISTS grant_tier VARCHAR(64);
ALTER TABLE trial_code_redemptions ADD COLUMN IF NOT EXISTS granted_tier VARCHAR(64);
