import { useCallback, useEffect, useRef, useState } from 'react';
import { fetchState, rememberSeen, writeCache } from './homeApi';

export const REFRESH_MS = 60000;
const FOCUS_REFETCH_MS = 10000;

function pageVisible() {
  return typeof document === 'undefined' || document.visibilityState !== 'hidden';
}

/**
 * Live data (DESIGN section m). The page has a document from the first read
 * (or from the cache, labelled with its time). It reads the state again every
 * 60 seconds while the tab is visible, at once when the tab becomes visible or
 * the window regains focus, and stops while the tab is hidden. A failed read
 * keeps the last good document on screen and marks the page stale; a 404 means
 * the home was switched off, and the caller falls back to the old dashboard.
 *
 * live: 'live' (refreshing), 'paused' (tab hidden), 'stale' (last read failed,
 * or the document is older than three cycles), 'cached' (painted from the
 * cache, the first read still on its way).
 */
export default function useHomeState({
  initialDoc,
  fromCache = false,
  fetchImpl = globalThis.fetch,
  onOff = () => {},
  prepare,
  intervalMs = REFRESH_MS,
  now = () => Date.now()
}) {
  const [doc, setDoc] = useState(initialDoc);
  const [live, setLive] = useState(fromCache ? 'cached' : pageVisible() ? 'live' : 'paused');
  const [loading, setLoading] = useState(false);
  const [lastGoodAt, setLastGoodAt] = useState(fromCache ? null : now());
  const etagRef = useRef(null);
  const timerRef = useRef(null);
  const inflightRef = useRef(null);
  const lastFetchRef = useRef(fromCache ? 0 : now());
  const mountedRef = useRef(true);
  const firstDoneRef = useRef(!fromCache);
  const onOffRef = useRef(onOff);
  onOffRef.current = onOff;

  const clearTimer = () => {
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = null;
  };

  const refresh = useCallback(async () => {
    if (!mountedRef.current) return undefined;
    if (inflightRef.current) return inflightRef.current;
    const run = (async () => {
      lastFetchRef.current = now();
      setLoading(true);
      let result;
      try {
        result = await fetchState({ fetchImpl, etag: etagRef.current });
      } catch {
        result = { kind: 'error', status: 0 };
      }
      if (!mountedRef.current) return;
      setLoading(false);
      if (result.kind === 'ok') {
        etagRef.current = result.etag;
        setDoc(result.doc);
        setLastGoodAt(now());
        writeCache(result.doc);
        if (pageVisible()) rememberSeen(result.doc);
        setLive(pageVisible() ? 'live' : 'paused');
      } else if (result.kind === 'not-modified') {
        setLastGoodAt(now());
        setLive(pageVisible() ? 'live' : 'paused');
      } else if (result.kind === 'off' || (!firstDoneRef.current && result.status >= 400 && result.status < 500 && result.status !== 408 && result.status !== 429)) {
        // 404: the home was switched off. The first read after a cached paint
        // that is refused (signed out, no organization) also goes back to the
        // dashboard the person would otherwise see.
        onOffRef.current();
      } else {
        setLive('stale');
      }
      firstDoneRef.current = true;
    })();
    inflightRef.current = run;
    try {
      await run;
    } finally {
      inflightRef.current = null;
    }
    return undefined;
  }, [fetchImpl, now]);

  const schedule = useCallback(() => {
    clearTimer();
    if (!pageVisible()) return;
    timerRef.current = setTimeout(async () => {
      await refresh();
      if (mountedRef.current) schedule();
    }, intervalMs);
  }, [intervalMs, refresh]);

  useEffect(() => {
    mountedRef.current = true;
    if (fromCache) {
      Promise.resolve(prepare ? prepare() : null)
        .catch(() => null)
        .then(() => refresh())
        .then(() => mountedRef.current && schedule());
    } else {
      if (initialDoc) rememberSeen(initialDoc);
      schedule();
    }
    const onVisibility = () => {
      if (!pageVisible()) {
        clearTimer();
        setLive(current => (current === 'stale' ? current : 'paused'));
        return;
      }
      refresh().then(() => mountedRef.current && schedule());
    };
    const onFocus = () => {
      if (pageVisible() && now() - lastFetchRef.current > FOCUS_REFETCH_MS) {
        refresh().then(() => mountedRef.current && schedule());
      }
    };
    document.addEventListener('visibilitychange', onVisibility);
    window.addEventListener('focus', onFocus);
    return () => {
      mountedRef.current = false;
      clearTimer();
      document.removeEventListener('visibilitychange', onVisibility);
      window.removeEventListener('focus', onFocus);
    };
    // The cycle is set up once per mount; refresh and schedule are stable.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const retry = useCallback(async () => {
    await refresh();
    if (mountedRef.current) schedule();
  }, [refresh, schedule]);

  // Older than three cycles counts as stale even if no read failed (a sleeping laptop).
  const old = live === 'live' && lastGoodAt && now() - lastGoodAt > intervalMs * 3 + 5000;
  return { doc, live: old ? 'stale' : live, loading, lastGoodAt, retry };
}
