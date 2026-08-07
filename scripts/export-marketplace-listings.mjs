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
 * Prices are pending. Every unset price is {{PRICE_TBD}} and the page renders
 * NOTHING for it: not a number, not an em-dash, not "Contact us", not an empty
 * element with margin. Absence is the design. Anything without a numbered
 * private-beta capacity is "In development", per the shared access vocabulary.
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
 * Marketplace overlay: the five confirmed products, what kind of listing each
 * is, and where its CTAs go today. Canonical URLs follow the shared-spine
 * product-page rule and are HEAD-verified by scripts/verify-hosts.mjs before
 * any page is generated, so a hand-typed hostname cannot ship.
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
    // Task 14 visual identity: approved Brand-Ops mascot + brand tokens.
    mascot: '/marketplace/media/mascot-meeting-ops.webp',
    mascot_alt: 'The Meeting-Ops scribe, in a camo patrol cap and headset',
    mascot_role: 'The scribe',
    // MEASURED 2026-08-07 on the live asset: 0.0% transparent, corner
    // (211,211,211). The currently shipped file has a flat LIGHT GREY
    // background baked in, so it is a scene, not a cutout, and it needs a
    // declared plate like the other baked assets. (Earlier notes calling this
    // a 71.5%-alpha cutout describe an older file and are stale.)
    // FLAGGED for Brand-Ops: Meeting-Ops is the flagship listing and a light
    // plate in an otherwise dark set is a brand inconsistency. The fix belongs
    // in the artwork, not in a crop here.
    plate: '#d3d3d3',
    brand_primary: '#1b3a6b',
    brand_accent: '#d4af37',
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
    source_license: 'AGPL-3.0',
    // Was .../meeting-ops-community, which returns 404 to an anonymous
    // visitor. verify-hosts.mjs caught it. This repo is public and its LICENSE
    // file is AGPL-3.0 verbatim.
    source_url: 'https://github.com/Unicorn-Commander/Meeting-Ops-OSS',
    data_egress: 'Self-hosted appliance: no. Hosted service: meeting data is processed in Unicorn Cloud.',
    cta: { label: 'Start free', href: 'https://meeting-ops.unicorncommander.ai/' },
    secondary_cta: { label: 'View AGPL source', href: 'https://github.com/Unicorn-Commander/Meeting-Ops-OSS' },
  },
  'center-deep-research': {
    access: 'Available now',
    listing_type: 'hosted',
    bundle: 'suite',
    dogfood: false,
    price: PRICE_TBD,
    // External canonical. research.unicorncommander.ai answers 302 to the
    // Keycloak realm for anonymous visitors, so it is not a public product
    // page; centerdeep.ai is. verify-hosts.mjs enforces this.
    canonical_url: 'https://centerdeep.ai/',
    learn_more_url: 'https://magicunicorn.tech/products/center-deep-research/',
    icon: '/logos/tile-center-deep.png',
    mascot: '/marketplace/media/mascot-center-deep-research.webp',
    mascot_alt: 'The Center Deep diver, suited up in the dark water',
    mascot_role: 'The diver',
    // 0.0% transparency: an illustrated scene with a baked background, not a
    // cutout. Sampled from its own corner pixel so the plate mounts it
    // honestly instead of cropping the artwork. See .plate in marketplace.css.
    plate: '#072745',
    brand_primary: '#0891b2',
    brand_accent: '#22d3ee',
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
    cta: { label: 'Open Center Deep', href: 'https://centerdeep.ai/' },
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
    mascot: '/marketplace/media/mascot-majiks-studio.webp',
    mascot_alt: 'The Majiks Studio DJ, headphones on, shades down',
    mascot_role: 'The DJ',
    plate: '#170922', // baked background, see center-deep note
    brand_primary: '#a855f7',
    brand_accent: '#9333ea',
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
    // The Forgejo repo answers 303 -> /user/login anonymously and no public
    // mirror exists. Under the sovereignty thesis a login-walled "source" link
    // is worse than none, so this renders the license with no link and the row
    // falls back to /marketplace/self-host. verify-hosts.mjs hard-fails if a
    // non-null source_url is ever set here without being publicly reachable.
    source_url: null,
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
    mascot: '/marketplace/media/mascot-accounting-ops.webp',
    mascot_alt: 'The Accounting-Ops bookkeeper, bowler hat, ledger, and brass scale',
    mascot_role: 'The bookkeeper',
    brand_primary: '#0f766e',
    brand_accent: '#d4af37',
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
    // Was the Forgejo host, which answers 303 -> /user/login anonymously.
    // This mirror is public and its LICENSE file is AGPL-3.0 verbatim.
    source_url: 'https://github.com/Unicorn-Commander/accounting-ops-community',
    data_egress: 'Self-hosted with a local model: no. Hosted models and connectors receive the records required for the task.',
    cta: { label: 'Read the build log', href: 'https://magicunicorn.dev/log?project=accounting-ops' },
    note: 'Standalone add-on. In development, with no signup list.',
  },
  // ── FIFTH LISTING ────────────────────────────────────────────────────────
  // Project-Ops is shipping (v1.13.0, backend healthy, /api/v1/health 200 with
  // database up) and is therefore Available now, not "In development".
  //
  // Three traps verified and avoided here:
  //  1. The hostname is `projectops` with NO hyphen. `project-ops.` answers 404
  //     (the wildcard CNAME sends it to commander, which has no router for it).
  //  2. `screenshot` is null on purpose. The only Project-Ops shots that exist
  //     are served at projectops.../product-shots/* and contain a real client's
  //     litigation matter and someone's prescription information. They are not
  //     cleared, must not be cropped into use, and are filed separately as a
  //     PII remediation ticket upstream. The mascot carries the row instead,
  //     exactly as center-deep-research already does.
  //  3. The CTA is "Request access", not "Open Project-Ops". Live prod is
  //     entitlement-gated and fails CLOSED
  //     (PROJECT_OPS_ENTITLEMENTS_FAIL_OPEN=false) over a 4-entry allowlist, so
  //     a stranger clicking "Open" would bounce. A CTA that bounces a stranger
  //     is a broken instrument.
  'project-ops': {
    access: 'Available now',
    listing_type: 'hosted',
    bundle: 'suite',
    sold_standalone: true,
    dogfood: true,
    price: PRICE_TBD,
    canonical_url: 'https://projectops.unicorncommander.ai/',
    learn_more_url: 'https://projectops.unicorncommander.ai/',
    icon: '/logos/tile-project-ops.png',
    mascot: '/marketplace/media/mascot-project-ops.webp',
    // The shipped art is a purple judo gi with a black belt. The old alt text
    // said "in beret" (that is the Colonel, a different character) and the
    // brand.yaml spec is stale in the same way. The art is right; the words
    // were wrong.
    mascot_alt: 'The Project-Ops coordinator, in a purple judo gi and black belt',
    mascot_role: 'The coordinator',
    brand_primary: '#4f46e5',
    brand_accent: '#f59e0b',
    screenshot: null,
    screenshot_alt: null,
    og_image: null,
    capabilities: [
      'Turns meeting decisions into tasks with the source conversation attached',
      'Runs projects as list, kanban, and Gantt across every client and org',
      'Assigns work to a person or an AI agent on the same board and audit trail',
      'Tracks time, capacity, billing, and client-visible progress in one place',
    ],
    approval_boundary: 'AI-proposed action items land in a Triage queue: nothing becomes project work until a human approves, routes, or rejects it. Agents act only through the MCP surface, under the caller’s own role, so a CLIENT is read-only and write tools refuse.',
    deployment_options: ['Unicorn Cloud', 'Self-host'],
    deployment_note: 'Self-host is a Docker Compose stack: Postgres, Redis, S3-compatible storage, a NestJS backend, and a Next.js frontend. The AI agent is optional and can point at your own Brigade installation.',
    // Verified from the shipping product: LICENSE is Apache-2.0 verbatim, and
    // both package.json files plus the README badge agree. NOTE for the owner:
    // the public project-ops-community mirror carries an AGPL-3.0 LICENSE file
    // while its GitHub description claims Apache-2.0. Those two editions
    // disagree, so no source link is published here until that is resolved.
    source_license: 'Apache-2.0',
    source_url: null,
    data_egress: 'Self-hosted: your data and deployment stay yours, and the optional agent can point at your own installation. Unicorn Cloud: assistant turns are processed by Unicorn Brigade on Magic Unicorn infrastructure.',
    cta: { label: 'Request access', href: 'https://projectops.unicorncommander.ai/' },
    secondary_cta: null,
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
})
  // Ledger order is access state, then alphabetical. It is an INDEX, NOT A
  // RANK, and the column header says so. No trending, no ratings, no staff
  // picks. Sorting here (not in either renderer) is what keeps the SSR pages,
  // the SPA, and the deployment matrix in the same order: the matrix only
  // reads as "the same instrument, different axis" if the rows rhyme.
  .sort((a, b) => {
    const rank = (l) => (l.access === 'Available now' ? 0 : 1);
    return rank(a) - rank(b) || a.name.localeCompare(b.name);
  })
  // Part numbers are assigned from that final order and printed under every
  // mascot plate as "UC-03 · AGPL-3.0". This states the exact license once more
  // per listing, in the art furniture, at the one place a scanner is already
  // looking, without adding a badge.
  .map((l, i) => ({ ...l, part: `UC-${String(i + 1).padStart(2, '0')}` }));

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
  includes: suiteSlugs.map((s) => {
    // Prefer the products-data name unless it is just the slug echoed back
    // (the stable entry does this in some checkouts).
    const proper = { 'knowledge-ops': 'Knowledge-Ops', stable: 'Unicorn Stable' };
    const n = bySlug[s]?.name;
    return (n && n.toLowerCase() !== s.toLowerCase()) ? n : (proper[s] || n || s);
  }),
  callouts: [
    'Meeting-Ops is also sold standalone.',
    'Accounting-Ops is a standalone add-on, in or out of the bundle.',
  ],
  cta: { label: 'Read the build log', href: 'https://magicunicorn.dev/log?project=unicorn-commander-suite' },
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
// Access states follow the confirmed catalog (2026-08-07, five listings).
// price === '{{PRICE_TBD}}' means: render NO number.

export const LISTINGS = ${JSON.stringify(LISTINGS, null, 2)};

export const SUITE = ${JSON.stringify(SUITE, null, 2)};

export const PRICE_TBD = '{{PRICE_TBD}}';
`;

const outPath = resolve(here, '../src/data/marketplaceListings.js');
mkdirSync(dirname(outPath), { recursive: true });
writeFileSync(outPath, out);
console.log(`Wrote ${outPath}: ${LISTINGS.length} listings + suite bundle (source: ${sourceLabel})`);
