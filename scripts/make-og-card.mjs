/**
 * uc-og-card.png — the 1200x630 social card for the APEX (unicorncommander.ai)
 * and every /marketplace page.
 *
 * Sibling to public/marketplace/media/og-marketplace.png, deliberately in the
 * same system (same canvas, same rail hairline, same Fraunces/Manrope/DM Mono,
 * same accent chord) but a different JOB: this is the BRAND card, so the
 * wordmark is the hero. A cold link to the apex has to say who this is.
 *
 * Palette + type are read from the SHIPPED marketplace.css tokens, not invented.
 * Rendered by Playwright's Chromium at deviceScaleFactor 1, clipped to exactly
 * 1200x630. Fonts + the Colonel are inlined as data: URIs so the render never
 * depends on network or on fontconfig (the box only has DejaVu installed).
 */
import { readFileSync, writeFileSync } from 'node:fs';
import { chromium } from 'playwright';

const ROOT = '/home/muut/Production/UC-Cloud/services/ops-center';
const OUT = process.argv[2] || `${ROOT}/public/logos/uc-og-card.png`;

const b64 = (p) => readFileSync(p).toString('base64');
const font = (p) => `data:font/woff2;base64,${b64(p)}`;
const png = (p) => `data:image/png;base64,${b64(p)}`;

const FRAUNCES = font(`${ROOT}/public/marketplace/fonts/fraunces-var.woff2`);
const MANROPE = font(`${ROOT}/public/marketplace/fonts/manrope-var.woff2`);
const DMMONO = font(`${ROOT}/public/marketplace/fonts/dm-mono-400.woff2`);
const COLONEL = png(`${ROOT}/public/logos/The_Colonel.png`);

// Measured alpha bounding box of The_Colonel.png (1024x1024, 74.2% transparent).
// The character occupies only this region; the rest is empty. Cropping via a
// clipping wrapper (rather than shipping a second trimmed asset) keeps the card
// derived from the ONE canonical file, so it can never drift from it.
const BB = { x: 231, y: 69, w: 544, h: 692 };
const ART_H = 430;
const s = ART_H / BB.h;
const artW = Math.round(BB.w * s);
const imgW = Math.round(1024 * s);
const offX = Math.round(BB.x * s);
const offY = Math.round(BB.y * s);

