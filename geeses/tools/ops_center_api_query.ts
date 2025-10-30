/**
 * Tool: ops_center_api_query
 *
 * Query any Ops-Center API endpoint directly.
 * Provides flexible access to all Ops-Center operations.
 *
 * @author Tools Engineer (AI Agent Team)
 * @version 1.0.0
 */

import axios, { AxiosRequestConfig, Method } from 'axios';

export interface OpsCenterAPIQueryParams {
  endpoint: string;
  method: Method;
  body?: any;
  headers?: Record<string, string>;
  queryParams?: Record<string, string>;
}

export interface OpsCenterAPIQueryResult {
  success: boolean;
  status: number;
  data?: any;
  error?: string;
  metadata: {
    endpoint: string;
    method: string;
    executionTime: number;
    timestamp: string;
  };
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
  name: 'ops_center_api_query',
  description: 'Query any Ops-Center API endpoint directly. Use for custom queries, advanced operations, or accessing endpoints not covered by specialized tools.',
  parameters: {
    type: 'object',
    properties: {
      endpoint: {
        type: 'string',
        description: 'API endpoint path (e.g., "/api/v1/services/status" or just "/services/status")',
      },
      method: {
        type: 'string',
        enum: ['GET', 'POST', 'PUT', 'DELETE', 'PATCH'],
        description: 'HTTP method to use',
        default: 'GET',
      },
      body: {
        type: 'object',
        description: 'Request body (for POST, PUT, PATCH methods)',
      },
      headers: {
        type: 'object',
        description: 'Additional HTTP headers',
      },
      queryParams: {
        type: 'object',
        description: 'URL query parameters',
      },
    },
    required: ['endpoint', 'method'],
  },
  handler: opsCenterAPIQuery,
};

/**
 * Validate tool parameters
 */
function validateParams(params: OpsCenterAPIQueryParams): { valid: boolean; error?: string } {
  if (!params.endpoint) {
    return { valid: false, error: 'Endpoint is required' };
  }

  if (!params.method) {
    return { valid: false, error: 'Method is required' };
  }

  const validMethods = ['GET', 'POST', 'PUT', 'DELETE', 'PATCH'];
  if (!validMethods.includes(params.method)) {
    return { valid: false, error: `Invalid method. Must be one of: ${validMethods.join(', ')}` };
  }

  // Validate endpoint format
  if (!params.endpoint.startsWith('/')) {
    return { valid: false, error: 'Endpoint must start with /' };
  }

  // Prevent accessing forbidden endpoints
  const forbiddenPaths = ['/admin/credentials', '/internal/secrets'];
  if (forbiddenPaths.some(path => params.endpoint.includes(path))) {
    return { valid: false, error: 'Access to this endpoint is not permitted' };
  }

  return { valid: true };
}

/**
 * Normalize endpoint path
 */
function normalizeEndpoint(endpoint: string): string {
  // Remove leading slash
  let normalized = endpoint.startsWith('/') ? endpoint.substring(1) : endpoint;

  // Add API version if not present
  if (!normalized.startsWith('api/')) {
    normalized = `api/${API_VERSION}/${normalized}`;
  }

  return `/${normalized}`;
}

/**
 * Build full URL with query parameters
 */
function buildUrl(endpoint: string, queryParams?: Record<string, string>): string {
  const normalizedEndpoint = normalizeEndpoint(endpoint);
  const baseUrl = `${OPS_CENTER_BASE_URL}${normalizedEndpoint}`;

  if (!queryParams || Object.keys(queryParams).length === 0) {
    return baseUrl;
  }

  const params = new URLSearchParams(queryParams);
  return `${baseUrl}?${params.toString()}`;
}

/**
 * Main tool handler
 */
export async function opsCenterAPIQuery(
  params: OpsCenterAPIQueryParams,
  context?: any
): Promise<OpsCenterAPIQueryResult> {
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
          endpoint: params.endpoint,
          method: params.method,
          executionTime: Date.now() - startTime,
          timestamp: new Date().toISOString(),
        },
      };
    }

    // Build request configuration
    const url = buildUrl(params.endpoint, params.queryParams);
    const config: AxiosRequestConfig = {
      method: params.method,
      url,
      headers: {
        'Content-Type': 'application/json',
        ...params.headers,
      },
      timeout: 30000, // 30 seconds
    };

    // Add body for non-GET requests
    if (params.method !== 'GET' && params.body) {
      config.data = params.body;
    }

    // Add authentication if context provides it
    if (context?.keycloakToken) {
      config.headers.Authorization = `Bearer ${context.keycloakToken}`;
    }

    // Execute request
    const response = await axios(config);

    return {
      success: true,
      status: response.status,
      data: response.data,
      metadata: {
        endpoint: params.endpoint,
        method: params.method,
        executionTime: Date.now() - startTime,
        timestamp: new Date().toISOString(),
      },
    };
  } catch (error: any) {
    // Handle axios errors
    if (error.response) {
      // Server responded with error status
      return {
        success: false,
        status: error.response.status,
        error: error.response.data?.message || error.response.statusText,
        data: error.response.data,
        metadata: {
          endpoint: params.endpoint,
          method: params.method,
          executionTime: Date.now() - startTime,
          timestamp: new Date().toISOString(),
        },
      };
    } else if (error.request) {
      // Request made but no response received
      return {
        success: false,
        status: 0,
        error: 'No response from Ops-Center API. Service may be down.',
        metadata: {
          endpoint: params.endpoint,
          method: params.method,
          executionTime: Date.now() - startTime,
          timestamp: new Date().toISOString(),
        },
      };
    } else {
      // Error setting up request
      return {
        success: false,
        status: 0,
        error: error.message || 'Unknown error occurred',
        metadata: {
          endpoint: params.endpoint,
          method: params.method,
          executionTime: Date.now() - startTime,
          timestamp: new Date().toISOString(),
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
    description: 'Get all services status',
    params: {
      endpoint: '/services/status',
      method: 'GET' as Method,
    },
  },
  {
    description: 'Get specific user details',
    params: {
      endpoint: '/users/uuid-123',
      method: 'GET' as Method,
    },
  },
  {
    description: 'Update service configuration',
    params: {
      endpoint: '/services/vllm/config',
      method: 'PUT' as Method,
      body: {
        gpu_memory_utilization: 0.95,
        max_model_len: 16384,
      },
    },
  },
  {
    description: 'Search logs with query parameters',
    params: {
      endpoint: '/logs/search',
      method: 'GET' as Method,
      queryParams: {
        service: 'vllm',
        level: 'error',
        since: '2025-10-27T00:00:00Z',
      },
    },
  },
];

export default tool;
