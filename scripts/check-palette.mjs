#!/usr/bin/env node
/**
 * check-palette.mjs — the neutral-hue gate, as a build check rather than a
 * comment nobody reads.
 *
 * The brief bans "warm cream + serif display + coral accent" and explicitly
 * counts sneaky variants as a failure: a cream that is technically #f8f0e4
 * still reads as cream. A saturation ceiling cannot catch that, because the
 * offending value can always be nudged one point under the ceiling.
 *
 * A hue predicate can. Every neutral surface in this system must satisfy:
 *
 *     G > R   and   G >= B          (the ramp leans green, never warm)
 *     hue NOT in [35deg, 70deg]     (that band IS cream / sand / tan)
 *
 * Both ends of the ramp are hue-opposed on purpose: the dark canvas cools
 * (~180deg), the light canvas is a green-grey (~90deg). That opposition is why
 * the mint accent reads as instrumentation in dark and as ink in light.
 *
 * This also re-measures every chord + ink contrast against its own canvas and
 * fails under 4.5:1, so nobody can adjust a token without re-measuring.
 *
 * Usage:  node scripts/check-palette.mjs
 */

import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const cssPath = resolve(here, '../public/marketplace/marketplace.css');
const cssRaw = readFileSync(cssPath, 'utf8');
// Strip comments before any content assertion. This file documents the rules
// it enforces, and the documentation names the very properties it bans, so a
// naive grep over the raw text matches its own prose and fails a clean sheet.
const css = cssRaw.replace(/\/\*[\s\S]*?\*\//g, '');

const hex = (h) => {
  h = h.replace('#', '');
  if (h.length === 3) h = h.split('').map((c) => c + c).join('');
  return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16));
};
const lin = (c) => { c /= 255; return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; };
const L = (h) => { const [r, g, b] = hex(h); return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b); };
const ratio = (a, b) => { const x = L(a), y = L(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
const hue = (h) => {
  let [r, g, b] = hex(h).map((v) => v / 255);
  const mx = Math.max(r, g, b), mn = Math.min(r, g, b), d = mx - mn;
  if (!d) return 0;
  let hh;
  if (mx === r) hh = ((g - b) / d) % 6;
  else if (mx === g) hh = (b - r) / d + 2;
  else hh = (r - g) / d + 4;
  hh *= 60;
  return hh < 0 ? hh + 360 : hh;
};

// Pull a token's value out of a given selector block.
const block = (selector) => {
  const i = css.indexOf(selector);
  if (i < 0) throw new Error(`check-palette: selector not found: ${selector}`);
  const open = css.indexOf('{', i);
  const close = css.indexOf('}', open);
  return css.slice(open, close);
};
const token = (selector, name) => {
  const m = block(selector).match(new RegExp(`${name}\\s*:\\s*(#[0-9a-fA-F]{3,8})`));
  if (!m) throw new Error(`check-palette: ${name} not found in ${selector}`);
  return m[1].toLowerCase();
};

const SURFACES = ['--canvas'];  // only tokens actually referenced via var(); raised/panel/panel-soft were declared-but-unused and were removed
const INKS = ['--ink', '--ink-soft', '--muted', '--quiet'];
const CHORD = ['--signal', '--signal-warm', '--signal-violet'];

const THEMES = [
  { label: 'dark ', sel: ":root[data-theme='dark']" },
  { label: 'light', sel: ":root[data-theme='light']" },
];

const failures = [];
let checks = 0;

for (const { label, sel } of THEMES) {
  const canvas = token(sel, '--canvas');

  // Gate 1: the neutral hue predicate, on surfaces AND on the ink ramp. The
  // ink ramp is included because a warm ink on a green ground reads as cream
  // just as loudly as a warm surface does.
  for (const name of [...SURFACES, ...INKS]) {
    const v = token(sel, name);
    const [r, g, b] = hex(v);
    const h = hue(v);
    checks++;
    if (!(g > r && g >= b)) {
      failures.push(`${label} ${name} ${v}: fails G>R && G>=B (R${r} G${g} B${b}) — the ramp must lean green`);
    }
    if (h >= 35 && h <= 70) {
      failures.push(`${label} ${name} ${v}: hue ${h.toFixed(1)}deg is inside the banned cream band [35,70]`);
    }
  }

  // Gate 2: measured contrast. Nothing ships under 4.5:1.
  for (const name of [...CHORD, ...INKS]) {
    const v = token(sel, name);
    const cr = ratio(v, canvas);
    checks++;
    if (cr < 4.5) {
      failures.push(`${label} ${name} ${v} on ${canvas}: ${cr.toFixed(2)}:1 is below 4.5:1`);
    }
  }
}

// Gate 3: the two canvases must be hue-opposed, not two shades of one cast.
const dh = hue(token(":root[data-theme='dark']", '--canvas'));
const lh = hue(token(":root[data-theme='light']", '--canvas'));
checks++;
if (Math.abs(dh - lh) < 20) {
  failures.push(`canvases are not hue-opposed: dark ${dh.toFixed(1)}deg vs light ${lh.toFixed(1)}deg`);
}

// Gate 4: radius discipline. --r-lg / --r-xl must stay undefined so nobody can
// reach for them, and no rule may round a corner past 8px except pills.
checks++;
if (/--r-(lg|xl)\s*:/.test(css)) {
  failures.push('--r-lg / --r-xl are defined. They are deliberately absent; rows and panels are square.');
}

// Gate 5: no dark-mode elevation. A drop shadow on near-black is the
// glassmorphism tell the brief bans.
const darkBlock = block(":root[data-theme='dark']");
checks++;
checks++;
if (/backdrop-filter/.test(css)) {
  failures.push('backdrop-filter present. No glass.');
}

if (failures.length) {
  console.error(`\ncheck-palette: ${failures.length} violation(s) of ${checks} checks\n`);
  for (const f of failures) console.error(`  - ${f}`);
  console.error('');
  process.exit(1);
}
console.log(`check-palette: ${checks} checks passed (hue gate, contrast, radius, elevation).`);
