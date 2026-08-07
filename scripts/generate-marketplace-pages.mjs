#!/usr/bin/env node

// Pre-renders the public marketplace (index + one page per listing) into
// public/marketplace/. These files are what crawlers, unfurls, and agents
// see; the SPA re-renders the same markup for logged-out humans. Task 14
// gave both surfaces the market-square skin; the honesty skeleton (real
// listings only, verified trust claims, no invented numbers) is task 12's
// and is not negotiable.

import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { LISTINGS, PRICE_TBD, SUITE } from '../src/data/marketplaceListings.js';

const here = dirname(fileURLToPath(import.meta.url));
const outputRoot = resolve(here, '../public/marketplace');
const origin = 'https://unicorncommander.ai';
const CSS_VERSION = '20260807c';

const escapeHtml = (value = '') => String(value)
  .replaceAll('&', '&amp;')
  .replaceAll('<', '&lt;')
  .replaceAll('>', '&gt;')
  .replaceAll('"', '&quot;')
  .replaceAll("'", '&#039;');

const absolute = (path) => path?.startsWith('http') ? path : `${origin}${path}`;
const accessClass = (access) => access === 'Available now' ? 'available' : 'development';
const priceText = (listing) => {
  if (listing.price && listing.price !== PRICE_TBD) return listing.price;
  if (listing.free_tier) return 'Free tier available';
  return '';
};

// Per-card brand identity. Colors come from Brand-Ops tokens; falls back to
// the page's own palette for anything unlisted.
const brandStyle = (listing) => listing.brand_primary
  ? ` style="--b:${escapeHtml(listing.brand_primary)};--ba:${escapeHtml(listing.brand_accent || listing.brand_primary)}"`
  : '';

// The designed deployment-badge system: one icon per runtime home,
// consistent across every card. Matched by prefix so "BYOK (ACE Music)"
// gets the key.
const DEPLOY_ICONS = [
  ['Local app', '<path d="M3 11.5 12 4l9 7.5"/><path d="M5.5 9.8V20h13V9.8"/>'],
  ['Unicorn Cloud', '<path d="M7 18a4.5 4.5 0 1 1 .6-8.96A6 6 0 0 1 18.6 11 3.6 3.6 0 0 1 18 18Z"/>'],
  ['Hybrid', '<circle cx="12" cy="12" r="8"/><path d="M12 4a8 8 0 0 0 0 16Z" fill="currentColor" stroke="none"/>'],
  ['BYOK', '<circle cx="7.5" cy="12" r="3.2"/><path d="M10.7 12H20"/><path d="M16.6 12v3"/><path d="M19.6 12v2.2"/>'],
  ['Self-host', '<rect x="4" y="5" width="16" height="6" rx="1.5"/><rect x="4" y="13" width="16" height="6" rx="1.5"/><path d="M7.2 8h.01M7.2 16h.01"/>'],
];
const deployIcon = (option) => {
  const hit = DEPLOY_ICONS.find(([prefix]) => option.startsWith(prefix));
  return hit
    ? `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${hit[1]}</svg>`
    : '';
};

const deploymentList = (listing) => `
  <ul class="deployment" aria-label="Where it runs">
    ${listing.deployment_options.map((option) => `<li>${deployIcon(option)}${escapeHtml(option)}</li>`).join('')}
  </ul>`;

const accessBadges = (listing) => `
  <div class="listing-meta">
    <span class="badge ${accessClass(listing.access)}">${escapeHtml(listing.access)}</span>
    ${listing.dogfood ? '<span class="badge dogfood">We run our company on this</span>' : ''}
  </div>`;

const pageHead = ({ title, description, canonical, image, jsonLd = null }) => `
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>${escapeHtml(title)}</title>
    <meta name="description" content="${escapeHtml(description)}">
    <link rel="canonical" href="${escapeHtml(canonical)}">
    <meta property="og:type" content="website">
    <meta property="og:title" content="${escapeHtml(title)}">
    <meta property="og:description" content="${escapeHtml(description)}">
    <meta property="og:url" content="${escapeHtml(canonical)}">
    <meta property="og:image" content="${escapeHtml(absolute(image))}">
    <meta name="twitter:card" content="summary_large_image">
    <meta name="twitter:title" content="${escapeHtml(title)}">
    <meta name="twitter:description" content="${escapeHtml(description)}">
    <meta name="twitter:image" content="${escapeHtml(absolute(image))}">
    <link rel="icon" type="image/webp" href="/logos/uc-mark-colonel.webp">
    <link rel="preload" href="/marketplace/fonts/fraunces-var.woff2" as="font" type="font/woff2" crossorigin>
    <link rel="preload" href="/marketplace/fonts/archivo-var.woff2" as="font" type="font/woff2" crossorigin>
    <link rel="stylesheet" href="/marketplace/marketplace.css?v=${CSS_VERSION}">
    ${jsonLd ? `<script type="application/ld+json">${JSON.stringify(jsonLd).replaceAll('<', '\\u003c')}</script>` : ''}
  </head>`;

