/**
 * Signed-in Connect your AI catalog.
 * Prod URLs are the set measured 2026-11-06. Flip `oauth` here when an app's
 * door lands — the page reads this data and does not branch on the app name.
 *
 * Ring: a host of magicunicorn.dev (the dogfood console) uses `dogfoodUrl`
 * when an entry has one. There is no ring/host URL table elsewhere in src/,
 * so an optional VITE_MCP_APPS_JSON build var can replace the list:
 * a JSON array, or `{ "prod": [...], "dogfood": [...] }`.
 * Invalid JSON, a non-https URL, or a URL with userinfo falls back to prod.
 */

export const PROD_MCP_APPS = [
  {
    slug: 'email-ops',
    name: 'Email-Ops',
    url: 'https://email-ops.unicorncommander.ai/api/v1/mcp',
    oauth: true,
    dogfoodUrl: 'https://email-ops.magicunicorn.dev/api/v1/mcp',
    tokenLocation: 'Email-Ops → Settings → API tokens'
  },
  {
    slug: 'project-ops',
    name: 'Project-Ops',
    url: 'https://api.projectops.unicorncommander.ai/api/v1/mcp',
    oauth: true,
    dogfoodUrl: 'https://api.projectops.magicunicorn.dev/api/v1/mcp',
    tokenLocation: 'Project-Ops → Settings → API tokens'
  },
  {
    slug: 'customer-ops',
    name: 'Customer-Ops',
    url: 'https://api.customer-ops.unicorncommander.ai/api/v1/mcp',
    oauth: true,
    dogfoodUrl: 'https://customer-ops.magicunicorn.dev/api/v1/mcp',
    tokenLocation: 'Customer-Ops → Settings → API tokens'
  },
  {
    slug: 'accounting-ops',
    name: 'Accounting-Ops',
    url: 'https://accounting-ops.unicorncommander.ai/mcp/',
    oauth: true,
    dogfoodUrl: 'https://accounting-ops.magicunicorn.dev/mcp/',
    tokenLocation: 'Accounting-Ops → Settings → Personal access tokens'
  },
  {
    slug: 'tax-planning-ops',
    name: 'Tax-Planning-Ops',
    url: 'https://api.taxplanningops.unicorncommander.ai/api/v1/mcp',
    oauth: true,
    dogfoodUrl: 'https://api.taxplanningops.magicunicorn.dev/api/v1/mcp',
    tokenLocation: 'Tax-Planning-Ops → Connect your AI'
  },
  {
    slug: 'meeting-ops',
    name: 'Meeting-Ops',
    url: 'https://meeting-ops.unicorncommander.ai/mcp/',
    oauth: false,
    dogfoodUrl: 'https://meetingops.magicunicorn.dev/mcp',
    tokenLocation: 'Meeting-Ops → Settings → Personal access tokens'
  },
  {
    slug: 'contact-ops',
    name: 'Contact-Ops',
    url: 'https://mcp.contacts.unicorncommander.ai/mcp',
    oauth: true,
    dogfoodUrl: 'https://mcp.contacts.magicunicorn.dev/mcp',
    tokenLocation: 'Contact-Ops → Profile → tokens'
  }
];

const SLUG_RE = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

export function isDogfoodHost(hostname) {
  const host = String(hostname || '').toLowerCase().replace(/:\d+$/, '').replace(/\.$/, '');
  return host === 'magicunicorn.dev' || host.endsWith('.magicunicorn.dev');
}

export function isHttpsUrl(value) {
  if (typeof value !== 'string' || value.length === 0) return false;
  try {
    const parsed = new URL(value);
    return parsed.protocol === 'https:' && parsed.username === '' && parsed.password === '';
  } catch {
    return false;
  }
}

