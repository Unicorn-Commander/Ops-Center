import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';

const PRODUCT_TIERS = ['free', 'app', 'byok', 'managed'];

const formatPrice = (value) => {
  const amount = Number(value || 0);
  return amount === 0 ? 'Free' : `$${amount.toFixed(0)}`;
};

// The billing cycle has to survive the login round-trip. A buyer who picked
// "annual" and then signed in used to come back through /checkout/continue, which
// hardcoded monthly — so the annual prices that exist in Stripe were unreachable
// from every UI path. It now travels in the return_url.
const signupUrl = (tierCode, cycle) => {
  const destination = tierCode === 'free'
    ? '/dashboard'
    : `/checkout/continue?tier=${encodeURIComponent(tierCode)}&cycle=${encodeURIComponent(cycle)}`;
  return `/auth/login?signup=1&return_url=${encodeURIComponent(destination)}`;
};

export default function MarketplaceLanding() {
  const [tiers, setTiers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [startingTier, setStartingTier] = useState(null);
  const [cycle, setCycle] = useState('monthly');
  const annual = cycle === 'yearly';
  const maxDiscount = tiers.reduce(
    (best, t) => (t.stripe_price_yearly_configured ? Math.max(best, Number(t.annual_discount_pct) || 0) : best),
    0
  );

  useEffect(() => {
    const loadTiers = async () => {
      try {
        const response = await fetch('/api/v1/public/pricing/tiers?include_features=true');
        if (!response.ok) throw new Error('Pricing is temporarily unavailable.');
        const data = await response.json();
        setTiers(
          PRODUCT_TIERS
            .map((code) => data.find((tier) => tier.tier_code === code))
            .filter(Boolean)
        );
      } catch (err) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    };
    loadTiers();
  }, []);

  // A tier can only be bought on the selected cycle if that cycle's price id exists.
  const cycleForTier = (tier) =>
    (annual && tier.stripe_price_yearly_configured ? 'yearly' : 'monthly');

  const selectTier = async (tier) => {
    if (tier.tier_code === 'free') {
      window.location.href = signupUrl('free', 'monthly');
      return;
    }

    const chosenCycle = cycleForTier(tier);
    setStartingTier(tier.tier_code);
    try {
      const sessionResponse = await fetch('/api/v1/auth/session', { credentials: 'include' });
      const sessionData = await sessionResponse.json().catch(() => ({}));
      if (!sessionData.authenticated) {
        window.location.href = signupUrl(tier.tier_code, chosenCycle);
        return;
      }
      const checkoutResponse = await fetch('/api/v1/billing/subscriptions/checkout', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tier_id: tier.tier_code, billing_cycle: chosenCycle })
      });
      const checkout = await checkoutResponse.json().catch(() => ({}));
      if (!checkoutResponse.ok) {
        throw new Error(checkout.detail || 'Unable to start checkout.');
      }
      window.location.href = checkout.checkout_url;
    } catch (err) {
      setError(err.message);
      setStartingTier(null);
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-950 via-purple-950 to-slate-950 text-white">
      <header className="border-b border-purple-500/20 bg-slate-950/80 backdrop-blur">
        <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-4 sm:px-6">
          <Link to="/" className="flex items-center gap-3 font-bold">
            <img src="/logos/The_Colonel.png" alt="" className="h-10 w-10 rounded-full" />
            Unicorn Commander
          </Link>
          <a href="/auth/login" className="rounded-lg border border-purple-400/60 px-5 py-2 font-medium hover:bg-purple-500/10">
            Sign in
          </a>
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-4 py-16 sm:px-6">
        <section className="mx-auto max-w-3xl text-center">
          <p className="mb-4 text-sm font-semibold uppercase tracking-[0.25em] text-purple-300">AI operations suite</p>
          <h1 className="text-4xl font-bold sm:text-6xl">Choose the setup that fits your work</h1>
          <p className="mt-6 text-lg text-slate-300">
            Start free with on-device meeting AI, or unlock Meeting-Ops for full server-side processing. More Ops apps rolling out soon.
          </p>
        </section>

        <section id="pricing" className="mt-14">
          <div className="mb-10 flex justify-center">
            <div
              role="radiogroup"
              aria-label="Billing cycle"
              className="inline-flex rounded-xl border border-purple-500/30 bg-slate-900/70 p-1"
            >
              {[
                { id: 'monthly', label: 'Monthly' },
                { id: 'yearly', label: 'Annual' }
              ].map((option) => (
                <button
                  key={option.id}
                  type="button"
                  role="radio"
                  aria-checked={cycle === option.id}
                  onClick={() => setCycle(option.id)}
                  className={`rounded-lg px-5 py-2 text-sm font-semibold transition ${
                    cycle === option.id
                      ? 'bg-purple-600 text-white'
                      : 'text-slate-300 hover:text-white'
                  }`}
                >
                  {option.label}
                  {/* Computed from the live prices, never asserted — the annual
                      discount is not the same on every tier. */}
                  {option.id === 'yearly' && maxDiscount > 0 && (
                    <span className="ml-2 text-xs font-normal opacity-80">
                      save up to {maxDiscount}%
                    </span>
                  )}
                </button>
              ))}
            </div>
          </div>

          {error && (
            <div role="alert" className="mx-auto mb-6 max-w-2xl rounded-lg border border-red-400/40 bg-red-950/40 p-4 text-red-200">
              {error}
            </div>
          )}

          {loading ? (
            <div className="py-20 text-center text-slate-300">Loading current plans…</div>
          ) : (
            <div className="grid gap-6 md:grid-cols-2 xl:grid-cols-4">
              {tiers.map((tier) => {
                const paid = Number(tier.monthly_price_usd) > 0;
                const showAnnual = annual && paid && tier.stripe_price_yearly_configured
                  && Number(tier.annual_price_usd) > 0;
                // What the buyer is actually charged, per the cycle they picked.
                const chargeCycle = cycleForTier(tier);
                const checkoutReady = !paid || (chargeCycle === 'yearly'
                  ? tier.stripe_price_yearly_configured
                  : tier.stripe_price_monthly_configured);
                const busy = startingTier === tier.tier_code;
                return (
                  <article
                    key={tier.tier_code}
                    className={`flex min-h-[430px] flex-col rounded-2xl border p-6 ${
                      tier.is_popular
                        ? 'border-purple-400 bg-purple-500/15 shadow-xl shadow-purple-950/40'
                        : 'border-slate-700 bg-slate-900/70'
                    }`}
                  >
                    {tier.badge_text && (
                      <span className="mb-4 w-fit rounded-full bg-purple-500 px-3 py-1 text-xs font-semibold">
                        {tier.badge_text}
                      </span>
                    )}
                    <h2 className="text-2xl font-semibold">{tier.display_name || tier.tier_name}</h2>
                    <p className="mt-2 min-h-16 text-sm text-slate-300">{tier.description}</p>
                    <p className="mt-5 text-4xl font-bold text-purple-300">
                      {showAnnual
                        ? formatPrice(tier.annual_price_usd)
                        : formatPrice(tier.monthly_price_usd)}
                      {paid && (
                        <span className="text-base font-normal text-slate-400">
                          {showAnnual ? '/year' : '/month'}
                        </span>
                      )}
                    </p>
                    {showAnnual && (
                      <p className="mt-1 text-sm text-emerald-300">
                        ${(Number(tier.annual_price_usd) / 12).toFixed(2)}/month, billed annually
                        {tier.annual_discount_pct ? ` — save ${tier.annual_discount_pct}%` : ''}
                      </p>
                    )}
                    {annual && paid && !showAnnual && (
                      <p className="mt-1 text-sm text-slate-400">Monthly billing only</p>
                    )}
                    {/* Render the FULL feature list. A slice(0, 6) here once hid
                        priority support and most of the Suite's apps from the
                        card while the blurb claimed them — the page must show
                        exactly what the tier grants, nothing less. */}
                    <ul className="mt-6 flex-1 space-y-3 text-sm text-slate-200">
                      {(tier.features || []).map((feature) => (
                        <li key={feature} className="flex gap-2">
                          <span className="text-emerald-400">✓</span>
                          <span>{feature}</span>
                        </li>
                      ))}
                    </ul>
                    <button
                      type="button"
                      disabled={!checkoutReady || busy}
                      onClick={() => selectTier(tier)}
                      className="mt-6 rounded-lg bg-purple-600 px-5 py-3 font-semibold hover:bg-purple-500 disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-400"
                    >
                      {busy
                        ? 'Starting checkout…'
                        : !checkoutReady
                          ? 'Contact us'
                          : paid
                            ? 'Choose plan'
                            : 'Start free'}
                    </button>
                  </article>
                );
              })}
            </div>
          )}
        </section>
      </main>
    </div>
  );
}
