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
 * Re-run whenever products-data.js changes. Marketplace-only truth
 * (listing_type, access state, bundle membership, trust facts, deployment
 * modes, image clearance, and CTA targets) lives in the OVERLAY below.
 *
 * Prices are pending Aaron. Every unset price is {{PRICE_TBD}} and the page
 * renders no number for it. Access states follow the confirmed four-listing
 * catalog from 2026-08-07. Anything without a numbered private-beta capacity
 * is "In development", per the shared access vocabulary.
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

/**
 * Marketplace overlay: the four products Aaron confirmed on 2026-08-07,
 * what kind of listing each is, and where its CTAs go today. Canonical URLs
 * follow the shared-spine product-page rule.
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
    screenshot: '/marketplace/media/meeting-ops-ai-chat.webp',
    screenshot_alt: 'Meeting-Ops AI chat answering from a fictional meeting transcript',
    og_image: '/marketplace/media/og-meeting-ops.png',
    capabilities: [
      'Records and transcribes meetings',
      'Builds summaries, decisions, and action items',
      'Runs the appliance path entirely on your network',
    ],
    approval_boundary: null,
    deployment_options: ['Local app', 'Unicorn Cloud', 'Self-host'],
    deployment_note: 'Local means the Meeting-Ops appliance path, including local transcription and Ollama analysis.',
    source_license: 'AGPL-3.0 (Community)',
    source_url: 'https://github.com/Unicorn-Commander/meeting-ops-community',
    data_egress: 'Self-hosted appliance: no. Hosted service: meeting data is processed in Unicorn Cloud.',
    cta: { label: 'Start free', href: 'https://meeting-ops.unicorncommander.ai/' },
    secondary_cta: { label: 'View AGPL source', href: 'https://github.com/Unicorn-Commander/meeting-ops-community' },
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
    screenshot: null,
    screenshot_alt: null,
    og_image: '/marketplace/media/og-center-deep-research.png',
    capabilities: [
      'Searches configured providers',
      'Reranks and normalizes results',
      'Produces research with citations',
    ],
    approval_boundary: 'Its verified MCP surface is research-only: search and deep_research. No mail, payment, or account-writing tool is listed.',
    deployment_options: ['Local app', 'Unicorn Cloud', 'Self-host'],
    deployment_note: 'Self-hosting controls the application and history. Web searches still contact the providers you configure.',
    source_license: 'AGPL-3.0 (Core)',
    source_url: 'https://github.com/Unicorn-Commander/Center-Deep',
    data_egress: 'Yes. Search queries and selected filters go to each configured search provider.',
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
    screenshot: null,
    screenshot_alt: null,
    og_image: '/marketplace/media/og-majiks-studio.png',
    platforms: 'macOS and Linux',
    capabilities: [
      'Generates music locally with ACE-Step and MLX',
      'Keeps sessions and audio in a local library',
      'Publishes selected tracks to majiks.online after sign-in',
    ],
    approval_boundary: 'Publishing is optional. It requires Unicorn Commander sign-in and an explicit publish action.',
    deployment_options: ['Local app', 'Hybrid', 'BYOK (ACE Music)'],
    deployment_note: 'Local generation stays on the Mac. Hybrid mode can use a user server or the ACE Music API.',
    source_license: 'Apache-2.0',
    source_url: 'https://git.unicorncommander.ai/MajiksStudio/majiks-music-studio-pro',
    data_egress: 'Local mode: no. Cloud generation and publishing send only the material you choose to those services.',
    cta: { label: 'Download free', href: 'https://majiks.studio/download' },
  },
  'accounting-ops': {
    access: 'In development',
    listing_type: 'hosted',
    bundle: 'standalone-addon',
    dogfood: true,
    price: PRICE_TBD,
    canonical_url: 'https://accounting-ops.unicorncommander.ai/',
    learn_more_url: 'https://magicunicorn.tech/products/accounting-ops/',
    icon: '/logos/tile-accounting-ops.png',
    screenshot: '/marketplace/media/accounting-ops-provenance.webp',
    screenshot_alt: 'Accounting-Ops tracing a fictional ledger figure back through its source and approval history',
    og_image: '/marketplace/media/og-accounting-ops.png',
    capabilities: [
      'Categorizes transactions and reconciles receipts',
      'Drafts statements and tax packages',
      'Traces report lines through an append-only journal',
    ],
    approval_boundary: 'Material items and missing-receipt entries stop for human approval. Tax packages remain draft and do not file themselves.',
    deployment_options: ['Local app', 'Unicorn Cloud', 'Hybrid', 'BYOK', 'Self-host'],
    deployment_note: 'The app self-hosts on your hardware and can use a local model, your hosted model API, or Unicorn Cloud.',
    source_license: 'AGPL-3.0',
    source_url: 'https://git.unicorncommander.ai/UnicornCommander/Accounting-Ops',
    data_egress: 'Self-hosted with a local model: no. Hosted models and connectors receive the records required for the task.',
    cta: { label: 'Read the build log', href: 'https://magicunicorn.dev/log/?project=accounting-ops' },
    note: 'Standalone add-on. In development, with no signup list.',
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
  access: 'In development',
  price: PRICE_TBD,
  entitlement_sku: null,
  dogfood: true,
  tagline: 'The whole AI staff, hired together. One account, one credit pool, and every app already knows what the others are doing.',
  includes: suiteSlugs.map((s) => bySlug[s]?.name || ({ 'knowledge-ops': 'Knowledge-Ops' }[s] || s)),
  callouts: [
    'Meeting-Ops is also sold standalone.',
    'Accounting-Ops is a standalone add-on, in or out of the bundle.',
  ],
  cta: { label: 'Read the build log', href: 'https://magicunicorn.dev/log/?project=unicorn-commander-suite' },
};

// Hard rule (spine §4): the literal placeholder must never be renderable copy.
for (const l of [...LISTINGS, SUITE]) {
  for (const [k, v] of Object.entries(l)) {
    if (k !== 'price' && typeof v === 'string' && v.includes('{{PRICE_TBD}}')) {
      throw new Error(`{{PRICE_TBD}} leaked into renderable field ${l.slug}.${k}`);
    }
  }
}

const out = `// GENERATED FILE - do not edit by hand.
// Built by scripts/export-marketplace-listings.mjs
// Source of product facts: ${sourceLabel}
// Generated: ${new Date().toISOString()}
// Access states follow Aaron's confirmed four-listing catalog (2026-08-07).
// price === '{{PRICE_TBD}}' means: render NO number.

export const LISTINGS = ${JSON.stringify(LISTINGS, null, 2)};

export const SUITE = ${JSON.stringify(SUITE, null, 2)};

export const PRICE_TBD = '{{PRICE_TBD}}';
`;

const outPath = resolve(here, '../src/data/marketplaceListings.js');
mkdirSync(dirname(outPath), { recursive: true });
writeFileSync(outPath, out);
console.log(`Wrote ${outPath}: ${LISTINGS.length} listings + suite bundle (source: ${sourceLabel})`);
