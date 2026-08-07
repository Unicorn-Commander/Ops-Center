// GENERATED FILE - do not edit by hand.
// Built by scripts/export-marketplace-listings.mjs
// Source of product facts: magic-unicorn-landing products-data.js @ da13d8a (04B cleared @ e4e19db baseline)
// Generated: 2026-08-07T19:37:57.413Z
// Access states follow Aaron's confirmed four-listing catalog (2026-08-07).
// price === '{{PRICE_TBD}}' means: render NO number.

export const LISTINGS = [
  {
    "slug": "meeting-ops",
    "name": "Meeting-Ops",
    "tagline": "Walk out of every meeting with a transcript, speaker-tagged notes, and action items already done. And your audio stays yours.",
    "pillar": "AI Employees",
    "publisher": "Magic Unicorn",
    "entitlement_sku": null,
    "access": "Available now",
    "listing_type": "hosted",
    "bundle": "suite",
    "sold_standalone": true,
    "dogfood": true,
    "price": "{{PRICE_TBD}}",
    "free_tier": true,
    "canonical_url": "https://meeting-ops.unicorncommander.ai/",
    "learn_more_url": "https://meeting-ops.unicorncommander.ai/",
    "icon": "/logos/tile-meeting-ops.png",
    "mascot": "/marketplace/media/mascot-meeting-ops.webp",
    "mascot_alt": "The Meeting-Ops scribe, in headset",
    "mascot_role": "The scribe",
    "brand_primary": "#1b3a6b",
    "brand_accent": "#d4af37",
    "screenshot": "/marketplace/media/meeting-ops-ai-chat.webp",
    "screenshot_alt": "Meeting-Ops AI chat answering from a fictional meeting transcript",
    "og_image": "/marketplace/media/og-meeting-ops.png",
    "capabilities": [
      "Records and transcribes meetings",
      "Builds summaries, decisions, and action items",
      "Runs the appliance path entirely on your network"
    ],
    "approval_boundary": null,
    "deployment_options": [
      "Local app",
      "Unicorn Cloud",
      "Self-host"
    ],
    "deployment_note": "Local means the Meeting-Ops appliance path, including local transcription and Ollama analysis.",
    "source_license": "AGPL-3.0 (Community)",
    "source_url": "https://github.com/Unicorn-Commander/meeting-ops-community",
    "data_egress": "Self-hosted appliance: no. Hosted service: meeting data is processed in Unicorn Cloud.",
    "cta": {
      "label": "Start free",
      "href": "https://meeting-ops.unicorncommander.ai/"
    },
    "secondary_cta": {
      "label": "View AGPL source",
      "href": "https://github.com/Unicorn-Commander/meeting-ops-community"
    }
  },
  {
    "slug": "center-deep-research",
    "name": "Center Deep Research",
    "tagline": "Ask a hard question, get a cited report with per-claim confidence, synthesized on hardware you own. Your AI agents can use it too.",
    "pillar": "Discovery",
    "publisher": "Magic Unicorn",
    "entitlement_sku": null,
    "access": "Available now",
    "listing_type": "hosted",
    "bundle": "suite",
    "dogfood": false,
    "price": "{{PRICE_TBD}}",
    "canonical_url": "https://research.unicorncommander.ai/",
    "learn_more_url": "https://magicunicorn.tech/products/center-deep-research/",
    "icon": "/logos/tile-center-deep.png",
    "mascot": "/marketplace/media/mascot-center-deep-research.webp",
    "mascot_alt": "The Center Deep diver, suited up in the dark water",
    "mascot_role": "The diver",
    "brand_primary": "#0891b2",
    "brand_accent": "#22d3ee",
    "screenshot": null,
    "screenshot_alt": null,
    "og_image": "/marketplace/media/og-center-deep-research.png",
    "capabilities": [
      "Searches configured providers",
      "Reranks and normalizes results",
      "Produces research with citations"
    ],
    "approval_boundary": "Its verified MCP surface is research-only: search and deep_research. No mail, payment, or account-writing tool is listed.",
    "deployment_options": [
      "Local app",
      "Unicorn Cloud",
      "Self-host"
    ],
    "deployment_note": "Self-hosting controls the application and history. Web searches still contact the providers you configure.",
    "source_license": "AGPL-3.0 (Core)",
    "source_url": "https://github.com/Unicorn-Commander/Center-Deep",
    "data_egress": "Yes. Search queries and selected filters go to each configured search provider.",
    "cta": {
      "label": "Get started",
      "href": "/auth/login?signup=1&return_url=%2Fdashboard"
    },
    "secondary_cta": {
      "label": "Self-host Core (AGPL)",
      "href": "https://github.com/Unicorn-Commander/Center-Deep"
    }
  },
  {
    "slug": "majiks-studio",
    "name": "Majiks Studio",
    "tagline": "Make AI music on your own Mac and actually own it, with a cryptographic chain of custody from generation to publish.",
    "pillar": "Creative",
    "publisher": "Magic Unicorn",
    "entitlement_sku": null,
    "access": "Available now",
    "listing_type": "download",
    "bundle": null,
    "dogfood": false,
    "price": "Free",
    "canonical_url": "https://majiks.studio/download",
    "learn_more_url": "https://majiks.studio/",
    "icon": "/logos/tile-majiks-studio.png",
    "mascot": "/marketplace/media/mascot-majiks-studio.webp",
    "mascot_alt": "The Majiks Studio DJ, headphones on, shades down",
    "mascot_role": "The DJ",
    "brand_primary": "#a855f7",
    "brand_accent": "#9333ea",
    "screenshot": null,
    "screenshot_alt": null,
    "og_image": "/marketplace/media/og-majiks-studio.png",
    "platforms": "macOS and Linux",
    "capabilities": [
      "Generates music locally with ACE-Step and MLX",
      "Keeps sessions and audio in a local library",
      "Publishes selected tracks to majiks.online after sign-in"
    ],
    "approval_boundary": "Publishing is optional. It requires Unicorn Commander sign-in and an explicit publish action.",
    "deployment_options": [
      "Local app",
      "Hybrid",
      "BYOK (ACE Music)"
    ],
    "deployment_note": "Local generation stays on the Mac. Hybrid mode can use a user server or the ACE Music API.",
    "source_license": "Apache-2.0",
    "source_url": "https://git.unicorncommander.ai/MajiksStudio/majiks-music-studio-pro",
    "data_egress": "Local mode: no. Cloud generation and publishing send only the material you choose to those services.",
    "cta": {
      "label": "Download free",
      "href": "https://majiks.studio/download"
    }
  },
  {
    "slug": "accounting-ops",
    "name": "Accounting-Ops",
    "tagline": "An autonomous bookkeeper that closes your books and hands you finished work. Your ledger, your machine, CPA review optional.",
    "pillar": "AI Employees",
    "publisher": "Magic Unicorn",
    "entitlement_sku": null,
    "access": "In development",
    "listing_type": "hosted",
    "bundle": "standalone-addon",
    "dogfood": true,
    "price": "{{PRICE_TBD}}",
    "canonical_url": "https://accounting-ops.unicorncommander.ai/",
    "learn_more_url": "https://magicunicorn.tech/products/accounting-ops/",
    "icon": "/logos/tile-accounting-ops.png",
    "mascot": "/marketplace/media/mascot-accounting-ops.webp",
    "mascot_alt": "The Accounting-Ops bookkeeper, bowler hat, ledger, and brass scale",
    "mascot_role": "The bookkeeper",
    "brand_primary": "#0f766e",
    "brand_accent": "#d4af37",
    "screenshot": "/marketplace/media/accounting-ops-provenance.webp",
    "screenshot_alt": "Accounting-Ops tracing a fictional ledger figure back through its source and approval history",
    "og_image": "/marketplace/media/og-accounting-ops.png",
    "capabilities": [
      "Categorizes transactions and reconciles receipts",
      "Drafts statements and tax packages",
      "Traces report lines through an append-only journal"
    ],
    "approval_boundary": "Material items and missing-receipt entries stop for human approval. Tax packages remain draft and do not file themselves.",
    "deployment_options": [
      "Local app",
      "Unicorn Cloud",
      "Hybrid",
      "BYOK",
      "Self-host"
    ],
    "deployment_note": "The app self-hosts on your hardware and can use a local model, your hosted model API, or Unicorn Cloud.",
    "source_license": "AGPL-3.0",
    "source_url": "https://git.unicorncommander.ai/UnicornCommander/Accounting-Ops",
    "data_egress": "Self-hosted with a local model: no. Hosted models and connectors receive the records required for the task.",
    "cta": {
      "label": "Read the build log",
      "href": "https://magicunicorn.dev/log/?project=accounting-ops"
    },
    "note": "Standalone add-on. In development, with no signup list."
  }
];

export const SUITE = {
  "slug": "unicorn-commander-suite",
  "name": "Unicorn Commander Suite",
  "publisher": "Magic Unicorn",
  "listing_type": "hosted",
  "access": "In development",
  "price": "{{PRICE_TBD}}",
  "entitlement_sku": null,
  "dogfood": true,
  "tagline": "The whole AI staff, hired together. One account, one credit pool, and every app already knows what the others are doing.",
  "includes": [
    "Project-Ops",
    "Contact-Ops",
    "Customer-Ops",
    "Email-Ops",
    "Knowledge-Ops",
    "Center Deep Research",
    "Unicorn Stable",
    "Meeting-Ops"
  ],
  "callouts": [
    "Meeting-Ops is also sold standalone.",
    "Accounting-Ops is a standalone add-on, in or out of the bundle."
  ],
  "cta": {
    "label": "Read the build log",
    "href": "https://magicunicorn.dev/log/?project=unicorn-commander-suite"
  }
};

export const PRICE_TBD = '{{PRICE_TBD}}';
