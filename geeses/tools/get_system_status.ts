/**
 * Tool: get_system_status
 *
 * Fetch comprehensive system health and status information.
 * Aggregates data from multiple sources: Docker containers, GPU metrics,
 * service uptime, and resource utilization.
 *
 * @author Tools Engineer (AI Agent Team)
 * @version 1.0.0
 */

import axios, { AxiosRequestConfig } from 'axios';

export interface SystemStatusParams {
  includeGpu?: boolean;
  includeNetwork?: boolean;
  includeMetrics?: boolean;
}

export interface SystemStatusResult {
  success: boolean;
  status: number;
  data?: {
    services: ServiceStatus[];
    gpu?: GpuStatus;
    network?: NetworkStatus;
    metrics?: SystemMetrics;
    timestamp: string;
  };
  error?: string;
  metadata: {
    executionTime: number;
    timestamp: string;
    toolVersion: string;
  };
}

export interface ServiceStatus {
  name: string;
  container: string;
  status: 'running' | 'stopped' | 'restarting' | 'error';
  health: 'healthy' | 'unhealthy' | 'starting' | 'unknown';
  uptime: string;
  port?: number;
  cpu: string;
  memory: string;
  restartCount: number;
}

export interface GpuStatus {
  available: boolean;
  devices: Array<{
    id: number;
    name: string;
    utilization: number;
    memoryTotal: string;
    memoryUsed: string;
    memoryFree: string;
    temperature: number;
    powerUsage: string;
  }>;
}

export interface NetworkStatus {
  connectivity: boolean;
  latency: number;
  endpoints: Array<{
    name: string;
    url: string;
    reachable: boolean;
    responseTime?: number;
  }>;
}

export interface SystemMetrics {
  cpuUsage: number;
  memoryUsage: number;
  diskUsage: number;
  networkIn: string;
  networkOut: string;
  uptime: string;
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
  name: 'get_system_status',
  description: 'Fetch comprehensive system health and status. Returns Docker container status, GPU metrics (if available), network connectivity, and resource utilization for all UC-Cloud services.',
  parameters: {
    type: 'object',
    properties: {
      includeGpu: {
        type: 'boolean',
        description: 'Include GPU status and metrics (default: true)',
        default: true,
      },
      includeNetwork: {
        type: 'boolean',
        description: 'Include network connectivity checks (default: true)',
        default: true,
      },
      includeMetrics: {
        type: 'boolean',
        description: 'Include detailed system metrics (CPU, memory, disk) (default: true)',
        default: true,
      },
    },
    required: [],
  },
  handler: getSystemStatus,
};

/**
 * Validate tool parameters
 */
function validateParams(params: SystemStatusParams): { valid: boolean; error?: string } {
  // All parameters are optional and boolean, so validation is minimal
  if (params.includeGpu !== undefined && typeof params.includeGpu !== 'boolean') {
    return { valid: false, error: 'includeGpu must be a boolean' };
  }
  if (params.includeNetwork !== undefined && typeof params.includeNetwork !== 'boolean') {
    return { valid: false, error: 'includeNetwork must be a boolean' };
  }
  if (params.includeMetrics !== undefined && typeof params.includeMetrics !== 'boolean') {
    return { valid: false, error: 'includeMetrics must be a boolean' };
  }
  return { valid: true };
}

/**
 * Parse uptime string to human-readable format
 */
function formatUptime(seconds: number): string {
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);

  if (days > 0) {
    return `${days}d ${hours}h ${minutes}m`;
  } else if (hours > 0) {
    return `${hours}h ${minutes}m`;
  } else {
    return `${minutes}m`;
  }
}

/**
 * Parse memory string (e.g., "2.1GiB / 4.0GiB") to percentage
 */
function parseMemoryUsage(memoryStr: string): string {
  const match = memoryStr.match(/(\d+\.?\d*)\s*(\w+)\s*\/\s*(\d+\.?\d*)\s*(\w+)/);
  if (!match) return memoryStr;

  const used = parseFloat(match[1]);
  const total = parseFloat(match[3]);
  const percentage = ((used / total) * 100).toFixed(1);

  return `${used}${match[2]} / ${total}${match[4]} (${percentage}%)`;
}

/**
 * Main tool handler
 */
