import { useCallback, useEffect, useRef, useState } from 'react';
import {
  advanceDashboardCursor,
  fetchDashboardActivity,
  fetchDashboardCursor,
  latestActivityTimestamp
} from './dashboardActivityAdapter';

const EMPTY_RESULT = {
  items: [],
  complete: true,
  sourceStatus: {},
  errors: {}
};
const EMPTY_ADAPTER_OPTIONS = {};

function readCursorPayload(value) {
  if (value && typeof value === 'object') {
    return {
      lastSeenAt: value.lastSeenAt || value.last_seen_at || null,
      serverNow: value.serverNow || value.server_now || null
    };
  }
  return { lastSeenAt: value || null, serverNow: null };
}

export function useDashboardActivity({
  orgId,
  activityAdapter = fetchDashboardActivity,
  cursorReader = fetchDashboardCursor,
  cursorWriter = advanceDashboardCursor,
  adapterOptions = EMPTY_ADAPTER_OPTIONS
}) {
  const [state, setState] = useState({
    ...EMPTY_RESULT,
    loading: Boolean(orgId),
    error: null,
    cursor: null,
    loadedOrgId: orgId || null,
    cursorReady: false,
    cursorSaving: false
  });
  const [reloadKey, setReloadKey] = useState(0);
  const advancedTimestamp = useRef(null);

  useEffect(() => {
    let cancelled = false;
    advancedTimestamp.current = null;

    if (!orgId) {
      setState({
        ...EMPTY_RESULT,
        loading: false,
        error: null,
        cursor: null,
        loadedOrgId: null,
        cursorReady: false,
        cursorSaving: false
      });
      return () => {
        cancelled = true;
      };
    }

    setState(previous => ({
      ...EMPTY_RESULT,
      loading: true,
      error: null,
      cursor: null,
      loadedOrgId: null,
      cursorReady: false,
      cursorSaving: false,
      sourceStatus: previous.sourceStatus
    }));

    async function load() {
      let cursor = null;
      let serverNow = null;
      let cursorReady = false;
      let cursorError = null;

      try {
        const payload = readCursorPayload(await cursorReader(orgId));
        cursor = payload.lastSeenAt;
        serverNow = payload.serverNow;
        cursorReady = true;
      } catch (error) {
        cursorError = error;
      }

      try {
        const result = await activityAdapter({
          orgId,
          cursor,
          ...adapterOptions
        });
        if (cancelled) return;

        const anyReady = Object.values(result.sourceStatus || {}).includes('ready');
        const totalFailure = !result.complete && !anyReady && result.items.length === 0;

        setState({
          ...result,
          loading: false,
          error: cursorError || (totalFailure
            ? new Error('Activity sources are unavailable')
            : null),
          cursor,
          serverNow,
          loadedOrgId: orgId,
          cursorReady,
          cursorSaving: false
        });
      } catch (error) {
        if (cancelled) return;
        setState({
          ...EMPTY_RESULT,
          loading: false,
          error: cursorError || error,
          cursor,
          serverNow,
          loadedOrgId: orgId,
          cursorReady,
          cursorSaving: false
        });
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, [activityAdapter, cursorReader, adapterOptions, orgId, reloadKey]);

  useEffect(() => {
    if (
      !orgId
      || state.loading
      || !state.cursorReady
      || !state.complete
    ) {
      return undefined;
    }

    // A complete empty feed still moves the marker to the server clock so the
    // next visit does not replay the same empty window. A source that is down
    // leaves the marker where it is, or items from the outage would be skipped.
    const nextTimestamp = state.items.length > 0
      ? latestActivityTimestamp(state.items)
      : state.serverNow;
    if (!nextTimestamp || advancedTimestamp.current === nextTimestamp) return undefined;

    let cancelled = false;
    advancedTimestamp.current = nextTimestamp;
    setState(previous => ({ ...previous, cursorSaving: true }));

    cursorWriter(orgId, nextTimestamp)
      .then(() => {
        if (cancelled) return;
        setState(previous => ({
          ...previous,
          cursorSaving: false
        }));
      })
      .catch(error => {
        if (cancelled) return;
        advancedTimestamp.current = null;
        setState(previous => ({ ...previous, cursorSaving: false, error }));
      });

    return () => {
      cancelled = true;
    };
  }, [cursorWriter, orgId, state.complete, state.cursorReady, state.items, state.loading, state.serverNow]);

  const retry = useCallback(() => setReloadKey(key => key + 1), []);

  return { ...state, retry };
}
