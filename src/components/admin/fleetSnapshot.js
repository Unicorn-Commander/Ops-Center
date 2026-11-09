/**
 * Shared helpers for the admin dashboard's GPU and Local Inference cards.
 *
 * Both cards read the fleet map snapshot through admin-only GET routes
 * (backend/fleet_map_api.py, summaries in backend/fleet_gpus.py). Missing data
 * arrives as null and is shown as "not reported", never as zero.
 */

export const FLEET_GPUS_ENDPOINT = '/api/v1/fleet/gpus';
export const FLEET_INFERENCE_ENDPOINT = '/api/v1/fleet/inference';
export const FLEET_MAP_PAGE = '/admin/infra/fleet-map';

// The collector pushes about every 5 minutes; a minute is plenty.
export const FLEET_REFRESH_MS = 60000;

export function plural(count, one, many = `${one}s`) {
  return `${count} ${count === 1 ? one : many}`;
}

export function ago(seconds) {
  if (seconds === null || seconds === undefined) return 'at an unknown time';
  if (seconds < 60) return 'under a minute ago';
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 48) return `${hours} h ago`;
  return `${Math.floor(hours / 24)} days ago`;
}

export function formatMiB(mib) {
  if (mib === null || mib === undefined) return null;
  const gb = mib / 1024;
  if (gb >= 100) return `${Math.round(gb)} GB`;
  return `${parseFloat(gb.toFixed(1))} GB`;
}

export function absoluteTime(iso) {
  if (!iso) return undefined;
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? undefined : date.toLocaleString();
}

/** GET a fleet summary. Returns { data } or { error } with a sentence an admin can act on. */
export async function fetchFleetSummary(fetchImpl, url) {
  try {
    const response = await fetchImpl(url, {
      credentials: 'include',
      headers: { Accept: 'application/json' },
    });
    if (response.ok) return { data: await response.json() };
    if (response.status === 401) return { error: 'Sign in again to read the fleet map.' };
    if (response.status === 403) return { error: 'The fleet map is for platform admins.' };
    if (response.status === 404) return { error: 'This server does not offer the fleet summary yet.' };
    return { error: `The fleet summary answered HTTP ${response.status}.` };
  } catch (err) {
    return { error: 'The fleet summary could not be reached.' };
  }
}

/** One line about the snapshot the counts come from. */
export function snapshotLine(doc) {
  if (!doc || !doc.available) return null;
  const when = ago(doc.age_seconds);
  return doc.stale
    ? `Fleet map snapshot is stale, taken ${when}`
    : `Fleet map snapshot taken ${when}`;
}

/** The not-connected explanation, shared by both cards. */
export function notConnectedLines(doc) {
  const lines = ['No fleet map snapshot has reached this server yet, so nothing here is a count of the fleet.'];
  if (doc && doc.ingest_configured === false) {
    lines.push('Ingest is not set up on this server: it needs a fleet map ingest token, and the collector pushing to /api/v1/fleet/ingest.');
  } else if (doc && doc.ingest_configured === true) {
    lines.push('Ingest is set up; the first push from the collector will fill this in.');
  }
  return lines;
}