export function isMcpAppEntry(entry) {
  if (!entry || typeof entry !== 'object') return false;
  if (typeof entry.name !== 'string' || entry.name.trim() === '') return false;
  if (typeof entry.slug !== 'string' || !SLUG_RE.test(entry.slug)) return false;
  if (!isHttpsUrl(entry.url)) return false;
  if (typeof entry.oauth !== 'boolean') return false;
  if (typeof entry.tokenLocation !== 'string' || entry.tokenLocation.trim() === '') return false;
  if (entry.dogfoodUrl != null && !isHttpsUrl(entry.dogfoodUrl)) return false;
  return true;
}

function asEntryList(value) {
  if (!Array.isArray(value) || value.length === 0) return null;
  return value.every(isMcpAppEntry) ? value : null;
}

/**
 * Parse VITE_MCP_APPS_JSON. Returns an array, a { prod, dogfood } pair, or null.
 */
export function parseMcpAppsJson(raw) {
  if (raw == null || raw === '') return null;
  let parsed = raw;
  if (typeof raw === 'string') {
    try {
      parsed = JSON.parse(raw);
    } catch {
      return null;
    }
  }
  const list = asEntryList(parsed);
  if (list) return list;
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return null;
  const prod = asEntryList(parsed.prod);
  const dogfood = asEntryList(parsed.dogfood);
  if (!prod && !dogfood) return null;
  return { prod, dogfood };
}

function readBuildOverride() {
  if (typeof import.meta === 'undefined') return undefined;
  return import.meta.env?.VITE_MCP_APPS_JSON;
}

function applyDogfoodUrls(apps) {
  return apps.map((app) => (
    app.dogfoodUrl ? { ...app, url: app.dogfoodUrl } : { ...app }
  ));
}

/**
 * Resolve the catalog for a hostname.
 * `appsJson` overrides the build var when provided (including '' to force prod).
 */
export function resolveMcpApps({ hostname = '', appsJson } = {}) {
  const raw = appsJson !== undefined ? appsJson : readBuildOverride();
  const override = parseMcpAppsJson(raw);
  const dogfood = isDogfoodHost(hostname);
  let apps = PROD_MCP_APPS;
  let explicitDogfoodList = false;

  if (Array.isArray(override)) {
    apps = override;
  } else if (override) {
    explicitDogfoodList = Boolean(dogfood && override.dogfood);
    const picked = dogfood ? (override.dogfood || override.prod) : override.prod;
    apps = picked || PROD_MCP_APPS;
  }

  // An explicit dogfood list is already the ring's list: its `url` wins over any dogfoodUrl.
  const resolved = dogfood && !explicitDogfoodList ? applyDogfoodUrls(apps) : apps.map((app) => ({ ...app }));
  return resolved;
}

export function claudeCodeCommand(app) {
  return `claude mcp add --transport http ${app.slug} ${app.url}`;
}

export function buildClientRecipes(apps) {
  const commands = apps.map(claudeCodeCommand).join('\n');
  return [
    {
      id: 'claude-desktop',
      title: 'claude.ai / Claude Desktop',
      body: 'Settings → Connectors → Add custom connector → paste the URL → sign in with Unicorn Commander.',
      copyText: 'Settings → Connectors → Add custom connector → paste the URL → sign in with Unicorn Commander.'
    },
    {
      id: 'chatgpt',
      title: 'ChatGPT',
      body: 'Settings → Connectors (developer mode) → add the URL → sign in.',
      copyText: 'Settings → Connectors (developer mode) → add the URL → sign in.'
    },
    {
      id: 'claude-code',
      title: 'Claude Code',
      body: `${commands}\nThen run /mcp to sign in.`,
      copyText: commands
    },
    {
      id: 'cursor-codex',
      title: 'Cursor / Codex',
      body: "Paste the URL, plus a token from the app's settings (the token location in the table).",
      copyText: "Paste the URL, plus a token from the app's settings (the token location in the table)."
    }
  ];
}

export function getMcpApps() {
  const hostname = typeof window !== 'undefined' ? window.location.hostname : '';
  return resolveMcpApps({ hostname });
}
