-- Entitlement-backed dashboard cards and the internal Legal-Ops ring.
-- This migration is intentionally additive and can be re-run after the catalog
-- registrations that created the existing *-Ops rows.

BEGIN;

ALTER TABLE add_ons
    ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}'::jsonb;

-- The dashboard namespace is the only metadata consumed by /my-apps/authorized.
-- MCP URLs are the measured dogfood endpoints, not placeholders or credentials.
UPDATE add_ons SET metadata = '{
  "dashboard": {
    "purpose": "Record, transcribe, summarize, and track action items from meetings.",
    "primary_action": {"label": "Open Meeting-Ops", "route_id": "home"},
    "readiness": {"check": "none"},
    "companion": {
      "label": "Connect your AI",
      "mcp_url": "https://meetingops.magicunicorn.dev/mcp",
      "chatgpt_url": "https://meetingops.magicunicorn.dev/mcp",
      "desktop": [],
      "mobile": []
    }
  }
}'::jsonb WHERE slug = 'meeting-ops';

UPDATE add_ons SET metadata = '{
  "dashboard": {
    "purpose": "Organize contacts, relationships, and follow-up work for your organization.",
    "primary_action": {"label": "Open Contact-Ops", "route_id": "home"},
    "readiness": {"check": "none"},
    "companion": {
      "label": "Connect your AI",
      "mcp_url": "https://mcp.contacts.magicunicorn.dev/mcp",
      "chatgpt_url": "https://mcp.contacts.magicunicorn.dev/mcp",
      "desktop": [],
      "mobile": []
    }
  }
}'::jsonb WHERE slug = 'contact-ops';

UPDATE add_ons SET metadata = '{
  "dashboard": {
    "purpose": "Manage brand identity, assets, and creative consistency across the organization.",
    "primary_action": {"label": "Open Brand-Ops", "route_id": "home"},
    "readiness": {"check": "none"},
    "companion": {
      "label": "Connect your AI",
      "mcp_url": "https://mcp.brand-ops.magicunicorn.dev/mcp",
      "chatgpt_url": "https://mcp.brand-ops.magicunicorn.dev/mcp",
      "desktop": [],
      "mobile": []
    }
  }
}'::jsonb WHERE slug = 'brand-ops';

UPDATE add_ons SET metadata = '{
  "dashboard": {
    "purpose": "Run projects, tasks, approvals, time tracking, and capacity planning.",
    "primary_action": {"label": "Open Project-Ops", "route_id": "home"},
    "readiness": {"check": "none"},
    "companion": {
      "label": "Connect your AI",
      "mcp_url": "https://api.projectops.magicunicorn.dev/api/v1/mcp",
      "chatgpt_url": "https://api.projectops.magicunicorn.dev/api/v1/mcp",
      "desktop": [],
      "mobile": []
    }
  }
}'::jsonb WHERE slug = 'project-ops';

UPDATE add_ons SET metadata = '{
  "dashboard": {
    "purpose": "Manage customer accounts, engagements, and lifecycle operations.",
    "primary_action": {"label": "Open Customer-Ops", "route_id": "home"},
    "readiness": {"check": "none"},
    "companion": {
      "label": "Connect your AI",
      "mcp_url": "https://customer-ops.magicunicorn.dev/api/v1/mcp",
      "chatgpt_url": "https://customer-ops.magicunicorn.dev/api/v1/mcp",
      "desktop": [],
      "mobile": []
    }
  }
}'::jsonb WHERE slug = 'customer-ops';

UPDATE add_ons SET metadata = '{
  "dashboard": {
    "purpose": "Track financial operations with ledger lineage and agent-assisted bookkeeping.",
    "primary_action": {"label": "Open Accounting-Ops", "route_id": "home"},
    "readiness": {"check": "none"},
    "companion": {
      "label": "Connect your AI",
      "mcp_url": "https://accounting-ops.magicunicorn.dev/mcp/",
      "chatgpt_url": "https://accounting-ops.magicunicorn.dev/mcp/",
      "desktop": [],
      "mobile": []
    }
  }
}'::jsonb WHERE slug = 'accounting-ops';

UPDATE add_ons SET metadata = '{
  "dashboard": {
    "purpose": "Plan taxes, model scenarios, and manage compliance workflows.",
    "primary_action": {"label": "Open Tax-Planning-Ops", "route_id": "home"},
    "readiness": {"check": "none"},
    "companion": {
      "label": "Connect your AI",
      "mcp_url": "https://api.taxplanningops.magicunicorn.dev/api/v1/mcp",
      "chatgpt_url": "https://api.taxplanningops.magicunicorn.dev/api/v1/mcp",
      "desktop": [],
      "mobile": []
    }
  }
}'::jsonb WHERE slug = 'tax-ops';

