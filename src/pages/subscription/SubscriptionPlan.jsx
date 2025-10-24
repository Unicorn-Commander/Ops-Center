import React, { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import {
  SparklesIcon,
  ArrowUpIcon,
  ArrowDownIcon,
  CheckCircleIcon,
  XCircleIcon,
  InformationCircleIcon
} from '@heroicons/react/24/outline';
import { useTheme } from '../../contexts/ThemeContext';

// Animation variants
const itemVariants = {
  hidden: { y: 20, opacity: 0 },
  visible: {
    y: 0,
    opacity: 1,
    transition: { duration: 0.3 }
  }
};

// Format currency
const formatCurrency = (amount) => {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD'
  }).format(amount);
};

// Format date
const formatDate = (dateString) => {
  return new Date(dateString).toLocaleDateString('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric'
  });
};

// Tier badge component
const TierBadge = ({ tier }) => {
  const colors = {
    trial: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
    starter: 'bg-green-500/20 text-green-400 border-green-500/30',
    professional: 'bg-purple-500/20 text-purple-400 border-purple-500/30',
    enterprise: 'bg-amber-500/20 text-amber-400 border-amber-500/30'
  };

  return (
    <span className={`px-3 py-1 rounded-full text-xs font-semibold border ${colors[tier] || colors.trial}`}>
      {tier.charAt(0).toUpperCase() + tier.slice(1)}
    </span>
  );
};

// Status badge component
const StatusBadge = ({ status }) => {
  const colors = {
    active: 'bg-green-500/20 text-green-400 border-green-500/30',
    trialing: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
    canceled: 'bg-red-500/20 text-red-400 border-red-500/30',
    past_due: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30'
  };

  return (
    <span className={`px-2 py-1 rounded-full text-xs font-medium border ${colors[status] || colors.trialing}`}>
      {status.charAt(0).toUpperCase() + status.slice(1).replace('_', ' ')}
    </span>
  );
};

// Plan features data
const planFeatures = {
  trial: [
    { name: '100 API calls per day', included: true },
    { name: 'Open-WebUI access', included: true },
    { name: 'Basic AI models', included: true },
    { name: 'Community support', included: true },
    { name: 'Center-Deep access', included: false },
    { name: 'BYOK support', included: false }
  ],
  starter: [
    { name: '1,000 API calls per month', included: true },
    { name: 'Open-WebUI + Center-Deep', included: true },
    { name: 'All AI models', included: true },
    { name: 'BYOK support', included: true },
    { name: 'Email support', included: true },
    { name: 'Priority support', included: false }
  ],
  professional: [
    { name: '10,000 API calls per month', included: true },
    { name: 'All services (Chat, Search, TTS, STT)', included: true },
    { name: 'Billing dashboard access', included: true },
    { name: 'BYOK support', included: true },
    { name: 'Priority support', included: true },
    { name: 'Team management', included: false }
  ],
  enterprise: [
    { name: 'Unlimited API calls', included: true },
    { name: 'Team management (5 seats)', included: true },
    { name: 'Custom integrations', included: true },
    { name: '24/7 dedicated support', included: true },
    { name: 'White-label options', included: true },
    { name: 'SLA guarantees', included: true }
  ]
};

// Available plans for comparison
const availablePlans = [
  { tier: 'trial', name: 'Trial', price: 1.0, period: 'week', description: '7-day trial period' },
  { tier: 'starter', name: 'Starter', price: 19.0, period: 'month', description: 'For individuals' },
  { tier: 'professional', name: 'Professional', price: 49.0, period: 'month', description: 'Most popular', popular: true },
  { tier: 'enterprise', name: 'Enterprise', price: 99.0, period: 'month', description: 'For teams' }
];

