/**
 * UC-1 Pro Billing Module
 * Centralized billing and subscription management functions
 * Handles CSRF tokens, API calls, and Stripe integration
 */

class BillingManager {
    constructor() {
        this.csrfToken = null;
        this.subscriptionData = null;
        this.stripe = null;
        this.baseUrl = '/api/v1';

        // Initialize Stripe if available
        if (window.Stripe && window.STRIPE_PUBLISHABLE_KEY) {
            this.stripe = Stripe(window.STRIPE_PUBLISHABLE_KEY);
        }
    }

    /**
     * Initialize the billing manager
     */
    async init() {
        await this.fetchCsrfToken();
        return this;
    }

    /**
     * Fetch CSRF token for secure requests
     */
    async fetchCsrfToken() {
        try {
            const response = await fetch(`${this.baseUrl}/auth/csrf-token`, {
                credentials: 'include'
            });

            if (response.ok) {
                const data = await response.json();
                this.csrfToken = data.csrf_token;
                console.log('✓ CSRF token obtained');
                return this.csrfToken;
            }
        } catch (error) {
            console.error('Failed to fetch CSRF token:', error);
            throw new Error('Security token fetch failed');
        }
    }

    /**
     * Make an authenticated API call
     * @param {string} endpoint - API endpoint
     * @param {object} options - Fetch options
     */
    async apiCall(endpoint, options = {}) {
        const url = endpoint.startsWith('http') ? endpoint : `${this.baseUrl}${endpoint}`;

        // Add default headers
        const headers = {
            'Content-Type': 'application/json',
            ...options.headers
        };

        // Add CSRF token for state-changing requests
        if (['POST', 'PATCH', 'PUT', 'DELETE'].includes(options.method?.toUpperCase())) {
            if (!this.csrfToken) {
                await this.fetchCsrfToken();
            }
            headers['X-CSRF-Token'] = this.csrfToken;
        }

        // Make the request
        const response = await fetch(url, {
            ...options,
            headers,
            credentials: 'include'
        });

        return response;
    }

    /**
     * Fetch current subscription status
     */
    async fetchSubscriptionStatus() {
        try {
            const response = await this.apiCall('/subscriptions/my-access');

            if (response.ok) {
                this.subscriptionData = await response.json();
                return this.subscriptionData;
            } else {
                throw new Error('Failed to fetch subscription status');
            }
        } catch (error) {
            console.error('Subscription fetch error:', error);
            throw error;
        }
    }

    /**
     * Create Stripe checkout session
     * @param {string} tier - Subscription tier
     * @param {string} successUrl - Success redirect URL
     * @param {string} cancelUrl - Cancel redirect URL
     */
    async createCheckoutSession(tier, successUrl, cancelUrl) {
        try {
            const response = await this.apiCall('/billing/subscriptions/checkout', {
                method: 'POST',
                body: JSON.stringify({
                    tier,
                    success_url: successUrl || `${window.location.origin}/billing-settings.html?success=true`,
                    cancel_url: cancelUrl || `${window.location.origin}/signup-flow.html?canceled=true`
                })
            });

            if (response.ok) {
                const data = await response.json();
                return data.checkout_url;
            } else {
                const error = await response.json();
                throw new Error(error.detail || 'Failed to create checkout session');
            }
        } catch (error) {
            console.error('Checkout session error:', error);
            throw error;
        }
    }

    /**
     * Open Stripe Customer Portal
     * @param {string} returnUrl - Return URL after portal actions
     */
    async openCustomerPortal(returnUrl) {
        try {
            const response = await this.apiCall('/billing/customer-portal', {
                method: 'POST',
                body: JSON.stringify({
                    return_url: returnUrl || window.location.href
                })
            });

            if (response.ok) {
                const data = await response.json();

                if (data.portal_url) {
                    window.location.href = data.portal_url;
                    return data.portal_url;
                } else {
                    throw new Error('Portal URL not provided');
                }
            } else {
                const error = await response.json();
                throw new Error(error.detail || 'Failed to open customer portal');
            }
        } catch (error) {
            console.error('Customer portal error:', error);
            throw error;
        }
    }

