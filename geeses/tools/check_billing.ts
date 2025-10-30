/**
 * Tool: check_billing
 *
 * Query subscription and billing data via Lago and Stripe integration.
 * Provides access to subscription plans, usage metrics, invoices, and payment information.
 *
 * @author Tools Engineer (AI Agent Team)
 * @version 1.0.0
 */

import axios, { AxiosRequestConfig } from 'axios';

export interface CheckBillingParams {
  query: 'current_plan' | 'usage' | 'invoices' | 'payment_methods' | 'plans' | 'subscription_details';
  userId?: string;
  filters?: {
    startDate?: string;
    endDate?: string;
    status?: string;
    limit?: number;
    offset?: number;
  };
}

export interface CheckBillingResult {
  success: boolean;
  status: number;
  data?: any;
  error?: string;
  metadata: {
    query: string;
    userId?: string;
    executionTime: number;
    timestamp: string;
    toolVersion: string;
  };
}

export interface SubscriptionPlan {
  id: string;
  code: string;
  name: string;
  description: string;
  price: number;
  currency: string;
  interval: 'weekly' | 'monthly' | 'yearly';
  features: string[];
  apiCallsLimit: number;
}

export interface CurrentSubscription {
  planId: string;
  planName: string;
  planCode: string;
  status: 'active' | 'canceled' | 'past_due' | 'trialing';
  startDate: string;
  endDate?: string;
  canceledAt?: string;
  trialEndDate?: string;
  price: number;
  currency: string;
  interval: string;
  nextBillingDate?: string;
}

export interface UsageData {
  period: string;
  apiCalls: {
    used: number;
    limit: number;
    percentage: number;
  };
  billingMetrics: {
    totalCost: number;
    currency: string;
  };
  byService: Array<{
    service: string;
    calls: number;
    cost: number;
  }>;
}

export interface Invoice {
  id: string;
  number: string;
  status: 'draft' | 'finalized' | 'paid' | 'void';
  amount: number;
  currency: string;
  dueDate: string;
  paidAt?: string;
  downloadUrl?: string;
  items: Array<{
    description: string;
    quantity: number;
    unitPrice: number;
    total: number;
  }>;
}

/**
 * Configuration
 */
const OPS_CENTER_BASE_URL = process.env.OPS_CENTER_API_URL || 'http://ops-center-direct:8084';
const API_VERSION = 'v1';

/**
 * Tool definition for Brigade
 */
export const tool = {
  name: 'check_billing',
  description: 'Query subscription and billing information. Access current subscription plan, usage metrics, invoice history, and payment methods via Lago/Stripe integration.',
  parameters: {
    type: 'object',
    properties: {
      query: {
        type: 'string',
        enum: ['current_plan', 'usage', 'invoices', 'payment_methods', 'plans', 'subscription_details'],
        description: 'Type of billing information to retrieve',
      },
      userId: {
        type: 'string',
        description: 'User ID (UUID) - optional, defaults to current user if not provided',
      },
      filters: {
        type: 'object',
        description: 'Optional filters for data retrieval',
        properties: {
          startDate: { type: 'string', format: 'date' },
          endDate: { type: 'string', format: 'date' },
          status: { type: 'string' },
          limit: { type: 'number' },
          offset: { type: 'number' },
        },
      },
    },
    required: ['query'],
  },
  handler: checkBilling,
};

/**
 * Validate tool parameters
 */
function validateParams(params: CheckBillingParams): { valid: boolean; error?: string } {
  const validQueries = ['current_plan', 'usage', 'invoices', 'payment_methods', 'plans', 'subscription_details'];

  if (!params.query) {
    return { valid: false, error: 'Query type is required' };
  }

  if (!validQueries.includes(params.query)) {
    return { valid: false, error: `Invalid query. Must be one of: ${validQueries.join(', ')}` };
  }

  // Validate date format if provided
  if (params.filters?.startDate || params.filters?.endDate) {
    const dateRegex = /^\d{4}-\d{2}-\d{2}$/;
    if (params.filters.startDate && !dateRegex.test(params.filters.startDate)) {
      return { valid: false, error: 'Invalid startDate format. Use YYYY-MM-DD' };
    }
    if (params.filters.endDate && !dateRegex.test(params.filters.endDate)) {
      return { valid: false, error: 'Invalid endDate format. Use YYYY-MM-DD' };
    }
  }

  return { valid: true };
}

