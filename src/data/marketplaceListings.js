// GENERATED FILE — do not edit by hand.
// Built by scripts/export-marketplace-listings.mjs
// Source of product facts: magic-unicorn-landing products/products-data.js @ 85e3bed (feat/stable-landing-p-00127 HEAD, 2026-08-06)
// Generated: 2026-08-06T17:18:12.375Z
// Access states CONFIRMED by Aaron 2026-08-07. Tax-Planning-Ops,
// Security-Ops, Wealth-Ops and Crisis-Management-Ops were REMOVED: they are
// not ready for customers, and a marketplace lists only what you can get.
// Icons now use Brand-Ops launcher_tile (brand-colour background) rather than
// the transparent app_icon, because the mascots do not differentiate at small
// sizes -- every product reduces to the same rainbow unicorn head. price === '{{PRICE_TBD}}' means: render NO number.

export const LISTINGS = [
  {
    "slug": "meeting-ops",
    "name": "Meeting-Ops",
    "tagline": "An autonomous meeting scribe that records, transcribes, summarizes, and turns conversations into action.",
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
    "cta": {
      "label": "Start free",
      "href": "https://meeting-ops.unicorncommander.ai/"
    },
    "secondary_cta": {
      "label": "Self-host free (AGPL)",
      "href": "https://unicorncommander.ai/meeting-ops/self-host"
    }
  },
  {
    "slug": "center-deep-research",
    "name": "Center Deep Research",
    "tagline": "An AI deep-research engine that turns a question into search, reranking, and a cited report.",
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
    "tagline": "A Mac studio app for generating and owning AI music locally, then publishing into the Majiks ecosystem.",
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
    "platforms": "macOS and Linux",
    "cta": {
      "label": "Download free",
      "href": "https://majiks.studio/download"
    }
  },
  {
    "slug": "accounting-ops",
    "name": "Accounting-Ops",
    "tagline": "An autonomous bookkeeper that keeps ledgers, reconciliation, approvals, and accounting work moving toward a finished close.",
    "pillar": "AI Employees",
    "publisher": "Magic Unicorn",
    "entitlement_sku": null,
    "access": "Private beta",
    "listing_type": "hosted",
    "bundle": "standalone-addon",
    "dogfood": true,
    "price": "{{PRICE_TBD}}",
    "canonical_url": "https://accounting-ops.unicorncommander.ai/",
    "learn_more_url": "https://magicunicorn.tech/products/accounting-ops/",
    "icon": "/logos/tile-accounting-ops.png",
    "cta": {
      "label": "Talk to us",
      "href": "https://magicunicorn.dev/book/?product=accounting-ops"
    },
    "note": "Standalone add-on. Pairs with Tax-Planning-Ops."
  }
];

export const SUITE = {
  "slug": "unicorn-commander-suite",
  "name": "Unicorn Commander Suite",
  "publisher": "Magic Unicorn",
  "listing_type": "hosted",
  "access": "Private beta",
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
    "Accounting-Ops (with Tax-Planning-Ops) is a standalone add-on, in or out of the bundle."
  ],
  "cta": {
    "label": "Talk to us",
    "href": "https://magicunicorn.dev/book/?product=unicorn-commander-suite"
  }
};

export const PRICE_TBD = '{{PRICE_TBD}}';
