import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AppMark, ExtLink, ModuleFrame, TypePill, useRowPresence } from './HomeParts';
import { newIdempotencyKey, sendAction } from './homeApi';
import {
  appInfo, hueVar, itemApp, itemType, offeredActions, openAction, pendingText, PRIMARY_ACTIONS, proposerName, whenLabel
} from './homeModel';

// ------------------------------------------------------------- actions

/**
 * Home actions on a row (DESIGN h, wow moment 2): buttons come only from the
 * item's own actions list. A click gets a fresh Idempotency-Key; "Try again"
 * after a problem resends that same click with the same key. The receipt's
 * plain message is shown in the row, in a polite live region.
 */
export function useItemActions({ fetchImpl, onDone, announce }) {
  const [states, setStates] = useState({});
  const statesRef = useRef(states);
  statesRef.current = states;
  // Set synchronously, so a second fast click on the same row never mints a second key.
  const inflight = useRef(new Set());

  const run = useCallback(async (item, action, { again = false } = {}) => {
    const previous = statesRef.current[item.id];
    if (previous?.phase === 'pending' || inflight.current.has(item.id)) return;
    inflight.current.add(item.id);
    const key = again && previous?.key && previous.actionId === action.id ? previous.key : newIdempotencyKey();
    setStates(s => ({ ...s, [item.id]: { phase: 'pending', actionId: action.id, key, message: pendingText(item, action) } }));
    announce?.(`${pendingText(item, action)}: ${item.title}`);
    let result;
    try {
      result = await sendAction(action.href, key, { fetchImpl });
    } finally {
      inflight.current.delete(item.id);
    }
    announce?.(result.message || '');
    setStates(s => ({
      ...s,
      [item.id]: { phase: result.outcome, actionId: action.id, key, message: result.message, retry: Boolean(result.retry) }
    }));
    if (result.outcome === 'done') onDone?.(item, action, result);
  }, [fetchImpl, onDone, announce]);

  return { states, run };
}

/** After a done receipt the row stays 1.6 s so the person can read it, then leaves (DESIGN h). */
export function useResolvedRows(onResolved) {
  const [resolved, setResolved] = useState(() => new Set());
  const timers = useRef([]);
  useEffect(() => () => timers.current.forEach(clearTimeout), []);
  const onDone = useCallback((item) => {
    timers.current.push(setTimeout(() => {
      setResolved(previous => new Set(previous).add(item.id));
      onResolved?.(item);
    }, 1600));
  }, [onResolved]);
  return { resolved, onDone };
}

export function RowActions({ item, state, run, compact = false }) {
  const open = openAction(item);
  const offered = offeredActions(item);
  const size = compact ? ' is-sm' : '';
  if (state?.phase === 'pending' || state?.phase === 'done') {
    return (
      <div className="uh-acts">
        <span className={`uh-receipt is-${state.phase}`}>{state.message || (state.phase === 'done' ? 'Done.' : '')}</span>
      </div>
    );
  }
  const offeredAction = offered.find(a => a.id === state?.actionId);
  return (
    <div className="uh-acts">
      {state?.phase === 'problem' && state.retry && offeredAction && (
        <button type="button" className={`uh-btn${size}`} onClick={() => run(item, offeredAction, { again: true })}>Try again</button>
      )}
      {open && <ExtLink className={`uh-btn${size}`} href={open.href}>{open.label || 'Open'}</ExtLink>}
      {offered.filter(a => !PRIMARY_ACTIONS.has(a.id)).map(action => (
        <button key={action.id} type="button" className={`uh-btn is-quiet${size}`} title={action.note || undefined} onClick={() => run(item, action)}>
          {action.label}
        </button>
      ))}
      {offered.filter(a => PRIMARY_ACTIONS.has(a.id)).map(action => (
        <button
          key={action.id}
          type="button"
          className={`uh-btn is-primary${size}`}
          title={action.note || undefined}
          aria-describedby={action.note ? `uh-note-${action.id}-${item.id}` : undefined}
          data-primary-action="true"
          onClick={() => run(item, action)}
        >
          {action.label}
          {action.note && <span className="uh-sr" id={`uh-note-${action.id}-${item.id}`}>{action.note}</span>}
        </button>
      ))}
    </div>
  );
}

