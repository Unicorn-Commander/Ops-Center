/**
 * Stripe Provider Wrapper
 * Provides Stripe.js context to the application
 */

import React, { useMemo } from 'react';
import { loadStripe } from '@stripe/stripe-js';
import { Elements } from '@stripe/react-stripe-js';

// Load Stripe publishable key from environment
const STRIPE_PUBLISHABLE_KEY = import.meta.env.VITE_STRIPE_PUBLISHABLE_KEY;

/**
 * StripeProvider Component
 *
 * Wraps children with Stripe Elements provider for payment processing
 */
export const StripeProvider = ({ children }) => {
  // Memoize stripe promise to avoid recreating on every render
  const stripePromise = useMemo(() => {
    if (!STRIPE_PUBLISHABLE_KEY) {
      console.warn('VITE_STRIPE_PUBLISHABLE_KEY not configured');
      return null;
    }
    return loadStripe(STRIPE_PUBLISHABLE_KEY);
  }, []);

  // ALWAYS provide an Elements context. When Stripe is unconfigured, stripePromise
  // is null — <Elements stripe={null}> is valid (Stripe's documented "loading"
  // state) and useStripe() returns null instead of throwing "Could not find
  // Elements context". Children guard on a null stripe (the add-card button stays
  // disabled). This keeps the Payment Methods screen rendering, never crashing.
  if (!stripePromise) {
    console.warn('Stripe not configured (VITE_STRIPE_PUBLISHABLE_KEY missing) — card entry disabled, screen still renders.');
  }

  return (
    <Elements stripe={stripePromise}>
      {children}
    </Elements>
  );
};

export default StripeProvider;
