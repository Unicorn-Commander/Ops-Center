#!/usr/bin/env node
/**
 * export-marketplace-listings.mjs
 *
 * The marketplace at unicorncommander.ai does NOT own product facts.
 * Facts (name, tagline, pillar) come from magic-unicorn-landing's
 * products/products-data.js — the single source of truth (spine §6).
 * This script is the export step between the two repos: it reads that
 * file and emits src/data/marketplaceListings.js for the Marketplace page.
 *
 * Usage:
 *   node scripts/export-marketplace-listings.mjs <path-to-products-data.js> [source-label]
 *
 * Re-run whenever products-data.js changes (e.g. after the 01 access-vocabulary
 * pass lands). Marketplace-only truth (listing_type, access state, bundle
 * membership, CTA targets) lives in the OVERLAY below.
 *
 * ⚠ ACCESS STATES + PRICES ARE PENDING AARON. Every price is {{PRICE_TBD}}
 * and the page renders no number for it. The access mapping below is the
 * PROPOSED table from the 2026-08-06 site-refresh pack (01 step 4) and must
 * be confirmed by Aaron before the marketplace is flipped public.
 */

import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const srcPath = process.argv[2];
const sourceLabel = process.argv[3] || srcPath || 'unknown';
if (!srcPath) {
  console.error('Usage: node scripts/export-marketplace-listings.mjs <path-to-products-data.js> [source-label]');
  process.exit(1);
}

const raw = readFileSync(resolve(srcPath), 'utf8');
// products-data.js is `const PRODUCT_PAGES = [...]` with no export.
const PRODUCT_PAGES = new Function(`${raw}; return PRODUCT_PAGES;`)();
const bySlug = Object.fromEntries(PRODUCT_PAGES.map((p) => [p.slug, p]));

// Voice rule (spine §7): no em-dashes anywhere.
const deDash = (s) => (s || '').replace(/\s*—\s*/g, ': ').replace(/—/g, '-');

const PRICE_TBD = '{{PRICE_TBD}}'; // machine value; NEVER rendered literally

const BOOK = (slug) => `https://magicunicorn.dev/book/?product=${slug}`;

/**
 * Marketplace overlay: which products are LISTED (only things a visitor can
 * actually get: Available now / Private beta; In-development lives in the
 * catalog on magicunicorn.tech, not here), what kind of listing each is,
 * and where its CTAs go today. `canonical_url` follows the spine §6 rule
 * (<app>.unicorncommander.ai); `learn_more_url` is where "Learn more" can
 * safely point TODAY (canonical pages that are still login walls get their
 * catalog page until 03B ships the landing gates).
 */
const OVERLAY = {
  'meeting-ops': {
    access: 'Available now',
    listing_type: 'hosted',
    bundle: 'suite',
    sold_standalone: true,
    dogfood: true,
    price: PRICE_TBD,
    free_tier: true,
    canonical_url: 'https://meeting-ops.unicorncommander.ai/',
    learn_more_url: 'https://meeting-ops.unicorncommander.ai/',
    icon: '/logos/tile-meeting-ops.png',
    cta: { label: 'Start free', href: 'https://meeting-ops.unicorncommander.ai/' },
    secondary_cta: { label: 'Self-host free (AGPL)', href: 'https://unicorncommander.ai/meeting-ops/self-host' },
  },
  'center-deep-research': {
    access: 'Available now',
    listing_type: 'hosted',
    bundle: 'suite',
    dogfood: false,
    price: PRICE_TBD,
    canonical_url: 'https://research.unicorncommander.ai/',
    learn_more_url: 'https://magicunicorn.tech/products/center-deep-research/',
    icon: '/logos/tile-center-deep.png',
    cta: { label: 'Get started', href: '/auth/login?signup=1&return_url=%2Fdashboard' },
    secondary_cta: { label: 'Self-host Core (AGPL)', href: 'https://github.com/Unicorn-Commander/Center-Deep' },
  },
  'majiks-studio': {
    access: 'Available now',
    listing_type: 'download',
    bundle: null,
    dogfood: false,
    price: 'Free',
    canonical_url: 'https://majiks.studio/download',
    learn_more_url: 'https://majiks.studio/',
    icon: '/logos/tile-majiks-studio.png',
    platforms: 'macOS and Linux',
    cta: { label: 'Download free', href: 'https://majiks.studio/download' },
  },
  'accounting-ops': {
    access: 'Private beta',
    listing_type: 'hosted',
    bundle: 'standalone-addon',
    dogfood: true,
    price: PRICE_TBD,
    canonical_url: 'https://accounting-ops.unicorncommander.ai/',
    learn_more_url: 'https://magicunicorn.tech/products/accounting-ops/',
    icon: '/logos/tile-accounting-ops.png',
    cta: { label: 'Talk to us', href: BOOK('accounting-ops') },
    note: 'Standalone add-on. Pairs with Tax-Planning-Ops.',
  },
  'tax-planning-ops': {
    access: 'Private beta',
    listing_type: 'hosted',
    bundle: 'standalone-addon',
    dogfood: false,
    price: PRICE_TBD,
    canonical_url: 'https://tax-planning-ops.unicorncommander.ai/',
    learn_more_url: 'https://magicunicorn.tech/products/tax-planning-ops/',
    icon: '/logos/tax-ops.png',
    cta: { label: 'Talk to us', href: BOOK('tax-planning-ops') },
    note: 'Companion to Accounting-Ops.',
  },
  'security-ops': {
    access: 'Private beta',
    listing_type: 'hosted',
    bundle: null,
    dogfood: false,
    price: PRICE_TBD,
    canonical_url: 'https://security-ops.unicorncommander.ai/',
    learn_more_url: 'https://magicunicorn.tech/products/security-ops/',
    icon: null,
    cta: { label: 'Talk to us', href: BOOK('security-ops') },
    // Not present in products-data.js @ 85e3bed; facts taken from the LIVE
    // magicunicorn.tech/products/security-ops/ page (repo is behind live;
    // 01/03A are reconciling). Re-export once that lands.
    factsFallback: {
      name: 'Security-Ops',
      pillar: 'AI Employees',
      oneLiner: 'An autonomous AI pentester that only fires on targets you can prove you own, then exploits, verifies, and hands off.',
    },
  },
  'wealth-ops': {
    access: 'Private beta',
    listing_type: 'hosted',
    bundle: null,
    dogfood: false,
    price: PRICE_TBD,
    canonical_url: 'https://wealth-ops.unicorncommander.ai/',
    learn_more_url: 'https://magicunicorn.tech/products/wealth-ops/',
    icon: null,
    cta: { label: 'Talk to us', href: BOOK('wealth-ops') },
  },
  'crisis-management-ops': {
    access: 'Private beta',
    listing_type: 'hosted',
    bundle: null,
    dogfood: false,
    price: PRICE_TBD,
    canonical_url: 'https://crisis-management-ops.unicorncommander.ai/',
    learn_more_url: 'https://magicunicorn.tech/products/crisis-management-ops/',
    icon: '/logos/crisis-ops-logo.png',
    cta: { label: 'Talk to us', href: BOOK('crisis-management-ops') },
  },
};

