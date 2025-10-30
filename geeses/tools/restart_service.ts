/**
 * Tool: restart_service
 *
 * Docker container lifecycle management for UC-Cloud services.
 * Safely restart, stop, or start services with validation and health checks.
 *
 * @author Tools Engineer (AI Agent Team)
 * @version 1.0.0
 */

import axios, { AxiosRequestConfig } from 'axios';

export interface RestartServiceParams {
  action: 'restart' | 'stop' | 'start' | 'status';
  serviceName: string;
  force?: boolean;
  timeout?: number;
}

export interface RestartServiceResult {
  success: boolean;
  status: number;
  data?: {
    service: string;
    action: string;
    previousStatus?: string;
    currentStatus: string;
    message: string;
    healthCheck?: {
      healthy: boolean;
      responseTime?: number;
      endpoint?: string;
    };
    timestamp: string;
  };
  error?: string;
  metadata: {
    action: string;
    serviceName: string;
    executionTime: number;
    timestamp: string;
    toolVersion: string;
  };
}

/**
 * Configuration
 */
const OPS_CENTER_BASE_URL = process.env.OPS_CENTER_API_URL || 'http://ops-center-direct:8084';
const API_VERSION = 'v1';

/**
 * Whitelist of services that can be managed
 * Security measure to prevent unauthorized container manipulation
 */
const ALLOWED_SERVICES = [
  'ops-center',
  'ops-center-direct',
  'open-webui',
  'unicorn-open-webui',
  'vllm',
  'unicorn-vllm',
  'embeddings',
  'unicorn-embeddings',
  'reranker',
  'unicorn-reranker',
  'center-deep',
  'unicorn-centerdeep',
  'unicorn-center-deep',
  'brigade',
  'unicorn-brigade',
  'unicorn-brigade-ui',
  'orator',
  'unicorn-orator',
  'amanuensis',
  'unicorn-amanuensis',
  'redis',
  'unicorn-redis',
  'postgresql',
  'unicorn-postgresql',
  'qdrant',
  'unicorn-qdrant',
  'traefik',
  'keycloak',
  'uchub-keycloak',
  'authentik-server',
  'authentik-worker',
];

/**
 * Services that require special confirmation (destructive/critical)
 */
const CRITICAL_SERVICES = [
  'postgresql',
  'unicorn-postgresql',
  'redis',
  'unicorn-redis',
  'keycloak',
  'uchub-keycloak',
  'ops-center',
  'ops-center-direct',
];

/**
 * Tool definition for Brigade
 */
export const tool = {
  name: 'restart_service',
  description: 'Manage Docker container lifecycle for UC-Cloud services. Safely restart, stop, or start services with automatic health checks and validation. Only authorized services can be managed.',
  parameters: {
    type: 'object',
    properties: {
      action: {
        type: 'string',
        enum: ['restart', 'stop', 'start', 'status'],
        description: 'Action to perform on the service',
      },
      serviceName: {
        type: 'string',
        description: 'Name of the service/container to manage (e.g., "vllm", "open-webui", "redis")',
      },
      force: {
        type: 'boolean',
        description: 'Force the action even for critical services (default: false, requires explicit confirmation)',
        default: false,
      },
      timeout: {
        type: 'number',
        description: 'Timeout in seconds for the operation (default: 30)',
        default: 30,
        minimum: 5,
        maximum: 120,
      },
    },
    required: ['action', 'serviceName'],
  },
  handler: restartService,
};

/**
 * Validate tool parameters
 */
function validateParams(params: RestartServiceParams): { valid: boolean; error?: string } {
  const validActions = ['restart', 'stop', 'start', 'status'];

  if (!params.action) {
    return { valid: false, error: 'Action is required' };
  }

  if (!validActions.includes(params.action)) {
    return { valid: false, error: `Invalid action. Must be one of: ${validActions.join(', ')}` };
  }

  if (!params.serviceName) {
    return { valid: false, error: 'Service name is required' };
  }

  // Normalize service name (remove prefixes, lowercase)
  const normalizedService = params.serviceName.toLowerCase().replace(/^unicorn-/, '');
  const isAllowed = ALLOWED_SERVICES.some(service =>
    service.toLowerCase().includes(normalizedService) ||
    normalizedService.includes(service.toLowerCase())
  );

  if (!isAllowed) {
    return {
      valid: false,
      error: `Service '${params.serviceName}' is not in the allowed services list. Cannot manage unauthorized containers.`,
    };
  }

  // Check if critical service and force is not set
  const isCritical = CRITICAL_SERVICES.some(service =>
    params.serviceName.toLowerCase().includes(service.toLowerCase())
  );

  if (isCritical && ['stop', 'restart'].includes(params.action) && !params.force) {
    return {
      valid: false,
      error: `'${params.serviceName}' is a critical service. Use force=true to confirm this action. WARNING: This may cause service disruption.`,
    };
  }

  // Validate timeout
  if (params.timeout !== undefined) {
    if (params.timeout < 5 || params.timeout > 120) {
      return { valid: false, error: 'Timeout must be between 5 and 120 seconds' };
    }
  }

  return { valid: true };
}

