/**
 * The home's calls to Ops-Center, all same origin with the session cookie:
 *
 * - GET  /api/v1/home/state            the home-state document (404 when HOME_STATE_ENABLED is off)
 * - POST /api/v1/home/actions/...      approve, reject, accept or mark done one item (the href comes
 *                                      from the item's own actions list), with an Idempotency-Key and
 *                                      the X-CSRF-Token the CSRF middleware checks
 * - GET  /api/v1/auth/csrf-token       the session's CSRF token (falls back to the csrf_token cookie,
 *                                      the double-submit pattern NotificationSettings uses)
 * - PUT  /api/v1/org/{id}/dashboard-cursor   moves "Since you were last here" forward (see rememberSeen)
 */

import { isValidState } from './homeModel';

export const STATE_ROUTE = '/api/v1/home/state';
const CSRF_ROUTE = '/api/v1/auth/csrf-token';
const CACHE_KEY = 'uc.home.cache';
const SEEN_KEY = 'uc.home.seen';
const CACHE_MAX_AGE_MS = 12 * 60 * 60 * 1000;

function storage() {
  try {
    return typeof window !== 'undefined' ? window.localStorage : null;
  } catch {
    return null;
  }
}

function readJson(key) {
  try {
    const raw = storage()?.getItem(key);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function writeJson(key, value) {
  try {
    if (value === null) storage()?.removeItem(key);
    else storage()?.setItem(key, JSON.stringify(value));
  } catch {
    // Storage full or blocked: the page still works, it only loses the cached first paint.
  }
}

export function browserTimeZone() {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || '';
  } catch {
    return '';
  }
}

export function stateUrl(tz = browserTimeZone()) {
  return tz ? `${STATE_ROUTE}?tz=${encodeURIComponent(tz)}` : STATE_ROUTE;
}

/**
 * One read of the state document. Results:
 *   { kind: 'ok', doc, etag }     a valid uc.home.state/1 document
 *   { kind: 'not-modified' }      304 for the ETag sent
 *   { kind: 'off' }               404: the home is switched off for this ring
 *   { kind: 'error', status }     anything else, including a body that is not the document
 */
export async function fetchState({ fetchImpl = globalThis.fetch, etag = null, signal } = {}) {
  let response;
  try {
    const headers = { Accept: 'application/json' };
    if (etag) headers['If-None-Match'] = etag;
    response = await fetchImpl(stateUrl(), { credentials: 'include', headers, signal });
  } catch (error) {
    if (error?.name === 'AbortError') throw error;
    return { kind: 'error', status: 0 };
  }
  if (response.status === 304) return { kind: 'not-modified' };
  if (response.status === 404) return { kind: 'off' };
  if (!response.ok) return { kind: 'error', status: response.status };
  let doc = null;
  try {
    doc = await response.json();
  } catch {
    doc = null;
  }
  if (!isValidState(doc)) return { kind: 'error', status: response.status };
  const tag = typeof response.headers?.get === 'function' ? response.headers.get('ETag') : null;
  return { kind: 'ok', doc, etag: tag || null };
}

// ------------------------------------------------------------------ cache

/** Who is signed in, from the session ProtectedRoute refreshed for this page load. */
export function sessionOwner() {
  const info = readJson('userInfo') || {};
  return String(info.email || info.username || info.sub || info.id || '') || null;
}

/** The last complete state, for the first paint, if it is this person's and recent. */
export function readCache(owner = sessionOwner(), now = Date.now()) {
  const cached = readJson(CACHE_KEY);
  if (!cached || !owner || cached.owner !== owner || !isValidState(cached.doc)) return null;
  if (!cached.savedAt || now - cached.savedAt > CACHE_MAX_AGE_MS) return null;
  const currentOrg = storage()?.getItem?.('currentOrgId');
  if (currentOrg && cached.doc.organization?.id && String(currentOrg) !== String(cached.doc.organization.id)) return null;
  return cached.doc;
}

export function writeCache(doc, owner = sessionOwner(), now = Date.now()) {
  if (!owner || !isValidState(doc)) return;
  writeJson(CACHE_KEY, { owner, savedAt: now, doc });
}

export function clearCache() {
  writeJson(CACHE_KEY, null);
}

// ------------------------------------------------------------- since cursor

/**
 * "Since you were last here" counts from a per-person, per-organization cursor
 * the home-state route only reads. The page moves it, but never during a
 * visit: each successful render remembers the document's time here, and the
 * next visit (the next page load) sends that time first, so the deltas stay
 * put while the person is looking at them and nothing is skipped when a tab is
 * closed without warning. A module whose sources did not all answer is not
 * remembered, so changes from an outage are not skipped either.
 */
export function rememberSeen(doc) {
  const since = (doc?.modules || []).find(mod => mod.id === 'since_last_visit');
  const orgId = doc?.organization?.id;
  if (!orgId || !since || !['ok', 'empty'].includes(since.status) || since.partial) return;
  const owner = sessionOwner();
  if (!owner || !doc.generated_at) return;
  const seen = readJson(SEEN_KEY) || {};
  seen[orgId] = { owner, at: doc.generated_at };
  writeJson(SEEN_KEY, seen);
}

export async function sendSeen({ fetchImpl = globalThis.fetch, timeoutMs = 1500 } = {}) {
  const seen = readJson(SEEN_KEY) || {};
  const owner = sessionOwner();
  for (const id of Object.keys(seen)) {
    const record = seen[id];
    if (!record?.at || !owner || record.owner !== owner) continue;
    const controller = typeof AbortController !== 'undefined' ? new AbortController() : null;
    const timer = controller ? setTimeout(() => controller.abort(), timeoutMs) : null;
    try {
      const response = await fetchImpl(`/api/v1/org/${encodeURIComponent(id)}/dashboard-cursor`, {
        method: 'PUT',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({ last_seen_at: record.at, rendered: true }),
        signal: controller?.signal
      });
      if (response.ok || response.status === 400 || response.status === 403 || response.status === 404) {
        delete seen[id];
      }
    } catch {
      // Keep the record; the next visit tries again.
    } finally {
      if (timer) clearTimeout(timer);
    }
  }
  writeJson(SEEN_KEY, Object.keys(seen).length ? seen : null);
}

// ------------------------------------------------------------------ actions

let csrfToken = null;

function csrfCookie() {
  try {
    const match = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : null;
  } catch {
    return null;
  }
}

export async function getCsrfToken({ fetchImpl = globalThis.fetch, refresh = false } = {}) {
  if (csrfToken && !refresh) return csrfToken;
  try {
    const response = await fetchImpl(CSRF_ROUTE, { credentials: 'include', headers: { Accept: 'application/json' } });
    if (response.ok) {
      const data = await response.json();
      if (data?.csrf_token) {
        csrfToken = data.csrf_token;
        return csrfToken;
      }
    }
  } catch {
    // fall through to the cookie
  }
  csrfToken = csrfCookie();
  return csrfToken;
}

export function resetCsrfToken() {
  csrfToken = null;
}

export function newIdempotencyKey() {
  const c = globalThis.crypto;
  if (c?.randomUUID) return c.randomUUID();
  const bytes = new Uint8Array(16);
  if (c?.getRandomValues) c.getRandomValues(bytes);
  else for (let i = 0; i < 16; i += 1) bytes[i] = Math.floor(Math.random() * 256);
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, b => b.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

/**
 * Send one action and return what to show in the row. The key is the click's:
 * a retry of the same click reuses it, so the app is reached at most once.
 *
 *   { outcome: 'done' | 'refused' | 'reauth' | 'failed', message }   a receipt
 *   { outcome: 'problem', message, retry }                          no receipt (retry: the same key may be sent again)
 */
export async function sendAction(href, key, { fetchImpl = globalThis.fetch, wait = sleep, maxPolls = 5 } = {}) {
  if (typeof href !== 'string' || !href.startsWith('/api/v1/home/actions/')) {
    return { outcome: 'problem', message: 'This action is not available here. Open it in its app.', retry: false };
  }
  let csrfRetried = false;
  for (let attempt = 0; attempt <= maxPolls; attempt += 1) {
    let response;
    try {
      const token = await getCsrfToken({ fetchImpl });
      const headers = { Accept: 'application/json', 'Idempotency-Key': key };
      if (token) headers['X-CSRF-Token'] = token;
      response = await fetchImpl(href, { method: 'POST', credentials: 'include', headers });
    } catch {
      return { outcome: 'problem', message: 'Ops-Center could not be reached, so nothing was sent. Try again.', retry: true };
    }
    let body = null;
    try {
      body = await response.json();
    } catch {
      body = null;
    }
    if (response.ok && body && ['done', 'refused', 'reauth', 'failed'].includes(body.outcome)) {
      return { outcome: body.outcome, message: body.message || '', receiptId: body.id || null };
    }
    if (response.status === 409 && body?.code === 'action_in_progress') {
      const after = Number(response.headers?.get?.('Retry-After')) || 2;
      await wait(Math.min(after, 10) * 1000);
      continue;
    }
    if (response.status === 403 && /csrf/i.test(String(body?.detail || '')) && !csrfRetried) {
      csrfRetried = true;
      await getCsrfToken({ fetchImpl, refresh: true });
      continue;
    }
    if (response.status === 404) {
      return { outcome: 'problem', message: 'Acting from the home is not switched on here. Open it in its app.', retry: false };
    }
    if (response.status === 401) {
      return { outcome: 'reauth', message: 'Sign in again to finish this.' };
    }
    const detail = typeof body?.detail === 'string' ? body.detail : '';
    const fix = typeof body?.fix === 'string' ? body.fix : '';
    const message = [detail, fix].filter(Boolean).join(' ') || 'The home could not finish this. Check the item in its app.';
    return { outcome: 'problem', message, retry: response.status >= 500 || response.status === 409 };
  }
  return { outcome: 'problem', message: 'The app is still working on this. Check the item in its app before trying again.', retry: true };
}