    /**
     * Cancel subscription
     */
    async cancelSubscription() {
        try {
            const response = await this.apiCall('/billing/subscriptions/cancel', {
                method: 'POST'
            });

            if (response.ok) {
                const data = await response.json();
                return data;
            } else {
                const error = await response.json();
                throw new Error(error.detail || 'Failed to cancel subscription');
            }
        } catch (error) {
            console.error('Cancellation error:', error);
            throw error;
        }
    }

    /**
     * Upgrade to a different tier
     * @param {string} newTier - Target tier
     */
    async upgradeTier(newTier) {
        try {
            const checkoutUrl = await this.createCheckoutSession(
                newTier,
                `${window.location.origin}/billing-settings.html?upgrade=success`,
                `${window.location.origin}/billing-settings.html?upgrade=canceled`
            );

            window.location.href = checkoutUrl;
        } catch (error) {
            console.error('Upgrade error:', error);
            throw error;
        }
    }

    /**
     * Downgrade to a different tier
     * @param {string} newTier - Target tier
     */
    async downgradeTier(newTier) {
        try {
            const response = await this.apiCall('/billing/subscriptions/change-tier', {
                method: 'POST',
                body: JSON.stringify({ tier: newTier })
            });

            if (response.ok) {
                const data = await response.json();
                return data;
            } else {
                const error = await response.json();
                throw new Error(error.detail || 'Failed to downgrade tier');
            }
        } catch (error) {
            console.error('Downgrade error:', error);
            throw error;
        }
    }

    /**
     * Fetch usage statistics
     */
    async fetchUsage() {
        try {
            const response = await this.apiCall('/billing/account/usage');

            if (response.ok) {
                return await response.json();
            } else {
                throw new Error('Failed to fetch usage data');
            }
        } catch (error) {
            console.error('Usage fetch error:', error);
            throw error;
        }
    }

    /**
     * Fetch billing history
     */
    async fetchBillingHistory() {
        try {
            const response = await this.apiCall('/billing/invoices');

            if (response.ok) {
                return await response.json();
            } else {
                throw new Error('Failed to fetch billing history');
            }
        } catch (error) {
            console.error('Billing history error:', error);
            throw error;
        }
    }

    /**
     * Add BYOK API key
     * @param {string} provider - Provider name
     * @param {string} key - API key
     * @param {string} label - Optional label
     */
    async addBYOKKey(provider, key, label = null) {
        try {
            const response = await this.apiCall('/billing/account/byok-keys', {
                method: 'POST',
                body: JSON.stringify({
                    provider,
                    key,
                    label,
                    is_active: true
                })
            });

            if (response.ok) {
                return await response.json();
            } else {
                const error = await response.json();
                throw new Error(error.detail || 'Failed to add API key');
            }
        } catch (error) {
            console.error('Add key error:', error);
            throw error;
        }
    }

    /**
     * Remove BYOK API key
     * @param {string} provider - Provider name
     */
    async removeBYOKKey(provider) {
        try {
            const response = await this.apiCall(`/billing/account/byok-keys/${provider}`, {
                method: 'DELETE'
            });

            if (response.ok) {
                return true;
            } else {
                const error = await response.json();
                throw new Error(error.detail || 'Failed to remove API key');
            }
        } catch (error) {
            console.error('Remove key error:', error);
            throw error;
        }
    }

