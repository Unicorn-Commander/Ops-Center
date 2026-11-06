-- Pricing ladder convergence (Aaron's 2026-11-06 decision).
-- Free is the in-browser floor; Solo is BYOK at $49/month; Team workspace is
-- founder_workspace at $149/month. Enterprise remains quote-only and has no row.
-- This is intentionally a by-hand migration: it does not belong in migrations/core/
-- or migrations/manifest.json.
--
-- Rollback (inverse updates; assumes managed and app were active before applying):
-- BEGIN;
-- UPDATE subscription_tiers
--    SET is_active = TRUE,
--        updated_by = 'pricing_ladder_20261106_rollback'
--  WHERE tier_code IN ('managed', 'app');
-- UPDATE subscription_tiers
--    SET tier_name = 'Suite - BYOK',
--        description = 'Use your own API keys for OpenAI, Anthropic, Google, etc. No platform markup. Priority support included.',
--        price_yearly = 490.00,  -- stripe_price_yearly: the archived 'byok annual' price id (reactivate it in Stripe first)
--        updated_by = 'pricing_ladder_20261106_rollback'
--  WHERE tier_code = 'byok';
-- COMMIT;

BEGIN;

UPDATE subscription_tiers
   SET is_active = FALSE,
       updated_by = 'pricing_ladder_20261106'
 WHERE tier_code IN ('managed', 'app')
   AND is_active;

UPDATE subscription_tiers
   SET tier_name = 'Solo',
       price_yearly = NULL,
       stripe_price_yearly = NULL,
       description = 'Hosted bring-your-own-AI workspace for one seat at $49/month. Every app in the suite; the model bill stays with your AI provider. Price locked while the workspace stays paid, with a 30-day money-back guarantee for the Founding 100.',
       updated_by = 'pricing_ladder_20261106'
 WHERE tier_code = 'byok'
   AND (
       tier_name IS DISTINCT FROM 'Solo'
       OR price_yearly IS NOT NULL
       OR stripe_price_yearly IS NOT NULL
       OR description IS DISTINCT FROM 'Hosted bring-your-own-AI workspace for one seat at $49/month. Every app in the suite; the model bill stays with your AI provider. Price locked while the workspace stays paid, with a 30-day money-back guarantee for the Founding 100.'
   );

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM subscription_tiers
        WHERE tier_code = 'founder_workspace'
          AND is_active
    ) THEN
        RAISE EXCEPTION
            'pricing_ladder_20261106 requires an active founder_workspace tier; run add_founder_workspace_tier_20261105.sql first';
    END IF;
END
$$;

COMMIT;
