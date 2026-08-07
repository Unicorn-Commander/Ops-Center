#!/usr/bin/env node
/**
 * verify-hosts.mjs — the honesty gate. Run BEFORE the page generator.
 *
 * Convention degrades. A failing build does not.
 *
 * Two classes of defect this permanently retires:
 *
 *  1. THE HYPHEN TRAP. "projectops.unicorncommander.ai" resolves;
 *     "project-ops.unicorncommander.ai" returns Traefik's 404. Every outbound
 *     link is HEAD-checked, so a hand-typed hostname cannot ship.
 *
 *  2. THE LOGIN-WALLED SOURCE. The whole third audience is "they can host it
 *     too". A `source_url` that answers 303 -> /user/login to an anonymous
 *     visitor actively discredits that thesis: the sovereignty claim is the one
 *     thing no competing marketplace can match, and a dead link under it is
 *     worse than no link. So source_url must be anonymously reachable or null.
 *
 * Checked anonymously, with redirect:'manual', because that is exactly what a
 * stranger and a crawler get. A 302 to an SSO realm is a FAILURE here even
 * though it is a 200 in your logged-in browser.
 *
 * Usage:  node scripts/verify-hosts.mjs [--allow-offline]
 */

import { LISTINGS, SUITE } from '../src/data/marketplaceListings.js';

const TIMEOUT_MS = 15000;
const allowOffline = process.argv.includes('--allow-offline');

const UA = 'Mozilla/5.0 (compatible; UC-Marketplace-LinkVerifier/1.0; +https://unicorncommander.ai/marketplace)';

async function probe(url) {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), TIMEOUT_MS);
  try {
    // HEAD first; some origins refuse HEAD, so fall back to a ranged GET.
    let res = await fetch(url, {
      method: 'HEAD', redirect: 'manual', signal: ctl.signal,
      headers: { 'user-agent': UA },
    });
    if (res.status === 405 || res.status === 501) {
      res = await fetch(url, {
        method: 'GET', redirect: 'manual', signal: ctl.signal,
        headers: { 'user-agent': UA, range: 'bytes=0-0' },
      });
    }
    return { status: res.status, location: res.headers.get('location') || '' };
  } catch (err) {
    return { status: 0, location: '', error: err.name === 'AbortError' ? 'timeout' : String(err.message || err) };
  } finally {
    clearTimeout(timer);
  }
}

const targets = [];
const push = (slug, field, url) => {
  if (!url) return;                       // null is a legal, designed value
  if (url.startsWith('/')) return;        // same-origin route, not an outbound host
  targets.push({ slug, field, url });
};

for (const l of LISTINGS) {
  push(l.slug, 'canonical_url', l.canonical_url);
  push(l.slug, 'learn_more_url', l.learn_more_url);
  push(l.slug, 'cta.href', l.cta?.href);
  push(l.slug, 'secondary_cta.href', l.secondary_cta?.href);
  push(l.slug, 'source_url', l.source_url);
}
push(SUITE.slug, 'cta.href', SUITE.cta?.href);

const seen = new Map();
const failures = [];
const results = [];

for (const t of targets) {
  if (!seen.has(t.url)) seen.set(t.url, await probe(t.url));
  const r = seen.get(t.url);
  results.push({ ...t, ...r });

  const ok = r.status >= 200 && r.status < 300;

  if (r.status === 0) {
    if (allowOffline) continue;           // explicit opt-out for air-gapped builds
    failures.push(`${t.slug}.${t.field} UNREACHABLE (${r.error}) ${t.url}`);
    continue;
  }
  if (!ok) {
    const hint = r.location ? ` -> ${r.location}` : '';
    failures.push(`${t.slug}.${t.field} HTTP ${r.status}${hint}  ${t.url}`);
    continue;
  }
}

// Hard-fail: a non-null source_url that is not anonymously reachable. This is
// stricter than the generic check above because of what it claims.
for (const l of LISTINGS) {
  if (!l.source_url) continue;
  const r = seen.get(l.source_url);
  if (!r) continue;
  if (r.status === 0 && allowOffline) continue;
  if (!(r.status >= 200 && r.status < 300)) {
    failures.push(
      `${l.slug}.source_url is set but NOT anonymously reachable (HTTP ${r.status}). ` +
      `Set source_url: null and let the listing fall back to /marketplace/self-host. ` +
      `Linking a login-walled repo under the sovereignty claim is worse than linking nothing.`
    );
  }
}

const pad = (s, n) => String(s).padEnd(n);
for (const r of results) {
  const mark = r.status >= 200 && r.status < 300 ? 'ok  ' : (r.status === 0 ? '?? ' : 'FAIL');
  console.log(`  ${mark} ${pad(r.status || r.error, 8)} ${pad(`${r.slug}.${r.field}`, 34)} ${r.url}`);
}

if (failures.length) {
  console.error(`\nverify-hosts: ${failures.length} failure(s)\n`);
  for (const f of failures) console.error(`  - ${f}`);
  console.error('\nBuild stopped. Fix the URL or set the field to null.\n');
  process.exit(1);
}

console.log(`\nverify-hosts: ${results.length} outbound link(s) verified, all 2xx.`);
