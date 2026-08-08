// GENERATED FILE - do not edit by hand.
// Built by scripts/export-marketplace-listings.mjs
// Source of product facts: products-data.js @ 2026-08-07 instrument
// Generated: 2026-08-08T21:45:16.366Z
// Access states follow the confirmed catalog (2026-08-07, five listings).
// price === '{{PRICE_TBD}}' means: render NO number.

export const LISTINGS = [
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
    "canonical_url": "https://centerdeep.ai/",
    "learn_more_url": "https://magicunicorn.tech/products/center-deep-research/",
    "icon": "/logos/tile-center-deep.png",
    "mascot": "/marketplace/media/mascot-center-deep-research.webp",
    "mascot_alt": "The Center Deep diver, suited up in the dark water",
    "mascot_role": "The diver",
    "plate": "#072745",
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
      "label": "Open Center Deep",
      "href": "https://centerdeep.ai/"
    },
    "secondary_cta": {
      "label": "Self-host Core (AGPL)",
      "href": "https://github.com/Unicorn-Commander/Center-Deep"
    },
    "part": "UC-01"
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
    "plate": "#170922",
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
    "source_url": null,
    "data_egress": "Local mode: no. Cloud generation and publishing send only the material you choose to those services.",
    "cta": {
      "label": "Download free",
      "href": "https://majiks.studio/download"
    },
    "part": "UC-02"
  },
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
    "mascot_alt": "The Meeting-Ops scribe, in a camo patrol cap and headset",
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
    "approval_boundary": "Meeting-Ops proposes; the owning app disposes. Extracted action items are sent to Project-Ops as task proposals, and that push is off by default until an org turns it on. Nothing reaches a customer record until a human releases that summary, and it never overwrites another app’s state.",
    "deployment_options": [
      "Local app",
      "Unicorn Cloud",
      "Self-host"
    ],
    "deployment_note": "Local means the Meeting-Ops appliance path, including local transcription and Ollama analysis.",
    "source_license": "AGPL-3.0",
    "source_url": "https://github.com/Unicorn-Commander/Meeting-Ops-OSS",
    "data_egress": "Self-hosted appliance: no. Hosted service: meeting data is processed in Unicorn Cloud.",
    "cta": {
      "label": "Start free",
      "href": "https://meeting-ops.unicorncommander.ai/"
    },
    "secondary_cta": {
      "label": "View AGPL source",
      "href": "https://github.com/Unicorn-Commander/Meeting-Ops-OSS"
    },
    "part": "UC-03"
  },
  {
    "slug": "project-ops",
    "name": "Project-Ops",
    "tagline": "The project manager that tracks your AI agents like employees. Tasks, time, billing, and profitability in one loop, for humans and agents alike.",
    "pillar": "AI Employees",
    "publisher": "Magic Unicorn",
    "entitlement_sku": null,
    "access": "Available now",
    "listing_type": "hosted",
    "bundle": "suite",
    "sold_standalone": true,
    "dogfood": true,
    "price": "{{PRICE_TBD}}",
    "canonical_url": "https://projectops.unicorncommander.ai/",
    "learn_more_url": "https://projectops.unicorncommander.ai/",
    "icon": "/logos/tile-project-ops.png",
    "mascot": "/marketplace/media/mascot-project-ops.webp",
    "mascot_alt": "The Project-Ops coordinator, in a purple judo gi and black belt",
    "mascot_role": "The coordinator",
    "brand_primary": "#4f46e5",
    "brand_accent": "#f59e0b",
    "screenshot": null,
    "screenshot_alt": null,
    "og_image": null,
    "capabilities": [
      "Turns meeting decisions into tasks with the source conversation attached",
      "Runs projects as list, kanban, and Gantt across every client and org",
      "Assigns work to a person or an AI agent on the same board and audit trail",
      "Tracks time, capacity, billing, and client-visible progress in one place"
    ],
    "approval_boundary": "AI-proposed action items land in a Triage queue: nothing becomes project work until a human approves, routes, or rejects it. Agents act only through the MCP surface, under the caller’s own role, so a CLIENT is read-only and write tools refuse.",
    "deployment_options": [
      "Unicorn Cloud",
      "Self-host"
    ],
    "deployment_note": "Self-host is a Docker Compose stack: Postgres, Redis, S3-compatible storage, a NestJS backend, and a Next.js frontend. The AI agent is optional and can point at your own Brigade installation.",
    "source_license": "AGPL-3.0",
    "source_url": "https://github.com/Unicorn-Commander/project-ops-community",
    "source_note": "This is the public community edition, and its LICENSE file is AGPL-3.0. The repository description still says Apache-2.0, which is the license of our internal tree. We are reconciling the two, and this line will say so until we have.",
    "data_egress": "Self-hosted: your data and deployment stay yours, and the optional agent can point at your own installation. Unicorn Cloud: assistant turns are processed by Unicorn Brigade on Magic Unicorn infrastructure.",
    "cta": {
      "label": "Request access",
      "href": "https://projectops.unicorncommander.ai/"
    },
    "secondary_cta": null,
    "part": "UC-04"
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
    "source_url": "https://github.com/Unicorn-Commander/accounting-ops-community",
    "data_egress": "Self-hosted with a local model: no. Hosted models and connectors receive the records required for the task.",
    "cta": {
      "label": "See Accounting-Ops",
      "href": "https://accounting-ops.unicorncommander.ai/"
    },
    "secondary_cta": {
      "label": "Read the build log",
      "href": "https://magicunicorn.dev/log?project=accounting-ops"
    },
    "note": "Standalone add-on. In development, with no signup list.",
    "part": "UC-05"
  }
];

