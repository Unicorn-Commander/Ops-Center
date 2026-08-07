import React, { useEffect, useMemo, useState } from 'react';
import { LISTINGS, SUITE, PRICE_TBD } from '../../data/marketplaceListings';

/**
 * Marketplace — the public front door at the unicorncommander.ai apex.
 *
 * Rendered by RootRedirect for logged-out visitors when the landing mode is
 * `public_marketplace` (or forced with /?marketplace=1). Logged-in users
 * never see this; they continue into Ops-Center exactly as before.
 *
 * Hard boundaries (site-refresh pack 02, spine §9):
 *  - No checkout. No Stripe, Lago, entitlement, or billing API calls.
 *    CTAs route to the existing signup flow, real downloads, or booking.
 *  - Prices come from Aaron; PRICE_TBD renders as no number at all.
 *  - Listing facts come from magic-unicorn-landing via
 *    scripts/export-marketplace-listings.mjs — edit there, not here.
 */

// Rotating headline (spine §7): the joke rotates, the claim below does not.
// DRAFTS — Aaron picks the final set; trim this list to his picks.
const HEADLINES = [
  'Hire someone who never sleeps through a meeting.',
  "Software you own. Colleagues you don't have to manage.",
  'The unicorn is real, and it does your books.',
  'Take a unicorn home today.',
  'Agents with jobs, not job titles.',
  "Your next hire doesn't need a desk.",
  'Buy an app. Gain a coworker.',
  'Finished work, sold here.',
  'The company store for AI employees.',
  'Own the magic. Rent nothing.',
  'Where agents clock in so you can clock out.',
  'Meetings noted. Books closed. Nobody burned out.',
  'Shop for outcomes, not features.',
  'The front door to your AI workforce.',
  'Everything here works for you. Literally.',
  'Sovereign software, open for business.',
];

const SUBHEAD =
  'This is the Unicorn Commander marketplace: hosted AI employees and free creator ' +
  'tools from Magic Unicorn, running on infrastructure you can own. Self-host free ' +
  'under AGPL, or let us run it for you.';

const PAGE_TITLE = 'Unicorn Commander: the marketplace for AI employees and sovereign software';

// Spine §2: Center Deep Research is an AI employee now, not its own pillar.
const pillarGroup = (pillar) => (pillar === 'Creative' ? 'creative' : 'employees');

const PILLAR_FILTERS = [
  { key: 'all', label: 'Everything' },
  { key: 'employees', label: 'AI employees' },
  { key: 'creative', label: 'Creative' },
];
const TYPE_FILTERS = [
  { key: 'all', label: 'Hosted + downloads' },
  { key: 'hosted', label: 'Hosted' },
  { key: 'download', label: 'Downloads' },
];

function Monogram({ name }) {
  const initials = name
    .split(/[\s-]+/)
    .slice(0, 2)
    .map((w) => w[0])
    .join('');
  return (
    <div
      aria-hidden="true"
      className="flex h-12 w-12 items-center justify-center rounded-xl bg-gradient-to-br from-purple-500/40 to-cyan-500/30 text-base font-bold text-white"
    >
      {initials}
    </div>
  );
}

function AccessBadge({ access }) {
  const available = access === 'Available now';
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium ${
        available
          ? 'border-emerald-400/40 bg-emerald-500/10 text-emerald-300'
          : 'border-amber-400/40 bg-amber-500/10 text-amber-300'
      }`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${available ? 'bg-emerald-400' : 'bg-amber-400'}`} />
      {access}
    </span>
  );
}

function TypeChip({ type }) {
  return (
    <span className="inline-flex items-center rounded-full border border-slate-600/70 bg-slate-800/60 px-2.5 py-0.5 text-xs text-slate-300">
      {type === 'download' ? 'Free download' : 'Hosted service'}
    </span>
  );
}

function DogfoodBadge() {
  return (
    <span
      title="In daily production use at Magic Unicorn."
      className="inline-flex items-center gap-1.5 rounded-full border border-violet-400/60 bg-violet-500/15 px-2.5 py-0.5 text-xs font-semibold text-violet-200"
    >
      <span aria-hidden="true">✦</span> We run our company on this
    </span>
  );
}

function PriceLine({ listing }) {
  // Hard rule: the {{PRICE_TBD}} placeholder is never rendered. Until Aaron
  // supplies real prices, cards show the CTA with no number.
  if (listing.price && listing.price !== PRICE_TBD) {
    return <p className="text-sm font-semibold text-white">{listing.price}</p>;
  }
  if (listing.free_tier) {
    return <p className="text-sm font-medium text-emerald-300">Free tier available</p>;
  }
  return null;
}