/**
 * Build API endpoint based on query type
 */
function buildEndpoint(query: string, userId?: string): string {
  const basePath = `/api/${API_VERSION}`;

  switch (query) {
    case 'current_plan':
      return userId
        ? `${basePath}/admin/users/${userId}/subscription`
        : `${basePath}/subscriptions/current`;
    case 'usage':
      return userId
        ? `${basePath}/admin/users/${userId}/usage`
        : `${basePath}/billing/usage`;
    case 'invoices':
      return userId
        ? `${basePath}/admin/users/${userId}/invoices`
        : `${basePath}/billing/invoices`;
    case 'payment_methods':
      return userId
        ? `${basePath}/admin/users/${userId}/payment-methods`
        : `${basePath}/billing/payment-methods`;
    case 'plans':
      return `${basePath}/billing/plans`;
    case 'subscription_details':
      return userId
        ? `${basePath}/admin/users/${userId}/subscription/details`
        : `${basePath}/subscriptions/details`;
    default:
      return `${basePath}/billing/plans`;
  }
}

/**
 * Format subscription plan data
 */
function formatPlan(plan: any): SubscriptionPlan {
  return {
    id: plan.id || plan.plan_id,
    code: plan.code || plan.plan_code,
    name: plan.name,
    description: plan.description || '',
    price: plan.amount_cents ? plan.amount_cents / 100 : plan.price || 0,
    currency: plan.amount_currency || plan.currency || 'USD',
    interval: plan.interval || 'monthly',
    features: plan.features || [],
    apiCallsLimit: plan.api_calls_limit || 0,
  };
}

/**
 * Format current subscription data
 */
function formatSubscription(subscription: any): CurrentSubscription {
  return {
    planId: subscription.plan_id || subscription.planId,
    planName: subscription.plan_name || subscription.planName || 'Unknown',
    planCode: subscription.plan_code || subscription.planCode || '',
    status: subscription.status || 'active',
    startDate: subscription.start_date || subscription.startDate || subscription.started_at,
    endDate: subscription.end_date || subscription.endDate || subscription.terminated_at,
    canceledAt: subscription.canceled_at || subscription.canceledAt,
    trialEndDate: subscription.trial_end_date || subscription.trialEndDate,
    price: subscription.amount_cents ? subscription.amount_cents / 100 : subscription.price || 0,
    currency: subscription.amount_currency || subscription.currency || 'USD',
    interval: subscription.interval || 'monthly',
    nextBillingDate: subscription.next_billing_date || subscription.nextBillingDate,
  };
}

/**
 * Format invoice data
 */
function formatInvoice(invoice: any): Invoice {
  return {
    id: invoice.id || invoice.invoice_id,
    number: invoice.number || invoice.invoice_number || 'N/A',
    status: invoice.status || 'draft',
    amount: invoice.amount_cents ? invoice.amount_cents / 100 : invoice.amount || 0,
    currency: invoice.amount_currency || invoice.currency || 'USD',
    dueDate: invoice.due_date || invoice.dueDate || invoice.issuing_date,
    paidAt: invoice.paid_at || invoice.paidAt,
    downloadUrl: invoice.file_url || invoice.downloadUrl,
    items: (invoice.fees || invoice.items || []).map((item: any) => ({
      description: item.item_name || item.description || '',
      quantity: item.units || item.quantity || 1,
      unitPrice: item.unit_amount_cents ? item.unit_amount_cents / 100 : item.unitPrice || 0,
      total: item.amount_cents ? item.amount_cents / 100 : item.total || 0,
    })),
  };
}

/**
 * Main tool handler
 */
