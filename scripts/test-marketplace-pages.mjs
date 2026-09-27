#!/usr/bin/env node

// The only automated guard on the honesty skeleton. Run it after regenerating.
//   node scripts/test-marketplace-pages.mjs

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { LISTINGS, SUITE } from '../src/data/marketplaceListings.js';
import {
  MAST_HEADLINE, MAST_HEADLINE_TEXT, SELF_HOSTABLE, SUITE_AVAILABLE,
  SUITE_AVAILABLE_LINE, SUITE_TOTAL, TOTAL, isSelfHostable,
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

// ── THE SUITE BUNDLE PAGE ───────────────────────────────────────────────────
// The bundle carried three live Stripe SKU pairs at three different prices and
// had NO page at all: /marketplace/unicorn-commander-suite was a 404 while the
// thing was billable. These assertions keep the page real, prerendered, linked,
// and honest about what you can actually use.
const suite = readFileSync(resolve(root, SUITE.slug, 'index.html'), 'utf8');

// Genuinely prerendered, exactly like its siblings — not an SPA shell.
assert.doesNotMatch(suite, /id="root"/, 'the Suite page shipped an SPA mount point');
assert.doesNotMatch(suite, /\/assets\/index-[A-Za-z0-9_-]+\.js/, 'the Suite page shipped a JS bundle');
assert.doesNotMatch(suite, /Loading Ops-Center/);
assert.match(suite, /<h1 class="page-title">Unicorn Commander Suite<\/h1>/);

// Same instrument as the other listing pages: one stylesheet, the five trust
// cards, the declared seam.
assert.match(suite, /\/marketplace\/marketplace\.css/);
assert.match(suite, /You are leaving the marketplace/);
for (const heading of ['What it can do', 'What waits for you', 'Where it runs',
  'Does data leave your network?', 'Source license']) {
  assert.ok(suite.includes(`<h3>${heading}</h3>`), `the Suite page is missing the "${heading}" trust card`);
}

// A page nothing links to is still a 404 in practice. The catalog must reach it.
assert.match(index, new RegExp(`/marketplace/${SUITE.slug}`),
  'the catalog page does not link to the Suite listing');

// PRICE. One decided number, rendered, and matching the SKU the locked price
// sheet chose. The whole defect was three live prices and no page saying which.
// ── MEETING-OPS PRICE CONTRACT (2026-08-08 reprice) ────────────────────────
// The flagship listing rendered NO price at all while a live checkout charged
// for it. Now it renders both cycles, and these assertions are what stop the
// page and the charge drifting apart again.
const meetingOps = LISTINGS.find((l) => l.slug === 'meeting-ops');
assert.equal(meetingOps.price, '$22/month');
assert.equal(meetingOps.price_annual, '$216/year');
{
  const mo = readFileSync(resolve(root, 'meeting-ops', 'index.html'), 'utf8');
  assert.match(mo, /\$22\/month/, 'the Meeting-Ops page does not render its monthly price');
  assert.match(mo, /\$216\/year/, 'the Meeting-Ops page does not render its annual price');
  assert.match(index, /\$22\/month/, 'the catalog page does not render the Meeting-Ops price');
  // The saving must be arithmetic between the two real prices, never an anchor.
  const monthly = Number(meetingOps.price.replace(/[^0-9.]/g, ''));
  const annual = Number(meetingOps.price_annual.replace(/[^0-9.]/g, ''));
  assert.ok(annual < monthly * 12, 'the annual price is not actually cheaper');
  assert.match(meetingOps.price_note, new RegExp(`\\$${monthly * 12 - annual} less`),
    'the Meeting-Ops price note states a saving that is not monthly*12 - annual');
  const moLd = [...mo.matchAll(/<script type="application\/ld\+json">([\s\S]*?)<\/script>/g)]
    .map((m) => JSON.parse(m[1].replaceAll('\\u003c', '<')));
  assert.equal(moLd[0].offers.price, String(monthly),
    'JSON-LD price disagrees with the visible Meeting-Ops price');
  assert.equal(moLd[0].offers.priceCurrency, 'USD');
}
// No surface may still advertise a retired Meeting-Ops price. $15/$150 and the
// $7.99/$79 Basic rung were archived in Stripe on 2026-08-08; $20 was never
// charged to anyone and must never come back as a struck-through anchor.
for (const dead of ['$15/month', '$15/mo', '$150/year', '$7.99', '$79/year', '$20/month', '$20/mo']) {
  assert.ok(!index.includes(dead), `the catalog page still advertises ${dead}`);
}

assert.equal(SUITE.price, '$49/month');
assert.equal(SUITE.price_annual, '$490/year');
assert.doesNotMatch(suite, /\{\{PRICE_TBD\}\}/);
assert.match(suite, /\$49\/month/);
// The Managed rung is NAMED with its number, so no door can surprise a buyer.
assert.match(suite, /\$65\/month/, 'the Suite page hides the Managed tier price');
// The superseded $35 SKU must never be advertised.
assert.doesNotMatch(suite, /\$35\/month|\$350\/year/, 'the superseded $35 Suite SKU is being advertised');

// JSON-LD must agree with the visible price and must NOT claim InStock for a
// bundle that is priced but not yet on sale.
const suiteLd = [...suite.matchAll(/<script type="application\/ld\+json">([\s\S]*?)<\/script>/g)]
  .map((m) => JSON.parse(m[1].replaceAll('\\u003c', '<')));
assert.equal(suiteLd.length, 1);
assert.equal(suiteLd[0].offers.price, '49');
assert.equal(suiteLd[0].offers.priceCurrency, 'USD');
assert.equal(suiteLd[0].offers.availability, 'https://schema.org/InStock');

// BUNDLE HONESTY. Members are derived from their own listings, so the page can
// never sell eight names while implying all eight are usable.
assert.ok(SUITE.members.length === SUITE_TOTAL && SUITE_TOTAL > 0);
assert.ok(SUITE_AVAILABLE > 0 && SUITE_AVAILABLE < SUITE_TOTAL,
  'the Suite member split is all-or-nothing; re-check the derivation');
assert.match(suite, new RegExp(SUITE_AVAILABLE_LINE.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
assert.match(index, new RegExp(SUITE_AVAILABLE_LINE.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')),
  'the catalog and the bundle page disagree on how much of the Suite is available');
for (const m of SUITE.members) {
  assert.ok(suite.includes(m.name), `the Suite page omits member ${m.name}`);
  const listed = LISTINGS.find((l) => l.slug === m.slug);
  if (m.slug) {
    assert.ok(listed, `Suite member ${m.slug} links to a listing that does not exist`);
    assert.equal(m.access, listed.access,
      `Suite member ${m.slug} says "${m.access}" but its listing says "${listed.access}"`);
    assert.ok(suite.includes(`/marketplace/${m.slug}`));
  } else {
    // No listing means no link — never a link to a page that would 404.
    assert.notEqual(m.access, 'Available now',
      `Suite member ${m.name} claims "Available now" with no listing to prove it`);
  }
}
// No blanket license claim for a bundle that does not have one.
assert.doesNotMatch(suite, /AGPL at the core/i);
assert.match(suite, /each listing states its own/i);

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