export default function SubscriptionPlan() {
  const { theme } = useTheme();
  const [loading, setLoading] = useState(true);
  const [checkoutLoading, setCheckoutLoading] = useState(false);
  const [subscription, setSubscription] = useState(null);
  const [showComparison, setShowComparison] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    loadSubscription();

    // Check for canceled checkout
    const urlParams = new URLSearchParams(window.location.search);
    if (urlParams.get('canceled') === 'true') {
      setError('Checkout was canceled. Please try again when you\'re ready.');
      // Clean up URL
      window.history.replaceState({}, '', window.location.pathname);
    }
  }, []);

  const loadSubscription = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch('/api/v1/subscriptions/current');
      if (res.ok) {
        const data = await res.json();
        setSubscription(data);
      } else {
        setError('Failed to load subscription');
      }
    } catch (error) {
      console.error('Error loading subscription:', error);
      setError('Network error');
    } finally {
      setLoading(false);
    }
  };

  const handleUpgrade = async (targetTier) => {
    setCheckoutLoading(true);
    setError(null);

    try {
      // Find the plan object for the target tier
      const plan = availablePlans.find(p => p.tier === targetTier);
      if (!plan) {
        throw new Error('Invalid plan selected');
      }

      // Call the correct billing checkout endpoint
      const res = await fetch('/api/v1/billing/subscriptions/checkout', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${localStorage.getItem('authToken') || ''}`
        },
        credentials: 'include',
        body: JSON.stringify({
          tier_id: plan.tier,
          billing_cycle: 'monthly',
          success_url: window.location.origin + '/admin/subscription/success?session_id={CHECKOUT_SESSION_ID}',
          cancel_url: window.location.origin + '/admin/subscription/plan?canceled=true'
        })
      });

      if (!res.ok) {
        const errorData = await res.json().catch(() => ({}));
        throw new Error(errorData.detail || `Failed to create checkout session (${res.status})`);
      }

      const data = await res.json();

      // Redirect to Stripe Checkout
      if (data.checkout_url) {
        window.location.href = data.checkout_url;
      } else {
        throw new Error('No checkout URL returned from server');
      }
    } catch (error) {
      console.error('Checkout error:', error);
      setError(error.message || 'Failed to initiate checkout. Please try again.');
      setCheckoutLoading(false);
    }
  };

  const handleDowngrade = async (targetTier) => {
    if (confirm(`Are you sure you want to downgrade to ${targetTier}?`)) {
      try {
        const res = await fetch('/api/v1/subscriptions/change', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ target_tier: targetTier })
        });

        if (res.ok) {
          await loadSubscription();
        }
      } catch (error) {
        console.error('Error downgrading:', error);
      }
    }
  };

  const handleCancelSubscription = async () => {
    if (confirm('Are you sure you want to cancel your subscription? You will lose access at the end of your billing period.')) {
      try {
        const res = await fetch('/api/v1/subscriptions/cancel', {
          method: 'POST'
        });

        if (res.ok) {
          await loadSubscription();
        }
      } catch (error) {
        console.error('Error canceling subscription:', error);
      }
    }
  };

  if (loading) {
    return (
      <div className={`${theme.card} rounded-xl p-6 animate-pulse`}>
        <div className="h-6 bg-slate-700 rounded w-1/3 mb-4"></div>
        <div className="h-24 bg-slate-700 rounded"></div>
      </div>
    );
  }

  if (error) {
    return (
      <div className={`${theme.card} rounded-xl p-6 border border-red-500/30`}>
        <p className="text-red-400">{error}</p>
      </div>
    );
  }

  const currentFeatures = subscription ? planFeatures[subscription.tier] || [] : [];

  return (
    <div className="space-y-6">
      {/* Checkout Loading Overlay */}
      {checkoutLoading && (
        <div className="fixed inset-0 bg-black/50 backdrop-blur-sm z-50 flex items-center justify-center">
          <div className={`${theme.card} p-8 rounded-xl text-center`}>
            <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-purple-500 mx-auto mb-4"></div>
            <p className={`text-lg font-semibold ${theme.text.primary}`}>Redirecting to Stripe Checkout...</p>
            <p className={`text-sm ${theme.text.secondary} mt-2`}>Please wait while we prepare your payment</p>
          </div>
        </div>
      )}

      {/* Current Subscription Card */}
      <motion.div variants={itemVariants} className={`${theme.card} rounded-xl p-6`}>
        <div className="flex items-center justify-between mb-6">
          <h3 className={`text-lg font-semibold ${theme.text.primary} flex items-center gap-2`}>
            <SparklesIcon className="w-5 h-5 text-purple-400" />
            Current Subscription
          </h3>
          {subscription && <TierBadge tier={subscription.tier} />}
        </div>

        {subscription ? (
          <div className="space-y-6">
            {/* Plan Details Grid */}
            <div className="grid grid-cols-2 gap-6">
              <div>
                <p className={`text-sm ${theme.text.secondary} mb-1`}>Plan</p>
                <p className={`text-2xl font-bold ${theme.text.primary}`}>
                  {subscription.tier.charAt(0).toUpperCase() + subscription.tier.slice(1)}
                </p>
              </div>
              <div>
                <p className={`text-sm ${theme.text.secondary} mb-1`}>Price</p>
                <p className={`text-2xl font-bold ${theme.text.primary}`}>
                  {formatCurrency(subscription.price)}
                  <span className="text-sm font-normal text-slate-400">
                    /{subscription.tier === 'trial' ? 'week' : 'month'}
                  </span>
                </p>
              </div>
              <div>
                <p className={`text-sm ${theme.text.secondary} mb-1`}>Status</p>
                <div className="mt-1">
                  <StatusBadge status={subscription.status} />
                </div>
              </div>
              <div>
                <p className={`text-sm ${theme.text.secondary} mb-1`}>Next Billing Date</p>
                <p className={`text-sm font-medium ${theme.text.primary} mt-1`}>
                  {formatDate(subscription.next_billing_date)}
                </p>
              </div>
            </div>

            {/* Features List */}
            <div className="border-t border-slate-700 pt-6">
              <h4 className={`text-sm font-semibold ${theme.text.primary} mb-4`}>Plan Features</h4>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {currentFeatures.map((feature, index) => (
                  <div key={index} className="flex items-start gap-2">
                    {feature.included ? (
                      <CheckCircleIcon className="w-5 h-5 text-green-400 flex-shrink-0 mt-0.5" />
                    ) : (
                      <XCircleIcon className="w-5 h-5 text-slate-600 flex-shrink-0 mt-0.5" />
                    )}
                    <span className={`text-sm ${feature.included ? theme.text.primary : theme.text.secondary}`}>
                      {feature.name}
                    </span>
                  </div>
                ))}
              </div>
            </div>

            {/* Action Buttons */}
            <div className="flex gap-3 pt-4 border-t border-slate-700">
              {subscription.tier !== 'enterprise' && (
                <button
                  onClick={() => setShowComparison(!showComparison)}
                  className={`flex-1 ${theme.button} rounded-lg py-2 px-4 text-sm font-medium transition-all`}
                >
                  <ArrowUpIcon className="w-4 h-4 inline mr-2" />
                  Upgrade Plan
                </button>
              )}
              <button
                onClick={() => setShowComparison(!showComparison)}
                className="flex-1 border border-slate-600 text-slate-300 hover:bg-slate-700 rounded-lg py-2 px-4 text-sm font-medium transition-colors"
              >
                Compare Plans
              </button>
              {subscription.status === 'active' && (
                <button
                  onClick={handleCancelSubscription}
                  className="border border-red-600 text-red-400 hover:bg-red-500/10 rounded-lg py-2 px-4 text-sm font-medium transition-colors"
                >
                  Cancel
                </button>
              )}
            </div>
          </div>
        ) : (
          <div className="text-center py-8">
            <SparklesIcon className="w-16 h-16 mx-auto mb-4 text-slate-500" />
            <h3 className={`text-xl font-semibold mb-2 ${theme.text.primary}`}>No Active Subscription</h3>
            <p className={`${theme.text.secondary} mb-6`}>Start your subscription to access premium features</p>
            <button
              onClick={() => setShowComparison(true)}
              className={`${theme.button} rounded-lg py-2 px-6 text-sm font-medium`}
            >
              View Plans
            </button>
          </div>
        )}
      </motion.div>

      {/* Plan Comparison Table */}
      {showComparison && (
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          className={`${theme.card} rounded-xl p-6`}
        >
          <div className="flex items-center justify-between mb-6">
            <h3 className={`text-lg font-semibold ${theme.text.primary}`}>Compare Plans</h3>
            <button
              onClick={() => setShowComparison(false)}
              className="text-slate-400 hover:text-slate-300 text-sm"
            >
              Hide
            </button>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
            {availablePlans.map((plan) => (
              <div
                key={plan.tier}
                className={`relative border rounded-xl p-6 transition-all ${
                  subscription?.tier === plan.tier
                    ? 'border-purple-500 bg-purple-500/5'
                    : 'border-slate-700 hover:border-slate-600'
                } ${plan.popular ? 'ring-2 ring-purple-500/50' : ''}`}
              >
                {plan.popular && (
                  <div className="absolute -top-3 left-1/2 transform -translate-x-1/2">
                    <span className="bg-purple-500 text-white text-xs font-semibold px-3 py-1 rounded-full">
                      Popular
                    </span>
                  </div>
                )}

                <div className="text-center mb-4">
                  <TierBadge tier={plan.tier} />
                  <h4 className={`text-xl font-bold ${theme.text.primary} mt-3 mb-1`}>{plan.name}</h4>
                  <p className={`text-xs ${theme.text.secondary}`}>{plan.description}</p>
                </div>

                <div className="text-center mb-6">
                  <p className={`text-3xl font-bold ${theme.text.primary}`}>
                    {formatCurrency(plan.price)}
                  </p>
                  <p className={`text-sm ${theme.text.secondary}`}>per {plan.period}</p>
                </div>

                <div className="space-y-2 mb-6">
                  {planFeatures[plan.tier]?.slice(0, 4).map((feature, index) => (
                    <div key={index} className="flex items-start gap-2">
                      {feature.included ? (
                        <CheckCircleIcon className="w-4 h-4 text-green-400 flex-shrink-0 mt-0.5" />
                      ) : (
                        <XCircleIcon className="w-4 h-4 text-slate-600 flex-shrink-0 mt-0.5" />
                      )}
                      <span className={`text-xs ${feature.included ? theme.text.primary : theme.text.secondary}`}>
                        {feature.name}
                      </span>
                    </div>
                  ))}
                </div>

                {subscription?.tier === plan.tier ? (
                  <button
                    disabled
                    className="w-full bg-slate-700 text-slate-500 rounded-lg py-2 text-sm font-medium cursor-not-allowed"
                  >
                    Current Plan
                  </button>
                ) : subscription && getTierLevel(plan.tier) > getTierLevel(subscription.tier) ? (
                  <button
                    onClick={() => handleUpgrade(plan.tier)}
                    disabled={checkoutLoading}
                    className={`w-full ${theme.button} rounded-lg py-2 text-sm font-medium ${checkoutLoading ? 'opacity-50 cursor-not-allowed' : ''}`}
                  >
                    {checkoutLoading ? 'Processing...' : 'Upgrade'}
                  </button>
                ) : subscription ? (
                  <button
                    onClick={() => handleDowngrade(plan.tier)}
                    disabled={checkoutLoading}
                    className={`w-full border border-slate-600 text-slate-300 hover:bg-slate-700 rounded-lg py-2 text-sm font-medium transition-colors ${checkoutLoading ? 'opacity-50 cursor-not-allowed' : ''}`}
                  >
                    Downgrade
                  </button>
                ) : (
                  <button
                    onClick={() => handleUpgrade(plan.tier)}
                    disabled={checkoutLoading}
                    className={`w-full ${theme.button} rounded-lg py-2 text-sm font-medium ${checkoutLoading ? 'opacity-50 cursor-not-allowed' : ''}`}
                  >
                    {checkoutLoading ? 'Processing...' : 'Select Plan'}
                  </button>
                )}
              </div>
            ))}
          </div>

          <div className={`mt-6 p-4 bg-blue-500/10 border border-blue-500/30 rounded-lg flex gap-3`}>
            <InformationCircleIcon className="w-5 h-5 text-blue-400 flex-shrink-0" />
            <div className="text-sm">
              <p className={`font-medium ${theme.text.primary} mb-1`}>Plan Changes</p>
              <p className={theme.text.secondary}>
                Upgrades take effect immediately. Downgrades take effect at the end of your current billing period.
              </p>
            </div>
          </div>
        </motion.div>
      )}
    </div>
  );
}

// Helper function to determine tier level for comparison
function getTierLevel(tier) {
  const levels = { trial: 1, starter: 2, professional: 3, enterprise: 4 };
  return levels[tier] || 0;
}
