#!/usr/bin/env node

// The only automated guard on the honesty skeleton. Run it after regenerating.
//   node scripts/test-marketplace-pages.mjs

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { LISTINGS, SUITE } from '../src/data/marketplaceListings.js';
import { SELF_HOSTABLE, TOTAL, isSelfHostable } from '../src/data/marketplaceSystem.js';

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
// Never a blanket AGPL claim: Project-Ops is Apache-2.0.
assert.doesNotMatch(index, /AGPL at the core/i);
assert.match(index, /states its (own|exact) license/i);

// Self-host is a real destination and a top-level nav peer.
const selfHost = readFileSync(resolve(root, 'self-host', 'index.html'), 'utf8');
assert.match(selfHost, /Self-host/);
assert.match(index, /\/marketplace\/self-host/);

// ── The readout is derived, never typed ─────────────────────────────────────
assert.equal(SELF_HOSTABLE, LISTINGS.filter(isSelfHostable).length);
assert.equal(TOTAL, LISTINGS.length);
assert.match(index, new RegExp(`${String(SELF_HOSTABLE).padStart(2, '0')} / ${String(TOTAL).padStart(2, '0')} PRODUCTS SELF-HOSTABLE`));

console.log(`Marketplace static-page contract: passed (${LISTINGS.length} listings, ${SELF_HOSTABLE} self-hostable)`);
