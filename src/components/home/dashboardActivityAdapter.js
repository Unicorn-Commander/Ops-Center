import { isDogfoodHost } from '../../config/mcpApps';

const DEFAULT_LIMIT = 20;
const EXPLICIT_ORG_KEYS = ['org_id', 'orgId', 'ops_org_id', 'organization_uuid'];

// Meeting-Ops integer organization_id and Project-Ops workspaceId are not
// Ops-Center organization UUIDs. Dropping on those fields would hide every
// real row. Only an explicit Ops-Center org id can mark a row as foreign.
const ORIGINS = {
  prod: {
    projectApi: 'https://api.projectops.unicorncommander.ai',
    projectWeb: 'https://projectops.unicorncommander.ai',
    meetingApi: 'https://meeting-ops.unicorncommander.ai',
    meetingWeb: 'https://meeting-ops.unicorncommander.ai'
  },
  dogfood: {
    projectApi: 'https://api.projectops.magicunicorn.dev',
    projectWeb: 'https://projectops.magicunicorn.dev',
    meetingApi: 'https://meetingops.magicunicorn.dev',
    meetingWeb: 'https://meetingops.magicunicorn.dev'
  }
};

function trimTrailingSlash(value) {
  return String(value || '').replace(/\/+$/, '');
}

function firstValue(...values) {
  return values.find(value => value !== undefined && value !== null && value !== '');
}

function payloadItems(payload) {
  if (Array.isArray(payload)) return payload;
  return payload?.items || payload?.activities || payload?.events || payload?.sessions || [];
}

export function resolveActivityOrigins(hostname = '') {
  return isDogfoodHost(hostname) ? ORIGINS.dogfood : ORIGINS.prod;
}

export function parseActivityTimestamp(value) {
  if (!value) return null;
  const timestamp = new Date(value);
  return Number.isNaN(timestamp.getTime()) ? null : timestamp.toISOString();
}

export function explicitOpsOrgId(item) {
  if (!item || typeof item !== 'object') return undefined;
  for (const key of EXPLICIT_ORG_KEYS) {
    const value = item[key];
    if (value !== undefined && value !== null && value !== '') return String(value);
  }
  return undefined;
}

export function isActivityForOrganization(item, orgId) {
  const itemOrgId = explicitOpsOrgId(item);
  if (itemOrgId === undefined) return true;
  return itemOrgId === String(orgId);
}

export function filterActivitySince(items, cursor, orgId) {
  const cursorTime = cursor ? Date.parse(cursor) : Number.NEGATIVE_INFINITY;
  if (cursor && Number.isNaN(cursorTime)) return [];

  return items
    .filter(item => isActivityForOrganization(item, orgId))
    .filter(item => {
      const itemTime = Date.parse(item.timestamp);
      return !Number.isNaN(itemTime) && itemTime > cursorTime;
    })
    .sort((left, right) => Date.parse(right.timestamp) - Date.parse(left.timestamp));
}

function safeHref(candidate, fallback, baseUrl) {
  if (!candidate) return fallback;

  try {
    const base = new URL(baseUrl);
    const resolved = new URL(candidate, base);
    if (resolved.origin !== base.origin) return fallback;
    if (resolved.username || resolved.password) return fallback;
    return resolved.toString();
  } catch {
    return fallback;
  }
}

function projectLabel(item) {
  const title = firstValue(item.title, item.project?.title, item.project_title, item.name);
  const action = firstValue(item.label, item.action, item.event, item.description);
  if (action && title && String(action) !== String(title)) return `${action}: ${title}`;
  return String(action || title || 'Project update');
}

function projectHref(item, baseUrl) {
  const base = trimTrailingSlash(baseUrl);
  const isTask = item.kind === 'task' || item.resource === 'task' || Boolean(firstValue(item.task_id, item.taskId));
  const projectId = firstValue(
    item.project_id,
    item.projectId,
    item.project?.id,
    item.kind === 'project' ? item.id : null
  );
  const fallback = isTask
    ? `${base}/dashboard/my-tasks`
    : projectId
      ? `${base}/dashboard/projects/${encodeURIComponent(projectId)}`
      : `${base}/dashboard`;

  return safeHref(firstValue(item.href, item.url, item.deep_link), fallback, base);
}

function meetingHref(item, baseUrl) {
  const base = trimTrailingSlash(baseUrl);
  const sessionId = firstValue(item.session_id, item.sessionId, item.id);
  const fallback = sessionId
    ? `${base}/#/sessions/${encodeURIComponent(sessionId)}`
    : `${base}/#/sessions`;

  return safeHref(firstValue(item.href, item.url, item.deep_link), fallback, base);
}

export function normalizeProjectActivity(item, baseUrl) {
  const timestamp = parseActivityTimestamp(firstValue(
    item.timestamp,
    item.updated_at,
    item.updatedAt,
    item.created_at,
    item.createdAt,
    item.occurred_at
  ));
  if (!timestamp) return null;

  return {
    source: 'project-ops',
    label: projectLabel(item),
    timestamp,
    href: projectHref(item, baseUrl),
    org_id: explicitOpsOrgId(item)
  };
}

export function normalizeMeetingActivity(item, baseUrl) {
  const timestamp = parseActivityTimestamp(firstValue(
    item.created_at,
    item.updated_at,
    item.timestamp,
    item.started_at
  ));
  if (!timestamp) return null;

  return {
    source: 'meeting-ops',
    label: String(firstValue(item.name, item.title, item.label, item.summary_preview, 'Meeting update')),
    timestamp,
    href: meetingHref(item, baseUrl),
    org_id: explicitOpsOrgId(item)
  };
}

function joinUrl(baseUrl, path) {
  return `${trimTrailingSlash(baseUrl)}${path}`;
}

