import React, { useState } from 'react';
import { ArrowTopRightOnSquareIcon, LinkIcon, ServerIcon } from '@heroicons/react/24/outline';
import ConnectAiPanel from './ConnectAiPanel';

const STATE_LABELS = {
  ready: 'Ready',
  needs_first_open: 'Needs first open'
};

export default function EntitledAppCard({ app, index = 0, compact = false }) {
  const [isConnectOpen, setIsConnectOpen] = useState(false);

  if (!app || app.state === 'not_entitled') return null;

  const primary = app.primary_action || {
    label: `Open ${app.name}`,
    url: app.launch_url
  };
  const stateLabel = STATE_LABELS[app.state] || STATE_LABELS.ready;
  const purpose = app.purpose || app.description || 'Workspace access for this app.';
  const companion = app.companion;
  const gradient = [
    'from-slate-950 to-cyan-800',
    'from-indigo-950 to-violet-800',
    'from-slate-900 to-emerald-800',
    'from-blue-950 to-rose-800'
  ][index % 4];

  return (
    <article
      className="group flex min-h-[270px] flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm transition hover:-translate-y-1 hover:shadow-xl"
      data-testid={`app-card-${app.slug}`}
    >
      <div className={`relative bg-gradient-to-br ${gradient} p-5 text-white`}>
        <div className="flex items-start justify-between gap-3">
          <div className="flex h-14 w-14 items-center justify-center rounded-xl bg-white/95 p-2 shadow-lg">
            {app.icon_url ? (
              <img src={app.icon_url} alt={`${app.name} icon`} className="h-full w-full object-contain" />
            ) : (
              <ServerIcon className="h-8 w-8 text-slate-700" aria-hidden="true" />
            )}
          </div>
          <span className="rounded-full border border-white/20 bg-white/10 px-2.5 py-1 text-xs font-semibold">
            {stateLabel}
          </span>
        </div>
        <h3 className="mt-5 text-xl font-bold tracking-tight">{app.name}</h3>
      </div>

      <div className="flex flex-1 flex-col p-5">
        <p className="min-h-[3rem] text-sm leading-6 text-slate-600">{purpose}</p>

        <div className={`mt-5 flex flex-wrap gap-2 ${compact ? 'sm:flex-col' : ''}`}>
          <a
            href={primary.url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex flex-1 items-center justify-center gap-2 rounded-lg bg-slate-900 px-3 py-2.5 text-sm font-semibold text-white transition hover:bg-cyan-800 focus:outline-none focus:ring-2 focus:ring-cyan-500 focus:ring-offset-2"
          >
            {primary.label}
            <ArrowTopRightOnSquareIcon className="h-4 w-4" aria-hidden="true" />
          </a>
          {companion && (
            <button
              type="button"
              onClick={() => setIsConnectOpen(true)}
              className="inline-flex flex-1 items-center justify-center gap-2 rounded-lg border border-cyan-700 px-3 py-2.5 text-sm font-semibold text-cyan-800 transition hover:bg-cyan-50 focus:outline-none focus:ring-2 focus:ring-cyan-500 focus:ring-offset-2"
              aria-label={`Connect your AI to ${app.name}`}
            >
              <LinkIcon className="h-4 w-4" aria-hidden="true" />
              Connect your AI
            </button>
          )}
        </div>

        {(companion?.desktop?.length > 0 || companion?.mobile?.length > 0) && (
          <div className="mt-4 flex flex-wrap gap-x-4 gap-y-2 border-t border-slate-100 pt-3 text-xs">
            {companion.desktop?.map((link) => (
              <a key={`${link.label}-${link.url}`} href={link.url} target="_blank" rel="noopener noreferrer" className="text-cyan-700 underline">
                {link.label}
              </a>
            ))}
            {companion.mobile?.map((link) => (
              <a key={`${link.label}-${link.url}`} href={link.url} target="_blank" rel="noopener noreferrer" className="text-cyan-700 underline">
                {link.label}
              </a>
            ))}
          </div>
        )}
      </div>

      {isConnectOpen && (
        <ConnectAiPanel app={app} onClose={() => setIsConnectOpen(false)} />
      )}
    </article>
  );
}