/**
 * A receipt the row keeps (refused, failed, reauth, or a problem with no
 * receipt) is a line under the title, so the buttons keep their places.
 */
export function ReceiptLine({ state }) {
  if (!state || !['refused', 'failed', 'reauth', 'problem'].includes(state.phase)) return null;
  return (
    <div className={`uh-receipt-line is-${state.phase === 'problem' ? 'failed' : state.phase}`}>
      {state.message}
      {state.phase === 'reauth' && <> <a className="uh-link no-accent" href="/admin/login?next=%2Fdashboard">Sign in</a></>}
    </div>
  );
}

export function rowClass(row, extra = '') {
  return `uh-row${extra}${row.state === 'new' ? ' is-new' : ''}${row.state === 'leaving' ? ' is-leaving' : ''}`;
}

// ------------------------------------------------------------- needs you

export function NeedsYou({ mod, tz, nowIso, fetchImpl, onResolved, currentId, setCurrentId, onRetry, lastGood, loading, announce }) {
  const { resolved, onDone } = useResolvedRows(onResolved);
  const { states, run } = useItemActions({ fetchImpl, onDone, announce });
  const items = useMemo(() => (mod.items || []).filter(item => !resolved.has(item.id)), [mod.items, resolved]);
  const rows = useRowPresence(items, item => item.id);
  const hidden = (mod.items || []).length - items.length;
  const count = typeof mod.count === 'number' ? Math.max(0, mod.count - hidden) : null;
  const countLabel = count === null ? '' : `${count}${mod.count_is_lower_bound ? '+' : ''}`;
  const visible = rows.filter(row => row.state !== 'leaving').length;
  const status = mod.status === 'ok' && count === 0 && visible === 0 ? 'empty' : mod.status;

  return (
    <ModuleFrame mod={{ ...mod, status }} tz={tz} count={countLabel} onRetry={onRetry} lastGood={lastGood} loading={loading}>
      {status === 'ok' && (
        <>
          <div className="uh-list" id="uh-needs-list">
            {rows.map(row => {
              const item = row.item;
              const app = itemApp(item);
              const info = appInfo(app);
              const who = proposerName(item.proposed_by);
              const extra = item.summary?.text || item.preview?.text || (item.to ? `to ${item.to}` : '');
              const when = whenLabel(item.created_at, tz, nowIso);
              return (
                <div
                  key={row.key}
                  className={`${rowClass(row)}${currentId === item.id ? ' is-current' : ''}`}
                  style={{ '--uh-ac': hueVar(info.hue) }}
                  data-item={item.id}
                  tabIndex={-1}
                  onFocus={() => setCurrentId?.(item.id)}
                >
                  <AppMark app={app} />
                  <TypePill>{itemType(item, 'needs_you')}</TypePill>
                  <div className="uh-what">
                    <div className="uh-t">{item.title}</div>
                    <div className="uh-s">
                      <span className="uh-s-app">{info.label}</span>
                      {who.name ? <>{' · '}{item.scope === 'workspace' ? 'from ' : 'by '}{who.name}{who.agent && <>{' '}<span className="uh-agentname">(agent)</span></>}</> : null}
                      {when ? `, ${when}` : ''}
                      {extra && <span className="uh-s-src">{' · '}{extra}</span>}
                    </div>
                    <ReceiptLine state={states[item.id]} />
                  </div>
                  <RowActions item={item} state={states[item.id]} run={run} />
                </div>
              );
            })}
          </div>
          {visible === 0 && <p className="uh-empty">Nothing needs you.</p>}
          {visible > 0 && (
            <div className="uh-foot">
              <span className="uh-keyhint"><span className="uh-kbd">J</span> <span className="uh-kbd">K</span> move</span>
              <span className="uh-keyhint"><span className="uh-kbd">A</span> approve</span>
              <span className="uh-keyhint"><span className="uh-kbd">O</span> open</span>
              <span className="uh-push">Approvals from your apps and agents wait here until you decide</span>
            </div>
          )}
        </>
      )}
    </ModuleFrame>
  );
}