// Tokens copied verbatim from public/marketplace/marketplace.css :root (dark).
const html = `<!doctype html>
<html><head><meta charset="utf-8">
<style>
  @font-face { font-family:'Fraunces'; src:url('${FRAUNCES}') format('woff2-variations'); font-weight:100 900; font-style:normal; }
  @font-face { font-family:'Manrope';  src:url('${MANROPE}')  format('woff2-variations'); font-weight:200 800; font-style:normal; }
  @font-face { font-family:'DM Mono';  src:url('${DMMONO}')   format('woff2'); font-weight:400; font-style:normal; }

  :root{
    --canvas:#090b0b;
    --ink:#eceeea;
    --ink-soft:#c4c8c3;
    --muted:#859089;
    --line:#e1ebe421;
    --signal:#b8f4d6;         /* BUY     */
    --signal-warm:#efb295;    /* PUBLISH */
    --signal-violet:#a89bd8;  /* HOST    */
  }
  *{box-sizing:border-box;margin:0;padding:0}
  html,body{width:1200px;height:630px}
  body{
    background:var(--canvas);
    color:var(--ink);
    font-family:'Manrope',sans-serif;
    -webkit-font-smoothing:antialiased;
    position:relative;
    overflow:hidden;
  }

  /* The rail hairline, at the same x as the sibling card. */
  .rail{position:absolute;left:88px;top:0;bottom:0;width:1px;background:var(--line)}

  .stage{
    position:absolute;inset:0;
    display:flex;align-items:center;
    padding:0 88px 0 136px;
    gap:30px;
  }

  .copy{width:620px;flex:none}

  /* The serif NAMES things. The wordmark is the one thing being named. */
  .wordmark{
    font-family:'Fraunces',Georgia,serif;
    font-variation-settings:'opsz' 144,'wght' 400,'SOFT' 0,'WONK' 0;
    font-size:106px;
    line-height:.84;
    letter-spacing:-.042em;
    color:var(--ink);
  }

  /* The sans EXPLAINS things. One approved line, nothing else. */
  .line{
    margin-top:30px;
    font-family:'Manrope',sans-serif;
    font-weight:450;
    font-size:33px;
    line-height:1.42;
    letter-spacing:-.011em;
    color:var(--ink-soft);
    max-width:566px;
  }

  /* The three audiences as three equal segments. Structural equality, no
     positional hierarchy, no text that can go stale. Buy / publish / host.
     Sized so it SURVIVES the thumbnail: at a 400px preview this is still
     100px x 2px of three readable segments. At 4px tall it vanished. */
  .chord{margin-top:44px;display:flex;width:300px;height:6px}
  .chord i{flex:1}
  .chord i:nth-child(1){background:var(--signal)}
  .chord i:nth-child(2){background:var(--signal-warm)}
  .chord i:nth-child(3){background:var(--signal-violet)}

  .foot{
    position:absolute;left:136px;bottom:56px;
    font-family:'DM Mono',monospace;
    font-size:16px;
    letter-spacing:.14em;
    text-transform:uppercase;
    color:var(--muted);
  }

  .art{
    margin-left:auto;
    position:relative;
    width:${artW}px;height:${ART_H}px;
    overflow:hidden;flex:none;
  }
  .art img{position:absolute;left:${-offX}px;top:${-offY}px;width:${imgW}px;height:${imgW}px;display:block}
</style></head>
<body>
  <div class="rail"></div>
  <div class="stage">
    <div class="copy">
      <div class="wordmark">Unicorn<br>Commander</div>
      <div class="line">AI employees and creator tools on infrastructure you can own.</div>
      <div class="chord"><i></i><i></i><i></i></div>
    </div>
    <div class="art"><img src="${COLONEL}" alt=""></div>
  </div>
  <div class="foot">unicorncommander.ai</div>
</body></html>`;

const browser = await chromium.launch();
const page = await browser.newPage({
  viewport: { width: 1200, height: 630 },
  deviceScaleFactor: 1,
});
await page.setContent(html, { waitUntil: 'load' });
await page.evaluate(() => document.fonts.ready);
await page.waitForTimeout(300);

// Guard: if the woff2 did not decode, Chromium silently falls back to DejaVu and
// the card ships in the wrong face. Measure the wordmark instead of trusting it.
const probe = await page.evaluate(() => {
  const el = document.querySelector('.wordmark');
  const r = el.getBoundingClientRect();
  return {
    fraunces: document.fonts.check('106px Fraunces'),
    manrope: document.fonts.check('33px Manrope'),
    mono: document.fonts.check('16px "DM Mono"'),
    wordmarkW: Math.round(r.width),
    wordmarkH: Math.round(r.height),
    lineH: Math.round(document.querySelector('.line').getBoundingClientRect().height),
    // A CSS parse error upstream of these rules degrades SILENTLY: the card
    // still renders, just without the chord. Measure it, do not assume it.
    chord: [...document.querySelectorAll('.chord i')].map((i) => {
      const r = i.getBoundingClientRect();
      return { w: Math.round(r.width), h: Math.round(r.height), bg: getComputedStyle(i).backgroundColor };
    }),
  };
});
console.log('font/layout probe:', JSON.stringify(probe));
if (!probe.fraunces || !probe.manrope || !probe.mono) {
  throw new Error('FONT FALLBACK DETECTED — refusing to ship a card in DejaVu');
}
const TRANSPARENT = /rgba\(0, 0, 0, 0\)|transparent/;
if (probe.chord.length !== 3 || probe.chord.some((c) => c.w < 90 || c.h < 5 || TRANSPARENT.test(c.bg))) {
  throw new Error(`CHORD NOT PAINTED — three-audience mark missing: ${JSON.stringify(probe.chord)}`);
}

await page.screenshot({ path: OUT, clip: { x: 0, y: 0, width: 1200, height: 630 } });
await browser.close();
console.log('wrote', OUT);
