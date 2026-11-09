/**
 * Theme tokens for the signed-in home (User Home design, section k).
 *
 * Ported from the approved round 3.1 mock (mock/_src/build.py), which is the
 * single source of truth for the palette and its contrast gate. Six families,
 * each light and dark, plus one high contrast mode: thirteen themes. The family
 * sets the accent, a second accent and the two wash colours behind the
 * greeting; the mode sets the neutrals; a family overrides only the neutrals
 * that give it its identity. Section hues are per mode.
 *
 * The page reads these values as CSS custom properties set on the home's root
 * element (themeVars), so the page and the gate (checkTheme, run by the unit
 * test over every theme) derive exactly the same colours. A change here must
 * keep every text pairing at 4.5:1 or better; the test fails otherwise.
 */

export const LIGHT = Object.freeze({
  surface: '#ffffff', surface2: '#f2f4f8', inset: '#f7f8fb', line: '#e3e6ec', line2: '#cfd5df',
  text: '#0f172a', muted: '#4a5567', dim: '#525e6e', onAccent: '#ffffff',
  ok: '#1a6b32', warn: '#874d00', bad: '#a81f16'
});

export const DARK = Object.freeze({
  text: '#e7e9ef', muted: '#a9b1bd', dim: '#99a2b0', onAccent: '#0b0e14',
  ok: '#72d69c', warn: '#f2b85a', bad: '#ff8f85'
});

export const FAMILIES = Object.freeze({
  pro: {
    name: 'Professional', desc: 'Calm indigo on cool grey. The default.',
    light: { ...LIGHT, bg: '#f5f6fa', accent: '#3451d1', accentSoft: '#e7ebfa', accent2: '#0369a1', wash1: '#3451d1', wash2: '#38bdf8' },
    dark: { ...DARK, bg: '#0b0e14', surface: '#131720', surface2: '#1b2029', inset: '#0f131a', line: '#232a36', line2: '#313a48',
      accent: '#8ea4ff', accentSoft: '#1c2546', accent2: '#5fd3f3', wash1: '#3451d1', wash2: '#0ea5e9' }
  },
  unicorn: {
    name: 'Magic Unicorn', desc: 'Purple and violet on deep slate.',
    light: { ...LIGHT, bg: '#f7f5fb', surface2: '#f3f0f9', inset: '#f8f6fc', line: '#e6e1f0', line2: '#d4cce3',
      accent: '#6d28d9', accentSoft: '#ede6fb', accent2: '#8b2fd9', wash1: '#d8b4fe', wash2: '#99f6e4' },
    dark: { ...DARK, bg: '#0e0c15', surface: '#16131f', surface2: '#1e1a2a', inset: '#110f19', line: '#272136', line2: '#352e48',
      text: '#ece8f5', muted: '#b2abc3', dim: '#a29bb4', accent: '#c4a4ff', accentSoft: '#2a2143', accent2: '#b66eff', wash1: '#7c3aed', wash2: '#22d3ee' }
  },
  galaxy: {
    name: 'Unicorn Galaxy', desc: 'Purple with gold.',
    light: { ...LIGHT, bg: '#f6f4fb', surface2: '#f1eef9', inset: '#f8f6fc', line: '#e4dff0', line2: '#d1c9e4',
      accent: '#5b21b6', accentSoft: '#ebe4fa', accent2: '#7a5c00', wash1: '#c4b5fd', wash2: '#fde68a' },
    dark: { ...DARK, bg: '#0c0918', surface: '#15102a', surface2: '#1d1737', inset: '#100c21', line: '#2a2247', line2: '#3a3060',
      text: '#efeafa', muted: '#b8b0ce', dim: '#a69dc0', accent: '#c9a6ff', accentSoft: '#2c2250', accent2: '#f5c84b', wash1: '#7c3aed', wash2: '#f5c84b' }
  },
  special: {
    name: 'Special Projects', desc: 'Violet and cyan, the ops look.',
    light: { ...LIGHT, bg: '#f4f6fa', accent: '#5b3fd1', accentSoft: '#e9e5fa', accent2: '#0b6478', wash1: '#a78bfa', wash2: '#67e8f9' },
    dark: { ...DARK, bg: '#070912', surface: '#0e1220', surface2: '#151a2b', inset: '#0a0d18', line: '#1e2538', line2: '#2b3450',
      text: '#e6e9f3', muted: '#a8b1c4', dim: '#98a2b7', accent: '#a78bfa', accentSoft: '#231d45', accent2: '#22d3ee', wash1: '#6d28d9', wash2: '#0891b2' }
  },
  ocean: {
    name: 'Ocean', desc: 'Teal and sea blue.',
    light: { ...LIGHT, bg: '#f2f7f9', surface2: '#eaf2f5', inset: '#f5f9fb', line: '#dbe6eb', line2: '#c6d6de',
      accent: '#0b6478', accentSoft: '#dff3f7', accent2: '#035e90', wash1: '#67e8f9', wash2: '#7dd3fc' },
    dark: { ...DARK, bg: '#071318', surface: '#0e1d24', surface2: '#14272f', inset: '#0a171d', line: '#1c323b', line2: '#28444f',
      text: '#e3eef2', muted: '#a3bac3', dim: '#94acb6', accent: '#5fd0d6', accentSoft: '#113238', accent2: '#7dd3fc', wash1: '#0e7490', wash2: '#0369a1' }
  },
  sunset: {
    name: 'Sunset', desc: 'Warm orange and rose.',
    light: { ...LIGHT, bg: '#fbf5f1', surface2: '#f6ede7', inset: '#fcf7f3', line: '#ecdfd7', line2: '#dccbc0',
      accent: '#ad3806', accentSoft: '#fbe8df', accent2: '#b01555', wash1: '#fdba74', wash2: '#f9a8d4' },
    dark: { ...DARK, bg: '#160e0b', surface: '#211411', surface2: '#2b1b17', inset: '#1a100d', line: '#382521', line2: '#4a332d',
      text: '#f4ebe6', muted: '#c9b0a6', dim: '#b69e94', accent: '#fb923c', accentSoft: '#3d2214', accent2: '#f472b6', wash1: '#c2410c', wash2: '#be185d' }
  }
});

