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

// ── MEETING-OPS PRICE (decided 2026-08-08) ──────────────────────────────────
// See the block on the meeting-ops listing below for provenance. The saving is
// COMPUTED from the two real prices so it can never drift into a false claim:
// change either number and the sentence follows.
const MEETING_OPS_MONTHLY_USD = 22;
const MEETING_OPS_ANNUAL_USD = 216;
const MEETING_OPS_PRICE_MONTHLY = `$${MEETING_OPS_MONTHLY_USD}/month`;
const MEETING_OPS_PRICE_ANNUAL = `$${MEETING_OPS_ANNUAL_USD}/year`;
const MEETING_OPS_ANNUAL_PER_MONTH = MEETING_OPS_ANNUAL_USD / 12;
const MEETING_OPS_ANNUAL_SAVING = MEETING_OPS_MONTHLY_USD * 12 - MEETING_OPS_ANNUAL_USD;
if (!Number.isInteger(MEETING_OPS_ANNUAL_PER_MONTH) || MEETING_OPS_ANNUAL_SAVING <= 0) {
  throw new Error('Meeting-Ops annual price no longer divides into whole months, or is not cheaper than monthly. Rewrite the note before shipping it.');
}
const MEETING_OPS_PRICE_NOTE = `That is $${MEETING_OPS_MONTHLY_USD} a month, or $${MEETING_OPS_ANNUAL_USD} for a year. Paying yearly works out to $${MEETING_OPS_ANNUAL_PER_MONTH} a month, which is $${MEETING_OPS_ANNUAL_SAVING} less than twelve monthly payments. That is the only price comparison on this page: it is arithmetic between the two prices you can actually buy, not a discount off some former price. There is also a free tier that runs on your own device, forever, and it does not expire.`;

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
    // ── MEETING-OPS PRICE PROVENANCE ──────────────────────────────────────
    // Repriced 2026-08-08. Aaron: "Shouldn't meeting-ops be more? We didn't
    // want a race to the bottom." His written decision in
    // DECISIONS-2026-08-07.txt is "$18/seat/mo annual, $22 monthly", and
    // $18 x 12 = $216. That sits at the TOP of the sourced competitor band
    // (Granola $14, Otter $16.99, Fireflies $18-19, Fathom $20-34) instead
    // of under it.
    //
    // These two strings are the SAME numbers the customer is charged. The
    // live Stripe prices, both livemode + active on prod_UborP589krk3ur:
    //   $22/mo   price_1U2LVNDzk9HqAZnHVvaNigJ0   (STRIPE_PRO_PRICE_ID)
    //   $216/yr  price_1U2LVrDzk9HqAZnH4dL6Oypc   (STRIPE_PRO_ANNUAL_PRICE_ID)
    // and subscription_tiers.tier_code='app' carries the same pair, so the
    // marketplace, the app, and the charge cannot disagree.
    //
    // NO ANCHOR. The previous standing price was $15/$150 and it is archived,
    // but the account has never had a single subscription at ANY price, so
    // striking $15 through to make $22 look like a deal would be a fabricated
    // discount. The annual saving below is the only comparison on this page
    // and it is arithmetic between two real prices, not a former price.
    price: MEETING_OPS_PRICE_MONTHLY,
    price_annual: MEETING_OPS_PRICE_ANNUAL,
    price_note: MEETING_OPS_PRICE_NOTE,
    free_tier: true,
    canonical_url: 'https://meeting-ops.unicorncommander.ai/',
    learn_more_url: 'https://meeting-ops.unicorncommander.ai/',
    icon: '/logos/tile-meeting-ops.png',
    // Task 14 visual identity: approved Brand-Ops mascot + brand tokens.
    mascot: '/marketplace/media/mascot-meeting-ops.webp',
    mascot_alt: 'The Meeting-Ops scribe, in a camo patrol cap and headset',
    mascot_role: 'The scribe',
    // NO PLATE. Re-measured 2026-08-07 by decoding the actual served bytes
    // (https://unicorncommander.ai/marketplace/media/mascot-meeting-ops.webp,
    // md5 1308f0ee3cd28212d285740491220627, byte-identical to the file on
    // disk): 900x900 RGBA, colour-type 6, 71.8% of sampled pixels alpha<255,
    // 71.5% fully transparent, and ALL FOUR CORNERS (0,0,0,0). It is a true
    // cutout, exactly like project-ops and accounting-ops.
    //
    // The previous note here claimed "0.0% transparent, corner (211,211,211)"
    // and set plate:'#d3d3d3' on that basis. That measurement was wrong, and
    // it put a light-grey slab behind a transparent PNG on the flagship
    // listing, which read as a failed asset load in an otherwise dark crew.
    // Do not reintroduce a plate here without re-decoding the served bytes:
    // only the three colour-type-2 assets (center-deep-research,
    // customer-ops, majiks-studio) actually have baked backgrounds.
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
    // VERIFIED against the AGPL source README (Meeting-Ops-OSS, "Works with
    // the rest of the suite" + the stated design rule "Meeting-Ops proposes,
    // the owning app disposes"), and against the named implementation files
    // it cites: api/federation_summary_approval.py and
    // services/projectops_writer.py with the per-org auto_push_action_items
    // flag defaulting to off. Nothing here is inferred from the roadmap.
    approval_boundary: 'Meeting-Ops proposes; the owning app disposes. Extracted action items are sent to Project-Ops as task proposals, and that push is off by default until an org turns it on. Nothing reaches a customer record until a human releases that summary, and it never overwrites another app’s state.',
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
    // Re-measured 2026-08-13: centerdeep.ai itself says "Early access — by
    // invite" and research.unicorncommander.ai 302s to Keycloak with no
    // signup path. Per the shared vocabulary (no numbered private-beta
    // capacity => In development), this cannot read Available now until
    // invites open or a checkout exists.
    access: 'In development',
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
    cta: { label: 'Request an invite', href: 'https://centerdeep.ai/' },
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
    // The PRIMARY link is the product's own page, like every other listing.
    // canonical_url was already correct here and already verified healthy by
    // verify-hosts.mjs (200, 126,018 bytes, "Books that can answer for
    // themselves"), but nothing rendered it: every link on the listing pointed
    // at magicunicorn.dev, so the marketplace told visitors Accounting-Ops
    // lives on the build-log domain. In-development is a state, not a reason
    // to hide a live page, so the build log moves to the secondary slot.
    cta: { label: 'See Accounting-Ops', href: 'https://accounting-ops.unicorncommander.ai/' },
    secondary_cta: { label: 'Read the build log', href: 'https://magicunicorn.dev/log?project=accounting-ops' },
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
    // This card answers ONE question: "what can I actually go and get?"
    // So it states the PUBLIC edition, measured, not the internal tree.
    //
    // Measured 2026-08-07, unauthenticated:
    //   GET https://github.com/Unicorn-Commander/project-ops-community  -> 200
    //   api.github.com/repos/...  private=false  visibility=public
    //                             license.spdx_id=AGPL-3.0
    //   raw LICENSE -> 200, "GNU AFFERO GENERAL PUBLIC LICENSE Version 3"
    // The repo is public and the edition you can clone is AGPL-3.0.
    //
    // The previous value said Apache-2.0 with source_url:null, which made the
    // page print "The repository is not publicly reachable today" about a repo
    // that answers 200 to anyone. That was a verifiable falsehood on the one
    // page whose thesis is verified honesty, and it is why this changed.
    //
    // STILL UNRESOLVED, and deliberately disclosed rather than hidden: the
    // internal tree ships Apache-2.0 (LICENSE, both package.json files, README
    // badge all agree) and the community repo's GitHub *description* still
    // reads "Apache-2.0 OSS release ... Private staging mirror" — which
    // disagrees with its own LICENSE file and with its public visibility.
    // That is an owner decision about editions, not something a page generator
    // may quietly pick a winner for, so source_note says so in plain words.
    source_license: 'AGPL-3.0',
    source_url: 'https://github.com/Unicorn-Commander/project-ops-community',
    // 2026-08-13: reconciled. The GitHub description now reads "AGPL-3.0 +
    // commercial" (re-verified via the API), so the self-expiring note that
    // lived here was retired exactly as it promised it would be.
    source_note: 'This is the public community edition, and its LICENSE file is AGPL-3.0.',
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

