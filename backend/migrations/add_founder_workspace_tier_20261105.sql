-- Team workspace / Founding 100 tier ($149/month, five seats included).
-- Idempotent: the tier row is inserted once and its feature rows are upserted
-- from the current BYOK catalog rather than maintained as a second hand list.

BEGIN;

INSERT INTO subscription_tiers (
    tier_code,
    tier_name,
    description,
    price_monthly,
    price_yearly,
    is_active,
    is_invite_only,
    sort_order,
    api_calls_limit,
    team_seats,
    byok_enabled,
    priority_support,
    lago_plan_code,
    stripe_price_monthly,
    stripe_price_yearly,
    llm_markup_percentage,
    max_monthly_llm_budget,
    local_pricing_mode,
    local_monthly_token_quota,
    local_overflow_model,
    local_token_rate_per_1k,
    created_by
)
SELECT
    'founder_workspace',
    'Team workspace',
    'Hosted bring-your-own-AI workspace for up to 5 seats at $149/month. Additional seats are $25/month each. Price locked while the workspace stays paid, with a 30-day money-back guarantee for the Founding 100.',
    149.00,
    NULL,
    TRUE,
    FALSE,
    -- The current price sheet uses adjacent integer sort values (BYOK=3,
    -- Managed=4). Keep this tier in the BYOK bucket when there is no integer
    -- gap; the price tie-breaker places it after BYOK and before Managed.
    CASE
        WHEN managed.sort_order > byok.sort_order + 1 THEN byok.sort_order + 1
        ELSE byok.sort_order
    END,
    -1,
    5,
    TRUE,
    byok.priority_support,
    'founder_workspace',
    NULL,
    NULL,
    byok.llm_markup_percentage,
    byok.max_monthly_llm_budget,
    byok.local_pricing_mode,
    byok.local_monthly_token_quota,
    byok.local_overflow_model,
    byok.local_token_rate_per_1k,
    'system'
FROM subscription_tiers AS byok
LEFT JOIN subscription_tiers AS managed
    ON managed.tier_code = 'managed'
WHERE byok.tier_code = 'byok'
ON CONFLICT (tier_code) DO NOTHING;

-- Copy the complete, current BYOK feature set. The upsert makes re-running this
-- migration safe if BYOK feature values are refreshed before the founder tier is
-- first used; it only writes founder_workspace rows.
INSERT INTO tier_features (tier_id, feature_key, feature_value, enabled)
SELECT
    founder.id,
    byok_feature.feature_key,
    byok_feature.feature_value,
    byok_feature.enabled
FROM subscription_tiers AS founder
JOIN subscription_tiers AS byok
    ON byok.tier_code = 'byok'
JOIN tier_features AS byok_feature
    ON byok_feature.tier_id = byok.id
WHERE founder.tier_code = 'founder_workspace'
ON CONFLICT (tier_id, feature_key) DO UPDATE
SET feature_value = EXCLUDED.feature_value,
    enabled = EXCLUDED.enabled,
    updated_at = NOW();

COMMIT;
