import React, { useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import { useBranding } from '../contexts/BrandingContext';

export default function Login() {
  const { branding, loading: brandingLoading } = useBranding();

  const primaryColor = branding?.primary_color || '#7c3aed';
  const companyName = branding?.company_name || 'Ops-Center';
  const tagline = branding?.tagline || 'Operations Center';
  const subtitle = branding?.subtitle || '';
  const logoUrl = branding?.logo_url || '/logos/ops-center-logo.png';
  const upstreamName = branding?.federation_upstream_name || 'Unicorn Commander';
  const upstreamLogo = branding?.federation_upstream_logo || '/logos/The_Colonel.webp';

  // Post-login destination (set by ProtectedRoute when an expired session
  // bounces the user here). Only relative paths are honored — the backend
  // callback applies the same guard against open redirects.
  const nextParam = new URLSearchParams(window.location.search).get('next');
  const safeNext = nextParam && nextParam.startsWith('/') && !nextParam.startsWith('//') ? nextParam : null;

  const handleSSOLogin = () => {
    window.location.href = safeNext
      ? `/auth/login?return_url=${encodeURIComponent(safeNext)}`
      : '/auth/login';
  };

  // Avoid redirect loops when the SSO callback returns to this page.
  const AUTO_SSO_TS = 'oc_sso_auto_ts';
  const [autoRedirecting, setAutoRedirecting] = useState(false);

  useEffect(() => {
    if (brandingLoading) return;
    const last = Number(sessionStorage.getItem(AUTO_SSO_TS) || 0);
    if (Date.now() - last < 15000) return; // just bounced back -- show UI
    sessionStorage.setItem(AUTO_SSO_TS, String(Date.now()));
    setAutoRedirecting(true);
    handleSSOLogin();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [brandingLoading]);

  return (
    <div
      className="min-h-screen flex items-center justify-center p-4"
      style={{
        background: `linear-gradient(135deg, ${primaryColor}15 0%, ${primaryColor}08 100%), linear-gradient(to bottom right, #0f172a 0%, #1e293b 50%, #0f172a 100%)`
      }}
    >
      <motion.div
        initial={{ opacity: 0, scale: 0.9 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ duration: 0.5 }}
        className="bg-white/10 backdrop-blur-xl rounded-2xl shadow-2xl p-8 max-w-md w-full border border-white/20"
      >
        {/* Logo and Title */}
        <div className="text-center mb-8">
          {logoUrl && (
            <img
              src={logoUrl}
              alt={companyName}
              className="h-16 mx-auto mb-4 object-contain"
              onError={(e) => { e.target.style.display = 'none'; }}
            />
          )}
          <h1 className="text-3xl font-bold text-white mb-2">
            {companyName}
          </h1>
          {subtitle && (
            <p className="text-purple-200/80 text-sm font-medium mb-1">{subtitle}</p>
          )}
          <p className="text-purple-200/60">{tagline}</p>
        </div>

        {/* Redirecting straight to Keycloak -- minimal surface, with a
            manual link in case the browser blocked the navigation. */}
        {autoRedirecting && (
          <div className="text-center space-y-4 py-4">
            <p className="text-purple-200/80">
              Taking you to {upstreamName} sign-in&hellip;
            </p>
            <button
              onClick={handleSSOLogin}
              className="text-sm text-purple-300 hover:text-purple-200 underline transition-colors"
            >
              Continue if you are not redirected
            </button>
          </div>
        )}

        {!autoRedirecting && (
          <div className="space-y-4">
            <button
              onClick={handleSSOLogin}
              className="w-full py-3 px-4 text-white font-medium rounded-lg transition-all duration-200 flex items-center justify-center gap-2 shadow-lg"
              style={{
                background: `linear-gradient(135deg, ${primaryColor} 0%, ${primaryColor}dd 100%)`
              }}
              onMouseOver={(e) => {
                e.currentTarget.style.transform = 'translateY(-1px)';
                e.currentTarget.style.boxShadow = `0 8px 25px ${primaryColor}40`;
              }}
              onMouseOut={(e) => {
                e.currentTarget.style.transform = 'translateY(0)';
                e.currentTarget.style.boxShadow = '';
              }}
            >
              <img
                src={upstreamLogo}
                alt={upstreamName}
                className="h-6 w-6 object-contain"
                onError={(e) => { e.currentTarget.style.display = 'none'; }}
              />
              Continue with {upstreamName} SSO
            </button>

          </div>
        )}

        {/* Footer */}
        <div className="mt-8 text-center">
          <p className="text-purple-300/50 text-xs">
            {companyName} &mdash; {tagline}
          </p>
        </div>
      </motion.div>
    </div>
  );
}