// ── PRICE PROVENANCE ────────────────────────────────────────────────────────
// READ THIS BEFORE CHANGING THE NUMBER.
//
// The Suite carries THREE live Stripe SKU pairs for one bundle, which is how a
// customer could be quoted three different amounts depending which door they
// came through (all livemode, all active, verified read-only 2026-08-08):
//
//   prod_Ud0Mf9oqRAN7Qq  "Unicorn Commander Suite"           $35 /mo  $350 /yr
//   prod_UlHyxTDQgLCTJQ  "Unicorn Commander Suite - BYOK"    $49 /mo  $490 /yr
//   prod_UlHyYAsvaRdhZa  "Unicorn Commander Suite - Managed" $65 /mo  $650 /yr
//
// The page advertises $49 / $490 (BYOK). Reasons, in order of weight:
//
//  1. backend/migrations/update_pricing_sheet_2026.sql is the LOCKED price
//     sheet — "decision 2026-06-24, project P-00107 ... Free $0 / App $15 /
//     Suite-BYOK $49 / Suite-Managed $65" — and it sets the byok tier to
//     49.00 / 490.00 explicitly.
//  2. It is the only live number that also matches the written decision ($49).
//  3. subscription_tiers.stripe_price_monthly for tier_code='byok' points at
//     exactly this SKU, so display price and charged price already agree.
//  4. $35 / $350 PREDATES that decision (metadata product_tier:
//     'suite_v2_2026', created 2026-06-02), has no row in subscription_tiers,
//     and is superseded. It is the orphan, not the answer.
//  5. There are ZERO subscriptions on this Stripe account, so no existing
//     subscriber anchors any of the three.
//
// $65 Managed is NOT a rival price for the same thing — it is the
// hosted-inference rung of the same ladder (same migration, same second). It
// is therefore NAMED ON THE PAGE with its own number, so that no door can
// surprise a buyer. Hiding it would have created a fresh honesty problem while
// fixing the old one.
//
// This decides only what the PAGE advertises. It archives and edits nothing in
// Stripe, and it does not flip any tier's is_active.
const SUITE_PRICE_MONTHLY = '$49/month';
const SUITE_PRICE_ANNUAL = '$490/year';

