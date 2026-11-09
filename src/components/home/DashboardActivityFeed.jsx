import React, { useCallback } from 'react';
import { ArrowPathIcon, ClockIcon } from '@heroicons/react/24/outline';
import {
  advanceDashboardCursor,
  fetchDashboardCursor
} from './dashboardActivityAdapter';
import { useDashboardActivity } from './useDashboardActivity';

function formatActivityTime(timestamp) {
  return new Date(timestamp).toLocaleString([], {
    dateStyle: 'medium',
    timeStyle: 'short'
  });
}

export function unavailableActivityCopy(sourceStatus) {
  const entries = Object.entries(sourceStatus || {});
  const down = entries.filter(([, status]) => status === 'unavailable').map(([source]) => source);
  const ready = entries.some(([, status]) => status === 'ready');
  if (!ready || down.length === 0) return null;
  if (down.length === 1 && down[0] === 'meeting-ops') return 'Meeting-Ops is unavailable right now.';
  if (down.length === 1 && down[0] === 'project-ops') return 'Project-Ops is unavailable right now.';
  return 'Some activity is unavailable right now. Showing what we found.';
}

export default function DashboardActivityFeed({ orgId, adapterOptions }) {
  const fetchImpl = adapterOptions?.fetchImpl || globalThis.fetch;
  const cursorReader = useCallback(
    (id) => fetchDashboardCursor(id, fetchImpl),
    [fetchImpl]
  );
  const cursorWriter = useCallback(
    (id, timestamp) => advanceDashboardCursor(id, timestamp, fetchImpl),
    [fetchImpl]
  );
  const activity = useDashboardActivity({
    orgId,
    adapterOptions,
    cursorReader,
    cursorWriter
  });
  const sameOrg = Boolean(orgId) && activity.loadedOrgId === orgId;
  const partialCopy = sameOrg ? unavailableActivityCopy(activity.sourceStatus) : null;
  const hasItems = sameOrg && activity.items.length > 0;
  const heading = activity.cursorReady && !activity.cursor
    ? 'Here is recent activity'
    : 'What happened since you were last here';
  const emptyCopy = activity.cursor
    ? 'No new activity since your last visit.'
    : 'Nothing new in Project-Ops or Meeting-Ops yet.';

  return (
    <section
      aria-labelledby="dashboard-activity-heading"
      aria-busy={activity.loading || !sameOrg}
      className="rounded-2xl border border-white/10 bg-slate-950/40 p-5 shadow-lg"
    >
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-cyan-300">Activity</p>
          <h2 id="dashboard-activity-heading" className="mt-1 text-xl font-semibold text-white">
            {heading}
          </h2>
        </div>
        <ClockIcon className="h-6 w-6 flex-none text-cyan-300" aria-hidden="true" />
      </div>

      {(activity.loading || !sameOrg) && (
        <p className="mt-5 text-sm text-slate-300" role="status">Loading what changed...</p>
      )}

      {partialCopy && (
        <p className="mt-4 rounded-lg border border-amber-300/30 bg-amber-300/10 p-3 text-sm text-amber-100" role="status">
          {partialCopy}
        </p>
      )}

      {!activity.loading && sameOrg && activity.error && !hasItems && !partialCopy && (
        <div className="mt-5 rounded-lg border border-amber-300/30 bg-amber-300/10 p-4" role="alert">
          <p className="text-sm text-amber-100">Recent activity is unavailable right now. Try again.</p>
          <button
            type="button"
            onClick={activity.retry}
            className="mt-3 inline-flex items-center gap-2 rounded-md border border-amber-200/40 px-3 py-2 text-sm font-medium text-amber-50 hover:bg-amber-200/10"
          >
            <ArrowPathIcon className="h-4 w-4" aria-hidden="true" />
            Try again
          </button>
        </div>
      )}

      {!activity.loading && sameOrg && !activity.error && !hasItems && (
        <p className="mt-5 rounded-lg border border-white/10 bg-white/[0.03] p-4 text-sm text-slate-300">
          {emptyCopy}
        </p>
      )}

      {hasItems && (
        <>
          {activity.error && (
            <p className="mt-4 text-sm text-slate-400" role="status">
              Activity is shown, but your last-seen marker could not be updated.
            </p>
          )}
          <ol className="mt-4 space-y-3" aria-label="Recent activity">
            {activity.items.map((item, index) => (
              <li key={`${item.source}-${item.timestamp}-${item.href}-${index}`}>
                <a
                  href={item.href}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-start gap-3 rounded-xl border border-white/10 bg-white/[0.04] p-4 transition hover:border-cyan-200/40 hover:bg-white/[0.08]"
                >
                  <span className="mt-1 h-2.5 w-2.5 flex-none rounded-full bg-cyan-300" aria-hidden="true" />
                  <span className="min-w-0 flex-1">
                    <span className="block text-sm font-medium text-white">{item.label}</span>
                    <span className="mt-1 block text-xs text-slate-400">
                      {item.source === 'project-ops' ? 'Project-Ops' : 'Meeting-Ops'}
                      {', '}
                      <time dateTime={item.timestamp}>{formatActivityTime(item.timestamp)}</time>
                    </span>
                  </span>
                  <span className="text-sm text-cyan-200">Open</span>
                </a>
              </li>
            ))}
          </ol>
        </>
      )}
    </section>
  );
}