const header = () => `
  <header class="site-header">
    <div class="shell">
      <a class="brand" href="/marketplace">
        <img src="/logos/uc-mark-colonel.webp" alt="">
        <span>Unicorn Commander</span>
      </a>
      <nav class="nav" aria-label="Primary">
        <a href="/marketplace#listings">Products</a>
        <a href="/marketplace#ecosystem">The platform</a>
        <a href="/marketplace#business-crew">The business crew</a>
        <a class="sign-in" href="/auth/login">Sign in</a>
      </nav>
    </div>
  </header>`;

const footer = () => `
  <footer class="site-footer">
    <div class="shell">
      <span>Built by Magic Unicorn in Charleston, South Carolina.</span>
      <span><a href="https://magicunicorn.dev/log">Build log</a> · <a href="https://magicunicorn.dev/book/?product=marketplace-publisher">Become a publisher</a> · <a href="/privacy">Privacy</a> · <a href="/terms">Terms</a></span>
    </div>
  </footer>`;

const listingCard = (listing) => {
  const outcome = listing.slug === 'meeting-ops' || listing.slug === 'accounting-ops'
    ? 'business'
    : listing.slug === 'center-deep-research' ? 'research' : 'music';
  const price = priceText(listing);
  return `
    <article class="stall" data-outcome="${outcome}"${brandStyle(listing)}>
      <div class="stall-awning"></div>
      <div class="stall-body">
        <div class="stall-info">
          ${accessBadges(listing)}
          <h3 class="stall-name"><a href="/marketplace/${escapeHtml(listing.slug)}">${escapeHtml(listing.name)}</a></h3>
          <p class="publisher">by ${escapeHtml(listing.publisher)}</p>
          <p class="tagline">${escapeHtml(listing.tagline)}</p>
          ${deploymentList(listing)}
          ${price ? `<p class="price-line">${escapeHtml(price)}</p>` : ''}
          <a class="card-link" href="/marketplace/${escapeHtml(listing.slug)}">See what it does</a>
          <details class="card-trust">
            <summary>Trust and permissions</summary>
            <p><strong>Can do:</strong> ${escapeHtml(listing.capabilities.join('; '))}.</p>
            ${listing.approval_boundary ? `<p><strong>Waits for you:</strong> ${escapeHtml(listing.approval_boundary)}</p>` : ''}
            <p><strong>Data egress:</strong> ${escapeHtml(listing.data_egress)}</p>
            <p><strong>Source:</strong> <a href="${escapeHtml(listing.source_url)}">${escapeHtml(listing.source_license)}</a></p>
          </details>
        </div>
        ${listing.mascot ? `
        <div class="stall-keeper">
          <img class="mascot" src="${escapeHtml(listing.mascot)}" alt="${escapeHtml(listing.mascot_alt || '')}">
          ${listing.mascot_role ? `<span class="keeper-caption">${escapeHtml(listing.mascot_role)}</span>` : ''}
        </div>` : ''}
      </div>
    </article>`;
};

// The crew, cast with the same approved Brand-Ops characters that keep the
// stalls. Facts (who is available) mirror the listings; do not edit access
// states here without editing the source of truth.
const CREW = [
  { name: 'Meeting-Ops', step: 'Meeting', mascot: '/marketplace/media/mascot-meeting-ops.webp', alt: 'The Meeting-Ops scribe, in headset', color: '#1b3a6b', blurb: 'Captures the conversation, decisions, owners, and due dates.', state: 'Available now' },
  { name: 'Project-Ops', step: 'Decision', mascot: '/marketplace/media/mascot-project-ops.webp', alt: 'The Project-Ops coordinator, in beret', color: '#4f46e5', blurb: 'Turns agreed work into owned tasks with status and context.', state: 'In development' },
  { name: 'Customer-Ops', step: 'Customer', mascot: '/marketplace/media/mascot-customer-ops.webp', alt: 'The Customer-Ops account keeper', color: '#FF5D73', blurb: 'Keeps the work tied to the customer and the promised outcome.', state: 'In development' },
  { name: 'Accounting-Ops', step: 'Close', mascot: '/marketplace/media/mascot-accounting-ops.webp', alt: 'The Accounting-Ops bookkeeper, bowler hat and brass scale', color: '#0f766e', blurb: 'Drafts the invoice, traces the posting, and stops for approval where money matters.', state: 'In development' },
];
const HANDOFFS = ['Decisions + owners', 'Owned tasks, in context', 'The promised outcome'];

