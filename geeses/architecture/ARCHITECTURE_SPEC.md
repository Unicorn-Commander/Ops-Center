# Navigator Geeses - Architecture Specification

## Document Control

- **Version**: 1.0.0
- **Status**: Design Phase
- **Author**: Agent Architect (AI Agent Team)
- **Date**: 2025-10-28
- **Parent System**: The Colonel Ecosystem

## Executive Summary

Navigator "Geeses" is a specialized AI agent designed to provide expert assistance for UC-Cloud Ops-Center infrastructure management. Geeses integrates with the Unicorn Brigade platform, providing conversational access to service monitoring, user management, billing operations, and Docker orchestration through natural language interactions.

## System Architecture

### High-Level Overview

```
┌────────────────────────────────────────────────────────────────┐
│                     The Colonel Ecosystem                       │
│                  (Ecosystem Orchestrator)                       │
└────────────────────────────────────────────────────────────────┘
                              │
                    ┌─────────┴─────────┐
                    │                   │
            ┌───────▼────────┐  ┌──────▼───────┐
            │  Lt. Col Geeses │  │   Future:    │
            │  (Ops-Center)  │  │  Brigade-One │
            │                │  │  DeepSearch  │
            └───────┬────────┘  └──────────────┘
                    │
        ┌───────────┼──────────────┐
        │           │              │
    ┌───▼───┐  ┌───▼────┐    ┌───▼──────┐
    │ Tools │  │Context │    │  Chat    │
    │  (6)  │  │ Layer  │    │Interface │
    └───┬───┘  └───┬────┘    └───┬──────┘
        │          │              │
        └──────────┴──────────────┘
                   │
        ┌──────────▼──────────┐
        │   Ops-Center API    │
        │   Brigade Platform  │
        │   Keycloak SSO      │
        └─────────────────────┘
```

### Component Architecture

#### 1. Agent Core

**Location**: Unicorn Brigade Agent Registry

**Responsibilities**:
- Natural language understanding for Ops-Center operations
- Tool selection and orchestration
- Response generation and formatting
- Session management
- Context awareness

**Implementation**:
- Hosted as Brigade agent (ID assigned on creation)
- LLM routing through Ops-Center LLM Hub
- Model: GPT-4o (default, configurable)
- Temperature: 0.7 (balanced creativity/precision)

#### 2. Tool Layer

**Location**: `/services/ops-center/geeses/tools/`

**Six Custom Tools**:

1. **ops_center_api_query**
   - Direct API access to any Ops-Center endpoint
   - HTTP methods: GET, POST, PUT, DELETE, PATCH
   - Authentication: Inherits user's Keycloak session
   - Error handling: Graceful degradation with user-friendly messages

2. **get_system_status**
   - Aggregates health data from multiple sources
   - Docker container status via Docker API
   - GPU metrics via nvidia-smi (if available)
   - Service uptime and resource utilization
   - Network connectivity checks

3. **manage_user**
   - CRUD operations for user accounts
   - Keycloak integration for SSO
   - Ops-Center user table synchronization
   - Actions: create, read, update, delete, list, reset_password
   - Permission validation before execution

4. **check_billing**
   - Lago API integration for subscription data
   - Stripe API for payment information
   - Query types: current_plan, usage, invoices, payment_methods
   - Usage analytics and trending

5. **restart_service**
   - Docker container lifecycle management
   - Actions: restart, stop, start, status
   - Service whitelist for security
   - Confirmation required for destructive actions
   - Rollback capability

6. **query_logs**
   - Docker logs API integration
   - Full-text search across service logs
   - Time range filtering
   - Log level filtering (DEBUG, INFO, WARN, ERROR, CRITICAL)
   - Pattern matching and highlighting