const LISTINGS = Object.entries(OVERLAY).map(([slug, o]) => {
  const facts = bySlug[slug] || o.factsFallback;
  if (!facts) throw new Error(`No facts for listed product: ${slug}`);
  const { factsFallback, ...overlay } = o;
  return {
    slug,
    name: facts.name,
    tagline: deDash(facts.oneLiner),
    pillar: facts.pillar || 'AI Employees',
    publisher: 'Magic Unicorn',
    entitlement_sku: null, // reserved for the entitlements phase; NOT wired
    ...overlay,
  };
});

// The Unicorn Commander Suite bundle (spine §4). Names come from
// products-data where present so chips track the source of truth.
const suiteSlugs = ['project-ops', 'contact-ops', 'customer-ops', 'email-ops', 'knowledge-ops', 'center-deep-research', 'stable', 'meeting-ops'];
const SUITE = {
  slug: 'unicorn-commander-suite',
  name: 'Unicorn Commander Suite',
  publisher: 'Magic Unicorn',
  listing_type: 'hosted',
  access: 'Private beta',
  price: PRICE_TBD,
  entitlement_sku: null,
  dogfood: true,
  tagline: 'The whole AI staff, hired together. One account, one credit pool, and every app already knows what the others are doing.',
  includes: suiteSlugs.map((s) => bySlug[s]?.name || ({ 'knowledge-ops': 'Knowledge-Ops' }[s] || s)),
  callouts: [
    'Meeting-Ops is also sold standalone.',
    'Accounting-Ops (with Tax-Planning-Ops) is a standalone add-on, in or out of the bundle.',
  ],
  cta: { label: 'Talk to us', href: BOOK('unicorn-commander-suite') },
};

// Hard rule (spine §4): the literal placeholder must never be renderable copy.
for (const l of [...LISTINGS, SUITE]) {
  for (const [k, v] of Object.entries(l)) {
    if (k !== 'price' && typeof v === 'string' && v.includes('{{PRICE_TBD}}')) {
      throw new Error(`{{PRICE_TBD}} leaked into renderable field ${l.slug}.${k}`);
    }
  }
}

const out = `// GENERATED FILE — do not edit by hand.
// Built by scripts/export-marketplace-listings.mjs
// Source of product facts: ${sourceLabel}
// Generated: ${new Date().toISOString()}
// Access states are the PROPOSED 2026-08-06 mapping, pending Aaron's
// confirmation. price === '{{PRICE_TBD}}' means: render NO number.

export const LISTINGS = ${JSON.stringify(LISTINGS, null, 2)};

export const SUITE = ${JSON.stringify(SUITE, null, 2)};

export const PRICE_TBD = '{{PRICE_TBD}}';
`;

const outPath = resolve(here, '../src/data/marketplaceListings.js');
mkdirSync(dirname(outPath), { recursive: true });
writeFileSync(outPath, out);
console.log(`Wrote ${outPath}: ${LISTINGS.length} listings + suite bundle (source: ${sourceLabel})`);
