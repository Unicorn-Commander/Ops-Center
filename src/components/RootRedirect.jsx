import React, { Suspense, lazy, useEffect, useState } from 'react';
import { Navigate } from 'react-router-dom';
import LoadingScreen from './LoadingScreen';

const Marketplace = lazy(() => import('../pages/public/Marketplace'));

/**
 * RootRedirect - Smart router for the root path (/)
 *
 * Logic:
 * 1. If the URL carries an OIDC callback (code/state/error in the QUERY OR
 *    the FRAGMENT) → never paint marketing over it; fall through to the
 *    normal auth path. Keycloak can return the code in the URL fragment
 *    (#code=&state=), and a gate that only checks window.location.search
 *    has stranded users on a landing page here before. Check both.
 * 2. ?app=1 → explicit bypass: skip any landing, go straight to login
 *    (marketing CTAs use this to send people into the app).
 * 3. Check if user is authenticated → /dashboard, exactly as before.
 * 4. If NOT authenticated → resolve landing mode:
 *      - /?marketplace=1 forces the marketplace (preview/verification hook)
 *      - /marketplace.config.json (static, anon-readable, bind-mounted on
 *        the host so the flip needs no rebuild and no restart)
 *      - fallback: GET /api/v1/system/settings (the designed mechanism;
 *        currently 401s for anonymous callers behind the API auth
 *        middleware, kept for the day it is made public)
 *    - 'direct_sso'          → redirect to /auth/login (today's behavior)
 *    - 'public_marketplace'  → render the Marketplace front door
 *    - 'custom'              → Marketplace (custom landing not built yet)
 */
export default function RootRedirect() {
  const [loading, setLoading] = useState(true);
  const [authenticated, setAuthenticated] = useState(false);
  const [landingMode, setLandingMode] = useState('direct_sso');

  const query = new URLSearchParams(window.location.search);
  const fragment = new URLSearchParams((window.location.hash || '').replace(/^#/, ''));
  const hasOidcCallback = ['code', 'state', 'session_state', 'iss', 'error'].some(
    (k) => query.has(k) || fragment.has(k)
  );
  const forceApp = query.has('app');
  const forceMarketplace = query.has('marketplace') && !hasOidcCallback && !forceApp;

  useEffect(() => {
    const checkAuth = async () => {
      // Explicit /?marketplace=1 wins over everything, including an active
      // session — it is the preview/deep-link view of the storefront, and a
      // logged-in reviewer must be able to see it without logging out.
      if (forceMarketplace) {
        setLandingMode('public_marketplace');
        setAuthenticated(false);
        setLoading(false);
        return;
      }

      // Check for authToken in localStorage
      const token = localStorage.getItem('authToken');

      if (token) {
        setAuthenticated(true);
        setLoading(false);
        return;
      }

      // Check for OAuth session
      try {
        const response = await fetch('/api/v1/auth/session', { credentials: 'include' });
        if (response.ok) {
          const data = await response.json();
          if (data.authenticated) {
            setAuthenticated(true);
            setLoading(false);
            return;
          }
        }
      } catch (error) {
        console.error('Failed to check auth session:', error);
      }

      // User is NOT authenticated - resolve the landing page mode.
      if (forceApp || hasOidcCallback) {
        setLandingMode('direct_sso');
        setAuthenticated(false);
        setLoading(false);
        return;
      }

      let resolved = null;

      // Static config first: served from the bind-mounted public/ dir, so
      // flipping the front door is a one-line file edit with no restart.
      // NB: unknown paths return the SPA shell as HTTP 200, so a missing
      // file surfaces as a JSON parse error — treat any failure as "no config".
      try {
        const response = await fetch('/marketplace.config.json', { cache: 'no-store' });
        if (response.ok) {
          const data = await response.json();
          if (data && typeof data.landing_page_mode === 'string') {
            resolved = data.landing_page_mode;
          }
        }
      } catch (error) {
        console.debug('marketplace.config.json unavailable, trying system settings');
      }

      if (!resolved) {
        try {
          const response = await fetch('/api/v1/system/settings', { credentials: 'include' });
          if (response.ok) {
            const data = await response.json();
            resolved = data.landing_page_mode || null;
          }
        } catch (error) {
          console.debug('Landing page mode unavailable, using default SSO redirect');
        }
      }

      setLandingMode(resolved || 'direct_sso');
      setAuthenticated(false);
      setLoading(false);
    };

    checkAuth();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Show loading screen while checking auth
  if (loading) {
    return <LoadingScreen />;
  }

  // If authenticated, redirect to user landing page (search bar, apps, user dropdown)
  // Users can access admin console via link in PublicLanding
  if (authenticated) {
    return <Navigate to="/dashboard" replace />;
  }

  // User is NOT authenticated - show appropriate landing page
  switch (landingMode) {
    case 'public_marketplace':
    case 'custom':
      return (
        <Suspense fallback={<LoadingScreen />}>
          <Marketplace />
        </Suspense>
      );

    case 'direct_sso':
    default:
      // Use window.location.replace() for immediate redirect without history
      // This prevents React from continuing to render and make API calls
      if (typeof window !== 'undefined') {
        window.location.replace('/auth/login');
      }
      // Return null to stop rendering immediately
      return null;
  }
}
