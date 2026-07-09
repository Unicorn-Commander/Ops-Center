-- ============================================================================
-- Campaigns / Promos Layer
-- ============================================================================
-- Creates the central campaign model and attribution ledger, and links invite/coupon
-- codes so promos can be scoped to a campaign.
-- ============================================================================

BEGIN;

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ---------------------------------------------------------------------------
-- campaigns
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS campaigns (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    slug VARCHAR(120) UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    app_feature_keys TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    comp_tier_code VARCHAR(50),
    starts_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ends_at TIMESTAMP WITH TIME ZONE,
    status VARCHAR(20) NOT NULL DEFAULT 'draft',
    notes TEXT,
    created_by VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT valid_campaign_status CHECK (status IN ('draft', 'active', 'paused', 'ended'))
);

CREATE INDEX IF NOT EXISTS idx_campaigns_status ON campaigns(status);
CREATE INDEX IF NOT EXISTS idx_campaigns_starts_at ON campaigns(starts_at DESC);
CREATE INDEX IF NOT EXISTS idx_campaigns_ends_at ON campaigns(ends_at DESC) WHERE ends_at IS NOT NULL;

-- ---------------------------------------------------------------------------
-- campaign_grants
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS campaign_grants (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    campaign_id UUID NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id VARCHAR(255),
    granted_feature_keys TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    comp_tier_code VARCHAR(50),
    source VARCHAR(20) NOT NULL DEFAULT 'admin',
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    expires_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(255),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT valid_campaign_grant_source CHECK (source IN ('admin', 'invite', 'coupon')),
    CONSTRAINT valid_campaign_grant_status CHECK (status IN ('active', 'revoked', 'expired'))
);

CREATE INDEX IF NOT EXISTS idx_campaign_grants_campaign_id ON campaign_grants(campaign_id);
CREATE INDEX IF NOT EXISTS idx_campaign_grants_org_id ON campaign_grants(org_id);
CREATE INDEX IF NOT EXISTS idx_campaign_grants_user_id ON campaign_grants(user_id) WHERE user_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_campaign_grants_status ON campaign_grants(status);
CREATE INDEX IF NOT EXISTS idx_campaign_grants_created_at ON campaign_grants(created_at DESC);

CREATE OR REPLACE FUNCTION update_campaign_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_campaigns_update ON campaigns;
CREATE TRIGGER trg_campaigns_update
    BEFORE UPDATE ON campaigns
    FOR EACH ROW
    EXECUTE FUNCTION update_campaign_timestamp();

DROP TRIGGER IF EXISTS trg_campaign_grants_update ON campaign_grants;
CREATE TRIGGER trg_campaign_grants_update
    BEFORE UPDATE ON campaign_grants
    FOR EACH ROW
    EXECUTE FUNCTION update_campaign_timestamp();

-- ---------------------------------------------------------------------------
-- Code scoping
-- ---------------------------------------------------------------------------
ALTER TABLE invite_codes
    ADD COLUMN IF NOT EXISTS campaign_id UUID REFERENCES campaigns(id) ON DELETE SET NULL;

ALTER TABLE coupon_codes
    ADD COLUMN IF NOT EXISTS campaign_id UUID REFERENCES campaigns(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_invite_codes_campaign_id ON invite_codes(campaign_id) WHERE campaign_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_coupon_codes_campaign_id ON coupon_codes(campaign_id) WHERE campaign_id IS NOT NULL;

COMMIT;

DO $$
BEGIN
    RAISE NOTICE 'campaigns schema created successfully';
END $$;
