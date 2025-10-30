/**
 * Tool: manage_user
 *
 * User CRUD operations via Ops-Center API and Keycloak integration.
 * Handles user creation, updates, deletion, role management, and password resets.
 *
 * @author Tools Engineer (AI Agent Team)
 * @version 1.0.0
 */

import axios, { AxiosRequestConfig } from 'axios';

export interface ManageUserParams {
  action: 'create' | 'read' | 'update' | 'delete' | 'list' | 'reset_password' | 'assign_role' | 'remove_role';
  userId?: string;
  userData?: {
    email?: string;
    username?: string;
    firstName?: string;
    lastName?: string;
    password?: string;
    subscriptionTier?: 'trial' | 'starter' | 'professional' | 'enterprise';
    roles?: string[];
    enabled?: boolean;
    emailVerified?: boolean;
  };
  role?: string;
  filters?: {
    search?: string;
    tier?: string;
    role?: string;
    status?: string;
    limit?: number;
    offset?: number;
  };
}

export interface ManageUserResult {
  success: boolean;
  status: number;
  data?: any;
  error?: string;
  metadata: {
    action: string;
    userId?: string;
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
 * Tool definition for Brigade
 */
export const tool = {
  name: 'manage_user',
  description: 'Comprehensive user management operations. Create, read, update, delete user accounts with Keycloak SSO integration. Manage roles, reset passwords, and query user data.',
  parameters: {
    type: 'object',
    properties: {
      action: {
        type: 'string',
        enum: ['create', 'read', 'update', 'delete', 'list', 'reset_password', 'assign_role', 'remove_role'],
        description: 'Action to perform on user account',
      },
      userId: {
        type: 'string',
        description: 'User ID (UUID) - required for read, update, delete, reset_password, assign_role, remove_role',
      },
      userData: {
        type: 'object',
        description: 'User data for create or update operations',
        properties: {
          email: { type: 'string', format: 'email' },
          username: { type: 'string' },
          firstName: { type: 'string' },
          lastName: { type: 'string' },
          password: { type: 'string' },
          subscriptionTier: {
            type: 'string',
            enum: ['trial', 'starter', 'professional', 'enterprise'],
          },
          roles: { type: 'array', items: { type: 'string' } },
          enabled: { type: 'boolean' },
          emailVerified: { type: 'boolean' },
        },
      },
      role: {
        type: 'string',
        description: 'Role name for assign_role or remove_role actions',
      },
      filters: {
        type: 'object',
        description: 'Filters for list action',
        properties: {
          search: { type: 'string' },
          tier: { type: 'string' },
          role: { type: 'string' },
          status: { type: 'string' },
          limit: { type: 'number' },
          offset: { type: 'number' },
        },
      },
    },
    required: ['action'],
  },
  handler: manageUser,
};

/**
 * Validate tool parameters
 */
function validateParams(params: ManageUserParams): { valid: boolean; error?: string } {
  const validActions = ['create', 'read', 'update', 'delete', 'list', 'reset_password', 'assign_role', 'remove_role'];

  if (!params.action) {
    return { valid: false, error: 'Action is required' };
  }

  if (!validActions.includes(params.action)) {
    return { valid: false, error: `Invalid action. Must be one of: ${validActions.join(', ')}` };
  }

  // Actions that require userId
  const requireUserId = ['read', 'update', 'delete', 'reset_password', 'assign_role', 'remove_role'];
  if (requireUserId.includes(params.action) && !params.userId) {
    return { valid: false, error: `userId is required for ${params.action} action` };
  }

  // Actions that require userData
  if (params.action === 'create' && !params.userData) {
    return { valid: false, error: 'userData is required for create action' };
  }

  // Validate email format for create action
  if (params.action === 'create' && params.userData?.email) {
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!emailRegex.test(params.userData.email)) {
      return { valid: false, error: 'Invalid email format' };
    }
  }

  // Actions that require role
  if (['assign_role', 'remove_role'].includes(params.action) && !params.role) {
    return { valid: false, error: `role is required for ${params.action} action` };
  }

  return { valid: true };
}

/**
 * Build API endpoint based on action
 */
function buildEndpoint(action: string, userId?: string): string {
  const basePath = `/api/${API_VERSION}/admin/users`;

  switch (action) {
    case 'create':
      return `${basePath}/comprehensive`;
    case 'read':
      return `${basePath}/${userId}`;
    case 'update':
      return `${basePath}/${userId}`;
    case 'delete':
      return `${basePath}/${userId}`;
    case 'list':
      return basePath;
    case 'reset_password':
      return `${basePath}/${userId}/reset-password`;
    case 'assign_role':
      return `${basePath}/${userId}/roles/assign`;
    case 'remove_role':
      return `${basePath}/${userId}/roles/${params.role}`;
    default:
      return basePath;
  }
}

/**
 * Build HTTP method based on action
 */
function buildMethod(action: string): string {
  switch (action) {
    case 'create':
    case 'reset_password':
    case 'assign_role':
      return 'POST';
    case 'read':
    case 'list':
      return 'GET';
    case 'update':
      return 'PUT';
    case 'delete':
    case 'remove_role':
      return 'DELETE';
    default:
      return 'GET';
  }
}

/**
 * Main tool handler
 */
export async function manageUser(
  params: ManageUserParams,
  context?: any
): Promise<ManageUserResult> {
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
          userId: params.userId,
          executionTime: Date.now() - startTime,
          timestamp: new Date().toISOString(),
          toolVersion: '1.0.0',
        },
      };
    }

    // Build request configuration
    const endpoint = buildEndpoint(params.action, params.userId);
    const method = buildMethod(params.action);

    const config: AxiosRequestConfig = {
      method,
      url: `${OPS_CENTER_BASE_URL}${endpoint}`,
      headers: {
        'Content-Type': 'application/json',
      },
      timeout: 30000, // 30 seconds
    };

    // Add authentication if context provides it
    if (context?.keycloakToken) {
      config.headers.Authorization = `Bearer ${context.keycloakToken}`;
    }

    // Add request body for POST/PUT
    if (['POST', 'PUT'].includes(method)) {
      if (params.action === 'create' || params.action === 'update') {
        config.data = params.userData;
      } else if (params.action === 'assign_role') {
        config.data = { role: params.role };
      }
    }

    // Add query parameters for list action
    if (params.action === 'list' && params.filters) {
      config.params = params.filters;
    }

    // Execute request
    const response = await axios(config);

    // Format response based on action
    let formattedData = response.data;

    if (params.action === 'list' && response.data.users) {
      formattedData = {
        users: response.data.users.map((user: any) => ({
          id: user.id,
          email: user.email,
          username: user.username,
          firstName: user.first_name || user.firstName,
          lastName: user.last_name || user.lastName,
          subscriptionTier: user.subscription_tier || user.subscriptionTier || 'trial',
          roles: user.roles || [],
          enabled: user.enabled !== false,
          emailVerified: user.email_verified || user.emailVerified || false,
          createdAt: user.created_at || user.createdTimestamp,
          lastLogin: user.last_login || user.lastLogin,
        })),
        total: response.data.total || response.data.users.length,
        limit: response.data.limit,
        offset: response.data.offset,
      };
    } else if (params.action === 'read' && response.data) {
      formattedData = {
        id: response.data.id,
        email: response.data.email,
        username: response.data.username,
        firstName: response.data.first_name || response.data.firstName,
        lastName: response.data.last_name || response.data.lastName,
        subscriptionTier: response.data.subscription_tier || response.data.subscriptionTier || 'trial',
        roles: response.data.roles || [],
        enabled: response.data.enabled !== false,
        emailVerified: response.data.email_verified || response.data.emailVerified || false,
        createdAt: response.data.created_at || response.data.createdTimestamp,
        lastLogin: response.data.last_login || response.data.lastLogin,
        attributes: response.data.attributes || {},
      };
    }

    return {
      success: true,
      status: response.status,
      data: formattedData,
      metadata: {
        action: params.action,
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
        error: error.response.data?.message || error.response.statusText || `Failed to ${params.action} user`,
        data: error.response.data,
        metadata: {
          action: params.action,
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
          action: params.action,
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
        error: error.message || `Unknown error occurred while ${params.action}ing user`,
        metadata: {
          action: params.action,
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
    description: 'Create a new user',
    params: {
      action: 'create',
      userData: {
        email: 'newuser@example.com',
        username: 'newuser',
        firstName: 'New',
        lastName: 'User',
        password: 'SecurePassword123!',
        subscriptionTier: 'trial',
        emailVerified: false,
      },
    },
  },
  {
    description: 'Get user details',
    params: {
      action: 'read',
      userId: '12345678-1234-1234-1234-123456789abc',
    },
  },
  {
    description: 'List all users with filtering',
    params: {
      action: 'list',
      filters: {
        tier: 'professional',
        status: 'enabled',
        limit: 50,
        offset: 0,
      },
    },
  },
  {
    description: 'Update user subscription tier',
    params: {
      action: 'update',
      userId: '12345678-1234-1234-1234-123456789abc',
      userData: {
        subscriptionTier: 'professional',
      },
    },
  },
  {
    description: 'Assign admin role to user',
    params: {
      action: 'assign_role',
      userId: '12345678-1234-1234-1234-123456789abc',
      role: 'admin',
    },
  },
  {
    description: 'Remove role from user',
    params: {
      action: 'remove_role',
      userId: '12345678-1234-1234-1234-123456789abc',
      role: 'moderator',
    },
  },
  {
    description: 'Reset user password',
    params: {
      action: 'reset_password',
      userId: '12345678-1234-1234-1234-123456789abc',
    },
  },
  {
    description: 'Delete user account',
    params: {
      action: 'delete',
      userId: '12345678-1234-1234-1234-123456789abc',
    },
  },
];

export default tool;
