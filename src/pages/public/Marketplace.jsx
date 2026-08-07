import React, { useEffect, useMemo, useState } from 'react';
import { LISTINGS, PRICE_TBD, SUITE } from '../../data/marketplaceListings';

// The market-square skin (task 14). This page mirrors the pre-rendered
// public/marketplace/index.html; if you change structure here, change
// scripts/generate-marketplace-pages.mjs too. Both share marketplace.css.

// The joke rotates; the claim underneath never does (spine §7).
const HEADLINES = [
  ['Put AI to ', 'work', '.'],
  ['Meetings noted. Books ', 'closed', '.'],
  ['Finished work ', 'lives', ' here.'],
  ['Own the magic. ', 'Keep', ' the data.'],
];

const OUTCOMES = [
  { key: 'business', number: 'No. 01', title: 'Run my business', detail: 'Meetings to invoices', color: '#0f766e' },
  { key: 'research', number: 'No. 02', title: 'Research something', detail: 'Question to cited report', color: '#0891b2' },
  { key: 'music', number: 'No. 03', title: 'Make music', detail: 'Idea to owned track', color: '#a855f7' },
];

const CREW = [
  { name: 'Meeting-Ops', mascot: '/marketplace/media/mascot-meeting-ops.webp', alt: 'The Meeting-Ops scribe, in headset', color: '#1b3a6b', blurb: 'Captures the conversation, decisions, owners, and due dates.', state: 'Available now' },
  { name: 'Project-Ops', mascot: '/marketplace/media/mascot-project-ops.webp', alt: 'The Project-Ops coordinator, in beret', color: '#4f46e5', blurb: 'Turns agreed work into owned tasks with status and context.', state: 'In development' },
  { name: 'Customer-Ops', mascot: '/marketplace/media/mascot-customer-ops.webp', alt: 'The Customer-Ops account keeper', color: '#FF5D73', blurb: 'Keeps the work tied to the customer and the promised outcome.', state: 'In development' },
  { name: 'Accounting-Ops', mascot: '/marketplace/media/mascot-accounting-ops.webp', alt: 'The Accounting-Ops bookkeeper, bowler hat and brass scale', color: '#0f766e', blurb: 'Drafts the invoice, traces the posting, and stops for approval where money matters.', state: 'In development' },
];
const HANDOFFS = ['Decisions + owners', 'Owned tasks, in context', 'The promised outcome'];

const PUBLISHER_URL = 'https://magicunicorn.dev/book/?product=marketplace-publisher';

const outcomeFor = (listing) => {
  if (listing.slug === 'meeting-ops' || listing.slug === 'accounting-ops') return 'business';
  if (listing.slug === 'center-deep-research') return 'research';
  return 'music';
};

const priceText = (listing) => {
  if (listing.price && listing.price !== PRICE_TBD) return listing.price;
  if (listing.free_tier) return 'Free tier available';
  return '';
};

const accessClass = (access) => access === 'Available now' ? 'available' : 'development';

const brandVars = (listing) => listing.brand_primary
  ? { '--b': listing.brand_primary, '--ba': listing.brand_accent || listing.brand_primary }
  : undefined;

const DEPLOY_ICONS = [
  ['Local app', <><path d="M3 11.5 12 4l9 7.5" /><path d="M5.5 9.8V20h13V9.8" /></>],
  ['Unicorn Cloud', <path d="M7 18a4.5 4.5 0 1 1 .6-8.96A6 6 0 0 1 18.6 11 3.6 3.6 0 0 1 18 18Z" />],
  ['Hybrid', <><circle cx="12" cy="12" r="8" /><path d="M12 4a8 8 0 0 0 0 16Z" fill="currentColor" stroke="none" /></>],
  ['BYOK', <><circle cx="7.5" cy="12" r="3.2" /><path d="M10.7 12H20" /><path d="M16.6 12v3" /><path d="M19.6 12v2.2" /></>],
  ['Self-host', <><rect x="4" y="5" width="16" height="6" rx="1.5" /><rect x="4" y="13" width="16" height="6" rx="1.5" /><path d="M7.2 8h.01M7.2 16h.01" /></>],
];

function DeployIcon({ option }) {
  const hit = DEPLOY_ICONS.find(([prefix]) => option.startsWith(prefix));
  if (!hit) return null;
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {hit[1]}
    </svg>
  );
}

function DeploymentList({ listing }) {
  return (
    <ul className="deployment" aria-label="Where it runs">
      {listing.deployment_options.map((option) => (
        <li key={option}><DeployIcon option={option} />{option}</li>
      ))}
    </ul>
  );
}