function ListingCard({ listing }) {
  const [iconBroken, setIconBroken] = useState(false);
  const showIcon = listing.icon && !iconBroken;
  return (
    <article className="flex flex-col rounded-2xl border border-slate-700/80 bg-slate-900/70 p-6 transition hover:border-purple-400/50 motion-reduce:transition-none">
      <div className="flex items-start gap-4">
        {showIcon ? (
          <img
            src={listing.icon}
            alt=""
            loading="lazy"
            onError={() => setIconBroken(true)}
            className="h-16 w-16 shrink-0 rounded-xl bg-white/5 object-contain p-0.5"
          />
        ) : (
          <Monogram name={listing.name} />
        )}
        <div className="min-w-0">
          <h3 className="truncate text-lg font-bold text-white">{listing.name}</h3>
          <p className="text-xs text-slate-400">
            by <span className="text-slate-300">{listing.publisher}</span>
          </p>
        </div>
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-2">
        <AccessBadge access={listing.access} />
        <TypeChip type={listing.listing_type} />
      </div>
      {listing.dogfood && (
        <div className="mt-2">
          <DogfoodBadge />
        </div>
      )}

      <p className="mt-3 flex-1 text-sm leading-relaxed text-slate-300">{listing.tagline}</p>
      {listing.note && <p className="mt-2 text-xs text-slate-400">{listing.note}</p>}
      {listing.platforms && <p className="mt-2 text-xs text-slate-400">{listing.platforms}</p>}

      <div className="mt-4 space-y-3">
        <PriceLine listing={listing} />
        <div className="flex flex-wrap items-center gap-3">
          <a
            href={listing.cta.href}
            className="inline-flex items-center rounded-lg bg-gradient-to-r from-purple-500 to-purple-600 px-4 py-2 text-sm font-semibold text-white shadow hover:from-purple-400 hover:to-purple-500 focus-visible:outline focus-visible:outline-2 focus-visible:outline-purple-300"
          >
            {listing.cta.label}
          </a>
          {listing.secondary_cta && (
            <a
              href={listing.secondary_cta.href}
              className="text-sm font-medium text-purple-300 hover:text-purple-200"
            >
              {listing.secondary_cta.label} →
            </a>
          )}
        </div>
        {listing.learn_more_url && (
          <a href={listing.learn_more_url} className="block text-xs text-slate-400 hover:text-slate-300">
            Learn more →
          </a>
        )}
      </div>
    </article>
  );
}

