/**
 * Tool: query_logs
 *
 * Search and analyze logs from UC-Cloud services via Docker logs API.
 * Supports time range filtering, log level filtering, pattern matching,
 * and full-text search across all service logs.
 *
 * @author Tools Engineer (AI Agent Team)
 * @version 1.0.0
 */

import axios, { AxiosRequestConfig } from 'axios';

export interface QueryLogsParams {
  service?: string;
  query?: string;
  logLevel?: 'DEBUG' | 'INFO' | 'WARN' | 'WARNING' | 'ERROR' | 'CRITICAL' | 'FATAL';
  timeRange?: string;
  since?: string;
  until?: string;
  tail?: number;
  follow?: boolean;
  regex?: boolean;
}

export interface QueryLogsResult {
  success: boolean;
  status: number;
  data?: {
    logs: LogEntry[];
    total: number;
    service?: string;
    timeRange?: string;
    filters: {
      query?: string;
      logLevel?: string;
      since?: string;
      until?: string;
    };
  };
  error?: string;
  metadata: {
    service?: string;
    query?: string;
    executionTime: number;
    timestamp: string;
    toolVersion: string;
  };
}

export interface LogEntry {
  timestamp: string;
  level: string;
  service: string;
  container: string;
  message: string;
  context?: Record<string, any>;
  stackTrace?: string;
}

/**
 * Configuration
 */
const OPS_CENTER_BASE_URL = process.env.OPS_CENTER_API_URL || 'http://ops-center-direct:8084';
const API_VERSION = 'v1';

/**
 * Services that can be queried for logs
 */
const AVAILABLE_SERVICES = [
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
  'brigade',
  'unicorn-brigade',
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
];

/**
 * Tool definition for Brigade
 */
export const tool = {
  name: 'query_logs',
  description: 'Search and analyze logs from UC-Cloud services. Supports filtering by service, log level, time range, and full-text search with regex patterns. Use for troubleshooting, error analysis, and audit trails.',
  parameters: {
    type: 'object',
    properties: {
      service: {
        type: 'string',
        description: 'Service name to query logs from (e.g., "vllm", "open-webui"). If not specified, searches all services.',
      },
      query: {
        type: 'string',
        description: 'Search query or pattern to match in log messages',
      },
      logLevel: {
        type: 'string',
        enum: ['DEBUG', 'INFO', 'WARN', 'WARNING', 'ERROR', 'CRITICAL', 'FATAL'],
        description: 'Filter logs by severity level',
      },
      timeRange: {
        type: 'string',
        description: 'Relative time range (e.g., "1h", "24h", "7d", "30d")',
      },
      since: {
        type: 'string',
        description: 'Start time in ISO 8601 format (e.g., "2025-10-28T00:00:00Z")',
      },
      until: {
        type: 'string',
        description: 'End time in ISO 8601 format (e.g., "2025-10-28T23:59:59Z")',
      },
      tail: {
        type: 'number',
        description: 'Number of most recent log entries to return (default: 100, max: 1000)',
        default: 100,
        minimum: 1,
        maximum: 1000,
      },
      follow: {
        type: 'boolean',
        description: 'Stream logs in real-time (not recommended for Geeses, use for debugging)',
        default: false,
      },
      regex: {
        type: 'boolean',
        description: 'Treat query as a regular expression pattern',
        default: false,
      },
    },
    required: [],
  },
  handler: queryLogs,
};

/**
 * Validate tool parameters
 */
