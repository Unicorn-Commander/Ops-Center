import React from 'react';
import { Link } from 'react-router-dom';
import ErrorBoundary from '../../components/ErrorBoundary';
import LandingHero from './components/LandingHero';
import LandingBenefits from './components/LandingBenefits';
import LandingFeatures from './components/LandingFeatures';
import LandingAppShowcase from './components/LandingAppShowcase';
import LandingPricing from './components/LandingPricing';
import LandingUseCases from './components/LandingUseCases';
import LandingFinalCTA from './components/LandingFinalCTA';

/**
 * MarketplaceLanding - Public-facing landing page for unauthenticated users
 *
 * This page showcases:
 * - Hero section with value proposition
 * - Benefits of the platform
 * - Feature highlights
 * - App showcase
 * - Pricing tiers
 * - Use cases
 * - Final call-to-action
 *
 * When users click CTAs, they're redirected to /auth/login (Keycloak SSO)
 */
export default function MarketplaceLanding() {
  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-purple-900 to-slate-900">
      {/* Navigation Header */}
      <header className="fixed top-0 left-0 right-0 z-50 bg-slate-900/80 backdrop-blur-md border-b border-purple-500/20">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex items-center justify-between h-16">
            {/* Logo */}
            <div className="flex items-center space-x-3">
              <img
                src="/logos/The_Colonel.webp"
                alt="The Colonel - Unicorn Commander"
                className="h-10 w-10 rounded-full"
              />
              <span className="text-xl font-bold text-white">
                Unicorn Commander
              </span>
            </div>

            {/* Navigation Links */}
            <nav className="hidden md:flex items-center space-x-8">
              <a href="#features" className="text-gray-300 hover:text-white transition-colors">
                Features
              </a>
              <a href="#pricing" className="text-gray-300 hover:text-white transition-colors">
                Pricing
              </a>
              <a href="#apps" className="text-gray-300 hover:text-white transition-colors">
                Apps
              </a>
            </nav>

            {/* Sign In Button */}
            <div className="flex items-center space-x-4">
              <Link
                to="/auth/login"
                className="px-6 py-2 bg-gradient-to-r from-purple-600 to-pink-600 text-white font-semibold rounded-lg hover:from-purple-700 hover:to-pink-700 transition-all duration-200 shadow-lg hover:shadow-purple-500/50"
              >
                Sign In
              </Link>
            </div>
          </div>
        </div>
      </header>

      {/* Add padding to account for fixed header */}
      <div className="pt-16">
        <main id="main-content">
          <LandingHero />
          <LandingBenefits />
          <LandingFeatures />

          <ErrorBoundary>
            <LandingAppShowcase />
          </ErrorBoundary>

          <LandingPricing />
          <LandingUseCases />
          <LandingFinalCTA />
        </main>
      </div>
    </div>
  );
}