function AccessBadges({ listing }) {
  return (
    <div className="listing-meta">
      <span className={`badge ${accessClass(listing.access)}`}>{listing.access}</span>
      {listing.dogfood && <span className="badge dogfood">We run our company on this</span>}
    </div>
  );
}

function ListingCard({ listing }) {
  const price = priceText(listing);
  return (
    <article className="stall" data-outcome={outcomeFor(listing)} style={brandVars(listing)}>
      <div className="stall-awning" />
      <div className="stall-body">
        <div className="stall-info">
          <AccessBadges listing={listing} />
          <h3 className="stall-name"><a href={`/marketplace/${listing.slug}`}>{listing.name}</a></h3>
          <p className="publisher">by {listing.publisher}</p>
          <p className="tagline">{listing.tagline}</p>
          <DeploymentList listing={listing} />
          {price && <p className="price-line">{price}</p>}
          <a className="card-link" href={`/marketplace/${listing.slug}`}>See what it does</a>
          <details className="card-trust">
            <summary>Trust and permissions</summary>
            <p><strong>Can do:</strong> {listing.capabilities.join('; ')}.</p>
            {listing.approval_boundary && <p><strong>Waits for you:</strong> {listing.approval_boundary}</p>}
            <p><strong>Data egress:</strong> {listing.data_egress}</p>
            <p><strong>Source:</strong> <a href={listing.source_url}>{listing.source_license}</a></p>
          </details>
        </div>
        {listing.mascot && (
          <div className="stall-keeper">
            <img className="mascot" src={listing.mascot} alt={listing.mascot_alt || ''} />
            {listing.mascot_role && <span className="keeper-caption">{listing.mascot_role}</span>}
          </div>
        )}
      </div>
    </article>
  );
}

