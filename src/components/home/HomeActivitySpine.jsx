import React, { useEffect, useMemo, useState } from 'react';
import DashboardActivityFeed from './DashboardActivityFeed';
import InviteTeammateAction from './InviteTeammateAction';

// The activity feed reads Project-Ops and Meeting-Ops from the browser, which those apps do not
// allow (Project-Ops accepts only a bearer token; Meeting-Ops allows only its own origins), so it
// would name healthy apps as unavailable. It stays off until a server-side aggregator in Ops-Center
// feeds it. Set VITE_HOME_ACTIVITY_FEED=true at build time to turn it on.
export const HOME_ACTIVITY_FEED_ENABLED = import.meta.env?.VITE_HOME_ACTIVITY_FEED === 'true';

const ORG_LIST_URLS = ['/api/v1/org/my-orgs', '/api/v1/users/me/organizations'];

export function organizationsFromPayload(payload) {
  if (Array.isArray(payload)) return { organizations: payload, payload: null };
  if (payload && Array.isArray(payload.organizations)) {
    return { organizations: payload.organizations, payload };
  }
  return { organizations: [], payload: null };
}

export function pickCurrentOrganization(organizations, payload, storedId) {
  const preferred = payload?.current_org_id || payload?.default_org_id || storedId;
  return organizations.find(org => String(org.id) === String(preferred)) || organizations[0] || null;
}

export function orgRole(organization) {
  return organization?.role || organization?.org_role || null;
}

async function readJson(response) {
  return response.json().catch(() => null);
}

async function loadOrganizations(fetchImpl) {
  let sawFailure = false;
  for (const url of ORG_LIST_URLS) {
    try {
      const response = await fetchImpl(url, {
        credentials: 'include',
        headers: { Accept: 'application/json' }
      });
      if (response.status === 404) continue;
      if (!response.ok) {
        sawFailure = true;
        continue;
      }
      return organizationsFromPayload(await readJson(response));
    } catch {
      sawFailure = true;
    }
  }
  if (sawFailure) {
    throw new Error('We could not load your organization.');
  }
  return { organizations: [], payload: null };
}

/**
 * Drop-in home section. It loads the signed-in organizations itself so the
 * dashboard can render it without the admin organization provider.
 */
export default function HomeActivitySpine({
  className = '',
  fetchImpl = globalThis.fetch,
  hostname = typeof window !== 'undefined' ? window.location.hostname : '',
  storage = typeof window !== 'undefined' ? window.localStorage : null,
  reload = () => window.location.reload(),
  adapterOptions,
  showActivity = HOME_ACTIVITY_FEED_ENABLED
}) {
  const [orgState, setOrgState] = useState({
    loading: true,
    error: null,
    organizations: [],
    current: null
  });
  const [switchError, setSwitchError] = useState(null);
  const resolvedAdapterOptions = useMemo(() => ({
    ...(adapterOptions || {}),
    fetchImpl,
    hostname
  }), [adapterOptions, fetchImpl, hostname]);

  useEffect(() => {
    let cancelled = false;
    setOrgState(previous => ({ ...previous, loading: true, error: null }));
    loadOrganizations(fetchImpl)
      .then(result => {
        if (cancelled) return;
        const storedId = storage?.getItem?.('currentOrgId') || null;
        setOrgState({
          loading: false,
          error: null,
          organizations: result.organizations,
          current: pickCurrentOrganization(result.organizations, result.payload, storedId)
        });
      })
      .catch(() => {
        if (cancelled) return;
        setOrgState({
          loading: false,
          error: 'We could not load your organization. Refresh the page to try again.',
          organizations: [],
          current: null
        });
      });
    return () => {
      cancelled = true;
    };
  }, [fetchImpl, storage]);

  async function switchOrganization(orgId) {
    setSwitchError(null);
    try {
      const response = await fetchImpl('/api/v1/users/me/switch-org', {
        method: 'POST',
        credentials: 'include',
        headers: {
          Accept: 'application/json',
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ org_id: orgId })
      });
      if (!response.ok) {
        setSwitchError('We could not switch organization. Try again.');
        return;
      }
      storage?.setItem?.('currentOrgId', orgId);
      reload();
    } catch {
      setSwitchError('We could not switch organization. Try again.');
    }
  }

  const current = orgState.current;
  const role = orgRole(current);

  return (
    <section className={`space-y-5 ${className}`} aria-label="Workspace activity">
      <header className="flex flex-col gap-4 rounded-2xl border border-white/10 bg-slate-950/50 p-5 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">Workspace</p>
          <h1 className="mt-1 text-2xl font-semibold text-white">
            {orgState.loading ? 'Loading your workspace...' : current?.name || 'Choose a workspace'}
          </h1>
          <p className="mt-1 text-sm text-slate-300">
            {showActivity ? 'Your activity, apps, and teammates in one place.' : 'Your apps and teammates in one place.'}
          </p>
        </div>
        {orgState.organizations.length > 1 && (
          <label className="text-sm font-medium text-slate-200">
            Organization
            <select
              aria-label="Organization"
              className="mt-1 block min-w-[12rem] rounded-lg border border-white/15 bg-slate-900 px-3 py-2 text-white"
              value={current?.id || ''}
              onChange={event => switchOrganization(event.target.value)}
            >
              {orgState.organizations.map(organization => (
                <option key={organization.id} value={organization.id}>
                  {organization.name}
                </option>
              ))}
            </select>
          </label>
        )}
      </header>

      {orgState.error && (
        <div className="rounded-lg border border-amber-300/30 bg-amber-300/10 p-4" role="alert">
          <p className="text-sm text-amber-100">{orgState.error}</p>
          <button
            type="button"
            onClick={() => reload()}
            className="mt-3 rounded-md border border-amber-200/40 px-3 py-2 text-sm font-medium text-amber-50"
          >
            Refresh the page
          </button>
        </div>
      )}

      {switchError && (
        <p className="text-sm text-amber-100" role="alert">{switchError}</p>
      )}

      {!orgState.loading && !orgState.error && !current && (
        <p className="rounded-lg border border-white/10 p-4 text-sm text-slate-300">
          You are not in an organization yet.
        </p>
      )}

      {current && (
        <>
          {showActivity && <DashboardActivityFeed orgId={current.id} adapterOptions={resolvedAdapterOptions} />}
          <InviteTeammateAction organization={current} role={role} fetchImpl={fetchImpl} />
        </>
      )}
    </section>
  );
}

export { DashboardActivityFeed, InviteTeammateAction };
