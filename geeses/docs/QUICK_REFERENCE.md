# Navigator Geeses - Quick Reference Guide

**Version**: 1.0.0
**Last Updated**: October 28, 2025

---

## What is Geeses?

Navigator "Geeses" is an AI assistant for UC-Cloud Ops-Center that helps you manage infrastructure through natural language conversations.

**Think of Geeses like**: Asking a senior DevOps engineer questions instead of navigating complex UIs or running CLI commands.

---

## Quick Start

### 1. Access Geeses

Navigate to: **https://unicorncommander.ai/admin/geeses**

Or click **"Geeses AI Assistant"** in the Ops-Center navigation menu.

### 2. Login

Authenticate with Keycloak SSO (Google, GitHub, Microsoft, or email/password).

### 3. Start Chatting

Type your question or command in the input field at the bottom. Press **Enter** to send (or **Shift+Enter** for a new line).

---

## Common Use Cases

### System Health Checks

**Questions to Ask**:
- "What's the status of all services?"
- "Show me GPU utilization"
- "Are there any unhealthy services?"
- "What's the CPU and memory usage?"

**Geeses Uses**: `get_system_status` tool

### User Management

**Questions to Ask**:
- "How many users do we have?"
- "Show me users on Professional plan"
- "Create a user for email@example.com"
- "What roles does user@example.com have?"
- "Reset password for user@example.com"

**Geeses Uses**: `manage_user` tool

### Billing & Subscriptions

**Questions to Ask**:
- "What subscription plans are available?"
- "What plan am I on?"
- "Show me my invoices"
- "How many API calls have I used?"
- "When is my next billing date?"

**Geeses Uses**: `check_billing` tool

### Service Management

**Questions to Ask**:
- "Restart the vLLM service"
- "What's the status of Redis?"
- "Stop the embeddings service"
- "Start Open-WebUI"

**Geeses Uses**: `restart_service` tool

### Log Analysis

**Questions to Ask**:
- "Show me recent errors from vLLM"
- "Are there any CUDA errors in the last hour?"
- "Search logs for 'out of memory'"
- "Get PostgreSQL logs from yesterday"

**Geeses Uses**: `query_logs` tool

### API Queries

**Questions to Ask**:
- "Query the services endpoint"
- "Get user details for user ID 12345"
- "Update service configuration"
- "Check the health endpoint"

**Geeses Uses**: `ops_center_api_query` tool

---

## Geeses Capabilities

### What Geeses Can Do ✅

- ✅ **Monitor Services**: Check status, health, uptime of all UC-Cloud services
- ✅ **Manage Users**: Create, update, delete users; assign roles; reset passwords
- ✅ **Check Billing**: View subscriptions, invoices, usage, payment methods
- ✅ **Manage Services**: Restart, stop, start Docker containers
- ✅ **Analyze Logs**: Search logs by service, time, level, pattern
- ✅ **Query APIs**: Direct access to any Ops-Center API endpoint

### What Geeses Cannot Do ❌

- ❌ **Direct Database Edits**: No direct SQL execution (security)
- ❌ **Server Shell Access**: No SSH or bash commands
- ❌ **Code Deployment**: Can't deploy new code or modify configuration files
- ❌ **External Services**: Can't manage services outside UC-Cloud
- ❌ **Financial Transactions**: Can't process payments or issue refunds

---

## Understanding Geeses Responses

### Message Format

Geeses messages include:
1. **Text Response**: Human-readable answer
2. **Tool Chips**: Shows which tools were used
3. **Timestamp**: When the response was generated

**Example**:
```
Geeses: "Open-WebUI is operational:
- Status: Running
- Uptime: 3 days, 14 hours
- Health: Healthy
- Memory: 2.1GB / 4GB
- CPU: 12%"

[get_system_status]  [Tool chip]
3:45 PM  [Timestamp]
```

### Tool Execution Indicators

When Geeses is working on your request, you'll see:
- **Loading spinner**: Geeses is processing
- **Tool chips**: After response, shows which tools were used

### Error Messages