**Tool Interface**:
```typescript
interface Tool {
  name: string;
  description: string;
  parameters: {
    type: "object";
    properties: Record<string, ParameterDefinition>;
    required: string[];
  };
  handler: (params: any, context: Context) => Promise<ToolResult>;
  validation: (params: any) => ValidationResult;
  permissions: Permission[];
}

interface ToolResult {
  success: boolean;
  data?: any;
  error?: string;
  metadata?: {
    executionTime: number;
    toolVersion: string;
    timestamp: string;
  };
}
```

#### 3. Context Layer

**Location**: Redis-backed session storage

**Context Sources**:
- **Current Page**: Detected from Ops-Center frontend router
- **User Session**: Keycloak authentication context
- **Recent Actions**: Last 10 user actions in current session
- **Entity Context**: Relevant IDs (user_id, org_id, service_id)

**Context Structure**:
```typescript
interface GeesesContext {
  sessionId: string;
  user: {
    id: string;
    email: string;
    roles: string[];
    organization: string;
  };
  page: {
    path: string;
    name: string;
    entity?: {
      type: string;
      id: string;
    };
  };
  recentActions: Action[];
  timestamp: string;
}
```

**Session Management**:
- Storage: Redis with 1-hour TTL
- Max history: 50 messages per session
- Automatic cleanup on session end
- Cross-tab synchronization

#### 4. Chat Interface

**Location**: `/services/ops-center/frontend/src/components/Geeses/`

**Components**:

1. **GeesesWidget** (Main container)
   - Collapsible widget positioned bottom-right
   - Minimized state with notification badge
   - Z-index management for overlays
   - Drag-to-reposition (future enhancement)

2. **GeesesChat** (Chat container)
   - Message history display
   - Typing indicators
   - Auto-scroll to latest message
   - Message grouping by time
   - Markdown rendering

3. **ChatMessage** (Individual message)
   - User messages (right-aligned, purple)
   - Geeses responses (left-aligned, blue)
   - Timestamp display
   - Tool usage indicators
   - Copy-to-clipboard functionality

4. **ChatInput** (User input)
   - Multi-line text input
   - Submit on Enter (Shift+Enter for newline)
   - Quick action buttons
   - Voice input (future enhancement)
   - Attachment support (future enhancement)

5. **useBrigadeAPI** (API integration hook)
   - POST /api/agents/:id/chat for message sending
   - WebSocket for real-time responses
   - Session persistence
   - Error handling and retries
   - Loading states

**Integration Pattern**:
```typescript
// Ops-Center → Brigade → Geeses → Tools → Ops-Center API
const sendMessage = async (message: string) => {
  const context = getCurrentPageContext();

  const response = await fetch(
    `https://api.brigade.unicorncommander.ai/api/agents/${GEESES_ID}/chat`,
    {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${keycloakToken}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        message,
        context,
        sessionId: getSessionId()
      })
    }
  );

  return await response.json();
};
```

### 5. A2A Protocol Integration

**Agent Card** (GET /api/agents/geeses/card):
```json
{
  "id": "geeses",
  "name": "Navigator Geeses",
  "version": "1.0.0",
  "capabilities": [
    "ops_center_management",
    "service_monitoring",
    "user_administration",
    "billing_operations"
  ],
  "endpoints": {
    "invoke": "https://api.brigade.unicorncommander.ai/api/agents/geeses/invoke",
    "chat": "https://api.brigade.unicorncommander.ai/api/agents/geeses/chat"
  },
  "inputFormats": ["text/plain", "application/json"],
  "outputFormats": ["text/plain", "application/json", "text/markdown"]
}
```

**Invocation** (POST /api/agents/geeses/invoke):
```json
{
  "message": "What's the status of Open-WebUI?",
  "context": {
    "user_id": "uuid-123",
    "page": "services_dashboard"
  },
  "mode": "synchronous"
}
```

## Integration Architecture

### Integration Points

```
┌─────────────────────────────────────────────────────────────┐
│                    Geeses Agent (Brigade)                     │
└─────────────────────────────────────────────────────────────┘
         │                │               │              │
         │                │               │              │
    ┌────▼─────┐    ┌────▼────┐    ┌────▼────┐   ┌────▼────┐
    │ Ops-     │    │ Brigade │    │Keycloak │   │  Docker │
    │ Center   │    │   API   │    │   SSO   │   │   API   │
    │   API    │    │         │    │         │   │         │
    └────┬─────┘    └─────────┘    └────┬────┘   └─────────┘
         │                                │
    ┌────▼──────────────────────────┐────▼────┐
    │  PostgreSQL                   │  Redis  │
    │  - ops_center_db              │         │
    │  - brigade_db                 │         │
    └───────────────────────────────┴─────────┘