export const CONTRAST = Object.freeze({
  bg: '#ffffff', surface: '#ffffff', surface2: '#f2f2f2', inset: '#f7f7f7', line: '#000000', line2: '#000000',
  text: '#000000', muted: '#1a1a1a', dim: '#262626', onAccent: '#ffffff',
  accent: '#0000c8', accentSoft: '#e6e6ff', accent2: '#4b0082', wash1: '#ffffff', wash2: '#ffffff',
  ok: '#006400', warn: '#7a4a00', bad: '#a00000'
});

// One hue per module and per app, constant across themes; only the shade moves
// so each hue passes AA as text inside its own tint on that theme's surface.
export const HUES = Object.freeze(['blue', 'violet', 'teal', 'amber', 'green', 'rose', 'slate', 'indigo', 'coral']);
export const HUE_LIGHT = Object.freeze({ blue: '#2450c4', violet: '#5f3fc4', teal: '#0a6066', amber: '#874d00', green: '#1a6b32', rose: '#a62a52', slate: '#4e5866', indigo: '#3d33b5', coral: '#a33314' });
export const HUE_DARK = Object.freeze({ blue: '#8ab0ff', violet: '#b8a6ff', teal: '#5fd0d6', amber: '#f0b453', green: '#6fd39a', rose: '#ff9bbd', slate: '#a3aab6', indigo: '#a5b4fc', coral: '#ffa38f' });
export const HUE_CONTRAST = Object.freeze({ blue: '#0000c8', violet: '#4b0082', teal: '#005a5f', amber: '#7a4a00', green: '#006400', rose: '#8b0038', slate: '#1a1a1a', indigo: '#1e1b8a', coral: '#8f2400' });