const crewFlow = () => CREW.map((actor, i) => `
      <article class="crew-actor" style="--b:${actor.color}">
        <img class="mascot" src="${actor.mascot}" alt="${escapeHtml(actor.alt)}">
        <h3>${escapeHtml(actor.name)}</h3>
        <p class="crew-role">${escapeHtml(actor.blurb)}</p>
        <span class="crew-state ${accessClass(actor.state)}">${escapeHtml(actor.state)}</span>
      </article>
      ${i < HANDOFFS.length ? `
      <div class="crew-handoff" aria-label="Hands off: ${escapeHtml(HANDOFFS[i])}">
        <span class="packet" aria-hidden="true"></span>
        <span class="handoff-label">${escapeHtml(HANDOFFS[i])}</span>
      </div>` : ''}`).join('');

const ecosystemSection = () => `
    <section class="ecosystem" id="ecosystem">
      <div class="shell">
        <div class="section-head">
          <h2>An ecosystem,<br>not a catalog.</h2>
          <p>Identity, credits, the model gateway, and MCP tools are the ground. Our apps stand on it today. The stalls are real products only, which is why one of them is empty.</p>
        </div>
        <div class="platform-diagram">
          <div class="stall-row">
            ${LISTINGS.map((listing) => `
            <a class="mini-stall" href="/marketplace/${escapeHtml(listing.slug)}"${brandStyle(listing)}>
              <img src="${escapeHtml(listing.icon)}" alt="" loading="lazy">
              <strong>${escapeHtml(listing.name)}</strong>
              <span>${escapeHtml(listing.access)}</span>
            </a>`).join('')}
            <div class="mini-stall open">
              <span class="stall-hole" aria-hidden="true">+</span>
              <strong>This spot is for your app</strong>
              <a href="https://magicunicorn.dev/book/?product=marketplace-publisher">Become a publisher</a>
            </div>
          </div>
          <div class="platform-rail" role="img" aria-label="The Unicorn Commander platform: identity and SSO, credits and metering, model gateway, MCP tools">
            <span class="rail-title">The Unicorn Commander platform</span>
            <span class="rail-cells">
              <span class="rail-cell">Identity + SSO</span>
              <span class="rail-cell">Credits + metering</span>
              <span class="rail-cell">Model gateway</span>
              <span class="rail-cell">MCP tools</span>
            </span>
          </div>
        </div>
        <p class="ecosystem-note">Self-hostable, AGPL at the core, or hosted in Unicorn Cloud. Apps built by other people run on the same rail ours do.</p>
      </div>
    </section>`;

const indexJsonLd = {
  '@context': 'https://schema.org',
  '@type': 'CollectionPage',
  name: 'Unicorn Commander Marketplace',
  description: 'AI employees and creator tools that finish work on infrastructure you can own.',
  url: `${origin}/marketplace`,
  hasPart: LISTINGS.map((listing) => ({
    '@type': 'SoftwareApplication',
    name: listing.name,
    url: `${origin}/marketplace/${listing.slug}`,
  })),
};