If something goes wrong, Geeses will:
- Explain what failed
- Suggest alternatives
- Provide troubleshooting steps

**Example**:
```
Geeses: "Communication error: Service vllm not found.
Available services: vllm, open-webui, redis, postgresql.
Did you mean 'vllm'?"
```

---

## System Status Sidebar

The right sidebar shows **real-time system metrics**:

### System Metrics Card
- **CPU Usage**: Current CPU utilization (%)
- **Memory Usage**: RAM usage (%)
- **Disk Usage**: Storage usage (%)

### GPU Status Card (if available)
- **GPU Name**: NVIDIA RTX 5090 (or other)
- **Utilization**: GPU usage (%)
- **Memory**: VRAM used / total
- **Temperature**: GPU temperature (°C)

### Services Card
- **Service List**: Up to 8 services with status
- **Status Indicator**: Green (running) or Red (stopped)
- **Health Badge**: healthy, unhealthy, starting, unknown

**Refresh**: Click the refresh icon to update metrics.

---

## Tips & Best Practices

### Writing Effective Queries

**Good Queries** ✅:
- "Show me vLLM errors from the last hour"
- "Restart the Open-WebUI service"
- "List users with Professional subscription"

**Vague Queries** ⚠️:
- "Fix the thing" (What thing?)
- "Check logs" (Which service? What time range?)
- "User problems" (What kind of problems?)

**Be Specific**:
- Mention **service names** explicitly
- Include **time ranges** for logs/metrics
- Specify **user emails** or IDs

### Multi-Step Workflows

Geeses remembers context within a conversation:

```
You: "What's the status of vLLM?"
Geeses: [Shows status]

You: "Show me its error logs"
Geeses: [Knows you mean vLLM logs]

You: "Restart it"
Geeses: [Knows to restart vLLM]
```

### Security & Permissions

Geeses respects your **Keycloak roles**:

| Role | Can Do |
|------|--------|
| **Admin** | Everything (all tools) |
| **Moderator** | User management, read-only services |
| **Developer** | Read services, query logs |
| **Analyst** | Read billing, view metrics |
| **Viewer** | Read-only access |

If Geeses says "Insufficient permissions", check with your admin.

---

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| **Enter** | Send message |
| **Shift + Enter** | New line in message |
| **Esc** | Clear input field |

---

## Troubleshooting

### "Communication error" Messages

**Problem**: Geeses can't reach Brigade API

**Solutions**:
1. Check internet connection
2. Verify you're logged in (Keycloak)
3. Refresh the page
4. Contact admin if persists

### "No response from Ops-Center API"

**Problem**: Ops-Center backend is down

**Solutions**:
1. Check if other Ops-Center pages load
2. Wait a few minutes and retry
3. Contact admin

### Sidebar Not Updating

**Problem**: System status stuck

**Solutions**:
1. Click the refresh icon
2. Refresh the browser page
3. Check browser console for errors

### Chat Not Sending

**Problem**: Input disabled or grayed out

**Solutions**:
1. Check if Geeses is still processing (loading spinner)
2. Ensure message field isn't empty
3. Verify authentication (re-login if needed)

---

## Example Conversations

### Example 1: Service Health Check

```
You: What's the status of all services?

Geeses: Roger that, checking system status...

I've checked all 20 UC-Cloud services. Here's the summary:

HEALTHY SERVICES (18):
✅ ops-center - Running (uptime: 7d 3h)
✅ open-webui - Running (uptime: 7d 3h)
✅ vllm - Running (uptime: 7d 2h)
✅ redis - Running (uptime: 7d 3h)
✅ postgresql - Running (uptime: 7d 3h)
... (13 more)

UNHEALTHY SERVICES (2):
⚠️ embeddings - Restarting (health: starting)
⚠️ reranker - Stopped (last seen: 2h ago)

Would you like me to restart the unhealthy services?

[get_system_status]
```

### Example 2: User Troubleshooting

