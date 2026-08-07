#!/usr/bin/env node

import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { LISTINGS, PRICE_TBD, SUITE } from '../src/data/marketplaceListings.js';

const here = dirname(fileURLToPath(import.meta.url));
const outputRoot = resolve(here, '../public/marketplace');
const origin = 'https://unicorncommander.ai';

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

const deploymentList = (listing) => `
  <ul class="deployment" aria-label="Where it runs">
    ${listing.deployment_options.map((option) => `<li>${escapeHtml(option)}</li>`).join('')}
  </ul>`;

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
    <link rel="icon" type="image/png" href="/logos/uc-logo-192.png">
    <link rel="stylesheet" href="/marketplace/marketplace.css?v=20260807">
    ${jsonLd ? `<script type="application/ld+json">${JSON.stringify(jsonLd).replaceAll('<', '\\u003c')}</script>` : ''}
  </head>`;

const header = () => `
  <header class="site-header">
    <div class="shell">
      <a class="brand" href="/marketplace">
        <img src="/logos/uc-logo-192.png" alt="">
        <span>Unicorn Commander</span>
      </a>
      <nav class="nav" aria-label="Primary">
        <a href="/marketplace#listings">Products</a>
        <a href="/marketplace#business-crew">The business crew</a>
        <a class="sign-in" href="/auth/login">Sign in</a>
      </nav>
    </div>
  </header>`;

const footer = () => `
  <footer class="site-footer">
    <div class="shell">
      <span>Built by Magic Unicorn in Folly Beach, South Carolina.</span>
      <span><a href="https://magicunicorn.dev/log">Build log</a> · <a href="/privacy">Privacy</a> · <a href="/terms">Terms</a></span>
    </div>
  </footer>`;

const listingCard = (listing) => {
  const outcomes = listing.slug === 'meeting-ops' || listing.slug === 'accounting-ops'
    ? 'business'
    : listing.slug === 'center-deep-research' ? 'research' : 'music';
  const price = priceText(listing);
  return `
    <article class="listing-card" data-outcome="${outcomes}">
      <img class="listing-icon" src="${escapeHtml(listing.icon)}" alt="">
      <div>
        <div class="listing-meta">
          <span class="badge ${accessClass(listing.access)}">${escapeHtml(listing.access)}</span>
          ${listing.dogfood ? '<span class="badge dogfood">We run our company on this</span>' : ''}
        </div>
        <h3>${escapeHtml(listing.name)}</h3>
        <p class="publisher">by ${escapeHtml(listing.publisher)}</p>
        <p class="tagline">${escapeHtml(listing.tagline)}</p>
        ${deploymentList(listing)}
        ${price ? `<p><strong>${escapeHtml(price)}</strong></p>` : ''}
        <a class="card-link" href="/marketplace/${escapeHtml(listing.slug)}">See what it does</a>
      </div>
    </article>`;
};

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
  image: '/logos/uc-logo-512.png',
  jsonLd: indexJsonLd,
})}
<body>
  ${header()}
  <main>
    <section class="hero shell">
      <div>
        <p class="eyebrow">The Unicorn Commander marketplace</p>
        <h1 id="marketplace-headline">Put AI to work.</h1>
      </div>
      <div class="hero-copy">
        <p>Tell us the job. Take home finished work from AI employees and creator tools that run on infrastructure you can own.</p>
        <p class="plain-truth">Four real products. No empty shelves. No fake popularity contest.</p>
      </div>
    </section>

    <section class="outcome-section shell" aria-labelledby="outcome-title">
      <p class="section-kicker" id="outcome-title">What do you need done?</p>
      <div class="outcomes">
        <a class="outcome" href="#business-crew" data-filter="business"><span class="outcome-num">01</span><strong>Run my business</strong><span>Meetings to invoices</span></a>
        <a class="outcome" href="#listings" data-filter="research"><span class="outcome-num">02</span><strong>Research something</strong><span>Question to cited report</span></a>
        <a class="outcome" href="#listings" data-filter="music"><span class="outcome-num">03</span><strong>Make music</strong><span>Idea to owned track</span></a>
      </div>
    </section>

    <section class="catalog" id="listings">
      <div class="shell">
        <div class="section-head">
          <h2>Choose the work,<br>not the software.</h2>
          <p>Each card says where the product runs. Open a listing for its verified capabilities, approval boundaries, source license, and data-egress answer.</p>
        </div>
        <div class="listing-grid">
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

    <section class="crew" id="business-crew">
      <div class="shell">
        <div class="crew-intro">
          <div><p class="eyebrow">One crew, shown honestly</p><h2>The I Have A Business To Run Crew</h2></div>
          <p>The product is the handoff. Meetings become decisions. Decisions become assigned work. Customer work stays connected. Completed work becomes a draft invoice and an auditable ledger entry.</p>
        </div>
        <div class="crew-flow" aria-label="Business crew handoff">
          <article class="crew-step"><span class="step">Meeting</span><h3>Meeting-Ops</h3><p>Captures the conversation, decisions, owners, and due dates.</p><span class="crew-state">Available now</span></article>
          <article class="crew-step"><span class="step">Decision</span><h3>Project-Ops</h3><p>Turns agreed work into owned tasks with status and context.</p><span class="crew-state">In development</span></article>
          <article class="crew-step"><span class="step">Customer</span><h3>Customer-Ops</h3><p>Keeps the work tied to the customer and the promised outcome.</p><span class="crew-state">In development</span></article>
          <article class="crew-step"><span class="step">Close</span><h3>Accounting-Ops</h3><p>Drafts the invoice, traces the posting, and stops for approval where money matters.</p><span class="crew-state">In development</span></article>
        </div>
        <p class="crew-note">You can use Meeting-Ops today. The remaining handoffs are in development, so this crew is not presented as an available bundle.</p>
      </div>
    </section>
  </main>
  ${footer()}
  <script>
    (() => {
      const headlines = ['Put AI to work.', 'Meetings noted. Books closed.', 'Finished work lives here.', 'Own the magic. Keep the data.'];
      const headline = document.getElementById('marketplace-headline');
      headline.textContent = headlines[Math.floor(Math.random() * headlines.length)];
      document.querySelectorAll('[data-filter]').forEach((entry) => entry.addEventListener('click', () => {
        const selected = entry.dataset.filter;
        document.querySelectorAll('[data-outcome]').forEach((card) => { card.hidden = card.dataset.outcome !== selected; });
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
    <section class="detail-hero shell">
      <div>
        <a class="back" href="/marketplace">← Marketplace</a>
        <p class="eyebrow">${escapeHtml(listing.pillar)} · by ${escapeHtml(listing.publisher)}</p>
        <h1>${escapeHtml(listing.name)}</h1>
        <p class="tagline">${escapeHtml(listing.tagline)}</p>
        <div class="listing-meta">
          <span class="badge ${accessClass(listing.access)}">${escapeHtml(listing.access)}</span>
          ${listing.dogfood ? '<span class="badge dogfood">We run our company on this</span>' : ''}
        </div>
        ${deploymentList(listing)}
        ${price ? `<p><strong>${escapeHtml(price)}</strong></p>` : ''}
        <div class="detail-actions">
          <a class="primary-link" href="${escapeHtml(listing.cta.href)}">${escapeHtml(listing.cta.label)}</a>
          ${listing.secondary_cta ? `<a class="secondary-link" href="${escapeHtml(listing.secondary_cta.href)}">${escapeHtml(listing.secondary_cta.label)}</a>` : ''}
        </div>
      </div>
      <img class="listing-icon" src="${escapeHtml(listing.icon)}" alt="">
    </section>
    <section class="product-view shell">${screenshot}</section>
    <section class="trust">
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