// Tint strengths (color-mix of a hue into --surface), emitted as --tint-* so
// the stylesheet and the gate derive the same colours.
export const CARD_PCT = 7; // vivid: module body tint
export const BAND_PCT = 16; // vivid: module header band
export const CHIP_PCT = 16; // subtle: chip, mark and type pills
export const CHIPV_PCT = 22; // vivid: chip, mark and type pills
export const AA = 4.5;

export const FAMILY_IDS = Object.freeze(Object.keys(FAMILIES));
export const MODES = Object.freeze(['system', 'light', 'dark', 'contrast']);
export const INTENSITIES = Object.freeze(['subtle', 'vivid']);
export const FONTS = Object.freeze({
  plex: { name: 'IBM Plex Sans', stack: '"IBM Plex Sans", var(--uh-font-system)', tracking: '0', trackingH1: '-0.012em' },
  manrope: { name: 'Manrope', stack: '"Manrope", var(--uh-font-system)', tracking: '0', trackingH1: '-0.02em' },
  archivo: { name: 'Archivo', stack: '"Archivo", var(--uh-font-system)', tracking: '0.002em', trackingH1: '-0.015em' },
  system: { name: 'System', stack: 'var(--uh-font-system)', tracking: '0', trackingH1: '-0.015em' }
});

export const DEFAULT_APPEARANCE = Object.freeze({ family: 'pro', mode: 'light', intensity: 'vivid', font: 'plex' });

// --------------------------------------------------------------- colour maths

function hexToRgb(hex) {
  const h = String(hex).replace('#', '');
  return [0, 2, 4].map(i => parseInt(h.slice(i, i + 2), 16));
}