// Members carry the access state of their OWN catalog listing, derived here at
// build time rather than typed, so the bundle page can never claim a member is
// available while that member's listing says otherwise.
const suiteMembers = suiteSlugs.map((s) => {
  // Prefer the products-data name unless it is just the slug echoed back
  // (the stable entry does this in some checkouts).
  const proper = { 'knowledge-ops': 'Knowledge-Ops', stable: 'Unicorn Stable' };
  const src = bySlug[s];
  const n = src?.name;
  const name = (n && n.toLowerCase() !== s.toLowerCase()) ? n : (proper[s] || n || s);
  const listed = LISTINGS.find((l) => l.slug === s) || null;
  return {
    name,
    // A listing link is emitted ONLY for a member that actually has a page in
    // this catalog. Everything else gets no link rather than a 404.
    slug: listed ? listed.slug : null,
    access: listed ? listed.access : 'In development',
    note: listed ? null : 'No listing in this catalog yet.',
  };
});

const SUITE = {
  slug: 'unicorn-commander-suite',
  name: 'Unicorn Commander Suite',
  publisher: 'Magic Unicorn',
  pillar: 'AI Employees',
  part: 'UC-00',
  listing_type: 'hosted',
  access: 'Available now',
  // A real, decided number now exists, so the price contract permits rendering
  // it. See PRICE PROVENANCE above.
  price: SUITE_PRICE_MONTHLY,
  price_annual: SUITE_PRICE_ANNUAL,
  price_note: 'That is the Suite — BYOK tier: every Suite app plus its MCP surface, calling model providers with keys you supply. A Managed tier is $65/month or $650/year and swaps your keys for UC-hosted inference credits, priority support, and 3 seats. Both tiers have an open checkout on the pricing page. Members still in development are marked in the table below, and you are not charged extra for them when they land.',
  entitlement_sku: null,
  dogfood: true,
  tagline: 'The whole AI staff, hired together. One account and one credit pool; cross-app handoffs are rolling out — not every app already knows what the others are doing yet.',
  // The Suite is the platform itself, so it wears the system signal colour
  // rather than a product hue. brand_primary is deliberately unset: every
  // var(--b) in the stylesheet falls back to var(--signal).
  mascot: '/logos/The_Colonel.png',
  mascot_alt: 'The Colonel, the Unicorn Commander mark: a white unicorn in a navy beret with a rainbow mane and a gold horn',
  canonical_url: 'https://unicorncommander.ai/marketplace/unicorn-commander-suite',
  og_image: null,
  includes: suiteMembers.map((m) => m.name),
  members: suiteMembers,
  capabilities: [
    'Entitles every Suite app under one Unicorn Commander account and one credit balance',
    'Includes each app’s MCP tool surface, under the caller’s own role',
    'BYOK tier calls model providers with keys you supply',
    'Managed tier substitutes UC-hosted inference credits and priority support',
  ],
  approval_boundary: 'The bundle grants entitlements; it does not widen them. Every member keeps the approval boundary printed on its own listing — Meeting-Ops still proposes rather than writes, and Project-Ops still holds AI-proposed work in a Triage queue until a human approves, routes, or rejects it. Buying the Suite never gives an agent a permission the owning app would refuse on its own.',
  deployment_options: ['Unicorn Cloud', 'BYOK'],
  deployment_note: 'The Suite is a hosted entitlement across Unicorn Cloud, with BYOK as the tier that points the apps at your own model provider keys. Self-hosting is decided per member rather than by the bundle, because the members do not all ship the same way — see what self-hosting takes.',
  data_egress: 'Depends on the tier and the member. On BYOK, model calls go to the provider whose keys you supply. On Managed, inference is processed on Magic Unicorn infrastructure. Each member listing states its own answer, and the bundle does not override it.',
  source_license: 'Per member — each listing states its own',
  source_url: null,
  source_note: 'The Suite is a commercial bundle, not a single codebase, so it has no license of its own and there is no blanket claim to make. Members with a listing in this catalog state their exact license there. Members without one have not had a license published yet.',
  callouts: [
    'Meeting-Ops is also sold standalone.',
    'Accounting-Ops is a standalone add-on, in or out of the bundle.',
  ],
  cta: { label: 'See Suite pricing', href: 'https://unicorncommander.ai/pricing' },
  secondary_cta: { label: 'Read the build log', href: 'https://magicunicorn.dev/log?project=unicorn-commander-suite' },
};

