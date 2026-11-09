import React, { useEffect, useMemo, useState } from 'react';
import {
  ClipboardDocumentIcon,
  ComputerDesktopIcon,
  DevicePhoneMobileIcon,
  XMarkIcon
} from '@heroicons/react/24/outline';

function CopyButton({ label, value, copiedKey, onCopy, copyKey }) {
  return (
    <button
      type="button"
      onClick={() => onCopy(copyKey, value)}
      aria-label={label}
      className="inline-flex shrink-0 items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-800 transition hover:border-cyan-500 hover:text-cyan-700 focus:outline-none focus:ring-2 focus:ring-cyan-500 focus:ring-offset-2"
    >
      <ClipboardDocumentIcon className="h-4 w-4" aria-hidden="true" />
      {copiedKey === copyKey ? 'Copied' : 'Copy'}
    </button>
  );
}

export default function ConnectAiPanel({ app, onClose }) {
  const [copiedKey, setCopiedKey] = useState('');
  const [copyError, setCopyError] = useState('');
  const clientConfig = useMemo(
    () => JSON.stringify(app.companion?.client_config || {}, null, 2),
    [app.companion]
  );

  useEffect(() => {
    const onKeyDown = (event) => {
      if (event.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [onClose]);

  const onCopy = async (copyKey, value) => {
    try {
      if (!navigator.clipboard?.writeText) throw new Error('Clipboard unavailable');
      await navigator.clipboard.writeText(value);
      setCopyError('');
      setCopiedKey(copyKey);
      window.setTimeout(() => setCopiedKey(''), 1800);
    } catch {
      setCopiedKey('');
      setCopyError('Copy failed. Select the text and copy it manually.');
    }
  };

  const companion = app.companion;
  if (!companion) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/70 p-4"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <section
        role="dialog"
        aria-modal="true"
        aria-labelledby="connect-ai-panel-title"
        data-testid="connect-ai-panel"
        className="max-h-[calc(100vh-2rem)] w-full max-w-3xl overflow-y-auto rounded-2xl bg-white p-5 text-slate-900 shadow-2xl sm:p-7"
      >
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-sm font-semibold uppercase tracking-wide text-cyan-700">Connect your AI</p>
            <h2 id="connect-ai-panel-title" className="mt-1 text-2xl font-bold">
              Connect your AI to {app.name}
            </h2>
            <p className="mt-2 text-sm text-slate-600">
              Use the endpoint below with an MCP client that you control. Sign in or add the app token when the client asks.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close connect your AI panel"
            className="rounded-lg p-2 text-slate-500 transition hover:bg-slate-100 hover:text-slate-900 focus:outline-none focus:ring-2 focus:ring-cyan-500"
          >
            <XMarkIcon className="h-6 w-6" aria-hidden="true" />
          </button>
        </div>

        {copyError && (
          <p className="mt-4 rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-700" role="status">
            {copyError}
          </p>
        )}

        <div className="mt-6 space-y-5">
          <section className="rounded-xl border border-slate-200 bg-slate-50 p-4" aria-labelledby="claude-code-heading">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h3 id="claude-code-heading" className="font-semibold">Claude Code</h3>
                <p className="mt-1 text-sm text-slate-600">Run this command in your terminal.</p>
              </div>
              <CopyButton
                label={`Copy ${app.name} Claude Code command`}
                value={companion.claude_code_command}
                copiedKey={copiedKey}
                onCopy={onCopy}
                copyKey="claude-code"
              />
            </div>
            <pre className="mt-3 overflow-x-auto rounded-lg bg-slate-900 p-3 text-xs leading-6 text-cyan-100" tabIndex="0">
              {companion.claude_code_command}
            </pre>
          </section>

          <section className="rounded-xl border border-slate-200 bg-slate-50 p-4" aria-labelledby="other-clients-heading">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h3 id="other-clients-heading" className="font-semibold">Other MCP clients</h3>
                <p className="mt-1 text-sm text-slate-600">Paste this JSON into a client that supports an mcpServers configuration.</p>
              </div>
              <CopyButton
                label={`Copy ${app.name} MCP client JSON`}
                value={clientConfig}
                copiedKey={copiedKey}
                onCopy={onCopy}
                copyKey="client-json"
              />
            </div>
            <pre
              className="mt-3 max-h-56 overflow-auto rounded-lg bg-slate-900 p-3 text-xs leading-6 text-emerald-100"
              aria-label="JSON configuration for other MCP clients"
              tabIndex="0"
            >
              {clientConfig}
            </pre>
          </section>

          <section className="rounded-xl border border-slate-200 bg-slate-50 p-4" aria-labelledby="chatgpt-heading">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <h3 id="chatgpt-heading" className="font-semibold">ChatGPT connector URL</h3>
                <a
                  href={companion.chatgpt_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="mt-2 block break-all font-mono text-xs text-cyan-700 underline"
                >
                  {companion.chatgpt_url}
                </a>
              </div>
              <CopyButton
                label={`Copy ${app.name} ChatGPT connector URL`}
                value={companion.chatgpt_url}
                copiedKey={copiedKey}
                onCopy={onCopy}
                copyKey="chatgpt-url"
              />
            </div>
            <p className="mt-2 text-sm text-slate-600">Add the URL in ChatGPT under Settings, Connectors, and developer mode.</p>
          </section>

          {(companion.desktop?.length > 0 || companion.mobile?.length > 0) && (
            <section className="grid gap-4 sm:grid-cols-2" aria-label="Companion apps">
              {companion.desktop?.length > 0 && (
                <div className="rounded-xl border border-slate-200 p-4">
                  <h3 className="flex items-center gap-2 font-semibold">
                    <ComputerDesktopIcon className="h-5 w-5 text-cyan-700" aria-hidden="true" />
                    Desktop apps
                  </h3>
                  <ul className="mt-3 space-y-2">
                    {companion.desktop.map((link) => (
                      <li key={`${link.label}-${link.url}`}>
                        <a className="text-sm text-cyan-700 underline" href={link.url} target="_blank" rel="noopener noreferrer">
                          {link.label}
                        </a>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {companion.mobile?.length > 0 && (
                <div className="rounded-xl border border-slate-200 p-4">
                  <h3 className="flex items-center gap-2 font-semibold">
                    <DevicePhoneMobileIcon className="h-5 w-5 text-cyan-700" aria-hidden="true" />
                    Mobile apps
                  </h3>
                  <ul className="mt-3 space-y-2">
                    {companion.mobile.map((link) => (
                      <li key={`${link.label}-${link.url}`}>
                        <a className="text-sm text-cyan-700 underline" href={link.url} target="_blank" rel="noopener noreferrer">
                          {link.label}
                        </a>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </section>
          )}
        </div>
      </section>
    </div>
  );
}