export async function checkBilling(
  params: CheckBillingParams,
  context?: any
): Promise<CheckBillingResult> {
  const startTime = Date.now();

  try {
    // Validate parameters
    const validation = validateParams(params);
    if (!validation.valid) {
      return {
        success: false,
        status: 400,
        error: validation.error,
        metadata: {
          query: params.query,
          userId: params.userId,
          executionTime: Date.now() - startTime,
          timestamp: new Date().toISOString(),
          toolVersion: '1.0.0',
        },
      };
    }

    // Build request configuration
    const endpoint = buildEndpoint(params.query, params.userId);

    const config: AxiosRequestConfig = {
      method: 'GET',
      url: `${OPS_CENTER_BASE_URL}${endpoint}`,
      headers: {
        'Content-Type': 'application/json',
      },
      timeout: 15000, // 15 seconds
    };

    // Add authentication if context provides it
    if (context?.keycloakToken) {
      config.headers.Authorization = `Bearer ${context.keycloakToken}`;
    }

    // Add query parameters if filters provided
    if (params.filters) {
      config.params = {
        start_date: params.filters.startDate,
        end_date: params.filters.endDate,
        status: params.filters.status,
        limit: params.filters.limit,
        offset: params.filters.offset,
      };
    }

    // Execute request
    const response = await axios(config);

    // Format response based on query type
    let formattedData: any;

    switch (params.query) {
      case 'plans':
        formattedData = {
          plans: (response.data.plans || response.data).map(formatPlan),
          total: response.data.total || (response.data.plans || response.data).length,
        };
        break;

      case 'current_plan':
      case 'subscription_details':
        formattedData = response.data.subscription
          ? formatSubscription(response.data.subscription)
          : formatSubscription(response.data);
        break;

      case 'usage':
        formattedData = {
          period: response.data.period || 'current',
          apiCalls: {
            used: response.data.api_calls_used || 0,
            limit: response.data.api_calls_limit || 0,
            percentage: response.data.api_calls_percentage || 0,
          },
          billingMetrics: {
            totalCost: response.data.total_cost || 0,
            currency: response.data.currency || 'USD',
          },
          byService: response.data.by_service || [],
        };
        break;

      case 'invoices':
        formattedData = {
          invoices: (response.data.invoices || response.data).map(formatInvoice),
          total: response.data.total || (response.data.invoices || response.data).length,
        };
        break;

      case 'payment_methods':
        formattedData = {
          paymentMethods: response.data.payment_methods || response.data || [],
          default: response.data.default_payment_method,
        };
        break;

      default:
        formattedData = response.data;
    }

    return {
      success: true,
      status: response.status,
      data: formattedData,
      metadata: {
        query: params.query,
        userId: params.userId,
        executionTime: Date.now() - startTime,
        timestamp: new Date().toISOString(),
        toolVersion: '1.0.0',
      },
    };
  } catch (error: any) {
    // Handle axios errors
    if (error.response) {
      return {
        success: false,
        status: error.response.status,
        error: error.response.data?.message || error.response.statusText || `Failed to retrieve ${params.query}`,
        data: error.response.data,
        metadata: {
          query: params.query,
          userId: params.userId,
          executionTime: Date.now() - startTime,
          timestamp: new Date().toISOString(),
          toolVersion: '1.0.0',
        },
      };
    } else if (error.request) {
      return {
        success: false,
        status: 0,
        error: 'No response from Ops-Center API. Service may be down.',
        metadata: {
          query: params.query,
          userId: params.userId,
          executionTime: Date.now() - startTime,
          timestamp: new Date().toISOString(),
          toolVersion: '1.0.0',
        },
      };
    } else {
      return {
        success: false,
        status: 0,
        error: error.message || `Unknown error occurred while retrieving ${params.query}`,
        metadata: {
          query: params.query,
          userId: params.userId,
          executionTime: Date.now() - startTime,
          timestamp: new Date().toISOString(),
          toolVersion: '1.0.0',
        },
      };
    }
  }
}

/**
 * Example usage
 */
export const examples = [
  {
    description: 'Get all available subscription plans',
    params: {
      query: 'plans',
    },
  },
  {
    description: 'Get current user subscription',
    params: {
      query: 'current_plan',
    },
  },
  {
    description: 'Get specific user subscription',
    params: {
      query: 'current_plan',
      userId: '12345678-1234-1234-1234-123456789abc',
    },
  },
  {
    description: 'Get current month usage',
    params: {
      query: 'usage',
    },
  },
  {
    description: 'Get invoice history',
    params: {
      query: 'invoices',
      filters: {
        status: 'paid',
        limit: 10,
      },
    },
  },
  {
    description: 'Get invoices for date range',
    params: {
      query: 'invoices',
      filters: {
        startDate: '2025-01-01',
        endDate: '2025-10-31',
      },
    },
  },
  {
    description: 'Get payment methods',
    params: {
      query: 'payment_methods',
    },
  },
  {
    description: 'Get detailed subscription information',
    params: {
      query: 'subscription_details',
      userId: '12345678-1234-1234-1234-123456789abc',
    },
  },
];

export default tool;
