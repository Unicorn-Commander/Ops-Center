#!/usr/bin/env node

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { LISTINGS, SUITE } from '../src/data/marketplaceListings.js';

const root = resolve(import.meta.dirname, '../public/marketplace');
const expected = ['accounting-ops', 'center-deep-research', 'majiks-studio', 'meeting-ops'];
const removed = ['tax-planning-ops', 'security-ops', 'wealth-ops', 'crisis-management-ops'];

assert.deepEqual(LISTINGS.map((listing) => listing.slug).sort(), expected);

const index = readFileSync(resolve(root, 'index.html'), 'utf8');
for (const listing of LISTINGS) {
  assert.match(index, new RegExp(listing.name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  assert.ok(listing.deployment_options.length > 0, `${listing.slug} needs a deployment mode`);
  assert.ok(listing.capabilities.length > 0, `${listing.slug} needs verified capabilities`);
  assert.ok(listing.source_license, `${listing.slug} needs a source license`);
  assert.ok(listing.data_egress, `${listing.slug} needs a data-egress answer`);

  const detail = readFileSync(resolve(root, listing.slug, 'index.html'), 'utf8');
  assert.match(detail, /SoftwareApplication/);
  assert.match(detail, /"@type":"Offer"/);
  assert.match(detail, /Trust, in plain language/);
  assert.match(detail, new RegExp(listing.canonical_url.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  assert.doesNotMatch(detail, /\{\{PRICE_TBD\}\}/);
  assert.doesNotMatch(detail, /Loading Ops-Center/);
}

for (const slug of removed) {
  assert.doesNotMatch(index, new RegExp(slug, 'i'));
  assert.doesNotMatch(JSON.stringify({ LISTINGS, SUITE }), new RegExp(slug, 'i'));
}

assert.doesNotMatch(index, /Trending|Staff picks|reviews and ratings|Compare three/i);
assert.match(index, /The I Have A Business To Run Crew/);
assert.match(index, /Unicorn Commander Suite/);
assert.match(index, /Project-Ops[\s\S]*In development/);

console.log('Marketplace static-page contract: passed');
