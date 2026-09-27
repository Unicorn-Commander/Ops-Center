/**
 * Public Trial Redemption Page  (route: /redeem/:code)
 *
 * Not behind the admin guard, but the redeem/validate endpoints require a
 * logged-in session — a 401 renders a "Sign in to redeem" CTA that bounces
 * through /auth/login with a return_url back here.
 *
 * Flow:
 *   1. On mount, GET /api/v1/trial-codes/validate/{code}.
 *        - 401  -> show sign-in CTA.
 *        - 4xx  -> show the invalid/expired/used message.
 *        - 200  -> show the offer (feature/tier + trial length + free/$1).
 *   2. "Redeem" -> POST /api/v1/trial-codes/redeem { code }.
 *        - status "checkout" -> window.location.href = checkout_url (Stripe).
 *        - status "granted"  -> success state with expiry + link to the app.
 *        - already_redeemed  -> "already active" state.
 *
 * The offer copy is tier-aware: a grant_tier (e.g. "founder_friend") is a
 * full-suite comp; otherwise it's a Project-Ops trial (free 14-day or $1).
 *
 * Visual style mirrors pages/public/CheckoutContinue.jsx (Tailwind, dark card).
 */

import React, { useEffect, useState, useCallback } from 'react';
import { useParams } from 'react-router-dom';

// Human label for the offer headline — tier-aware.
const offerHeadline = (code) => {
  if (code?.grant_tier === 'founder_friend') {
    return 'Founder Friend — full suite access (comp)';
  }
  const keys = code?.feature_keys || [];
  const app = keys.includes('project_ops_access') ? 'Project-Ops' : (keys[0] || 'App');
  const days = code?.trial_days ?? 14;
  if (code?.mode === 'paid') {
    const price = `$${(((code?.price_cents ?? 100) / 100)).toFixed(2).replace(/\.00$/, '')} trial`;
    return days ? `${app} — ${price} (${days} days)` : `${app} — ${price}`;
  }
  return days ? `${app} — ${days}-day free trial` : `${app} — free trial`;
};

// Short supporting line under the headline while deciding to redeem.
const offerBlurb = (code) => {
  if (code?.grant_tier === 'founder_friend') {
    return 'Redeem to unlock the full suite as a comp — no card required. Local inference is free; cloud inference is metered/paid.';
  }
  return code?.mode === 'paid'
    ? 'Redeem to start your trial — a small charge confirms your card, and access unlocks right away.'
    : 'Redeem to activate your trial instantly — no card required.';
};

const formatDate = (dateStr) => {
  if (!dateStr) return null;
  const d = new Date(dateStr);
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' });
};

// App destination after a successful grant.
const APP_URL = '/dashboard';

