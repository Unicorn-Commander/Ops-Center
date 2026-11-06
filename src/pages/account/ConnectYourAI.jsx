/**
 * Signed-in Connect your AI page.
 * Lists each app's MCP URL and a copyable recipe per client.
 * The route sits under /admin, behind the console session.
 */

import React, { useEffect, useRef, useState } from 'react';
import { ClipboardDocumentIcon } from '@heroicons/react/24/outline';
import { useTheme } from '../../contexts/ThemeContext';
import { buildClientRecipes, claudeCodeCommand, getMcpApps } from '../../config/mcpApps';

function CopyButton({ label, copied, onClick, className }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium ${className}`}
    >
      <ClipboardDocumentIcon className="h-4 w-4 shrink-0" aria-hidden="true" />
      {copied ? 'Copied' : 'Copy'}
    </button>
  );
}

export default function ConnectYourAI() {
  const { theme } = useTheme();
  const apps = getMcpApps();
  const recipes = buildClientRecipes(apps);
  const tokenOnly = apps.filter((app) => !app.oauth).map((app) => app.name);
  const [copiedId, setCopiedId] = useState('');
  const [copyError, setCopyError] = useState('');
  const timer = useRef(null);

  useEffect(() => () => clearTimeout(timer.current), []);

  const onCopy = async (id, text) => {
    try {
      if (!navigator.clipboard?.writeText) {
        throw new Error('clipboard unavailable');
      }
      await navigator.clipboard.writeText(text);
      setCopyError('');
      setCopiedId(id);
      clearTimeout(timer.current);
      timer.current = setTimeout(() => setCopiedId(''), 2000);
    } catch {
      setCopiedId('');
      setCopyError('Copy failed. Select the text and copy it manually.');
    }
  };

  return (
    <div className="min-w-0 max-w-full space-y-6">
      <header className="min-w-0">
        <h1 className={`text-3xl font-bold ${theme.text.primary}`}>Connect your AI</h1>
        <p className={`mt-2 max-w-3xl ${theme.text.secondary}`}>
          Your AI signs in as you. Nothing of yours routes through our model bill.
        </p>
      </header>

      <section className={`min-w-0 rounded-xl p-4 sm:p-6 ${theme.card}`} aria-labelledby="connect-clients-heading">
        <h2 id="connect-clients-heading" className={`text-xl font-semibold ${theme.text.primary}`}>
          How to connect
        </h2>
        <p className={`mt-2 ${theme.text.secondary}`}>
          Paste one app URL from the table. OAuth apps sign in with your Unicorn Commander account.
        </p>
        {tokenOnly.length > 0 && (
          <p className={`mt-2 ${theme.text.secondary}`}>
            Token only for now: {tokenOnly.join(', ')}. Use the token location in the table for those.
          </p>
        )}
        {copyError && (
          <p className={`mt-2 text-sm ${theme.status.error}`} role="status">{copyError}</p>
        )}
        <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
          {recipes.map((recipe) => (
            <article key={recipe.id} className="min-w-0 rounded-lg bg-black/10 p-4">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <h3 className={`text-base font-semibold ${theme.text.primary}`}>{recipe.title}</h3>
                <CopyButton
                  label={`Copy ${recipe.title} recipe`}
                  copied={copiedId === recipe.id}
                  onClick={() => onCopy(recipe.id, recipe.copyText)}
                  className={theme.button}
                />
              </div>
              <pre className={`mt-3 whitespace-pre-wrap break-all font-mono text-xs sm:text-sm ${theme.text.secondary}`}>
                {recipe.body}
              </pre>
            </article>
          ))}
        </div>
      </section>

      <section className={`min-w-0 max-w-full rounded-xl p-4 sm:p-6 ${theme.card}`} aria-labelledby="connect-apps-heading">
        <h2 id="connect-apps-heading" className={`text-xl font-semibold ${theme.text.primary}`}>
          Apps
        </h2>
        <ul className="mt-4 min-w-0 divide-y divide-white/10">
          {apps.map((app) => {
            const command = claudeCodeCommand(app);
            return (
              <li key={app.slug} className="min-w-0 max-w-full py-4 first:pt-0 last:pb-0">
                <div className="flex min-w-0 flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className={`text-base font-semibold ${theme.text.primary}`}>{app.name}</h3>
                      <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                        app.oauth ? theme.status.success : theme.status.warning
                      }`}>
                        {app.oauth ? 'OAuth' : 'Token only'}
                      </span>
                    </div>
                    <p className={`mt-2 break-all font-mono text-xs sm:text-sm ${theme.text.primary}`}>{app.url}</p>
                    <p className={`mt-2 text-sm ${theme.text.secondary}`}>
                      <span className="font-medium">Token: </span>
                      <span>{app.tokenLocation}</span>
                    </p>
                    <p className={`mt-2 break-all font-mono text-xs ${theme.text.secondary}`}>{command}</p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <CopyButton
                      label={`Copy ${app.name} MCP URL`}
                      copied={copiedId === `${app.slug}-url`}
                      onClick={() => onCopy(`${app.slug}-url`, app.url)}
                      className={theme.button}
                    />
                    <CopyButton
                      label={`Copy ${app.name} Claude Code command`}
                      copied={copiedId === `${app.slug}-cmd`}
                      onClick={() => onCopy(`${app.slug}-cmd`, command)}
                      className={theme.button}
                    />
                  </div>
                </div>
              </li>
            );
          })}
        </ul>
      </section>
    </div>
  );
}