```

### Network Architecture

**Container Networks**:
- `unicorn-network` - Primary service mesh
- `web` - Traefik reverse proxy
- `uchub-network` - Keycloak integration

**Service Discovery**:
- Internal DNS via Docker
- Service aliases for failover
- Health check endpoints

## Data Flow

### Message Flow

1. **User sends message** in Ops-Center chat interface
2. **Frontend collects context** (current page, user info)
3. **Request sent to Brigade API** with message + context
4. **Brigade routes to Geeses agent**
5. **Geeses processes message**:
   - Analyzes intent
   - Selects appropriate tools
   - Executes tool calls
   - Aggregates results
6. **Geeses generates response** with structured data
7. **Response returned to frontend** via Brigade API
8. **Frontend renders response** with formatting

### Tool Execution Flow

1. **Geeses selects tool** based on user intent
2. **Tool handler invoked** with parameters
3. **Tool validates permissions** for current user
4. **Tool executes operation**:
   - API call to Ops-Center
   - Docker command
   - Database query
   - External service call
5. **Tool returns structured result**
6. **Geeses incorporates into response**

## Security Architecture

### Authentication & Authorization

**Multi-Layer Security**:
1. **Keycloak SSO** - User authentication
2. **Brigade API Keys** - Service authentication
3. **Tool-Level Permissions** - Operation authorization
4. **Audit Logging** - All actions tracked

**Permission Model**:
```typescript
enum Permission {
  READ_SYSTEM_STATUS,
  READ_USER_DATA,
  WRITE_USER_DATA,
  READ_BILLING,
  WRITE_BILLING,
  RESTART_SERVICES,
  READ_LOGS,
  ADMIN_ACCESS
}

interface ToolPermissions {
  requiredRoles: string[];
  requiredPermissions: Permission[];
  allowedUsers?: string[];
  blockedUsers?: string[];
}
```

### Data Protection

- **In-Transit**: HTTPS/TLS for all external communication
- **At-Rest**: Encrypted session storage in Redis
- **Sensitive Data**: Never log API keys, passwords, or tokens
- **PII Protection**: Mask sensitive user data in logs

### Rate Limiting

```typescript
interface RateLimit {
  tool: string;
  maxRequestsPerMinute: number;
  maxRequestsPerHour: number;
  maxRequestsPerDay: number;
  burstAllowance: number;
}

const rateLimits: RateLimit[] = [
  { tool: 'restart_service', maxRequestsPerMinute: 5, ... },
  { tool: 'manage_user', maxRequestsPerMinute: 10, ... },
  { tool: 'query_logs', maxRequestsPerMinute: 20, ... }
];
```

## Performance Requirements

### Response Time Targets

| Operation | Target | Maximum |
|-----------|--------|---------|
| Simple query (status check) | < 500ms | 1s |
| Complex query (log search) | < 2s | 5s |
| User management | < 1s | 3s |
| Service restart | < 5s | 15s |
| Billing query | < 1s | 3s |

### Scalability

- **Concurrent Users**: 100+ simultaneous chat sessions
- **Message Throughput**: 1000+ messages/minute
- **Tool Execution**: 500+ tool calls/minute
- **Session Storage**: 10,000+ active sessions in Redis

### Resource Utilization

- **Memory**: < 512MB per Geeses instance
- **CPU**: < 2 cores per Geeses instance
- **Network**: < 10MB/s bandwidth
- **Storage**: Minimal (sessions in Redis)

## Deployment Architecture

### Deployment Flow

```bash
# 1. Build Geeses agent definition
cd /home/muut/Production/UC-Cloud/services/ops-center/geeses

