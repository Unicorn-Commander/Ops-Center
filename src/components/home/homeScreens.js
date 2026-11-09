/**
 * Screens the Apps menu and the command palette may link to (DESIGN section l).
 *
 * The allowlist names each app's screens by path. A screen is offered only
 * when the state document itself carries its URL (a module source's `url`, an
 * item's link, an app tile's `open`), so the host is the org's own app host on
 * its ring, checked by the backend, and only for apps the organization is
 * entitled to (the Your apps module). No URL is built here from a guess.
 */

import { appInfo, appKey, itemApp } from './homeModel';

const SCREENS = {
  'project-ops': [['/dashboard/my-tasks', 'My tasks'], ['/dashboard/triage', 'Triage proposals'], ['/dashboard/projects', 'Projects'], ['/dashboard/schedule', 'Schedule']],
  'meeting-ops': [['/#/sessions', 'Sessions'], ['/#/action-items', 'Action items'], ['/#/record/personal', 'Record a meeting'], ['/#/import', 'Import a recording']],
  'email-ops': [['/agent-inbox', 'Agent inbox'], ['/mail', 'Mail'], ['/insights', 'Insights'], ['/accounts', 'Accounts']],
  'customer-ops': [['/dashboard/pipeline', 'Pipeline'], ['/dashboard/customers', 'Customers'], ['/dashboard/leads', 'Leads'], ['/dashboard/invoices', 'Invoices']],
  'accounting-ops': [['/dashboard', 'Overview'], ['/approvals', 'Approvals'], ['/invoices', 'Invoices'], ['/transactions', 'Transactions']],
  'center-deep': [['/', 'Watched topics'], ['/#/situations', 'Situations'], ['/#/schedules', 'Schedules'], ['/#/library', 'Library']]
};

function routeOf(url) {
  try {
    const u = new URL(url);
    if (u.protocol !== 'https:' && u.protocol !== 'http:') return null;
    const path = u.pathname.replace(/\/+$/, '') || '/';
    return { origin: u.origin, route: u.hash ? `${path === '/' ? '' : path}/${u.hash}`.replace(/^\/?#/, '/#') : path };
  } catch {
    return null;
  }
}

function collectUrls(doc) {
  const urls = [];
  for (const mod of doc?.modules || []) {
    for (const source of mod.source || []) {
      if (source?.url && source.status !== 'not_entitled') urls.push({ app: appKey(source.app), url: source.url });
    }
  }
  return urls;
}

/** The entitled apps with their catalogued screens, in the order of the Your apps module. */
export function appScreens(doc) {
  const appsModule = (doc?.modules || []).find(mod => mod.id === 'apps');
  const tiles = appsModule?.items || [];
  const urls = collectUrls(doc);
  return tiles.map(tile => {
    const key = appKey(tile.slug);
    const catalogue = SCREENS[key] || [];
    const openOrigin = tile.open ? routeOf(tile.open)?.origin : null;
    const seen = new Set();
    const screens = [];
    for (const [route, label] of catalogue) {
      const hit = urls.find(entry => entry.app === key && routeOf(entry.url)?.route === route
        && (!openOrigin || routeOf(entry.url)?.origin === openOrigin));
      if (hit && !seen.has(label)) {
        seen.add(label);
        screens.push({ label, href: hit.url });
      }
    }
    return { key, slug: tile.slug, name: tile.name || appInfo(key).label, open: tile.open || null, tile, screens };
  });
}

/**
 * The palette's index: screens, then the records already on the home (each
 * opens its own link), then things the home itself can do. Labels are the
 * document's own words.
 */
export function paletteIndex(doc, { commands = [] } = {}) {
  const entries = [];
  for (const app of appScreens(doc)) {
    if (app.open) entries.push({ id: `open:${app.key}`, label: `Open ${app.name}`, sub: `${app.name} · app`, app: app.key, href: app.open });
    for (const screen of app.screens) {
      entries.push({ id: `screen:${app.key}:${screen.label}`, label: screen.label, sub: `${app.name} · screen`, app: app.key, href: screen.href });
    }
  }
  const recordModules = { needs_you: 'needs you', today: 'today', recent_meetings: 'meeting', watched_topics: 'watched topic', since_last_visit: 'since your last visit' };
  for (const mod of doc?.modules || []) {
    const what = recordModules[mod.id];
    if (!what || !['ok', 'empty'].includes(mod.status)) continue;
    for (const item of mod.items || []) {
      const href = item.run_href || item.href || (item.actions || []).find(a => a.id === 'open')?.href;
      if (!href || !item.title) continue;
      const app = itemApp(item) || appKey(item.app);
      entries.push({ id: `item:${mod.id}:${item.id || item.monitor_id}`, label: item.title, sub: `${appInfo(app).label} · ${what}`, app, href });
    }
  }
  return [...entries, ...commands];
}

export function filterPalette(entries, query, limit = 10) {
  const q = String(query || '').trim().toLowerCase();
  if (!q) return entries.slice(0, limit);
  const words = q.split(/\s+/);
  return entries.filter(entry => {
    const hay = `${entry.label} ${entry.sub || ''}`.toLowerCase();
    return words.every(word => hay.includes(word));
  }).slice(0, limit);
}