/**
 * Build API endpoint based on action
 */
function buildEndpoint(action: string, serviceName: string): string {
  const basePath = `/api/${API_VERSION}/services`;

  switch (action) {
    case 'restart':
      return `${basePath}/${serviceName}/restart`;
    case 'stop':
      return `${basePath}/${serviceName}/stop`;
    case 'start':
      return `${basePath}/${serviceName}/start`;
    case 'status':
      return `${basePath}/${serviceName}/status`;
    default:
      return `${basePath}/${serviceName}/status`;
  }
}

/**
 * Main tool handler
 */
export async function restartService(
  params: RestartServiceParams,
  context?: any
): Promise<RestartServiceResult> {
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
          action: params.action,
          serviceName: params.serviceName,
          executionTime: Date.now() - startTime,
          timestamp: new Date().toISOString(),
          toolVersion: '1.0.0',
        },
      };
    }

    // Build request configuration
    const endpoint = buildEndpoint(params.action, params.serviceName);
    const method = params.action === 'status' ? 'GET' : 'POST';

    const config: AxiosRequestConfig = {
      method,
      url: `${OPS_CENTER_BASE_URL}${endpoint}`,
      headers: {
        'Content-Type': 'application/json',
      },
      timeout: (params.timeout || 30) * 1000, // Convert to milliseconds
    };

    // Add authentication if context provides it
    if (context?.keycloakToken) {
      config.headers.Authorization = `Bearer ${context.keycloakToken}`;
    }

    // Add request body for POST actions
    if (method === 'POST') {
      config.data = {
        force: params.force || false,
        timeout: params.timeout || 30,
      };
    }

    // Execute request
    const response = await axios(config);

    // Format response
    const responseData = response.data;
    const formattedData = {
      service: params.serviceName,
      action: params.action,
      previousStatus: responseData.previous_status || responseData.previousStatus,
      currentStatus: responseData.status || responseData.currentStatus || 'unknown',
      message: responseData.message || `${params.action} operation completed successfully`,
      timestamp: new Date().toISOString(),
    };

    // Add health check data if available
    if (responseData.health || responseData.healthCheck) {
      const health = responseData.health || responseData.healthCheck;
      formattedData.healthCheck = {
        healthy: health.healthy !== false,
        responseTime: health.response_time || health.responseTime,
        endpoint: health.endpoint,
      };
    }

    // For restart/start actions, add a brief wait and perform health check
    if (['restart', 'start'].includes(params.action) && !formattedData.healthCheck) {
      // Wait 2 seconds for service to start
      await new Promise(resolve => setTimeout(resolve, 2000));

      // Attempt health check
      try {
        const healthConfig: AxiosRequestConfig = {
          method: 'GET',
          url: `${OPS_CENTER_BASE_URL}${buildEndpoint('status', params.serviceName)}`,
          headers: config.headers,
          timeout: 5000,
        };

        const healthCheck = await axios(healthConfig);
        formattedData.healthCheck = {
          healthy: healthCheck.data.status === 'running' || healthCheck.data.healthy === true,
          responseTime: healthCheck.data.response_time,
          endpoint: healthCheck.config.url,
        };
      } catch (healthError) {
        // Health check failed, service may not be fully ready
        formattedData.healthCheck = {
          healthy: false,
          responseTime: undefined,
          endpoint: undefined,
        };
      }
    }

    return {
      success: true,
      status: response.status,
      data: formattedData,
      metadata: {
        action: params.action,
        serviceName: params.serviceName,
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
        error: error.response.data?.message || error.response.statusText || `Failed to ${params.action} service`,
        data: error.response.data,
        metadata: {
          action: params.action,
          serviceName: params.serviceName,
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
          action: params.action,
          serviceName: params.serviceName,
          executionTime: Date.now() - startTime,
          timestamp: new Date().toISOString(),
          toolVersion: '1.0.0',
        },
      };
    } else {
      return {
        success: false,
        status: 0,
        error: error.message || `Unknown error occurred while ${params.action}ing service`,
        metadata: {
          action: params.action,
          serviceName: params.serviceName,
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
    description: 'Get service status',
    params: {
      action: 'status',
      serviceName: 'vllm',
    },
  },
  {
    description: 'Restart a service',
    params: {
      action: 'restart',
      serviceName: 'open-webui',
    },
  },
  {
    description: 'Stop a service',
    params: {
      action: 'stop',
      serviceName: 'embeddings',
    },
  },
  {
    description: 'Start a stopped service',
    params: {
      action: 'start',
      serviceName: 'embeddings',
    },
  },
  {
    description: 'Force restart a critical service (PostgreSQL)',
    params: {
      action: 'restart',
      serviceName: 'postgresql',
      force: true,
      timeout: 60,
    },
  },
  {
    description: 'Restart with custom timeout',
    params: {
      action: 'restart',
      serviceName: 'center-deep',
      timeout: 45,
    },
  },
];

export default tool;