// Hard rule: the bundle page must never advertise a member as available while
// that member's own listing says otherwise. The states are derived above, so
// this asserts the derivation actually ran rather than trusting it.
for (const m of SUITE.members) {
  const listed = LISTINGS.find((l) => l.slug === m.slug);
  if (m.slug && listed && m.access !== listed.access) {
    throw new Error(`Suite member ${m.slug} claims "${m.access}" but its listing says "${listed.access}".`);
  }
  if (!m.slug && m.access === 'Available now') {
    throw new Error(`Suite member ${m.name} is "Available now" with no listing to prove it.`);
  }
}

// Hard rule (spine §4): the literal placeholder must never be renderable copy.
for (const l of [...LISTINGS, SUITE]) {
  for (const [k, v] of Object.entries(l)) {
    if (k !== 'price' && typeof v === 'string' && v.includes('{{PRICE_TBD}}')) {
      throw new Error(`{{PRICE_TBD}} leaked into renderable field ${l.slug}.${k}`);
    }
  }
}

// Hard rule: the trust & permissions panel has FIVE elements and every listing
// owes all five. The generator used to emit the approval card conditionally, so
// meeting-ops (approval_boundary: null) silently shipped a 4-of-5 panel on the
// flagship listing. A missing answer to "what waits for a human?" is not a
// smaller panel, it is an unanswered trust question, so it fails the build.
// The Suite is in this loop too: it renders the same five-card panel as any
// listing, so it owes the same five answers.
const TRUST_FIELDS = ['capabilities', 'approval_boundary', 'deployment_options', 'source_license', 'data_egress'];
for (const l of [...LISTINGS, SUITE]) {
  for (const f of TRUST_FIELDS) {
    const v = l[f];
    const empty = v == null || (Array.isArray(v) ? v.length === 0 : String(v).trim() === '');
    if (empty) throw new Error(`Trust panel incomplete: ${l.slug} is missing ${f}. Every listing owes all five elements.`);
  }
}

// Hard rule: a listing's own product page is the destination. canonical_url is
// verified by verify-hosts.mjs, but "verified" is worthless if nothing renders
// it — accounting-ops had a healthy canonical_url and every rendered link
// pointed at the build-log domain instead. At least one CTA must go there.
for (const l of LISTINGS) {
  const hrefs = [l.cta?.href, l.secondary_cta?.href].filter(Boolean);
  if (!hrefs.includes(l.canonical_url)) {
    throw new Error(`${l.slug}: canonical_url ${l.canonical_url} is not reachable from any CTA (${hrefs.join(', ') || 'none'}).`);
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