export function luminance(hex) {
  const [r, g, b] = hexToRgb(hex).map(c => {
    const v = c / 255;
    return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

export function contrastRatio(a, b) {
  const la = luminance(a);
  const lb = luminance(b);
  const hi = Math.max(la, lb);
  const lo = Math.min(la, lb);
  return (hi + 0.05) / (lo + 0.05);
}

// Python's round(): halves go to the even neighbour. Matches build.py exactly.
function roundHalfEven(value) {
  const floor = Math.floor(value);
  const diff = value - floor;
  if (Math.abs(diff - 0.5) < 1e-9) return floor % 2 === 0 ? floor : floor + 1;
  return Math.round(value);
}

/** color-mix(in srgb, a pct%, b), component-wise in gamma space as the browser does. */
export function mix(a, b, pctA) {
  const ra = hexToRgb(a);
  const rb = hexToRgb(b);
  const t = pctA / 100;
  return `#${[0, 1, 2]
    .map(i => roundHalfEven(ra[i] * t + rb[i] * (1 - t)).toString(16).padStart(2, '0'))
    .join('')}`;
}

// ------------------------------------------------------------------- themes

export function themeTokens(family, mode) {
  if (mode === 'contrast') return { tokens: CONTRAST, hues: HUE_CONTRAST };
  const fam = FAMILIES[family] || FAMILIES.pro;
  return mode === 'dark'
    ? { tokens: fam.dark, hues: HUE_DARK }
    : { tokens: fam.light, hues: HUE_LIGHT };
}

/** Every theme the person can pick: six families in two modes, and high contrast. */
export function allThemes() {
  const themes = [];
  for (const id of FAMILY_IDS) {
    for (const mode of ['light', 'dark']) {
      themes.push({ id: `${id}/${mode}`, name: `${FAMILIES[id].name} ${mode}`, ...themeTokens(id, mode) });
    }
  }
  themes.push({ id: 'contrast', name: 'High contrast', ...themeTokens('pro', 'contrast') });
  return themes;
}

/**
 * The contrast gate, ported from build.py ``check``. Every pairing here occurs
 * in the page: text, muted, dim, accent, ok, warn and bad on the four flat
 * surfaces and on every section's vivid body tint and header band; the second
 * accent on the flat surfaces (it is only ever the Galaxy brand word); every
 * hue on the flat surfaces and inside its own pill at both intensities; and
 * text on the accent button. Returns the worst ratio, where it is, and every
 * failing pairing.
 */
export function checkTheme(tokens, hues) {
  const fails = [];
  let worst = { ratio: 99, where: '' };
  const need = (fg, bg, label) => {
    const r = contrastRatio(fg, bg);
    if (r < AA) fails.push({ ratio: r, label });
    if (r < worst.ratio) worst = { ratio: r, where: label };
  };
  const flat = { bg: tokens.bg, surface: tokens.surface, surface2: tokens.surface2, inset: tokens.inset };
  const tinted = {};
  for (const [key, value] of Object.entries(hues)) {
    tinted[`card-${key}`] = mix(value, tokens.surface, CARD_PCT);
    tinted[`band-${key}`] = mix(value, tokens.surface, BAND_PCT);
  }
  for (const tk of ['text', 'muted', 'dim', 'accent', 'ok', 'warn', 'bad']) {
    for (const [sk, sv] of [...Object.entries(flat), ...Object.entries(tinted)]) {
      need(tokens[tk], sv, `${tk} on ${sk}`);
    }
  }
  for (const [sk, sv] of Object.entries(flat)) need(tokens.accent2, sv, `accent2 on ${sk}`);
  for (const [hk, hv] of Object.entries(hues)) {
    const own = {
      ...flat,
      [`chip-${hk}`]: mix(hv, tokens.surface, CHIP_PCT),
      [`chipv-${hk}`]: mix(hv, tokens.surface, CHIPV_PCT)
    };
    for (const [sk, sv] of Object.entries(own)) need(hv, sv, `hue-${hk} on ${sk}`);
  }
  need(tokens.onAccent, tokens.accent, 'onAccent on accent');
  fails.sort((x, y) => x.ratio - y.ratio);
  return { worst: worst.ratio, where: worst.where, fails };
}

/**
 * CSS custom properties for one theme, set on the home's root element. Names
 * match the mock's stylesheet with a uh- prefix so nothing leaks to or from
 * the rest of Ops-Center.
 */
export function themeVars({ family, mode, font }) {
  const { tokens: t, hues } = themeTokens(family, mode);
  const face = FONTS[font] || FONTS.plex;
  const vars = {
    '--uh-bg': t.bg, '--uh-surface': t.surface, '--uh-surface-2': t.surface2, '--uh-inset': t.inset,
    '--uh-line': t.line, '--uh-line-2': t.line2, '--uh-text': t.text, '--uh-muted': t.muted, '--uh-dim': t.dim,
    '--uh-accent': t.accent, '--uh-accent-soft': t.accentSoft, '--uh-on-accent': t.onAccent, '--uh-accent-2': t.accent2,
    '--uh-wash-1': t.wash1, '--uh-wash-2': t.wash2, '--uh-ok': t.ok, '--uh-warn': t.warn, '--uh-bad': t.bad,
    '--uh-tint-card': `${CARD_PCT}%`, '--uh-tint-band': `${BAND_PCT}%`,
    '--uh-tint-chip': `${CHIP_PCT}%`, '--uh-tint-chipv': `${CHIPV_PCT}%`,
    '--uh-font': face.stack, '--uh-tracking': face.tracking, '--uh-tracking-h1': face.trackingH1
  };
  for (const [key, value] of Object.entries(hues)) vars[`--uh-h-${key}`] = value;
  return vars;
}

/** Swatch colours for the Appearance panel: accent and second wash per mode. */
export function familySwatch(family, resolvedMode) {
  const fam = FAMILIES[family] || FAMILIES.pro;
  const set = resolvedMode === 'dark' ? fam.dark : fam.light;
  return [set.accent, set.wash2];
}

export function normalizeAppearance(value) {
  const source = value && typeof value === 'object' ? value : {};
  return {
    family: FAMILY_IDS.includes(source.family) ? source.family : DEFAULT_APPEARANCE.family,
    mode: MODES.includes(source.mode) ? source.mode : DEFAULT_APPEARANCE.mode,
    intensity: INTENSITIES.includes(source.intensity) ? source.intensity : DEFAULT_APPEARANCE.intensity,
    font: Object.prototype.hasOwnProperty.call(FONTS, source.font) ? source.font : DEFAULT_APPEARANCE.font
  };
}
