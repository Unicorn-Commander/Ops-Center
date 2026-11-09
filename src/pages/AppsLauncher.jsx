import React, { useEffect, useState } from 'react';
import EntitledAppCard from '../components/EntitledAppCard';

const APPS_ENDPOINT = '/api/v1/my-apps/authorized';

export default function AppsLauncher() {
  const [apps, setApps] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    let isCurrent = true;

    const loadApps = async () => {
      setIsLoading(true);
      setError('');

      try {
        const response = await fetch(APPS_ENDPOINT, {
          credentials: 'include',
          signal: controller.signal
        });
        if (!response.ok) throw new Error('authorized apps request failed');

        const data = await response.json();
        if (!Array.isArray(data)) throw new Error('authorized apps response was invalid');
        if (isCurrent) setApps(data.filter((app) => app?.state !== 'not_entitled'));
      } catch (loadError) {
        if (loadError.name === 'AbortError' || !isCurrent) return;
        setApps([]);
        setError('We could not load the apps for this organization. Try again.');
      } finally {
        if (isCurrent) setIsLoading(false);
      }
    };

    loadApps();
    return () => {
      isCurrent = false;
      controller.abort();
    };
  }, [retry]);

  return (
    <main className="min-h-screen bg-slate-50 px-4 py-10 text-slate-900 sm:px-6 lg:px-8">
      <div className="mx-auto max-w-7xl">
        <header className="mb-8">
          <p className="text-sm font-semibold uppercase tracking-wide text-cyan-700">Ops-Center</p>
          <h1 className="mt-2 text-3xl font-bold tracking-tight sm:text-4xl">My apps</h1>
          <p className="mt-2 max-w-2xl text-slate-600">
            Apps available to your organization, with the tools you need to open and connect each one.
          </p>
        </header>

        {isLoading && (
          <div className="rounded-2xl border border-slate-200 bg-white p-10 text-center shadow-sm" role="status">
            <div className="mx-auto h-10 w-10 animate-spin rounded-full border-4 border-slate-200 border-t-cyan-700" />
            <p className="mt-4 text-sm font-medium text-slate-600">Loading your apps...</p>
          </div>
        )}

        {!isLoading && error && (
          <div className="rounded-2xl border border-rose-200 bg-rose-50 p-8 text-center" role="alert">
            <h2 className="text-xl font-semibold text-rose-900">We could not load your apps</h2>
            <p className="mt-2 text-sm text-rose-800">{error}</p>
            <button
              type="button"
              onClick={() => setRetry((value) => value + 1)}
              className="mt-5 rounded-lg bg-rose-800 px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-rose-900 focus:outline-none focus:ring-2 focus:ring-rose-600 focus:ring-offset-2"
            >
              Try again
            </button>
          </div>
        )}

        {!isLoading && !error && apps.length === 0 && (
          <div className="rounded-2xl border border-slate-200 bg-white p-10 text-center shadow-sm">
            <h2 className="text-xl font-semibold">No apps are available for this organization</h2>
            <p className="mt-2 text-slate-600">Your organization does not currently have access to any apps.</p>
          </div>
        )}

        {!isLoading && !error && apps.length > 0 && (
          <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {apps.map((app, index) => (
              <EntitledAppCard key={app.slug || app.id} app={app} index={index} compact />
            ))}
          </div>
        )}
      </div>
    </main>
  );
}
