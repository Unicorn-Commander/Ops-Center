#!/usr/bin/env node

// The only automated guard on the honesty skeleton. Run it after regenerating.
//   node scripts/test-marketplace-pages.mjs

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { LISTINGS, SUITE } from '../src/data/marketplaceListings.js';
import {
  MAST_HEADLINE, MAST_HEADLINE_TEXT, SELF_HOSTABLE, TOTAL, isSelfHostable,
} from '../src/data/marketplaceSystem.js';

const root = resolve(import.meta.dirname, '../public/marketplace');

// Five listings. Project-Ops joined the catalog when it started shipping.
const expected = ['accounting-ops', 'center-deep-research', 'majiks-studio', 'meeting-ops', 'project-ops'];
// Deliberately removed earlier and must never reappear.
const removed = ['tax-planning-ops', 'security-ops', 'wealth-ops', 'crisis-management-ops'];

assert.deepEqual(LISTINGS.map((listing) => listing.slug).sort(), expected);

const index = readFileSync(resolve(root, 'index.html'), 'utf8');

for (const listing of LISTINGS) {
  assert.match(index, new RegExp(listing.name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  assert.ok(listing.deployment_options.length > 0, `${listing.slug} needs a deployment mode`);
  assert.ok(listing.capabilities.length > 0, `${listing.slug} needs verified capabilities`);
  assert.ok(listing.source_license, `${listing.slug} needs a source license`);
  assert.ok(listing.data_egress, `${listing.slug} needs a data-egress answer`);
  assert.ok(listing.part, `${listing.slug} needs a part number`);

  // All FIVE elements of the trust & permissions panel, on every listing.
  // approval_boundary was the one the generator emitted conditionally, so
  // Meeting-Ops — the flagship — silently shipped a 4-of-5 panel.
  assert.ok(listing.approval_boundary, `${listing.slug} needs an approval boundary`);

  const detail = readFileSync(resolve(root, listing.slug, 'index.html'), 'utf8');
  assert.match(detail, /SoftwareApplication/);
  assert.match(detail, /"@type":"Offer"/);
  assert.match(detail, new RegExp(listing.canonical_url.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  assert.doesNotMatch(detail, /\{\{PRICE_TBD\}\}/);
  assert.doesNotMatch(detail, /Loading Ops-Center/);
  // The seam is declared in words, not just implied by a hostname.
  assert.match(detail, /You are leaving the marketplace/);
  // The exact license appears as a field, never as a blanket claim.
  assert.match(detail, new RegExp(listing.source_license.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));

  // The five trust cards, by heading, in the rendered bytes.
  for (const heading of ['What it can do', 'What waits for you', 'Where it runs',
    'Does data leave your network?', 'Source license']) {
    assert.ok(detail.includes(`<h3>${heading}</h3>`),
      `${listing.slug} is missing the "${heading}" trust card`);
  }

  // A verified canonical_url that nothing renders is not a deep link. This is
  // exactly how accounting-ops ended up pointing only at magicunicorn.dev.
  assert.ok(detail.includes(listing.canonical_url),
    `${listing.slug} never renders its own canonical_url`);
  assert.ok(index.includes(listing.canonical_url),
    `${listing.slug} canonical_url is absent from the catalog page`);

  // PRICE CONTRACT, STRUCTURED-DATA HALF. The visible sweep below only reads
  // text, which is why a machine-readable "price":"0" for a {{PRICE_TBD}}
  // product got through. Parse the JSON-LD and check the offer itself.
  const ld = [...detail.matchAll(/<script type="application\/ld\+json">([\s\S]*?)<\/script>/g)]
    .map((m) => JSON.parse(m[1].replaceAll('\\u003c', '<')));
  const offers = ld.map((o) => o.offers).filter(Boolean);
  assert.equal(offers.length, 1, `${listing.slug} should publish exactly one Offer`);
  if (!listing.price || listing.price === '{{PRICE_TBD}}') {
    assert.ok(!('price' in offers[0]),
      `${listing.slug} price is undecided but JSON-LD publishes price=${offers[0].price}`);
    assert.ok(!('priceCurrency' in offers[0]),
      `${listing.slug} price is undecided but JSON-LD publishes a currency`);
  }
}

for (const slug of removed) {
  assert.doesNotMatch(index, new RegExp(slug, 'i'));
  assert.doesNotMatch(JSON.stringify({ LISTINGS, SUITE }), new RegExp(slug, 'i'));
}

// ── The honesty skeleton ────────────────────────────────────────────────────
assert.doesNotMatch(index, /Trending|Staff picks|reviews and ratings|Compare three/i);
assert.doesNotMatch(index, /\{\{PRICE_TBD\}\}/);
assert.match(index, /The I Have A Business/);
assert.match(index, /Unicorn Commander Suite/);
// The deliberately empty stall, in the ledger with the shipping products.
assert.match(index, /This spot is for your app/);

// Project-Ops is Available now in BOTH the catalog and the crew. A page that
// says "Available now" in the table and "In development" in the crew is a
// self-contradicting page, which is the specific failure this guards.
const projectOps = LISTINGS.find((l) => l.slug === 'project-ops');
assert.equal(projectOps.access, 'Available now');
assert.doesNotMatch(index, /Project-Ops[\s\S]{0,400}?In development/);
assert.match(index, /You can use Meeting-Ops and Project-Ops today/);
// The hyphen trap: projectops resolves, project-ops 404s.
assert.match(projectOps.canonical_url, /^https:\/\/projectops\.unicorncommander\.ai\//);
assert.doesNotMatch(index, /project-ops\.unicorncommander\.ai/);
// The gate is closed, so the verb must not promise entry.
assert.equal(projectOps.cta.label, 'Request access');
// No cleared screenshot exists; the mascot carries the row.
assert.equal(projectOps.screenshot, null);

// ── The sovereignty thesis ──────────────────────────────────────────────────
// A source_url must be null or publicly reachable. verify-hosts.mjs proves
// reachability over the network; this proves the rule is still encoded.
for (const l of LISTINGS) {
  if (l.source_url) {
    assert.doesNotMatch(l.source_url, /git\.unicorncommander\.ai/,
      `${l.slug}.source_url points at the login-walled Forgejo host`);
  }
}
// Never a blanket AGPL claim: Majiks Studio is Apache-2.0 with no public repo.
assert.doesNotMatch(index, /AGPL at the core/i);
assert.match(index, /states its (own|exact) license/i);

// The page must never tell a visitor a public repository is unreachable. This
// shipped as a verifiable falsehood about project-ops-community, which answers
// 200 to anyone, on the one page whose thesis is verified honesty.
for (const l of LISTINGS) {
  const detail = readFileSync(resolve(root, l.slug, 'index.html'), 'utf8');
  if (l.source_url) {
    assert.doesNotMatch(detail, /not publicly reachable/i,
      `${l.slug} has a source_url but the page claims the repo is unreachable`);
    assert.ok(detail.includes(l.source_url), `${l.slug} must link its source_url`);
  }
}

// Self-host is a real destination and a top-level nav peer.
const selfHost = readFileSync(resolve(root, 'self-host', 'index.html'), 'utf8');
assert.match(selfHost, /Self-host/);
assert.match(index, /\/marketplace\/self-host/);

// ── The readout is derived, never typed ─────────────────────────────────────
assert.equal(SELF_HOSTABLE, LISTINGS.filter(isSelfHostable).length);
assert.equal(TOTAL, LISTINGS.length);
assert.match(index, new RegExp(`${String(SELF_HOSTABLE).padStart(2, '0')} / ${String(TOTAL).padStart(2, '0')} PRODUCTS SELF-HOSTABLE`));

// ── The mast is static, and it is the same sentence everywhere ──────────────
// A client-side randomiser used to overwrite the H1 on every load with copy
// that was never approved, so the crawled page and the seen page disagreed on
// ~75% of loads. There must be no headline array and no rotator in the bytes.
assert.doesNotMatch(index, /Math\.random/, 'the index ships a client-side randomiser');
assert.doesNotMatch(index, /const headlines/, 'the headline rotator is back');
for (const invented of ['Meetings noted. Books', 'Finished work <em>lives</em>', 'Own the magic.']) {
  assert.ok(!index.includes(invented), `unapproved headline copy shipped: ${invented}`);
}
assert.ok(index.includes(`<h1 class="mast" id="marketplace-headline">${MAST_HEADLINE}</h1>`),
  'the approved mast is not rendered statically');
// The crawled title and the visible H1 must be the same sentence.
const titleMatch = index.match(/<title>([^<]+)<\/title>/);
assert.ok(titleMatch[1].startsWith(MAST_HEADLINE_TEXT.replace(/\.$/, '')),
  `<title> "${titleMatch[1]}" does not lead with the mast "${MAST_HEADLINE_TEXT}"`);
const ogTitle = index.match(/<meta property="og:title" content="([^"]+)"/);
assert.equal(ogTitle[1], titleMatch[1], 'og:title and <title> disagree');

// ── The crew reads as one set ───────────────────────────────────────────────
// Plates exist ONLY for the three assets with baked backgrounds. A plate
// behind a transparent cutout renders as a broken image, which is what
// --plate:#d3d3d3 did to Meeting-Ops on the front door.
assert.doesNotMatch(index, /--plate:#d3d3d3/, 'the light-grey plate is back on a cutout mascot');
for (const l of LISTINGS) {
  if (l.slug === 'meeting-ops' || l.slug === 'project-ops' || l.slug === 'accounting-ops') {
    assert.ok(!l.plate, `${l.slug} art is a true cutout and must not declare a plate`);
  }
}

console.log(`Marketplace static-page contract: passed (${LISTINGS.length} listings, ${SELF_HOSTABLE} self-hostable)`);
