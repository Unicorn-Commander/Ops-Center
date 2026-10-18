# P-00039 MCP and A2A discovery

Ops-Center publishes the Colonel's legacy card at `/.well-known/agent.json`, the current A2A card at `/.well-known/agent-card.json`, and the Unicorn Commander suite MCP index at `/.well-known/mcps.json`; the current card uses the JSON-RPC transport with bearer security, reports streaming and push notifications as unsupported, and the MCP index lists the nine suite endpoints without fabricating app-specific scopes.