const indexHtml = `<!doctype html>
<html lang="en">
${pageHead({
  title: 'Put AI to work | Unicorn Commander Marketplace',
  description: 'AI employees and creator tools that finish work on infrastructure you can own.',
  canonical: `${origin}/marketplace`,
  image: '/logos/uc-og-colonel.png',
  jsonLd: indexJsonLd,
})}
<body>
  ${header()}
  <main>
    <section class="hero shell">
      <div class="hero-main">
        <div class="sunburst" aria-hidden="true"></div>
        <p class="eyebrow">The Unicorn Commander marketplace</p>
        <h1 id="marketplace-headline">Put AI to <em>work</em>.</h1>
        <p class="hero-claim">Tell us the job. Take home finished work from AI employees and creator tools that run on infrastructure you can own.</p>
      </div>
      <aside class="hero-side">
        <p class="plain-truth">Four real products. No empty shelves. No fake popularity contest.</p>
        <p class="hero-hint">Every stall is a real product with a verified trust panel. New stalls open when they clear that bar.</p>
      </aside>
    </section>

    <section class="doors-section shell" aria-labelledby="outcome-title">
      <p class="section-kicker" id="outcome-title">What do you need done? Pick a door.</p>
      <div class="doors">
        <a class="door" href="#business-crew" data-filter="business" style="--b:#0f766e">
          <span class="door-num">No. 01</span>
          <strong class="door-title">Run my business</strong>
          <span class="door-detail">Meetings to invoices</span>
          <span class="door-go">Step in</span>
        </a>
        <a class="door" href="#listings" data-filter="research" style="--b:#0891b2">
          <span class="door-num">No. 02</span>
          <strong class="door-title">Research something</strong>
          <span class="door-detail">Question to cited report</span>
          <span class="door-go">Step in</span>
        </a>
        <a class="door" href="#listings" data-filter="music" style="--b:#a855f7">
          <span class="door-num">No. 03</span>
          <strong class="door-title">Make music</strong>
          <span class="door-detail">Idea to owned track</span>
          <span class="door-go">Step in</span>
        </a>
      </div>
    </section>

    <section class="catalog" id="listings">
      <div class="shell">
        <div class="section-head">
          <h2>Choose the work,<br>not the software.</h2>
          <p>Each stall says where the product runs. Open a listing for its verified capabilities, approval boundaries, source license, and data-egress answer.</p>
        </div>
        <div class="stall-grid">
          ${LISTINGS.map(listingCard).join('')}
        </div>
      </div>
    </section>

    <section class="suite-section">
      <div class="shell suite-card">
        <div>
          <p class="eyebrow">The bundle</p>
          <h2>${escapeHtml(SUITE.name)}</h2>
          <p>${escapeHtml(SUITE.tagline)}</p>
        </div>
        <div>
          <span class="badge development">${escapeHtml(SUITE.access)}</span>
          <ul class="suite-includes">${SUITE.includes.map((name) => `<li>${escapeHtml(name)}</li>`).join('')}</ul>
          <a class="card-link" href="${escapeHtml(SUITE.cta.href)}">${escapeHtml(SUITE.cta.label)}</a>
        </div>
      </div>
    </section>

    ${ecosystemSection()}

    <section class="crew" id="business-crew">
      <div class="shell">
        <div class="crew-intro">
          <div><p class="eyebrow">One crew, shown honestly</p><h2>The I Have A Business To Run Crew</h2></div>
          <p>The product is the handoff. Meetings become decisions. Decisions become assigned work. Customer work stays connected. Completed work becomes a draft invoice and an auditable ledger entry.</p>
        </div>
        <div class="crew-flow" aria-label="Business crew handoff">
          ${crewFlow()}
        </div>
        <p class="crew-note">You can use Meeting-Ops today. The remaining handoffs are in development, so this crew is not presented as an available bundle.</p>
      </div>
    </section>
  </main>
  ${footer()}
  <script>
    (() => {
      // The joke rotates; the claim underneath never does (spine §7).
      const headlines = [
        'Put AI to <em>work</em>.',
        'Meetings noted. Books <em>closed</em>.',
        'Finished work <em>lives</em> here.',
        'Own the magic. <em>Keep</em> the data.',
      ];
      const headline = document.getElementById('marketplace-headline');
      headline.innerHTML = headlines[Math.floor(Math.random() * headlines.length)];
      document.querySelectorAll('[data-filter]').forEach((entry) => entry.addEventListener('click', () => {
        const selected = entry.dataset.filter;
        document.querySelectorAll('[data-outcome]').forEach((card) => { card.hidden = card.dataset.outcome !== selected; });
        document.querySelectorAll('[data-filter]').forEach((door) => door.classList.toggle('selected', door === entry));
      }));
    })();
  </script>
</body>
</html>`;

mkdirSync(outputRoot, { recursive: true });
writeFileSync(resolve(outputRoot, 'index.html'), `${indexHtml.replace(/[ \t]+$/gm, '')}\n`);