export default function Marketplace() {
  const [headline] = useState(() => HEADLINES[Math.floor(Math.random() * HEADLINES.length)]);
  const [outcome, setOutcome] = useState('all');

  useEffect(() => {
    document.title = 'Put AI to work | Unicorn Commander Marketplace';
    let stylesheet = document.getElementById('marketplace-editorial-css');
    if (!stylesheet) {
      stylesheet = document.createElement('link');
      stylesheet.id = 'marketplace-editorial-css';
      stylesheet.rel = 'stylesheet';
      stylesheet.href = '/marketplace/marketplace.css?v=20260807c';
      document.head.appendChild(stylesheet);
    }
    return () => stylesheet?.remove();
  }, []);

  const visible = useMemo(
    () => outcome === 'all' ? LISTINGS : LISTINGS.filter((listing) => outcomeFor(listing) === outcome),
    [outcome]
  );

  const chooseOutcome = (key) => {
    setOutcome((current) => current === key ? 'all' : key);
    window.setTimeout(() => {
      document.getElementById(key === 'business' ? 'business-crew' : 'listings')?.scrollIntoView({ behavior: 'smooth' });
    }, 0);
  };

  return (
    <div className="marketplace-page">
      <header className="site-header">
        <div className="shell">
          <a className="brand" href="/marketplace">
            <img src="/logos/uc-mark-colonel.webp" alt="" />
            <span>Unicorn Commander</span>
          </a>
          <nav className="nav" aria-label="Primary">
            <a href="#listings">Products</a>
            <a href="#ecosystem">The platform</a>
            <a href="#business-crew">The business crew</a>
            <a className="sign-in" href="/auth/login">Sign in</a>
          </nav>
        </div>
      </header>

      <main>
        <section className="hero shell">
          <div className="hero-main">
            <div className="sunburst" aria-hidden="true" />
            <p className="eyebrow">The Unicorn Commander marketplace</p>
            <h1 id="marketplace-headline">{headline[0]}<em>{headline[1]}</em>{headline[2]}</h1>
            <p className="hero-claim">Tell us the job. Take home finished work from AI employees and creator tools that run on infrastructure you can own.</p>
          </div>
          <aside className="hero-side">
            <p className="plain-truth">Four real products. No empty shelves. No fake popularity contest.</p>
            <p className="hero-hint">Every stall is a real product with a verified trust panel. New stalls open when they clear that bar.</p>
          </aside>
        </section>

        <section className="doors-section shell" aria-labelledby="outcome-title">
          <p className="section-kicker" id="outcome-title">What do you need done? Pick a door.</p>
          <div className="doors">
            {OUTCOMES.map((entry) => (
              <button
                className={`door ${outcome === entry.key ? 'selected' : ''}`}
                key={entry.key}
                type="button"
                style={{ '--b': entry.color }}
                onClick={() => chooseOutcome(entry.key)}
                aria-pressed={outcome === entry.key}
              >
                <span className="door-num">{entry.number}</span>
                <strong className="door-title">{entry.title}</strong>
                <span className="door-detail">{entry.detail}</span>
                <span className="door-go">Step in</span>
              </button>
            ))}
          </div>
        </section>

        <section className="catalog" id="listings">
          <div className="shell">
            <div className="section-head">
              <h2>Choose the work,<br />not the software.</h2>
              <p>Each stall says where the product runs. Open a listing for its verified capabilities, approval boundaries, source license, and data-egress answer.</p>
            </div>
            <div className="stall-grid">
              {visible.map((listing) => <ListingCard key={listing.slug} listing={listing} />)}
            </div>
          </div>
        </section>

        <section className="suite-section">
          <div className="shell suite-card">
            <div>
              <p className="eyebrow">The bundle</p>
              <h2>{SUITE.name}</h2>
              <p>{SUITE.tagline}</p>
            </div>
            <div>
              <span className="badge development">{SUITE.access}</span>
              <ul className="suite-includes">{SUITE.includes.map((name) => <li key={name}>{name}</li>)}</ul>
              <a className="card-link" href={SUITE.cta.href}>{SUITE.cta.label}</a>
            </div>
          </div>
        </section>

        <section className="ecosystem" id="ecosystem">
          <div className="shell">
            <div className="section-head">
              <h2>An ecosystem,<br />not a catalog.</h2>
              <p>Identity, credits, the model gateway, and MCP tools are the ground. Our apps stand on it today. The stalls are real products only, which is why one of them is empty.</p>
            </div>
            <div className="platform-diagram">
              <div className="stall-row">
                {LISTINGS.map((listing) => (
                  <a className="mini-stall" key={listing.slug} href={`/marketplace/${listing.slug}`} style={brandVars(listing)}>
                    <img src={listing.icon} alt="" loading="lazy" />
                    <strong>{listing.name}</strong>
                    <span>{listing.access}</span>
                  </a>
                ))}
                <div className="mini-stall open">
                  <span className="stall-hole" aria-hidden="true">+</span>
                  <strong>This spot is for your app</strong>
                  <a href={PUBLISHER_URL}>Become a publisher</a>
                </div>
              </div>
              <div className="platform-rail" role="img" aria-label="The Unicorn Commander platform: identity and SSO, credits and metering, model gateway, MCP tools">
                <span className="rail-title">The Unicorn Commander platform</span>
                <span className="rail-cells">
                  <span className="rail-cell">Identity + SSO</span>
                  <span className="rail-cell">Credits + metering</span>
                  <span className="rail-cell">Model gateway</span>
                  <span className="rail-cell">MCP tools</span>
                </span>
              </div>
            </div>
            <p className="ecosystem-note">Self-hostable, AGPL at the core, or hosted in Unicorn Cloud. Apps built by other people run on the same rail ours do.</p>
          </div>
        </section>

        <section className="crew" id="business-crew">
          <div className="shell">
            <div className="crew-intro">
              <div><p className="eyebrow">One crew, shown honestly</p><h2>The I Have A Business To Run Crew</h2></div>
              <p>The product is the handoff. Meetings become decisions. Decisions become assigned work. Customer work stays connected. Completed work becomes a draft invoice and an auditable ledger entry.</p>
            </div>
            <div className="crew-flow" aria-label="Business crew handoff">
              {CREW.map((actor, i) => (
                <React.Fragment key={actor.name}>
                  <article className="crew-actor" style={{ '--b': actor.color }}>
                    <img className="mascot" src={actor.mascot} alt={actor.alt} />
                    <h3>{actor.name}</h3>
                    <p className="crew-role">{actor.blurb}</p>
                    <span className={`crew-state ${accessClass(actor.state)}`}>{actor.state}</span>
                  </article>
                  {i < HANDOFFS.length && (
                    <div className="crew-handoff" aria-label={`Hands off: ${HANDOFFS[i]}`}>
                      <span className="packet" aria-hidden="true" />
                      <span className="handoff-label">{HANDOFFS[i]}</span>
                    </div>
                  )}
                </React.Fragment>
              ))}
            </div>
            <p className="crew-note">You can use Meeting-Ops today. The remaining handoffs are in development, so this crew is not presented as an available bundle.</p>
          </div>
        </section>
      </main>

      <footer className="site-footer">
        <div className="shell">
          <span>Built by Magic Unicorn in Charleston, South Carolina.</span>
          <span><a href="https://magicunicorn.dev/log">Build log</a> · <a href={PUBLISHER_URL}>Become a publisher</a> · <a href="/privacy">Privacy</a> · <a href="/terms">Terms</a></span>
        </div>
      </footer>
    </div>
  );
}