function validateParams(params: QueryLogsParams): { valid: boolean; error?: string } {
  // Validate service name if provided
  if (params.service) {
    const normalizedService = params.service.toLowerCase();
    const isValid = AVAILABLE_SERVICES.some(service =>
      service.toLowerCase().includes(normalizedService) ||
      normalizedService.includes(service.toLowerCase())
    );

    if (!isValid) {
      return {
        valid: false,
        error: `Service '${params.service}' not found. Available services: ${AVAILABLE_SERVICES.slice(0, 10).join(', ')}...`,
      };
    }
  }

  // Validate log level if provided
  if (params.logLevel) {
    const validLevels = ['DEBUG', 'INFO', 'WARN', 'WARNING', 'ERROR', 'CRITICAL', 'FATAL'];
    if (!validLevels.includes(params.logLevel)) {
      return { valid: false, error: `Invalid log level. Must be one of: ${validLevels.join(', ')}` };
    }
  }

  // Validate time range format if provided
  if (params.timeRange) {
    const timeRangeRegex = /^\d+[smhd]$/;
    if (!timeRangeRegex.test(params.timeRange)) {
      return {
        valid: false,
        error: 'Invalid time range format. Use format like "1h", "24h", "7d" (s=seconds, m=minutes, h=hours, d=days)',
      };
    }
  }

  // Validate ISO 8601 date format if provided
  if (params.since || params.until) {
    const iso8601Regex = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(Z|[+-]\d{2}:\d{2})$/;
    if (params.since && !iso8601Regex.test(params.since)) {
      return { valid: false, error: 'Invalid since date format. Use ISO 8601 format (e.g., "2025-10-28T00:00:00Z")' };
    }
    if (params.until && !iso8601Regex.test(params.until)) {
      return { valid: false, error: 'Invalid until date format. Use ISO 8601 format (e.g., "2025-10-28T23:59:59Z")' };
    }
  }

  // Validate tail parameter
  if (params.tail !== undefined) {
    if (params.tail < 1 || params.tail > 1000) {
      return { valid: false, error: 'tail must be between 1 and 1000' };
    }
  }

  // Validate regex pattern if provided
  if (params.regex && params.query) {
    try {
      new RegExp(params.query);
    } catch (e) {
      return { valid: false, error: `Invalid regex pattern: ${e.message}` };
    }
  }

  return { valid: true };
}

/**
 * Parse log line into structured LogEntry
 */
function parseLogLine(line: string, service: string, container: string): LogEntry {
  // Try to parse structured log format (JSON or common patterns)
  // Format examples:
  // 1. JSON: {"timestamp": "2025-10-28T...", "level": "ERROR", "message": "..."}
  // 2. Common: [2025-10-28 12:34:56] ERROR: message here
  // 3. Docker: 2025-10-28T12:34:56.123Z level message

  let entry: LogEntry = {
    timestamp: new Date().toISOString(),
    level: 'INFO',
    service,
    container,
    message: line,
  };

  // Try JSON parse first
  if (line.trim().startsWith('{')) {
    try {
      const json = JSON.parse(line);
      entry = {
        timestamp: json.timestamp || json.time || json.ts || entry.timestamp,
        level: (json.level || json.severity || 'INFO').toUpperCase(),
        service,
        container,
        message: json.message || json.msg || json.log || line,
        context: json.context || json.data,
        stackTrace: json.stack || json.stackTrace,
      };
      return entry;
    } catch (e) {
      // Not JSON, continue with regex parsing
    }
  }

  // Try common log patterns
  const patterns = [
    // [2025-10-28 12:34:56] LEVEL: message
    /\[(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}[^\]]*)\]\s+(\w+):\s*(.+)/,
    // 2025-10-28T12:34:56.123Z LEVEL message
    /^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[^\s]*)\s+(\w+)\s+(.+)/,
    // LEVEL: message (no timestamp)
    /^(\w+):\s*(.+)/,
  ];

  for (const pattern of patterns) {
    const match = line.match(pattern);
    if (match) {
      if (pattern.source.startsWith('\\[(')) {
        // Pattern with timestamp and level
        entry.timestamp = match[1];
        entry.level = match[2].toUpperCase();
        entry.message = match[3];
      } else if (pattern.source.startsWith('^(\\d')) {
        // Pattern with ISO timestamp
        entry.timestamp = match[1];
        entry.level = match[2].toUpperCase();
        entry.message = match[3];
      } else {
        // Pattern without timestamp
        entry.level = match[1].toUpperCase();
        entry.message = match[2];
      }
      break;
    }
  }

  return entry;
}

/**
 * Main tool handler
 */