for (const listing of LISTINGS) {
  const offer = {
    '@type': 'Offer',
    availability: listing.access === 'Available now'
      ? 'https://schema.org/InStock'
      : 'https://schema.org/PreOrder',
    url: listing.cta.href.startsWith('http') ? listing.cta.href : `${origin}${listing.cta.href}`,
  };
  if (listing.price === 'Free' || listing.free_tier) {
    offer.price = '0';
    offer.priceCurrency = 'USD';
  } else if (listing.price && listing.price !== PRICE_TBD) {
    offer.price = listing.price.replace(/[^0-9.]/g, '');
    offer.priceCurrency = 'USD';
  }

  const jsonLd = {
    '@context': 'https://schema.org',
    '@type': 'SoftwareApplication',
    name: listing.name,
    description: listing.tagline,
    applicationCategory: listing.pillar,
    operatingSystem: listing.platforms || 'Web, self-hosted',
    author: { '@type': 'Organization', name: listing.publisher, url: 'https://magicunicorn.tech' },
    image: absolute(listing.og_image),
    url: listing.canonical_url,
    offers: offer,
  };
  const screenshot = listing.screenshot
    ? `<figure><img src="${escapeHtml(listing.screenshot)}" alt="${escapeHtml(listing.screenshot_alt)}"><figcaption>Cleared product screenshot using fictional data.</figcaption></figure>`
    : `<figure><img src="${escapeHtml(listing.og_image)}" alt="${escapeHtml(`${listing.name} brand art`)}"><figcaption>Brand art. A product screenshot is withheld until a current product view clears the two-pass public-image review.</figcaption></figure>`;
  const price = priceText(listing);
  const detailHtml = `<!doctype html>
<html lang="en">
${pageHead({
  title: `${listing.name} | Unicorn Commander Marketplace`,
  description: listing.tagline,
  canonical: listing.canonical_url,
  image: listing.og_image,
  jsonLd,
})}
<body>
  ${header()}
  <main>
    <div class="detail-stage"${brandStyle(listing)}>
      <section class="detail-hero shell">
        <div>
          <a class="back" href="/marketplace">← Marketplace</a>
          <p class="detail-eyebrow">${escapeHtml(listing.pillar)} · by ${escapeHtml(listing.publisher)}</p>
          <h1>${escapeHtml(listing.name)}</h1>
          <p class="tagline">${escapeHtml(listing.tagline)}</p>
          ${accessBadges(listing)}
          ${deploymentList(listing)}
          ${price ? `<p class="price-line">${escapeHtml(price)}</p>` : ''}
          <div class="detail-actions">
            <a class="primary-link" href="${escapeHtml(listing.cta.href)}">${escapeHtml(listing.cta.label)}</a>
            ${listing.secondary_cta ? `<a class="secondary-link" href="${escapeHtml(listing.secondary_cta.href)}">${escapeHtml(listing.secondary_cta.label)}</a>` : ''}
          </div>
        </div>
        ${listing.mascot ? `
        <div class="detail-portrait">
          <img class="mascot" src="${escapeHtml(listing.mascot)}" alt="${escapeHtml(listing.mascot_alt || '')}">
          ${listing.mascot_role ? `<span class="keeper-caption">${escapeHtml(listing.mascot_role)}</span>` : ''}
        </div>` : ''}
      </section>
    </div>
    <section class="product-view shell"${brandStyle(listing)}>${screenshot}</section>
    <section class="trust"${brandStyle(listing)}>
      <div class="shell">
        <p class="eyebrow">Trust, in plain language</p>
        <h2>What it can touch.<br>Where it runs.</h2>
        <div class="trust-grid">
          <article class="trust-card"><h3>What it can do</h3><ul>${listing.capabilities.map((item) => `<li>${escapeHtml(item)}</li>`).join('')}</ul></article>
          ${listing.approval_boundary ? `<article class="trust-card"><h3>What waits for you</h3><p>${escapeHtml(listing.approval_boundary)}</p></article>` : ''}
          <article class="trust-card"><h3>Where it runs</h3>${deploymentList(listing)}<p>${escapeHtml(listing.deployment_note)}</p></article>
          <article class="trust-card"><h3>Does data leave your network?</h3><p>${escapeHtml(listing.data_egress)}</p></article>
          <article class="trust-card"><h3>Source</h3><p><a href="${escapeHtml(listing.source_url)}">${escapeHtml(listing.source_license)} source repository</a></p></article>
        </div>
        <p class="truth-note">Claims on this page are intentionally narrower than the roadmap. If a capability was not verified in current source or operator documentation, it is not listed.</p>
      </div>
    </section>
  </main>
  ${footer()}
</body>
</html>`;

  const listingDir = resolve(outputRoot, listing.slug);
  mkdirSync(listingDir, { recursive: true });
  writeFileSync(resolve(listingDir, 'index.html'), `${detailHtml.replace(/[ \t]+$/gm, '')}\n`);
}

console.log(`Generated marketplace index and ${LISTINGS.length} listing pages in ${outputRoot}`);