function activityUrl(baseUrl, path, limit) {
  const url = new URL(joinUrl(baseUrl, path));
  url.searchParams.set('limit', String(limit));
  return url.toString();
}

async function fetchJson(url, fetchImpl) {
  const response = await fetchImpl(url, {
    credentials: 'include',
    headers: { Accept: 'application/json' }
  });
  if (!response.ok) {
    const error = new Error(`Activity request failed with status ${response.status}`);
    error.status = response.status;
    throw error;
  }
  return response.json();
}

async function fetchProjectActivity(apiBase, webBase, limit, fetchImpl) {
  try {
    const payload = await fetchJson(
      activityUrl(apiBase, '/api/v1/dashboard/recent-activity', limit),
      fetchImpl
    );
    return payloadItems(payload)
      .map(item => normalizeProjectActivity(item, webBase))
      .filter(Boolean);
  } catch (error) {
    if (error.status !== 401 && error.status !== 403) throw error;

    // These routes do not declare a limit query. An extra parameter is rejected.
    const [projectsResult, tasksResult] = await Promise.allSettled([
      fetchJson(joinUrl(apiBase, '/api/v1/dashboard/project-statistics'), fetchImpl),
      fetchJson(joinUrl(apiBase, '/api/v1/tasks/my-tasks'), fetchImpl)
    ]);
    if (projectsResult.status === 'rejected' && tasksResult.status === 'rejected') {
      throw projectsResult.reason;
    }

    const items = [];
    if (projectsResult.status === 'fulfilled') {
      const recent = projectsResult.value?.recentProjects || [];
      recent.forEach(item => {
        const normalized = normalizeProjectActivity({ ...item, kind: 'project' }, webBase);
        if (normalized) items.push(normalized);
      });
    }
    if (tasksResult.status === 'fulfilled') {
      const tasks = Array.isArray(tasksResult.value)
        ? tasksResult.value
        : (tasksResult.value?.tasks || tasksResult.value?.items || []);
      tasks.forEach(item => {
        const normalized = normalizeProjectActivity({ ...item, kind: 'task', resource: 'task' }, webBase);
        if (normalized) items.push(normalized);
      });
    }
    return items;
  }
}

async function fetchMeetingActivity(apiBase, webBase, limit, fetchImpl) {
  const payload = await fetchJson(
    activityUrl(apiBase, '/api/analytics/sessions', limit),
    fetchImpl
  );
  return payloadItems(payload)
    .map(item => normalizeMeetingActivity(item, webBase))
    .filter(Boolean);
}

export async function fetchDashboardActivity({
  orgId,
  cursor = null,
  fetchImpl = globalThis.fetch,
  hostname = '',
  projectBaseUrl,
  projectWebUrl,
  meetingBaseUrl,
  meetingWebUrl,
  limit = DEFAULT_LIMIT
}) {
  if (!orgId) {
    return { items: [], complete: true, sourceStatus: {}, errors: {} };
  }
  if (typeof fetchImpl !== 'function') {
    throw new Error('Activity fetch is unavailable');
  }

  const origins = resolveActivityOrigins(hostname);
  const projectApi = projectBaseUrl || origins.projectApi;
  const projectWeb = projectWebUrl || projectBaseUrl || origins.projectWeb;
  const meetingApi = meetingBaseUrl || origins.meetingApi;
  const meetingWeb = meetingWebUrl || meetingBaseUrl || origins.meetingWeb;

  const results = await Promise.allSettled([
    fetchProjectActivity(projectApi, projectWeb, limit, fetchImpl),
    fetchMeetingActivity(meetingApi, meetingWeb, limit, fetchImpl)
  ]);

  const items = [];
  const sourceStatus = {};
  const errors = {};
  const sources = ['project-ops', 'meeting-ops'];
  results.forEach((result, index) => {
    const source = sources[index];
    if (result.status === 'rejected') {
      sourceStatus[source] = 'unavailable';
      errors[source] = result.reason?.message || 'Activity is unavailable';
      return;
    }
    sourceStatus[source] = 'ready';
    result.value.forEach(item => items.push(item));
  });

  return {
    items: filterActivitySince(items, cursor, orgId),
    complete: results.every(result => result.status === 'fulfilled'),
    sourceStatus,
    errors
  };
}

function cursorUrl(orgId) {
  return `/api/v1/org/${encodeURIComponent(orgId)}/dashboard-cursor`;
}

export async function fetchDashboardCursor(orgId, fetchImpl = globalThis.fetch) {
  const response = await fetchImpl(cursorUrl(orgId), { credentials: 'include' });
  if (!response.ok) {
    const error = new Error(`Cursor request failed with status ${response.status}`);
    error.status = response.status;
    throw error;
  }
  const data = await response.json();
  return {
    lastSeenAt: data.last_seen_at || null,
    serverNow: data.server_now || null
  };
}

export async function advanceDashboardCursor(orgId, lastSeenAt, fetchImpl = globalThis.fetch) {
  const timestamp = parseActivityTimestamp(lastSeenAt);
  if (!timestamp) return null;

  const response = await fetchImpl(cursorUrl(orgId), {
    method: 'PUT',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ last_seen_at: timestamp, rendered: true })
  });
  if (!response.ok) {
    const error = new Error(`Cursor update failed with status ${response.status}`);
    error.status = response.status;
    throw error;
  }
  const data = await response.json();
  return data.last_seen_at || timestamp;
}

export function latestActivityTimestamp(items) {
  return items.reduce((latest, item) => {
    if (!latest || Date.parse(item.timestamp) > Date.parse(latest)) return item.timestamp;
    return latest;
  }, null);
}

export const ACTIVITY_DEFAULTS = {
  limit: DEFAULT_LIMIT
};