export async function queryLogs(
  params: QueryLogsParams = {},
  context?: any
): Promise<QueryLogsResult> {
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
          service: params.service,
          query: params.query,
          executionTime: Date.now() - startTime,
          timestamp: new Date().toISOString(),
          toolVersion: '1.0.0',
        },
      };
    }

    // Build request configuration
    const config: AxiosRequestConfig = {
      method: 'GET',
      url: `${OPS_CENTER_BASE_URL}/api/${API_VERSION}/logs/query`,
      headers: {
        'Content-Type': 'application/json',
      },
      params: {
        service: params.service,
        query: params.query,
        log_level: params.logLevel,
        time_range: params.timeRange,
        since: params.since,
        until: params.until,
        tail: params.tail || 100,
        follow: params.follow || false,
        regex: params.regex || false,
      },
      timeout: 30000, // 30 seconds
    };

    // Add authentication if context provides it
    if (context?.keycloakToken) {
      config.headers.Authorization = `Bearer ${context.keycloakToken}`;
    }

    // Execute request
    const response = await axios(config);

    // Parse and format response
    const rawData = response.data;
    const logs: LogEntry[] = [];

    if (rawData.logs && Array.isArray(rawData.logs)) {
      // Logs already structured
      logs.push(...rawData.logs.map((log: any) => ({
        timestamp: log.timestamp || log.time || new Date().toISOString(),
        level: (log.level || log.severity || 'INFO').toUpperCase(),
        service: log.service || params.service || 'unknown',
        container: log.container || log.container_name || 'unknown',
        message: log.message || log.msg || log.log || '',
        context: log.context || log.data,
        stackTrace: log.stack || log.stackTrace,
      })));
    } else if (rawData.lines && Array.isArray(rawData.lines)) {
      // Raw log lines, need parsing
      rawData.lines.forEach((line: string) => {
        const entry = parseLogLine(
          line,
          params.service || rawData.service || 'unknown',
          rawData.container || 'unknown'
        );
        logs.push(entry);
      });
    }

    const formattedData = {
      logs,
      total: logs.length,
      service: params.service,
      timeRange: params.timeRange || (params.since && params.until ? `${params.since} to ${params.until}` : undefined),
      filters: {
        query: params.query,
        logLevel: params.logLevel,
        since: params.since,
        until: params.until,
      },
    };

    return {
      success: true,
      status: response.status,
      data: formattedData,
      metadata: {
        service: params.service,
        query: params.query,
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
        error: error.response.data?.message || error.response.statusText || 'Failed to query logs',
        metadata: {
          service: params.service,
          query: params.query,
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
          service: params.service,
          query: params.query,
          executionTime: Date.now() - startTime,
          timestamp: new Date().toISOString(),
          toolVersion: '1.0.0',
        },
      };
    } else {
      return {
        success: false,
        status: 0,
        error: error.message || 'Unknown error occurred while querying logs',
        metadata: {
          service: params.service,
          query: params.query,
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
    description: 'Get recent logs from vLLM service',
    params: {
      service: 'vllm',
      tail: 50,
    },
  },
  {
    description: 'Search for errors in Open-WebUI',
    params: {
      service: 'open-webui',
      logLevel: 'ERROR',
      timeRange: '24h',
    },
  },
  {
    description: 'Find all logs containing "CUDA" in the last hour',
    params: {
      query: 'CUDA',
      timeRange: '1h',
    },
  },
  {
    description: 'Get critical errors from all services',
    params: {
      logLevel: 'CRITICAL',
      tail: 100,
    },
  },
  {
    description: 'Search logs with regex pattern',
    params: {
      service: 'vllm',
      query: 'OOM|out of memory|allocation failed',
      regex: true,
      timeRange: '7d',
    },
  },
  {
    description: 'Get logs for specific time range',
    params: {
      service: 'postgresql',
      since: '2025-10-28T00:00:00Z',
      until: '2025-10-28T23:59:59Z',
      logLevel: 'ERROR',
    },
  },
  {
    description: 'Get recent warnings from Redis',
    params: {
      service: 'redis',
      logLevel: 'WARN',
      tail: 20,
    },
  },
];

export default tool;
