import React, { useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';

/**
 * Where Stripe Checkout returns a buyer who paid.
 *
 * Stripe's redirect is not proof of anything — payment confirmation and tier
 * provisioning both arrive out-of-band on the webhook. So this page reads the real
 * session server-side and then polls until the org's tier actually reflects the
 * purchase, rather than asserting success the moment the browser lands.
 *
 * Before 2026-08-08 the success URL pointed at /signup-flow.html, which is neither a
 * route nor a file: it fell through to the SPA index shell, so a paying customer's
 * last impression was a page with nothing on it about their purchase.
 */
const POLL_INTERVAL_MS = 2000;
const POLL_TIMEOUT_MS = 45000;

const formatAmount = (cents, currency) => {
  if (cents == null) return null;
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: (currency || 'usd').toUpperCase()
  }).format(cents / 100);
};

export default function CheckoutSuccess() {
  const [searchParams] = useSearchParams();
  const sessionId = searchParams.get('session_id');
  const [state, setState] = useState('loading');
  const [details, setDetails] = useState(null);
  const [error, setError] = useState('');
  const startedAt = useRef(Date.now());

  useEffect(() => {
    if (!sessionId) {
      setState('unknown');
      return undefined;
    }

    let cancelled = false;
    let timer = null;

    const poll = async () => {
      try {
        const response = await fetch(
          `/api/v1/billing/subscriptions/checkout/${encodeURIComponent(sessionId)}`,
          { credentials: 'include' }
        );
        if (response.status === 401) {
          window.location.replace(
            `/auth/login?return_url=${encodeURIComponent(`/checkout/success?session_id=${sessionId}`)}`
          );
          return;
        }
        if (!response.ok) throw new Error('We could not look up that checkout session.');
        const data = await response.json();
        if (cancelled) return;
        setDetails(data);

        if (data.provisioned) {
          setState('ready');
          return;
        }
        if (Date.now() - startedAt.current > POLL_TIMEOUT_MS) {
          // Paid, but the grant has not landed. Say so plainly instead of
          // claiming success — support can fix a known case, not a silent one.
          setState(data.payment_status === 'paid' ? 'paid_pending' : 'pending');
          return;
        }
        timer = setTimeout(poll, POLL_INTERVAL_MS);
      } catch (err) {
        if (!cancelled) {
          setError(err.message);
          setState('error');
        }
      }
    };

    poll();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [sessionId]);

  const amount = details ? formatAmount(details.amount_total, details.currency) : null;
  const cycleWord = details?.billing_cycle === 'yearly' ? 'year' : 'month';

  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-950 p-6 text-white">
      <div className="w-full max-w-lg rounded-2xl border border-purple-500/30 bg-slate-900 p-8 text-center">
        {state === 'loading' && (
          <>
            <div className="mx-auto mb-5 h-10 w-10 animate-spin rounded-full border-4 border-purple-400 border-t-transparent" />
            <h1 className="text-2xl font-semibold">Confirming your subscription…</h1>
            <p className="mt-3 text-slate-300">
              Payment received. We are activating your plan — this usually takes a few seconds.
            </p>
          </>
        )}

        {state === 'ready' && (
          <>
            <div className="mx-auto mb-5 flex h-12 w-12 items-center justify-center rounded-full bg-emerald-500/20 text-2xl text-emerald-300">
              ✓
            </div>
            <h1 className="text-2xl font-semibold">You&rsquo;re on {details?.tier_name}</h1>
            <p className="mt-3 text-slate-300">
              {amount ? `${amount} per ${cycleWord}.` : ''} Your account has been upgraded and every
              app included in this plan is unlocked.
            </p>
            <a
              href="/dashboard"
              className="mt-6 inline-block rounded-lg bg-purple-600 px-6 py-3 font-semibold hover:bg-purple-500"
            >
              Go to your dashboard
            </a>
          </>
        )}

        {state === 'paid_pending' && (
          <>
            <h1 className="text-2xl font-semibold">Payment received</h1>
            <p className="mt-3 text-slate-300">
              We have your payment for {details?.tier_name}
              {amount ? ` (${amount} per ${cycleWord})` : ''}, but your account is still finishing
              activation. It normally completes within a minute — reload this page, and if it still
              has not unlocked, email support@magicunicorn.tech with this reference and we will fix
              it immediately.
            </p>
            <p className="mt-4 break-all rounded-lg bg-slate-800 p-3 font-mono text-xs text-slate-300">
              {details?.session_id}
            </p>
            <a
              href="/dashboard"
              className="mt-6 inline-block rounded-lg border border-purple-400/60 px-6 py-3 font-semibold hover:bg-purple-500/10"
            >
              Go to your dashboard
            </a>
          </>
        )}

        {state === 'pending' && (
          <>
            <h1 className="text-2xl font-semibold">Checkout not completed</h1>
            <p className="mt-3 text-slate-300">
              This checkout session has not been paid. Nothing has been charged.
            </p>
            <a href="/pricing" className="mt-6 inline-block text-purple-300 hover:text-purple-200">
              Back to pricing
            </a>
          </>
        )}

        {(state === 'unknown' || state === 'error') && (
          <>
            <h1 className="text-2xl font-semibold">We could not confirm this purchase</h1>
            <p className="mt-3 text-slate-300">
              {error || 'No checkout session was provided.'} If you were charged, email
              support@magicunicorn.tech and we will sort it out.
            </p>
            <a href="/pricing" className="mt-6 inline-block text-purple-300 hover:text-purple-200">
              Back to pricing
            </a>
          </>
        )}
      </div>
    </main>
  );
}