    /**
     * Get tier features and limits
     * @param {string} tierName - Tier name
     */
    getTierFeatures(tierName) {
        const tierFeatures = {
            trial: {
                name: 'Trial',
                price: 1.00,
                period: '7 days',
                apiCalls: 1000,
                features: [
                    '7-day trial period',
                    '1,000 API calls',
                    'Basic AI access',
                    'Community support',
                    'Center-Deep search'
                ],
                byok: false
            },
            starter: {
                name: 'Starter',
                price: 19.00,
                period: 'month',
                apiCalls: 10000,
                features: [
                    '10,000 API calls/month',
                    'BYOK support',
                    'Center-Deep search',
                    'Basic AI models',
                    'Email support'
                ],
                byok: true
            },
            professional: {
                name: 'Professional',
                price: 49.00,
                period: 'month',
                apiCalls: 100000,
                features: [
                    '100,000 API calls/month',
                    'BYOK support',
                    'All AI models',
                    'TTS & STT access',
                    'Priority support',
                    'Advanced features'
                ],
                byok: true,
                popular: true
            },
            enterprise: {
                name: 'Enterprise',
                price: 99.00,
                period: 'month',
                apiCalls: -1, // Unlimited
                features: [
                    'Unlimited API calls',
                    'BYOK support',
                    'Team management (5 seats)',
                    'All services',
                    '24/7 support',
                    'Custom integrations'
                ],
                byok: true
            }
        };

        return tierFeatures[tierName] || null;
    }

    /**
     * Format price for display
     * @param {number} amount - Amount in dollars
     */
    formatPrice(amount) {
        return new Intl.NumberFormat('en-US', {
            style: 'currency',
            currency: 'USD'
        }).format(amount);
    }

    /**
     * Format date for display
     * @param {string|Date} date - Date to format
     */
    formatDate(date) {
        return new Date(date).toLocaleDateString('en-US', {
            month: 'short',
            day: 'numeric',
            year: 'numeric'
        });
    }

    /**
     * Show notification/alert
     * @param {string} message - Message to display
     * @param {string} type - Alert type (success, error, info, warning)
     * @param {number} duration - Duration in ms (default 5000)
     */
    showAlert(message, type = 'info', duration = 5000) {
        // Create alert element
        const alert = document.createElement('div');
        alert.className = `billing-alert billing-alert-${type}`;
        alert.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            z-index: 9999;
            padding: 1rem 1.5rem;
            border-radius: 12px;
            background: ${this.getAlertColor(type)};
            color: white;
            font-weight: 600;
            box-shadow: 0 10px 40px rgba(0, 0, 0, 0.3);
            animation: slideIn 0.3s ease;
            max-width: 400px;
        `;

        const icon = this.getAlertIcon(type);
        alert.innerHTML = `${icon} ${message}`;

        document.body.appendChild(alert);

        // Auto-remove after duration
        setTimeout(() => {
            alert.style.animation = 'slideOut 0.3s ease';
            setTimeout(() => alert.remove(), 300);
        }, duration);
    }

    /**
     * Get alert background color
     */
    getAlertColor(type) {
        const colors = {
            success: 'rgba(16, 185, 129, 0.95)',
            error: 'rgba(239, 68, 68, 0.95)',
            warning: 'rgba(251, 191, 36, 0.95)',
            info: 'rgba(59, 130, 246, 0.95)'
        };
        return colors[type] || colors.info;
    }

    /**
     * Get alert icon
     */
    getAlertIcon(type) {
        const icons = {
            success: '✅',
            error: '❌',
            warning: '⚠️',
            info: 'ℹ️'
        };
        return icons[type] || icons.info;
    }
}

// Create global instance
const billing = new BillingManager();

// Auto-initialize on DOM load
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => billing.init());
} else {
    billing.init();
}

// Add CSS animations
if (!document.getElementById('billing-animations')) {
    const style = document.createElement('style');
    style.id = 'billing-animations';
    style.textContent = `
        @keyframes slideIn {
            from {
                transform: translateX(100%);
                opacity: 0;
            }
            to {
                transform: translateX(0);
                opacity: 1;
            }
        }

        @keyframes slideOut {
            from {
                transform: translateX(0);
                opacity: 1;
            }
            to {
                transform: translateX(100%);
                opacity: 0;
            }
        }
    `;
    document.head.appendChild(style);
}

// Export for use in other modules
if (typeof module !== 'undefined' && module.exports) {
    module.exports = BillingManager;
}