UPDATE add_ons SET metadata = '{
  "dashboard": {
    "purpose": "Run mailbox cleanup and agent-assisted email operations with audit controls.",
    "primary_action": {"label": "Open Email-Ops", "route_id": "home"},
    "readiness": {"check": "none"},
    "companion": {
      "label": "Connect your AI",
      "mcp_url": "https://email-ops.magicunicorn.dev/api/v1/mcp",
      "chatgpt_url": "https://email-ops.magicunicorn.dev/api/v1/mcp",
      "desktop": [],
      "mobile": []
    }
  }
}'::jsonb WHERE slug = 'email-ops';

UPDATE add_ons SET metadata = '{
  "dashboard": {
    "purpose": "Build and coordinate AI agents for internal operations.",
    "primary_action": {"label": "Open Brigade", "route_id": "home"},
    "readiness": {"check": "none"},
    "companion": null
  }
}'::jsonb WHERE slug = 'brigade';

UPDATE add_ons SET metadata = '{
  "dashboard": {
    "purpose": "Manage investigations, evidence, timelines, and crisis response matters.",
    "primary_action": {"label": "Open Crisis-Ops", "route_id": "home"},
    "readiness": {"check": "none"},
    "companion": null
  }
}'::jsonb WHERE slug = 'crisis-ops';

UPDATE add_ons SET metadata = '{
  "dashboard": {
    "purpose": "Create and organize AI-assisted music projects and production assets.",
    "primary_action": {"label": "Open Majik''s Studio", "route_id": "home"},
    "readiness": {"check": "none"},
    "companion": null
  }
}'::jsonb WHERE slug = 'majiks-studio';

-- Legal-Ops is an internal add-on. It is never granted through a customer tier.
INSERT INTO add_ons (
    name, slug, description, long_description, category, feature_key,
    launch_url, icon_url, base_price, billing_type, is_active, is_featured,
    is_public, access_type, min_org_role, sort_order, features, metadata
) VALUES (
    'Legal-Ops',
    'legal-ops',
    'Internal legal operations workspace',
    'Internal matter, document, and legal-program operations for the dogfood ring.',
    'productivity',
    'legal_ops_access',
    'https://legal.magicunicorn.dev',
    '/logos/legal-ops.png',
    0.00,
    'monthly',
    TRUE,
    FALSE,
    FALSE,
    'org_granted',
    'member',
    24,
    '{}'::jsonb,
    '{
      "dashboard": {
        "purpose": "Run internal matters, documents, and legal program operations.",
        "primary_action": {"label": "Open Legal-Ops", "route_id": "home"},
        "readiness": {"check": "none"},
        "internal_ring": true,
        "companion": {
          "label": "Connect your AI",
          "mcp_url": "https://legal.magicunicorn.dev/mcp",
          "chatgpt_url": "https://legal.magicunicorn.dev/mcp",
          "desktop": [],
          "mobile": []
        }
      }
    }'::jsonb
)
ON CONFLICT (slug) DO UPDATE SET
    name = EXCLUDED.name,
    description = EXCLUDED.description,
    long_description = EXCLUDED.long_description,
    category = EXCLUDED.category,
    feature_key = EXCLUDED.feature_key,
    launch_url = EXCLUDED.launch_url,
    icon_url = EXCLUDED.icon_url,
    is_active = TRUE,
    is_public = FALSE,
    access_type = EXCLUDED.access_type,
    min_org_role = EXCLUDED.min_org_role,
    sort_order = EXCLUDED.sort_order,
    metadata = EXCLUDED.metadata;

-- Keep any accidental tier grant disabled. The org grant below is the only
-- entitlement path for Legal-Ops.
UPDATE tier_features
SET enabled = FALSE
WHERE feature_key = 'legal_ops_access';

-- Stable internal dogfood org used by the Legal-Ops ring. Customer orgs are
-- never matched by this name or granted this feature.
INSERT INTO organizations (
    id, name, display_name, plan_tier, max_seats, status
) VALUES (
    '00000000-0000-4000-8000-000000000042',
    'ops-center-dogfood',
    'Ops-Center internal dogfood',
    'managed',
    100,
    'active'
)
ON CONFLICT (name) DO UPDATE SET
    display_name = EXCLUDED.display_name,
    status = 'active';

INSERT INTO org_features (org_id, feature_key, enabled, granted_by, notes)
SELECT id, 'legal_ops_access', TRUE, 'system',
       'Internal dogfood ring only. Not a customer-tier entitlement.'
FROM organizations
WHERE name = 'ops-center-dogfood'
ON CONFLICT (org_id, feature_key) DO UPDATE SET
    enabled = TRUE,
    granted_by = EXCLUDED.granted_by,
    notes = EXCLUDED.notes;

COMMIT;