export default function Marketplace() {
  const [headline] = useState(() => HEADLINES[Math.floor(Math.random() * HEADLINES.length)]);
  const [pillar, setPillar] = useState('all');
  const [type, setType] = useState('all');

  useEffect(() => {
    document.title = PAGE_TITLE;
    // BrandingContext sets the admin title after its config fetch resolves;
    // re-assert the public title once so the tab never reads as an admin tool.
    const t = setTimeout(() => {
      document.title = PAGE_TITLE;
    }, 2500);
    return () => clearTimeout(t);
  }, []);

  const visible = useMemo(
    () =>
      LISTINGS.filter(
        (l) =>
          (pillar === 'all' || pillarGroup(l.pillar) === pillar) &&
          (type === 'all' || l.listing_type === type)
      ),
    [pillar, type]
  );

  const filterPill = (active) =>
    `rounded-full border px-3.5 py-1.5 text-sm transition motion-reduce:transition-none ${
      active
        ? 'border-purple-400 bg-purple-500/20 font-semibold text-white'
        : 'border-slate-700 text-slate-300 hover:border-slate-500'
    }`;

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-950 via-purple-950 to-slate-950 text-white">
      <header className="border-b border-purple-500/20 bg-slate-950/80 backdrop-blur">
        <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-4 sm:px-6">
          <div className="flex items-center gap-3 font-bold">
            <img src="/logos/uc-logo-192.png" alt="" className="h-10 w-10 rounded-xl" />
            Unicorn Commander
          </div>
          <a
            href="/auth/login"
            className="rounded-lg border border-purple-400/60 px-5 py-2 text-sm font-medium hover:bg-purple-500/10"
          >
            Sign in
          </a>
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-4 pb-20 pt-14 sm:px-6">
        {/* Hero: rotating headline on top, the fixed claim underneath. */}
        <section className="mx-auto max-w-3xl text-center">
          <p className="mb-4 text-sm font-semibold uppercase tracking-[0.25em] text-purple-300">
            The Unicorn Commander marketplace
          </p>
          <h1 className="text-4xl font-bold leading-tight sm:text-5xl">{headline}</h1>
          <p className="mt-5 text-lg leading-relaxed text-slate-300">{SUBHEAD}</p>
          <p className="mt-6 text-sm text-slate-400">
            One account, one pool of credits, and a per-app entitlement unlocks each product,
            so you only pay for what you actually use.{' '}
            <a href="#bundles" className="font-medium text-purple-300 hover:text-purple-200">
              See how it's packaged ↓
            </a>
          </p>
        </section>

        {/* Filters: pillar + listing type. Deliberately simple. */}
        <section aria-label="Filters" className="mt-12 flex flex-wrap items-center justify-center gap-2">
          {PILLAR_FILTERS.map((f) => (
            <button key={f.key} type="button" onClick={() => setPillar(f.key)} className={filterPill(pillar === f.key)}>
              {f.label}
            </button>
          ))}
          <span aria-hidden="true" className="mx-2 hidden h-5 w-px bg-slate-700 sm:block" />
          {TYPE_FILTERS.map((f) => (
            <button key={f.key} type="button" onClick={() => setType(f.key)} className={filterPill(type === f.key)}>
              {f.label}
            </button>
          ))}
        </section>

        {/* The grid. Every card names its publisher: this is a venue, not a product page. */}
        <section aria-label="Listings" className="mt-8 grid gap-6 sm:grid-cols-2 xl:grid-cols-3">
          {visible.map((l) => (
            <ListingCard key={l.slug} listing={l} />
          ))}
          {visible.length === 0 && (
            <p className="col-span-full py-16 text-center text-slate-400">
              Nothing matches that combination yet. Try clearing a filter.
            </p>
          )}
        </section>

        {/* Bundles (spine §4): the suite sold together, the wedge sold alone, the add-on. */}
        <section id="bundles" aria-label="Bundles" className="mt-20">
          <h2 className="text-center text-2xl font-bold sm:text-3xl">Better together</h2>
          <p className="mx-auto mt-3 max-w-2xl text-center text-slate-300">
            Every app here runs alone. The point of the suite is that they stop working alone:
            your meetings feed your projects, your projects feed your books.
          </p>
          <div className="mx-auto mt-8 max-w-4xl rounded-2xl border border-purple-400/40 bg-purple-500/10 p-8 shadow-xl shadow-purple-950/40">
            <div className="flex flex-wrap items-center gap-3">
              <h3 className="text-xl font-bold">{SUITE.name}</h3>
              <AccessBadge access={SUITE.access} />
              <DogfoodBadge />
            </div>
            <p className="mt-2 text-xs text-slate-300">
              by <span className="text-slate-200">{SUITE.publisher}</span>
            </p>
            <p className="mt-4 text-slate-200">{SUITE.tagline}</p>
            <div className="mt-5 flex flex-wrap gap-2">
              {SUITE.includes.map((name) => (
                <span
                  key={name}
                  className="rounded-full border border-slate-600/70 bg-slate-900/60 px-3 py-1 text-xs text-slate-200"
                >
                  {name}
                </span>
              ))}
            </div>
            <ul className="mt-5 space-y-1 text-sm text-slate-300">
              {SUITE.callouts.map((c) => (
                <li key={c}>• {c}</li>
              ))}
            </ul>
            <div className="mt-6">
              <a
                href={SUITE.cta.href}
                className="inline-flex items-center rounded-lg bg-gradient-to-r from-purple-500 to-purple-600 px-5 py-2.5 text-sm font-semibold text-white shadow hover:from-purple-400 hover:to-purple-500"
              >
                {SUITE.cta.label}
              </a>
            </div>
          </div>
        </section>
      </main>

      <footer className="border-t border-purple-500/20 bg-slate-950/60">
        <div className="mx-auto flex max-w-7xl flex-col items-center gap-4 px-4 py-10 text-sm text-slate-400 sm:flex-row sm:justify-between sm:px-6">
          <p>
            Built by{' '}
            <a href="https://magicunicorn.tech" className="text-slate-300 hover:text-white">
              Magic Unicorn
            </a>{' '}
            in Folly Beach, SC.
          </p>
          <nav className="flex flex-wrap items-center justify-center gap-x-6 gap-y-2">
            <a href="https://magicunicorn.dev/log" className="hover:text-slate-200">
              Build log
            </a>
            <a href="/privacy" className="hover:text-slate-200">
              Privacy
            </a>
            <a href="/terms" className="hover:text-slate-200">
              Terms
            </a>
            {/* Quiet on purpose: the pitch waits for a real first partner. */}
            <a
              href="https://magicunicorn.dev/book/?product=marketplace-publisher"
              className="hover:text-slate-200"
            >
              Become a publisher
            </a>
            <a href="/auth/login" className="hover:text-slate-200">
              Sign in
            </a>
          </nav>
        </div>
      </footer>
    </div>
  );
}