export async function getSystemStatus(
  params: SystemStatusParams = {},
  context?: any
): Promise<SystemStatusResult> {
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
          executionTime: Date.now() - startTime,
          timestamp: new Date().toISOString(),
          toolVersion: '1.0.0',
        },
      };
    }

    // Set defaults
    const includeGpu = params.includeGpu !== false;
    const includeNetwork = params.includeNetwork !== false;
    const includeMetrics = params.includeMetrics !== false;

    // Build request configuration
    const config: AxiosRequestConfig = {
      method: 'GET',
      url: `${OPS_CENTER_BASE_URL}/api/${API_VERSION}/system/status`,
      headers: {
        'Content-Type': 'application/json',
      },
      params: {
        include_gpu: includeGpu,
        include_network: includeNetwork,
        include_metrics: includeMetrics,
      },
      timeout: 10000, // 10 seconds
    };

    // Add authentication if context provides it
    if (context?.keycloakToken) {
      config.headers.Authorization = `Bearer ${context.keycloakToken}`;
    }

    // Execute request
    const response = await axios(config);

    // Parse and format response data
    const rawData = response.data;
    const formattedData: any = {
      services: [],
      timestamp: new Date().toISOString(),
    };

    // Format service status
    if (rawData.services) {
      formattedData.services = rawData.services.map((service: any) => ({
        name: service.name,
        container: service.container_name || service.container,
        status: service.status || 'unknown',
        health: service.health || 'unknown',
        uptime: service.uptime_seconds ? formatUptime(service.uptime_seconds) : service.uptime || 'N/A',
        port: service.port,
        cpu: service.cpu_usage || 'N/A',
        memory: service.memory_usage ? parseMemoryUsage(service.memory_usage) : 'N/A',
        restartCount: service.restart_count || 0,
      }));
    }

    // Format GPU status
    if (includeGpu && rawData.gpu) {
      formattedData.gpu = {
        available: rawData.gpu.available || false,
        devices: (rawData.gpu.devices || []).map((device: any) => ({
          id: device.id,
          name: device.name,
          utilization: device.utilization_percent || 0,
          memoryTotal: device.memory_total || 'N/A',
          memoryUsed: device.memory_used || 'N/A',
          memoryFree: device.memory_free || 'N/A',
          temperature: device.temperature_celsius || 0,
          powerUsage: device.power_usage || 'N/A',
        })),
      };
    }

    // Format network status
    if (includeNetwork && rawData.network) {
      formattedData.network = {
        connectivity: rawData.network.connectivity !== false,
        latency: rawData.network.latency || 0,
        endpoints: (rawData.network.endpoints || []).map((endpoint: any) => ({
          name: endpoint.name,
          url: endpoint.url,
          reachable: endpoint.reachable !== false,
          responseTime: endpoint.response_time_ms,
        })),
      };
    }

    // Format system metrics
    if (includeMetrics && rawData.metrics) {
      formattedData.metrics = {
        cpuUsage: rawData.metrics.cpu_usage_percent || 0,
        memoryUsage: rawData.metrics.memory_usage_percent || 0,
        diskUsage: rawData.metrics.disk_usage_percent || 0,
        networkIn: rawData.metrics.network_in || 'N/A',
        networkOut: rawData.metrics.network_out || 'N/A',
        uptime: rawData.metrics.system_uptime ? formatUptime(rawData.metrics.system_uptime) : 'N/A',
      };
    }

    return {
      success: true,
      status: response.status,
      data: formattedData,
      metadata: {
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
        error: error.response.data?.message || error.response.statusText || 'Failed to fetch system status',
        metadata: {
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
          executionTime: Date.now() - startTime,
          timestamp: new Date().toISOString(),
          toolVersion: '1.0.0',
        },
      };
    } else {
      return {
        success: false,
        status: 0,
        error: error.message || 'Unknown error occurred while fetching system status',
        metadata: {
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
    description: 'Get full system status with all details',
    params: {
      includeGpu: true,
      includeNetwork: true,
      includeMetrics: true,
    },
  },
  {
    description: 'Get basic service status without GPU or network info',
    params: {
      includeGpu: false,
      includeNetwork: false,
      includeMetrics: false,
    },
  },
  {
    description: 'Get service and GPU status only',
    params: {
      includeGpu: true,
      includeNetwork: false,
      includeMetrics: false,
    },
  },
];

export default tool;
