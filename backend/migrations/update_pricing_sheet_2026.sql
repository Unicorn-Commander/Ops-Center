-- Locked self-service price sheet (decision 2026-06-24, project P-00107)
-- Current ladder: Free $0 / Solo $49 / Team workspace $149 + quote-only Enterprise.
-- App and Managed remain as inactive legacy rows for existing records.
-- REPRICED 2026-08-08: App was $15/$150 at the 2026-06-24 lock. Aaron, 2026-08-08:
--   "Shouldn't meeting-ops be more? We didn't want a race to the bottom."
--   New standing price $22/mo, $216/yr ($18/mo billed annually), matching his written
--   decision in DECISIONS-2026-08-07.txt. The $15/$150 Stripe prices are ARCHIVED, so
--   this file MUST NOT point at them again: re-running it would repoint a live tier at
--   a dead SKU and checkout would 400.
--
-- Idempotent: re-runnable. INSERTs use ON CONFLICT DO NOTHING; UPDATEs are keyed by tier_code.
-- NOTE: stripe_price_monthly / stripe_price_yearly are intentionally left NULL here — populate
--       them AFTER creating the Stripe products (setup_stripe_products.py) so display price and
--       the actual charged Stripe price stay in sync. Until then these tiers show the price but
--       checkout for them should remain disabled in the UI.

-- ── Free: the floor. On-device / bring-your-own AI + local storage, no platform LLM spend. ──
INSERT INTO subscription_tiers
  (tier_code, tier_name, description, price_monthly, price_yearly, is_active, is_invite_only,
   sort_order, api_calls_limit, team_seats, byok_enabled, priority_support, lago_plan_code, created_by)
VALUES
  ('free', 'Free',
   'On-device / bring-your-own AI, local storage, 1 seat. No platform LLM spend.',
   0.00, 0.00, TRUE, FALSE, 0, 0, 1, FALSE, FALSE, 'free', 'system')
ON CONFLICT (tier_code) DO NOTHING;

-- ── App: retired single-app entry; retain the row for existing records. ──
INSERT INTO subscription_tiers
  (tier_code, tier_name, description, price_monthly, price_yearly, is_active, is_invite_only,
   sort_order, api_calls_limit, team_seats, byok_enabled, priority_support, lago_plan_code, created_by)
VALUES
  ('app', 'App (Meeting + Contact)',
   'Meeting-Ops Pro. $22/month or $216/year ($18/month billed annually, $48 less than twelve monthly payments). MCP included, ~$4/mo platform credits, 1 seat.',
   22.00, 216.00, FALSE, FALSE, 2, -1, 1, FALSE, FALSE, 'app', 'system')
ON CONFLICT (tier_code) DO NOTHING;

-- ── App: the INSERT above is ON CONFLICT DO NOTHING, so explicitly retain its
--    retired state on an existing row. ──
UPDATE subscription_tiers
   SET price_monthly = 22.00,
       price_yearly  = 216.00,
       is_active      = FALSE,
       updated_by    = 'system',
       updated_at    = NOW()
 WHERE tier_code = 'app';

-- ── Solo: all apps + MCP, bring your own model keys. Price 30 -> 49. ──
UPDATE subscription_tiers
   SET price_monthly = 49.00,
       price_yearly  = NULL,  -- no annual for Solo (2026-11-06)
       stripe_price_yearly = NULL,
       tier_name     = 'Solo',
       description   = 'Hosted bring-your-own-AI workspace for one seat at $49/month. Every app in the suite; the model bill stays with your AI provider. Price locked while the workspace stays paid, with a 30-day money-back guarantee for the Founding 100.',
       sort_order    = 3,
       byok_enabled  = TRUE,
       is_active     = TRUE,
       updated_by    = 'system',
       updated_at    = NOW()
 WHERE tier_code = 'byok';

-- ── Managed: retired all-apps + UC-hosted inference tier. ──
UPDATE subscription_tiers
   SET price_monthly    = 65.00,
       price_yearly     = 650.00,
       tier_name        = 'Suite - Managed',
       team_seats       = 3,
       sort_order       = 4,
       priority_support = TRUE,
       is_active        = FALSE,
       updated_by       = 'system',
       updated_at       = NOW()
 WHERE tier_code = 'managed';

-- ── Stripe LIVE monthly price IDs (created 2026-06-24 on acct_1QwxFKDzk9HqAZnH). ──
-- Price IDs are not secret (used client-side in Stripe Checkout). Annual prices not yet
-- created → yearly checkout stays disabled in the UI. Free tier has no Stripe price.
-- 2026-08-08: was price_1TllOZDzk9HqAZnHU5ijAlmP ($15/mo on prod_UlHyb0hSk2d5FO). That
-- product was a SECOND Meeting-Ops SKU that the live checkout never used, so the tier
-- table and the checkout could quote different amounts. Both now point at the ONE pair
-- on prod_UborP589krk3ur that STRIPE_PRO_PRICE_ID/_ANNUAL_ also point at.
UPDATE subscription_tiers SET stripe_price_monthly = 'price_1U2LVNDzk9HqAZnHVvaNigJ0' WHERE tier_code = 'app';
UPDATE subscription_tiers SET stripe_price_yearly  = 'price_1U2LVrDzk9HqAZnH4dL6Oypc' WHERE tier_code = 'app';
UPDATE subscription_tiers SET stripe_price_monthly = 'price_1TllOaDzk9HqAZnHCkH7E20k' WHERE tier_code = 'byok';
UPDATE subscription_tiers SET stripe_price_monthly = 'price_1TllObDzk9HqAZnHw8mrzhou' WHERE tier_code = 'managed';