export const SUITE = {
  "slug": "unicorn-commander-suite",
  "name": "Unicorn Commander Suite",
  "publisher": "Magic Unicorn",
  "pillar": "AI Employees",
  "part": "UC-00",
  "listing_type": "hosted",
  "access": "In development",
  "price": "$49/month",
  "price_annual": "$490/year",
  "price_note": "That is the Suite — BYOK tier: every Suite app plus its MCP surface, calling model providers with keys you supply. A Managed tier is priced at $65/month or $650/year and swaps your keys for UC-hosted inference credits, priority support, and 3 seats. The Suite is not on sale yet, so neither tier has an open checkout on this page.",
  "entitlement_sku": null,
  "dogfood": true,
  "tagline": "The whole AI staff, hired together. One account and one credit pool; cross-app handoffs are rolling out — not every app already knows what the others are doing.",
  "mascot": "/logos/The_Colonel.png",
  "mascot_alt": "The Colonel, the Unicorn Commander mark: a white unicorn in a navy beret with a rainbow mane and a gold horn",
  "canonical_url": "https://unicorncommander.ai/marketplace/unicorn-commander-suite",
  "og_image": null,
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
  "members": [
    {
      "name": "Project-Ops",
      "slug": "project-ops",
      "access": "Available now",
      "note": null
    },
    {
      "name": "Contact-Ops",
      "slug": null,
      "access": "In development",
      "note": "No listing in this catalog yet."
    },
    {
      "name": "Customer-Ops",
      "slug": null,
      "access": "In development",
      "note": "No listing in this catalog yet."
    },
    {
      "name": "Email-Ops",
      "slug": null,
      "access": "In development",
      "note": "No listing in this catalog yet."
    },
    {
      "name": "Knowledge-Ops",
      "slug": null,
      "access": "In development",
      "note": "No listing in this catalog yet."
    },
    {
      "name": "Center Deep Research",
      "slug": "center-deep-research",
      "access": "Available now",
      "note": null
    },
    {
      "name": "Unicorn Stable",
      "slug": null,
      "access": "In development",
      "note": "No listing in this catalog yet."
    },
    {
      "name": "Meeting-Ops",
      "slug": "meeting-ops",
      "access": "Available now",
      "note": null
    }
  ],
  "capabilities": [
    "Entitles every Suite app under one Unicorn Commander account and one credit balance",
    "Includes each app’s MCP tool surface, under the caller’s own role",
    "BYOK tier calls model providers with keys you supply",
    "Managed tier substitutes UC-hosted inference credits and priority support"
  ],
  "approval_boundary": "The bundle grants entitlements; it does not widen them. Every member keeps the approval boundary printed on its own listing — Meeting-Ops still proposes rather than writes, and Project-Ops still holds AI-proposed work in a Triage queue until a human approves, routes, or rejects it. Buying the Suite never gives an agent a permission the owning app would refuse on its own.",
  "deployment_options": [
    "Unicorn Cloud",
    "BYOK"
  ],
  "deployment_note": "The Suite is a hosted entitlement across Unicorn Cloud, with BYOK as the tier that points the apps at your own model provider keys. Self-hosting is decided per member rather than by the bundle, because the members do not all ship the same way — see what self-hosting takes.",
  "data_egress": "Depends on the tier and the member. On BYOK, model calls go to the provider whose keys you supply. On Managed, inference is processed on Magic Unicorn infrastructure. Each member listing states its own answer, and the bundle does not override it.",
  "source_license": "Per member — each listing states its own",
  "source_url": null,
  "source_note": "The Suite is a commercial bundle, not a single codebase, so it has no license of its own and there is no blanket claim to make. Members with a listing in this catalog state their exact license there. Members without one have not had a license published yet.",
  "callouts": [
    "Meeting-Ops is also sold standalone.",
    "Accounting-Ops is a standalone add-on, in or out of the bundle."
  ],
  "cta": {
    "label": "Read the build log",
    "href": "https://magicunicorn.dev/log?project=unicorn-commander-suite"
  },
  "secondary_cta": {
    "label": "Start with Meeting-Ops",
    "href": "https://meeting-ops.unicorncommander.ai/"
  }
};

export const PRICE_TBD = '{{PRICE_TBD}}';