```
You: Show me users who signed up today

Geeses: Roger that, querying users...

Found 5 users who registered today (Oct 28, 2025):

1. alice@example.com - Trial plan - Joined 09:15 AM
2. bob@startup.com - Starter plan - Joined 10:42 AM
3. carol@company.com - Professional plan - Joined 11:23 AM
4. dave@tech.io - Trial plan - Joined 01:05 PM
5. eve@design.co - Trial plan - Joined 02:38 PM

Would you like details on any specific user?

[manage_user]

You: What's carol@company.com's usage?

Geeses: Roger that, checking subscription and usage...

carol@company.com (Professional Plan):
- Plan: Professional ($49/month)
- Started: Oct 28, 2025 (today!)
- API Calls: 47 / 10,000 (0.5% used)
- Next Billing: Nov 28, 2025
- Status: Active

Very light usage so far - just getting started!

[check_billing]
```

### Example 3: Service Restart Workflow

```
You: vLLM seems slow

Geeses: Roger that, checking vLLM status...

vLLM service is running but GPU utilization is very high:
- Status: Running
- GPU: 98% utilization
- VRAM: 30.5GB / 32GB (95%)
- Uptime: 2d 7h

This could explain the slowness. Would you like me to:
1. Restart vLLM to clear GPU memory?
2. Check vLLM logs for errors?
3. Both?

[get_system_status]

You: Show me error logs first

Geeses: Roger that, searching vLLM logs for errors...

Found 2 error events in the last 24 hours:

1. [12:34:56] CUDA OOM Error
   "Attempted to allocate 2GB, only 512MB available"
   → Auto-recovered via memory cleanup

2. [13:15:22] Model loading timeout
   "Qwen2.5 took 45s to load (timeout: 30s)"
   → Timeout increased, loaded successfully

Both errors were auto-resolved, but indicate memory pressure.
I recommend restarting vLLM to clear fragmented memory.

[query_logs]

You: Restart vLLM

Geeses: Roger that, restarting vLLM service...

⚠️ vLLM is a critical service. This will briefly interrupt
LLM inference. Proceeding with restart...

vLLM service restarted successfully:
- Previous status: Running (2d 7h uptime)
- Current status: Running (12s uptime)
- Health: Healthy ✅
- GPU: 35% utilization (down from 98%)
- VRAM: 12.3GB / 32GB (cleared 18GB!)

Restart successful. GPU memory pressure resolved.

[restart_service]
```

---

## Advanced Features

### Context Awareness

Geeses knows:
- **Current page**: Automatically scopes queries to relevant services
- **Recent actions**: References previous messages in conversation
- **User info**: Your roles, permissions, subscription

### Tool Orchestration

Geeses can use **multiple tools in sequence**:

```
You: "Create a user for test@example.com and assign them the admin role"

Geeses:
1. Creates user → [manage_user (create)]
2. Assigns admin role → [manage_user (assign_role)]

Both steps completed!
```

### Error Recovery

If a tool fails, Geeses will:
- Explain what went wrong
- Suggest alternative approaches
- Offer to retry with different parameters

---

## Getting Help

### Within Geeses

Ask Geeses for help:
- "What can you do?"
- "How do I check service status?"
- "Show me examples"

### Documentation

- **Full Guide**: `/geeses/docs/INTEGRATION_GUIDE.md`
- **Test Report**: `/geeses/docs/TEST_REPORT.md`
- **Architecture**: `/geeses/architecture/ARCHITECTURE_SPEC.md`

### Support

- **Ops-Center Docs**: `https://unicorncommander.ai/docs`
- **GitHub Issues**: `https://github.com/Unicorn-Commander/UC-Cloud/issues`
- **Admin Contact**: Check Ops-Center settings

---

## Feedback

Geeses is constantly improving! Share your experience:

**What's Working Well**:
- Which features you use most
- Queries that return exactly what you need
- Time saved vs manual operations

**What Needs Improvement**:
- Unclear responses
- Missing features
- Performance issues
- UI/UX suggestions

**How to Provide Feedback**:
- Use Ops-Center feedback form
- Submit GitHub issue
- Contact your admin

---

**Remember**: Geeses is here to help! Don't hesitate to ask questions or request assistance with Ops-Center operations.

**Roger that. Geeses out.** 🎖️
