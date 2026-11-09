import { describe, expect, test } from 'vitest';
import {
  AA,
  allThemes,
  checkTheme,
  contrastRatio,
  DEFAULT_APPEARANCE,
  FAMILY_IDS,
  mix,
  normalizeAppearance,
  themeVars
} from './homeTokens';

// The per-theme minimums the mock's build.py gate printed for round 3.1
// (LANE-REPORT.md, "Gate, final per-theme minimums"), to four places.
const MOCK_MINIMUMS = {
  'pro/light': 4.6899, 'pro/dark': 4.9848,
  'unicorn/light': 4.6899, 'unicorn/dark': 4.9928,
  'galaxy/light': 4.6899, 'galaxy/dark': 5.2608,
  'special/light': 4.6899, 'special/dark': 4.9974,
  'ocean/light': 4.6899, 'ocean/dark': 4.8537,
  'sunset/light': 4.6899, 'sunset/dark': 5.0679,
  contrast: 5.1705
};

describe('home theme tokens', () => {
  test('there are thirteen themes: six families in light and dark, and high contrast', () => {
    expect(FAMILY_IDS).toEqual(['pro', 'unicorn', 'galaxy', 'special', 'ocean', 'sunset']);
    expect(allThemes().map(t => t.id)).toEqual(Object.keys(MOCK_MINIMUMS));
  });

  test.each(allThemes().map(t => [t.id, t]))('%s: every text pairing in the page is at least 4.5:1', (id, theme) => {
    const { worst, where, fails } = checkTheme(theme.tokens, theme.hues);
    // Print every failing pairing, not only the worst, so a palette change says what to fix.
    expect(fails.map(f => `${f.label} ${f.ratio.toFixed(2)}`)).toEqual([]);
    expect(worst).toBeGreaterThanOrEqual(AA);
    expect(Number(worst.toFixed(4))).toBeCloseTo(MOCK_MINIMUMS[id], 4);
    expect(where).toBeTruthy();
  });

  test('colour mixing matches the browser and build.py', () => {
    expect(mix('#2450c4', '#ffffff', 7)).toBe('#f0f3fb');
    expect(mix('#8ab0ff', '#131720', 16)).toBe('#262f44');
    expect(contrastRatio('#000000', '#ffffff')).toBeCloseTo(21, 5);
  });

  test('the gate fails a pairing under AA and names it', () => {
    const theme = allThemes()[0];
    const { fails } = checkTheme({ ...theme.tokens, dim: '#b0b6c0' }, theme.hues);
    expect(fails.length).toBeGreaterThan(0);
    expect(fails[0].label).toMatch(/^dim on /);
  });

  test('the default appearance is Professional light, vivid, IBM Plex Sans', () => {
    expect(DEFAULT_APPEARANCE).toEqual({ family: 'pro', mode: 'light', intensity: 'vivid', font: 'plex' });
    expect(normalizeAppearance(null)).toEqual(DEFAULT_APPEARANCE);
    expect(normalizeAppearance({ family: 'nope', mode: 'dark', font: 'comic' })).toEqual({
      ...DEFAULT_APPEARANCE, mode: 'dark'
    });
  });

  test('theme variables carry every token and hue the stylesheet reads', () => {
    const vars = themeVars({ family: 'galaxy', mode: 'dark', font: 'plex' });
    expect(vars['--uh-accent-2']).toBe('#f5c84b');
    expect(vars['--uh-h-coral']).toBe('#ffa38f');
    expect(vars['--uh-tint-chipv']).toBe('22%');
    expect(vars['--uh-font']).toContain('IBM Plex Sans');
    expect(themeVars({ family: 'pro', mode: 'contrast', font: 'system' })['--uh-accent']).toBe('#0000c8');
  });
});
