import { describe, expect, test } from 'vitest';
import {
  PROD_MCP_APPS,
  buildClientRecipes,
  claudeCodeCommand,
  isDogfoodHost,
  resolveMcpApps
} from './mcpApps';

const MEASURED = [
  ['Email-Ops', 'https://email-ops.unicorncommander.ai/api/v1/mcp', true, 'Email-Ops → Settings → API tokens'],
  ['Project-Ops', 'https://api.projectops.unicorncommander.ai/api/v1/mcp', true, 'Project-Ops → Settings → API tokens'],
  ['Customer-Ops', 'https://api.customer-ops.unicorncommander.ai/api/v1/mcp', true, 'Customer-Ops → Settings → API tokens'],
  ['Accounting-Ops', 'https://accounting-ops.unicorncommander.ai/mcp/', true, 'Accounting-Ops → Settings → Personal access tokens'],
  ['Tax-Planning-Ops', 'https://api.taxplanningops.unicorncommander.ai/api/v1/mcp', true, 'Tax-Planning-Ops → Connect your AI'],
  ['Meeting-Ops', 'https://meeting-ops.unicorncommander.ai/mcp/', false, 'Meeting-Ops → Settings → Personal access tokens'],
  ['Contact-Ops', 'https://mcp.contacts.unicorncommander.ai/mcp', false, 'Contact-Ops → Profile → tokens']
];

describe('PROD_MCP_APPS', () => {
  test('matches the measured 2026-11-06 prod table', () => {
    expect(PROD_MCP_APPS.map((app) => [app.name, app.url, app.oauth, app.tokenLocation])).toEqual(MEASURED);
  });

  test('every entry has an https URL, an app name, an oauth boolean, and a token location', () => {
    expect(PROD_MCP_APPS.length).toBeGreaterThan(0);
    const slugs = new Set();
    for (const app of PROD_MCP_APPS) {
      expect(app.name).toEqual(expect.any(String));
      expect(app.name.trim().length).toBeGreaterThan(0);
      expect(app.url.startsWith('https://')).toBe(true);
      const parsed = new URL(app.url);
      expect(parsed.username).toBe('');
      expect(parsed.password).toBe('');
      expect(typeof app.oauth).toBe('boolean');
      expect(app.tokenLocation.trim().length).toBeGreaterThan(0);
      expect(slugs.has(app.slug)).toBe(false);
      slugs.add(app.slug);
    }
  });
});

describe('isDogfoodHost', () => {
  test('matches the dogfood console host and its subdomains only', () => {
    expect(isDogfoodHost('magicunicorn.dev')).toBe(true);
    expect(isDogfoodHost('api.magicunicorn.dev')).toBe(true);
    expect(isDogfoodHost('unicorncommander.ai')).toBe(false);
    expect(isDogfoodHost('notmagicunicorn.dev')).toBe(false);
    expect(isDogfoodHost('magicunicorn.dev.example.com')).toBe(false);
    expect(isDogfoodHost('localhost')).toBe(false);
    expect(isDogfoodHost('')).toBe(false);
  });
});

describe('resolveMcpApps', () => {
  test('defaults to the prod table off the dogfood ring', () => {
    const apps = resolveMcpApps({ hostname: 'unicorncommander.ai', appsJson: '' });
    expect(apps.map((app) => app.url)).toEqual(PROD_MCP_APPS.map((app) => app.url));
  });

  test('uses each app\'s dogfoodUrl on the dogfood host by default', () => {
    const apps = resolveMcpApps({ hostname: 'magicunicorn.dev', appsJson: '' });
    expect(apps.map((app) => app.url)).toEqual(PROD_MCP_APPS.map((app) => app.dogfoodUrl || app.url));
    expect(apps.every((app) => app.url.includes('magicunicorn.dev'))).toBe(true);
  });

  test('keeps the prod URL on the dogfood host when an entry has no dogfoodUrl', () => {
    const noDogfood = PROD_MCP_APPS.map(({ dogfoodUrl, ...app }) => app);
    const apps = resolveMcpApps({ hostname: 'magicunicorn.dev', appsJson: JSON.stringify(noDogfood) });
    expect(apps.map((app) => app.url)).toEqual(PROD_MCP_APPS.map((app) => app.url));
  });

  test('uses dogfoodUrl on the dogfood host', () => {
    const json = JSON.stringify([
      { ...PROD_MCP_APPS[0], dogfoodUrl: 'https://example.com/mcp/email' }
    ]);
    const onDogfood = resolveMcpApps({ hostname: 'ops.magicunicorn.dev', appsJson: json });
    const onProd = resolveMcpApps({ hostname: 'unicorncommander.ai', appsJson: json });
    expect(onDogfood).toHaveLength(1);
    expect(onDogfood[0].url).toBe('https://example.com/mcp/email');
    expect(onProd[0].url).toBe(PROD_MCP_APPS[0].url);
  });

  test('VITE_MCP_APPS_JSON object selects the ring list', () => {
    const dogfood = [{ ...PROD_MCP_APPS[0], url: 'https://example.com/mcp/dogfood' }];
    const json = JSON.stringify({ prod: PROD_MCP_APPS, dogfood });
    expect(resolveMcpApps({ hostname: 'magicunicorn.dev', appsJson: json })).toEqual(dogfood);
    expect(resolveMcpApps({ hostname: 'localhost', appsJson: json }).map((app) => app.url))
      .toEqual(PROD_MCP_APPS.map((app) => app.url));
  });

  test('invalid JSON or a URL with userinfo falls back to prod', () => {
    const prodUrls = PROD_MCP_APPS.map((app) => app.url);
    expect(resolveMcpApps({ hostname: 'localhost', appsJson: '{nope' }).map((app) => app.url)).toEqual(prodUrls);
    const leaked = JSON.stringify([
      { ...PROD_MCP_APPS[0], url: 'https://user:pass@example.com/mcp' }
    ]);
    expect(resolveMcpApps({ hostname: 'localhost', appsJson: leaked }).map((app) => app.url)).toEqual(prodUrls);
    const incomplete = JSON.stringify([{ name: 'Example', url: 'https://example.com/mcp' }]);
    expect(resolveMcpApps({ hostname: 'localhost', appsJson: incomplete }).map((app) => app.url)).toEqual(prodUrls);
  });
});

describe('buildClientRecipes', () => {
  test('includes each client recipe and a per-app Claude Code command', () => {
    const recipes = buildClientRecipes(PROD_MCP_APPS);
    const byId = Object.fromEntries(recipes.map((recipe) => [recipe.id, recipe]));
    expect(byId['claude-desktop'].body).toContain('Add custom connector');
    expect(byId['claude-desktop'].body).toContain('sign in with Unicorn Commander');
    expect(byId.chatgpt.body).toContain('developer mode');
    expect(byId['cursor-codex'].body).toContain('token');
    expect(byId['claude-code'].body).toContain('/mcp');
    expect(byId['claude-code'].copyText).toBe(PROD_MCP_APPS.map(claudeCodeCommand).join('\n'));
    expect(byId['claude-code'].copyText).toContain(
      'claude mcp add --transport http email-ops https://email-ops.unicorncommander.ai/api/v1/mcp'
    );
    expect(byId['claude-code'].copyText).not.toContain('/mcp to sign in');
  });
});
