import React, { useEffect, useMemo, useState } from 'react';
import { LISTINGS, PRICE_TBD, SUITE } from '../../data/marketplaceListings';

const HEADLINES = [
  'Put AI to work.',
  'Meetings noted. Books closed.',
  'Finished work lives here.',
  'Own the magic. Keep the data.',
];

const OUTCOMES = [
  { key: 'business', number: '01', title: 'Run my business', detail: 'Meetings to invoices' },
  { key: 'research', number: '02', title: 'Research something', detail: 'Question to cited report' },
  { key: 'music', number: '03', title: 'Make music', detail: 'Idea to owned track' },
];

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

function DeploymentList({ listing }) {
  return (
    <ul className="deployment" aria-label="Where it runs">
      {listing.deployment_options.map((option) => <li key={option}>{option}</li>)}
    </ul>
  );
}

function ListingCard({ listing }) {
  const price = priceText(listing);
  const available = listing.access === 'Available now';

  return (
    <article className="listing-card" data-outcome={outcomeFor(listing)}>
      <img className="listing-icon" src={listing.icon} alt="" />
      <div>
        <div className="listing-meta">
          <span className={`badge ${available ? 'available' : 'development'}`}>{listing.access}</span>
          {listing.dogfood && <span className="badge dogfood">We run our company on this</span>}
        </div>
        <h3>{listing.name}</h3>
        <p className="publisher">by {listing.publisher}</p>
        <p className="tagline">{listing.tagline}</p>
        <DeploymentList listing={listing} />
        {price && <p><strong>{price}</strong></p>}
        <a className="card-link" href={`/marketplace/${listing.slug}`}>See what it does</a>
        <details className="card-trust">
          <summary>Trust and permissions</summary>
          <p><strong>Can do:</strong> {listing.capabilities.join('; ')}.</p>
          {listing.approval_boundary && <p><strong>Waits for you:</strong> {listing.approval_boundary}</p>}
          <p><strong>Data egress:</strong> {listing.data_egress}</p>
          <p><strong>Source:</strong> <a href={listing.source_url}>{listing.source_license}</a></p>
        </details>
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
      stylesheet.href = '/marketplace/marketplace.css?v=20260807';
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
            <img src="/logos/uc-logo-192.png" alt="" />
            <span>Unicorn Commander</span>
          </a>
          <nav className="nav" aria-label="Primary">
            <a href="#listings">Products</a>
            <a href="#business-crew">The business crew</a>
            <a className="sign-in" href="/auth/login">Sign in</a>
          </nav>
        </div>
      </header>

      <main>
        <section className="hero shell">
          <div>
            <p className="eyebrow">The Unicorn Commander marketplace</p>
            <h1>{headline}</h1>
          </div>
          <div className="hero-copy">
            <p>Tell us the job. Take home finished work from AI employees and creator tools that run on infrastructure you can own.</p>
            <p className="plain-truth">Four real products. No empty shelves. No fake popularity contest.</p>
          </div>
        </section>

        <section className="outcome-section shell" aria-labelledby="outcome-title">
          <p className="section-kicker" id="outcome-title">What do you need done?</p>
          <div className="outcomes">
            {OUTCOMES.map((entry) => (
              <button
                className={`outcome ${outcome === entry.key ? 'selected' : ''}`}
                key={entry.key}
                type="button"
                onClick={() => chooseOutcome(entry.key)}
                aria-pressed={outcome === entry.key}
              >
                <span className="outcome-num">{entry.number}</span>
                <strong>{entry.title}</strong>
                <span>{entry.detail}</span>
              </button>
            ))}
          </div>
        </section>

        <section className="catalog" id="listings">
          <div className="shell">
            <div className="section-head">
              <h2>Choose the work,<br />not the software.</h2>
              <p>Each card says where the product runs. Open a listing for its verified capabilities, approval boundaries, source license, and data-egress answer.</p>
            </div>
            <div className="listing-grid">
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

        <section className="crew" id="business-crew">
          <div className="shell">
            <div className="crew-intro">
              <div><p className="eyebrow">One crew, shown honestly</p><h2>The I Have A Business To Run Crew</h2></div>
              <p>The product is the handoff. Meetings become decisions. Decisions become assigned work. Customer work stays connected. Completed work becomes a draft invoice and an auditable ledger entry.</p>
            </div>
            <div className="crew-flow" aria-label="Business crew handoff">
              <article className="crew-step"><span className="step">Meeting</span><h3>Meeting-Ops</h3><p>Captures the conversation, decisions, owners, and due dates.</p><span className="crew-state">Available now</span></article>
              <article className="crew-step"><span className="step">Decision</span><h3>Project-Ops</h3><p>Turns agreed work into owned tasks with status and context.</p><span className="crew-state">In development</span></article>
              <article className="crew-step"><span className="step">Customer</span><h3>Customer-Ops</h3><p>Keeps the work tied to the customer and the promised outcome.</p><span className="crew-state">In development</span></article>
              <article className="crew-step"><span className="step">Close</span><h3>Accounting-Ops</h3><p>Drafts the invoice, traces the posting, and stops for approval where money matters.</p><span className="crew-state">In development</span></article>
            </div>
            <p className="crew-note">You can use Meeting-Ops today. The remaining handoffs are in development, so this crew is not presented as an available bundle.</p>
          </div>
        </section>
      </main>

      <footer className="site-footer">
        <div className="shell">
          <span>Built by Magic Unicorn in Folly Beach, South Carolina.</span>
          <span><a href="https://magicunicorn.dev/log">Build log</a> · <a href="/privacy">Privacy</a> · <a href="/terms">Terms</a></span>
        </div>
      </footer>
    </div>
  );
}