export default function RedeemTrial() {
  const { code } = useParams();

  // status: 'loading' | 'needs_login' | 'invalid' | 'ready'
  //         | 'redeeming' | 'granted' | 'already' | 'error'
  const [status, setStatus] = useState('loading');
  const [offer, setOffer] = useState(null);
  const [message, setMessage] = useState('');
  const [expiresAt, setExpiresAt] = useState(null);

  const loginHref = () => {
    const returnUrl = `/redeem/${encodeURIComponent(code)}`;
    return `/auth/login?return_url=${encodeURIComponent(returnUrl)}`;
  };

  const validate = useCallback(async () => {
    setStatus('loading');
    try {
      const res = await fetch(`/api/v1/trial-codes/validate/${encodeURIComponent(code)}`, {
        credentials: 'include'
      });
      if (res.status === 401) {
        setStatus('needs_login');
        return;
      }
      const data = await res.json().catch(() => ({}));
      if (!res.ok || !data.valid) {
        setStatus('invalid');
        setMessage(data.detail || 'This code is invalid, expired, or already used.');
        return;
      }
      setOffer(data.code);
      setStatus('ready');
    } catch (err) {
      setStatus('error');
      setMessage(err.message || 'Something went wrong. Please try again.');
    }
  }, [code]);

  useEffect(() => {
    if (!code) {
      setStatus('invalid');
      setMessage('No code was provided.');
      return;
    }
    validate();
  }, [code, validate]);

  const handleRedeem = async () => {
    setStatus('redeeming');
    try {
      const res = await fetch('/api/v1/trial-codes/redeem', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code })
      });
      if (res.status === 401) {
        setStatus('needs_login');
        return;
      }
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setStatus('error');
        setMessage(data.detail || 'We could not redeem this code.');
        return;
      }
      if (data.status === 'checkout' && data.checkout_url) {
        // Off to Stripe — keep the spinner state while the browser navigates.
        window.location.href = data.checkout_url;
        return;
      }
      if (data.status === 'granted') {
        setExpiresAt(data.grant_expires_at || null);
        setStatus(data.already_redeemed ? 'already' : 'granted');
        return;
      }
      // Fallback: unexpected shape but 2xx.
      setStatus('error');
      setMessage('Unexpected response from the server. Please contact support.');
    } catch (err) {
      setStatus('error');
      setMessage(err.message || 'Something went wrong. Please try again.');
    }
  };

  // --- Card body per status ------------------------------------------------
  const renderBody = () => {
    switch (status) {
      case 'loading':
        return (
          <>
            <div className="mx-auto mb-5 h-10 w-10 animate-spin rounded-full border-4 border-purple-400 border-t-transparent" />
            <h1 className="text-2xl font-semibold">Checking your code…</h1>
            <p className="mt-3 text-slate-300">Hang tight while we look up this trial.</p>
          </>
        );

      case 'needs_login':
        return (
          <>
            <h1 className="text-2xl font-semibold">Sign in to redeem</h1>
            <p className="mt-3 text-slate-300">
              You need to be signed in to redeem this trial code. We'll bring you right back here.
            </p>
            <a
              href={loginHref()}
              className="mt-6 inline-block rounded-lg bg-purple-500 px-6 py-3 font-semibold text-white transition hover:bg-purple-400"
            >
              Sign in to redeem
            </a>
          </>
        );

      case 'invalid':
        return (
          <>
            <h1 className="text-2xl font-semibold">This code can't be used</h1>
            <p className="mt-3 text-slate-300">{message}</p>
            <a href="/pricing" className="mt-6 inline-block text-purple-300 hover:text-purple-200">
              Explore plans instead
            </a>
          </>
        );

      case 'ready':
      case 'redeeming':
        return (
          <>
            <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-purple-500/20 text-2xl">
              🎁
            </div>
            <p className="text-sm uppercase tracking-wide text-purple-300">You've been invited</p>
            <h1 className="mt-1 text-2xl font-semibold">{offerHeadline(offer)}</h1>
            <p className="mt-3 text-slate-300">{offerBlurb(offer)}</p>
            <button
              type="button"
              onClick={handleRedeem}
              disabled={status === 'redeeming'}
              className="mt-6 inline-flex items-center justify-center gap-2 rounded-lg bg-purple-500 px-6 py-3 font-semibold text-white transition hover:bg-purple-400 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {status === 'redeeming' && (
                <span className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
              )}
              {status === 'redeeming'
                ? 'Redeeming…'
                : offer?.mode === 'paid'
                  ? 'Redeem & continue to checkout'
                  : 'Redeem trial'}
            </button>
          </>
        );

      case 'granted':
        return (
          <>
            <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-emerald-500/20 text-2xl">
              ✅
            </div>
            <h1 className="text-2xl font-semibold">
              {offer?.grant_tier === 'founder_friend' ? 'Your comp access is active' : 'Your trial is active'}
            </h1>
            <p className="mt-3 text-slate-300">
              {offerHeadline(offer).split(' — ')[0]} is unlocked
              {formatDate(expiresAt) ? ` — expires ${formatDate(expiresAt)}.` : '.'}
            </p>
            <a
              href={APP_URL}
              className="mt-6 inline-block rounded-lg bg-purple-500 px-6 py-3 font-semibold text-white transition hover:bg-purple-400"
            >
              Open the app
            </a>
          </>
        );

      case 'already':
        return (
          <>
            <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-sky-500/20 text-2xl">
              👍
            </div>
            <h1 className="text-2xl font-semibold">You've already redeemed this</h1>
            <p className="mt-3 text-slate-300">
              {offer?.grant_tier === 'founder_friend' ? 'Your comp access is already active' : 'Your trial is already active'}
              {formatDate(expiresAt) ? ` — expires ${formatDate(expiresAt)}.` : '.'}
            </p>
            <a
              href={APP_URL}
              className="mt-6 inline-block rounded-lg bg-purple-500 px-6 py-3 font-semibold text-white transition hover:bg-purple-400"
            >
              Open the app
            </a>
          </>
        );

      case 'error':
      default:
        return (
          <>
            <h1 className="text-2xl font-semibold">Something went wrong</h1>
            <p className="mt-3 text-slate-300">{message || 'Please try again in a moment.'}</p>
            <button
              type="button"
              onClick={validate}
              className="mt-6 inline-block rounded-lg bg-purple-500 px-6 py-3 font-semibold text-white transition hover:bg-purple-400"
            >
              Try again
            </button>
          </>
        );
    }
  };

  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-950 p-6 text-white">
      <div className="max-w-lg rounded-2xl border border-purple-500/30 bg-slate-900 p-8 text-center">
        {renderBody()}
      </div>
    </main>
  );
}
