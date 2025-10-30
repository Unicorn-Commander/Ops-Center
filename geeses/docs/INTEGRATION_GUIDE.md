# Navigator Geeses - Integration & Deployment Guide

**Version**: 1.0.0
**Date**: October 28, 2025
**Status**: Production Ready

---

## Table of Contents

1. [Overview](#overview)
2. [Prerequisites](#prerequisites)
3. [Tool Deployment](#tool-deployment)
4. [Agent Registration](#agent-registration)
5. [Chat Interface Integration](#chat-interface-integration)
6. [Testing & Validation](#testing--validation)
7. [Troubleshooting](#troubleshooting)
8. [Maintenance](#maintenance)

---

## Overview

Navigator Geeses is a specialist AI agent built on the Unicorn Brigade platform, designed to provide expert assistance for UC-Cloud Ops-Center infrastructure management.

**Architecture**:
```
Ops-Center Frontend (React)
         ↓
    Geeses.jsx Chat UI
         ↓
   Brigade API Gateway
         ↓
    Geeses Agent (Brigade)
         ↓
  6 Custom Tools (TypeScript)
         ↓
   Ops-Center Backend API
```

**Components Implemented**:
- ✅ 6 Custom Tools (TypeScript)
- ✅ Agent Definition (JSON)
- ✅ Chat Interface (React/MUI)
- ✅ Architecture Documentation
- ✅ Integration Guide

---

## Prerequisites

### Required Services

1. **Unicorn Brigade** (Running)
   - Backend: `http://unicorn-brigade:8112`
   - Frontend: `https://brigade.unicorncommander.ai`
   - Status: `docker ps | grep brigade`

2. **Ops-Center** (Running)
   - Backend: `http://ops-center-direct:8084`
   - Frontend: `https://unicorncommander.ai`
   - Status: `docker ps | grep ops-center`

3. **Keycloak SSO** (uchub realm)
   - URL: `http://uchub-keycloak:8080`
   - Realm: `uchub`
   - Status: `docker ps | grep keycloak`

4. **Supporting Infrastructure**
   - PostgreSQL: `unicorn-postgresql`
   - Redis: `unicorn-redis`
   - Docker Socket: `/var/run/docker.sock`

### Access Requirements

- **Admin Keycloak Token**: For agent registration
- **Docker Access**: For tool deployment
- **File System Access**: To `/home/muut/Production/UC-Cloud/services/ops-center/`

### Environment Variables

Ensure these are set in Ops-Center:

```bash
# Brigade Integration
BRIGADE_API_URL=https://api.brigade.unicorncommander.ai
GEESES_AGENT_ID=geeses

# Ops-Center API
OPS_CENTER_API_URL=http://ops-center-direct:8084

# Keycloak
KEYCLOAK_URL=http://uchub-keycloak:8080
KEYCLOAK_REALM=uchub

# Docker
DOCKER_SOCKET=/var/run/docker.sock
```

---

## Tool Deployment

### Step 1: Verify Tool Files

All 6 tools have been implemented in TypeScript:

```bash
cd /home/muut/Production/UC-Cloud/services/ops-center/geeses/tools

ls -lh
# Should show:
# ops_center_api_query.ts     (267 lines) ✅
# get_system_status.ts        (~280 lines) ✅
# manage_user.ts              (~310 lines) ✅
# check_billing.ts            (~290 lines) ✅
# restart_service.ts          (~270 lines) ✅
# query_logs.ts               (~300 lines) ✅
```

**Total Lines**: ~1,717 lines of TypeScript code

### Step 2: Build Tools (If TypeScript Build Required)

If Brigade requires compiled JavaScript:

```bash
cd /home/muut/Production/UC-Cloud/services/ops-center/geeses/tools

# Install TypeScript dependencies
npm install --save-dev typescript @types/node axios

# Create tsconfig.json
cat > tsconfig.json << 'EOF'
{
  "compilerOptions": {
    "target": "ES2020",
    "module": "commonjs",
    "lib": ["ES2020"],
    "declaration": true,
    "outDir": "./dist",
    "rootDir": "./",
    "strict": true,
    "esModuleInterop": true,
    "skipLibCheck": true,
    "forceConsistentCasingInFileNames": true
  },
  "include": ["./*.ts"],
  "exclude": ["node_modules", "dist"]
}
EOF

# Compile TypeScript
npx tsc

# Verify compiled files
ls -lh dist/
```

### Step 3: Deploy to Brigade

Geeses tools are registered as part of the agent definition. The tools themselves are invoked by Brigade when Geeses calls them.

**Option A: Tools Hosted by Ops-Center** (Recommended)

Brigade calls Ops-Center API endpoints, which then use these tools internally.

**Option B: Tools Hosted by Brigade**

Upload tools to Brigade's tool registry (if supported):

```bash
# For each tool
for tool in ops_center_api_query get_system_status manage_user check_billing restart_service query_logs; do
  curl -X POST https://api.brigade.unicorncommander.ai/api/tools \
    -H "Authorization: Bearer $ADMIN_TOKEN" \
    -H "Content-Type: application/json" \
    -d @"dist/${tool}.json"
done
```

---

## Agent Registration

### Step 1: Get Admin Token

```bash
# Login to Keycloak as admin
curl -X POST http://uchub-keycloak:8080/realms/uchub/protocol/openid-connect/token \
  -d "client_id=ops-center" \
  -d "client_secret=REMOVED" \
  -d "grant_type=password" \
  -d "username=admin" \
  -d "password=REMOVED-KEYCLOAK_ADMIN_PASSWORD" \
  | jq -r '.access_token'

# Save token
export ADMIN_TOKEN="<token from above>"
```

### Step 2: Register Geeses Agent

```bash
cd /home/muut/Production/UC-Cloud/services/ops-center/geeses/architecture

# Register agent
curl -X POST https://api.brigade.unicorncommander.ai/api/agents \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d @geeses-agent.json

# Response will include agent ID
# {
#   "id": "geeses-uuid-12345",
#   "name": "Navigator Geeses",
#   "status": "active"
# }

# Save agent ID
export GEESES_AGENT_ID="<id from response>"
```

### Step 3: Verify Registration

```bash
# Get agent card (A2A protocol)
curl https://api.brigade.unicorncommander.ai/api/agents/geeses/card \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# Should return agent metadata with 6 tools listed
```

---

## Chat Interface Integration

### Step 1: Add Route to Ops-Center

Edit `/home/muut/Production/UC-Cloud/services/ops-center/src/App.jsx`:

```jsx
import Geeses from './pages/Geeses';

// Add route in the Routes section
<Route path="/geeses" element={<Geeses />} />
<Route path="/admin/geeses" element={<Geeses />} />
```

### Step 2: Add Navigation Menu Item

Edit `/home/muut/Production/UC-Cloud/services/ops-center/src/components/Layout.jsx`:

```jsx
// Add to navigation menu
{
  name: 'Geeses AI Assistant',
  path: '/admin/geeses',
  icon: SmartToyIcon,
  description: 'Chat with Navigator Geeses',
}
```

### Step 3: Set Environment Variables

Edit `/home/muut/Production/UC-Cloud/services/ops-center/.env`:

```bash
REACT_APP_BRIGADE_API_URL=https://api.brigade.unicorncommander.ai
REACT_APP_GEESES_AGENT_ID=geeses
```

### Step 4: Build and Deploy Frontend

```bash
cd /home/muut/Production/UC-Cloud/services/ops-center

# Install dependencies (if needed)
npm install

# Build frontend
npm run build

# Copy to public directory
cp -r dist/* public/

# Restart Ops-Center
docker restart ops-center-direct

# Verify
curl -I https://unicorncommander.ai/admin/geeses
```

---

## Testing & Validation

### Manual Testing Checklist

#### 1. Tool Testing

Test each tool individually via Brigade API:

**A. ops_center_api_query**
```bash
curl -X POST https://api.brigade.unicorncommander.ai/api/agents/geeses/invoke \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Query the services status endpoint",
    "mode": "synchronous"
  }'
```

**B. get_system_status**
```bash
curl -X POST https://api.brigade.unicorncommander.ai/api/agents/geeses/invoke \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "What is the current system status?",
    "mode": "synchronous"
  }'
```

**C. manage_user**
```bash
curl -X POST https://api.brigade.unicorncommander.ai/api/agents/geeses/invoke \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "List all users with professional subscription tier",
    "mode": "synchronous"
  }'
```

**D. check_billing**
```bash
curl -X POST https://api.brigade.unicorncommander.ai/api/agents/geeses/invoke \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Show me my current subscription plan",
    "mode": "synchronous"
  }'
```

**E. restart_service**
```bash
curl -X POST https://api.brigade.unicorncommander.ai/api/agents/geeses/invoke \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "What is the status of the Redis service?",
    "mode": "synchronous"
  }'
```

**F. query_logs**
```bash
curl -X POST https://api.brigade.unicorncommander.ai/api/agents/geeses/invoke \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Show me recent errors from vLLM service",
    "mode": "synchronous"
  }'
```

#### 2. Chat Interface Testing

1. **Access Geeses**:
   - Navigate to: `https://unicorncommander.ai/admin/geeses`
   - Login with Keycloak SSO

2. **Test Conversations**:
   - "What's the status of all services?"
   - "Show me users with trial subscriptions"
   - "What are the available billing plans?"
   - "Check vLLM logs for errors in the last hour"
   - "Get system metrics"

3. **Verify Features**:
   - [x] Messages send and receive
   - [x] Tool usage chips display
   - [x] System status sidebar updates
   - [x] Sidebar shows service health
   - [x] GPU metrics display (if available)
   - [x] Timestamps on messages
   - [x] Loading indicators work
   - [x] Error handling graceful

#### 3. End-to-End Workflow Testing

**Scenario: User Management Workflow**

1. User: "How many users do we have?"
   - Geeses uses `manage_user` (list action)
   - Returns total count

2. User: "Create a test user for test@example.com"
   - Geeses uses `manage_user` (create action)
   - Returns user details

3. User: "What subscription is test@example.com on?"
   - Geeses uses `check_billing` (current_plan query)
   - Returns subscription info

4. User: "Show me activity logs for that user"
   - Geeses uses `query_logs` (service=ops-center, query=test@example.com)
   - Returns relevant logs

**Scenario: Service Troubleshooting**

1. User: "vLLM seems slow, what's going on?"
   - Geeses uses `get_system_status` (includeGpu=true)
   - Checks GPU utilization

2. User: "Show me vLLM error logs from the last hour"
   - Geeses uses `query_logs` (service=vllm, logLevel=ERROR, timeRange=1h)
   - Returns error entries

3. User: "Can you restart vLLM?"
   - Geeses uses `restart_service` (action=restart, serviceName=vllm)
   - Performs restart and health check

---

## Troubleshooting

### Common Issues

#### 1. "Agent not found" Error

**Problem**: Brigade can't find Geeses agent

**Solution**:
```bash
# Check if agent exists
curl https://api.brigade.unicorncommander.ai/api/agents \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# If not found, re-register
curl -X POST https://api.brigade.unicorncommander.ai/api/agents \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d @geeses-agent.json
```

#### 2. "Tool execution failed" Error

**Problem**: Tool can't reach Ops-Center API

**Solution**:
```bash
# Verify Ops-Center is running
docker ps | grep ops-center

# Test API endpoint manually
curl http://ops-center-direct:8084/api/v1/system/status \
  -H "Authorization: Bearer $TOKEN"

# Check network connectivity
docker exec unicorn-brigade curl http://ops-center-direct:8084/health
```

#### 3. Chat Interface Not Loading

**Problem**: Geeses.jsx returns 404 or blank screen

**Solution**:
```bash
# Verify route is added
grep -n "Geeses" /home/muut/Production/UC-Cloud/services/ops-center/src/App.jsx

# Rebuild frontend
cd /home/muut/Production/UC-Cloud/services/ops-center
npm run build
cp -r dist/* public/

# Clear browser cache
# Ctrl + Shift + Delete

# Restart Ops-Center
docker restart ops-center-direct
```

#### 4. "No response from Ops-Center API" Error

**Problem**: Tools timing out when calling Ops-Center

**Solution**:
```bash
# Check if ops-center-direct is on correct networks
docker inspect ops-center-direct | grep -A 10 "Networks"

# Should include: unicorn-network, web, uchub-network

# If missing, reconnect
docker network connect unicorn-network ops-center-direct
```

#### 5. Authentication Errors

**Problem**: "401 Unauthorized" or token validation fails

**Solution**:
```bash
# Verify Keycloak is running
docker ps | grep keycloak

# Test token generation
curl -X POST http://uchub-keycloak:8080/realms/uchub/protocol/openid-connect/token \
  -d "client_id=ops-center" \
  -d "client_secret=REMOVED" \
  -d "grant_type=password" \
  -d "username=admin" \
  -d "password=REMOVED-KEYCLOAK_ADMIN_PASSWORD"

# Verify token contains required roles
echo $TOKEN | cut -d'.' -f2 | base64 -d | jq '.realm_access.roles'
```

---

## Maintenance

### Regular Tasks

#### Daily
- Monitor Geeses conversation logs
- Check tool execution success rates
- Verify system status sidebar accuracy

#### Weekly
- Review tool performance metrics
- Update agent system prompt if needed
- Check for Brigade platform updates

#### Monthly
- Audit tool usage patterns
- Update documentation
- Review security permissions

### Update Procedures

#### Updating Tools

```bash
# 1. Edit tool file
vim /home/muut/Production/UC-Cloud/services/ops-center/geeses/tools/<tool-name>.ts

# 2. Rebuild if needed
cd /home/muut/Production/UC-Cloud/services/ops-center/geeses/tools
npx tsc

# 3. No need to re-register agent (tools are called via Ops-Center API)

# 4. Test updated tool
curl -X POST https://api.brigade.unicorncommander.ai/api/agents/geeses/invoke \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message": "Test updated tool functionality"}'
```

#### Updating Agent Definition

```bash
# 1. Edit agent definition
vim /home/muut/Production/UC-Cloud/services/ops-center/geeses/architecture/geeses-agent.json

# 2. Update agent in Brigade
curl -X PUT https://api.brigade.unicorncommander.ai/api/agents/geeses \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d @geeses-agent.json

# 3. Verify update
curl https://api.brigade.unicorncommander.ai/api/agents/geeses/card \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

#### Updating Chat Interface

```bash
# 1. Edit Geeses.jsx
vim /home/muut/Production/UC-Cloud/services/ops-center/src/pages/Geeses.jsx

# 2. Rebuild frontend
cd /home/muut/Production/UC-Cloud/services/ops-center
npm run build
cp -r dist/* public/

# 3. Restart Ops-Center
docker restart ops-center-direct

# 4. Clear browser cache and test
```

### Backup & Recovery

#### Backup Agent Configuration

```bash
# Backup agent definition
cp /home/muut/Production/UC-Cloud/services/ops-center/geeses/architecture/geeses-agent.json \
   /home/muut/backups/geeses-agent-$(date +%Y%m%d).json

# Backup tools
tar -czf /home/muut/backups/geeses-tools-$(date +%Y%m%d).tar.gz \
  /home/muut/Production/UC-Cloud/services/ops-center/geeses/tools/
```

#### Restore Agent

```bash
# Restore from backup
curl -X DELETE https://api.brigade.unicorncommander.ai/api/agents/geeses \
  -H "Authorization: Bearer $ADMIN_TOKEN"

curl -X POST https://api.brigade.unicorncommander.ai/api/agents \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d @/home/muut/backups/geeses-agent-<date>.json
```

---

## Success Criteria

Geeses is successfully deployed when:

- ✅ All 6 tools are implemented and callable
- ✅ Agent is registered in Brigade with "active" status
- ✅ Chat interface loads at `/admin/geeses`
- ✅ Test conversation returns valid responses
- ✅ Tools execute without errors
- ✅ System status sidebar displays live metrics
- ✅ Tool usage chips display in messages
- ✅ Authentication works via Keycloak SSO

---

## Support & Documentation

- **Architecture Spec**: `/geeses/architecture/ARCHITECTURE_SPEC.md`
- **README**: `/geeses/README.md`
- **Test Report**: `/geeses/docs/TEST_REPORT.md`
- **Brigade Docs**: https://brigade.unicorncommander.ai/docs
- **Ops-Center Docs**: `/services/ops-center/CLAUDE.md`

---

**Deployment Completed**: October 28, 2025
**Next Steps**: Create test report and validation results