# 2. Deploy tools to Ops-Center
npm run build:tools
docker cp tools/ ops-center-direct:/app/geeses/tools/

# 3. Register agent in Brigade
curl -X POST https://api.brigade.unicorncommander.ai/api/agents \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d @architecture/geeses-agent.json

# 4. Integrate chat interface
npm run build:chat
docker cp chat/dist/ ops-center-direct:/app/frontend/src/components/Geeses/

# 5. Restart Ops-Center
docker restart ops-center-direct

# 6. Verify deployment
curl https://api.brigade.unicorncommander.ai/api/agents/geeses/card
```

### Configuration Management

**Environment Variables**:
```env
GEESES_AGENT_ID=uuid-geeses-agent
GEESES_API_KEY=secret-key-geeses
BRIGADE_API_URL=https://api.brigade.unicorncommander.ai
OPS_CENTER_API_URL=http://ops-center-direct:8084
KEYCLOAK_URL=http://uchub-keycloak:8080
KEYCLOAK_REALM=uchub
REDIS_URL=redis://unicorn-redis:6379
DOCKER_SOCKET=/var/run/docker.sock
```

### Health Checks

```typescript
interface HealthCheck {
  status: 'healthy' | 'degraded' | 'unhealthy';
  checks: {
    brigade_connectivity: boolean;
    ops_center_api: boolean;
    keycloak_auth: boolean;
    redis_cache: boolean;
    docker_socket: boolean;
  };
  uptime: number;
  lastHealthy: string;
}
```

## Monitoring & Observability

### Metrics

- **Message Metrics**: Volume, latency, success rate
- **Tool Metrics**: Usage per tool, execution time, error rate
- **User Metrics**: Active sessions, messages per user, engagement
- **System Metrics**: CPU, memory, network I/O

### Logging

```typescript
interface GeesesLog {
  timestamp: string;
  level: 'debug' | 'info' | 'warn' | 'error';
  component: 'agent' | 'tool' | 'chat' | 'integration';
  message: string;
  context: {
    sessionId?: string;
    userId?: string;
    toolName?: string;
    duration?: number;
  };
  metadata?: Record<string, any>;
}
```

### Alerting

- **Critical**: Tool execution failures, authentication errors
- **Warning**: High latency, rate limit approaching
- **Info**: Unusual usage patterns, new feature adoption

## Testing Strategy

### Unit Tests
- Tool handlers (100% coverage target)
- Input validation
- Error handling
- Permission checks

### Integration Tests
- Brigade API integration
- Ops-Center API calls
- Keycloak authentication
- Redis session management

### End-to-End Tests
- Complete user workflows
- Multi-turn conversations
- Tool orchestration
- Error recovery

### Performance Tests
- Load testing (100 concurrent users)
- Stress testing (1000 messages/minute)
- Endurance testing (24-hour sustained load)

## Future Enhancements

### Phase 2 (Q1 2026)
- Voice input/output integration
- Proactive notifications
- Predictive analytics
- Automated troubleshooting

### Phase 3 (Q2 2026)
- Multi-language support
- Custom tool creation by users
- Agent-to-agent collaboration
- Mobile app integration

### Phase 4 (Q3 2026)
- ML-based intent recognition
- Personalized recommendations
- Advanced analytics dashboard
- Integration marketplace

## References

- [Brigade API Documentation](https://brigade.unicorncommander.ai/docs/api)
- [Ops-Center API Reference](/services/ops-center/docs/API_REFERENCE.md)
- [A2A Protocol Specification](https://a2a.dev/)
- [UC-Cloud Architecture](/CLAUDE.md)
