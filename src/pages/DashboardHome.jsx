import React, { lazy, Suspense, useCallback, useEffect, useState } from 'react';
import LoadingScreen from '../components/LoadingScreen';
import { OrganizationProvider } from '../contexts/OrganizationContext';
import { clearCache, fetchState, readCache, sendSeen, writeCache } from '../components/home/homeApi';

const PublicLanding = lazy(() => import('./PublicLanding'));
const HomePage = lazy(() => import('./HomePage'));

/**
 * /dashboard. The new home renders when GET /api/v1/home/state answers 200
 * with a home-state document. When it answers 404 (HOME_STATE_ENABLED off) or
 * fails, the current dashboard renders exactly as before, so shipping this
 * changes nothing until the flag is on for a ring.
 *
 * A person who saw the new home recently gets the first paint from the cached
 * document (labelled with its time) while the live one loads.
 */
export default function DashboardHome({ fetchImpl = globalThis.fetch }) {
  const [view, setView] = useState(() => {
    const cached = readCache();
    return cached ? { phase: 'home', doc: cached, fromCache: true } : { phase: 'probe' };
  });

  useEffect(() => {
    if (view.phase !== 'probe') return undefined;
    let cancelled = false;
    (async () => {
      await sendSeen({ fetchImpl });
      let result;
      try {
        result = await fetchState({ fetchImpl });
      } catch {
        result = { kind: 'error', status: 0 };
      }
      if (cancelled) return;
      if (result.kind === 'ok') {
        writeCache(result.doc);
        setView({ phase: 'home', doc: result.doc, fromCache: false });
      } else {
        if (result.kind === 'off') clearCache();
        setView({ phase: 'legacy' });
      }
    })();
    return () => {
      cancelled = true;
    };
    // The probe runs once per visit.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const fallBack = useCallback(() => {
    clearCache();
    setView({ phase: 'legacy' });
  }, []);

  if (view.phase === 'probe') return <LoadingScreen />;
  if (view.phase === 'legacy') {
    return (
      <Suspense fallback={<LoadingScreen />}>
        <PublicLanding />
      </Suspense>
    );
  }
  return (
    <Suspense fallback={<LoadingScreen />}>
      <OrganizationProvider>
        <HomePage
          initialDoc={view.doc}
          fromCache={view.fromCache}
          onOff={fallBack}
          prepare={view.fromCache ? () => sendSeen({ fetchImpl }) : undefined}
          fetchImpl={fetchImpl}
        />
      </OrganizationProvider>
    </Suspense>
  );
}
