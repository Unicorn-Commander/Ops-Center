import React, { useMemo, useState } from 'react';
import Icon from './homeIcons';
import { AppMark, AsOf, ExtLink, ModuleFrame, TypePill, useRowPresence } from './HomeParts';
import { NeedsYou, RowActions, rowClass, useItemActions, useResolvedRows } from './HomeNeedsYou';
import {
  appInfo, appKey, cursorLabel, durationLabel, formatMoney, formatNumber, hhmm, hueVar, itemApp, itemType,
  openAction, parseAmount, plural, whenLabel
} from './homeModel';

// ------------------------------------------------------------- today

export function Today({ mod, tz, nowIso, fetchImpl, onResolved, onRetry, lastGood, loading }) {
  const { resolved, onDone } = useResolvedRows(onResolved);
  const { states, run } = useItemActions({ fetchImpl, onDone });
  const items = useMemo(() => (mod.items || []).filter(item => !resolved.has(item.id)), [mod.items, resolved]);
  const rows = useRowPresence(items, item => item.id);
  const counts = mod.counts || {};
  const parts = [];
  if (counts.tasks_due_today) parts.push(plural(counts.tasks_due_today, 'task due', 'tasks due'));
  if (counts.follow_ups_due) parts.push(plural(counts.follow_ups_due, 'follow-up', 'follow-ups'));
  if (counts.tasks_overdue) parts.push(`${counts.tasks_overdue} overdue`);

  return (
    <ModuleFrame mod={mod} tz={tz} count={parts.join(' · ')} className="is-today" onRetry={onRetry} lastGood={lastGood} loading={loading}>
      {mod.status === 'ok' && (
        <div className="uh-list uh-tnum">
          {rows.map(row => {
            const item = row.item;
            const app = itemApp(item);
            const info = appInfo(app);
            const late = Boolean(item.overdue);
            const time = item.all_day ? 'All day' : (late ? 'Overdue' : hhmm(item.due_at, tz));
            const bits = [];
            if (item.project) bits.push(`project ${item.project}`);
            if (item.kind === 'follow_up') bits.push(late ? `was due ${whenLabel(item.due_at, tz, nowIso)}` : 'follow-up due');
            if (item.stage) bits.push(`stage ${String(item.stage).toLowerCase()}`);
            if (item.priority && String(item.priority).toUpperCase() !== 'MEDIUM') bits.push(`${String(item.priority).toLowerCase()} priority`);
            return (
              <div key={row.key} className={rowClass(row)} style={{ '--uh-ac': hueVar(info.hue) }} data-item={item.id}>
                <span className={`uh-time${late ? ' is-late' : ''}`}>{time || 'Today'}</span>
                <AppMark app={app} />
                <TypePill>{itemType(item, 'today')}</TypePill>
                <div className="uh-what">
                  <div className="uh-t">{item.title}</div>
                  <div className="uh-s">
                    <span className="uh-s-app">{info.label}</span>
                    {bits.length > 0 && <>{' · '}{bits.join(' · ')}</>}
                  </div>
                </div>
                <RowActions item={item} state={states[item.id]} run={run} />
              </div>
            );
          })}
        </div>
      )}
    </ModuleFrame>
  );
}

// ------------------------------------------------------------- meetings

export function Meetings({ mod, tz, nowIso, onRetry, lastGood, loading }) {
  const rows = useRowPresence(mod.items || [], item => item.id);
  return (
    <ModuleFrame mod={mod} tz={tz} onRetry={onRetry} lastGood={lastGood} loading={loading}>
      {mod.status === 'ok' && (
        <>
          <div className="uh-subh">Recent <span className="uh-subh-n">recordings and summaries</span></div>
          <div className="uh-list">
            {rows.map(row => {
              const item = row.item;
              const bits = [whenLabel(item.created_at, tz, nowIso), durationLabel(item.duration_seconds)];
              if (item.speakers) bits.push(plural(item.speakers, 'speaker', 'speakers'));
              if (item.open_action_items) bits.push(plural(item.open_action_items, 'action item', 'action items'));
              if (!item.has_summary) bits.push(item.status === 'processing' ? 'summary in progress' : 'no summary yet');
              const open = openAction(item);
              return (
                <div key={row.key} className={rowClass(row, ' is-compact')} style={{ '--uh-ac': hueVar('violet') }} data-item={item.id}>
                  <AppMark app="meeting-ops" />
                  <div className="uh-what">
                    <div className="uh-t">{item.title}</div>
                    <div className="uh-s uh-tnum"><TypePill>{itemType(item, 'recent_meetings')}</TypePill>{bits.filter(Boolean).join(' · ')}</div>
                  </div>
                  <div className="uh-acts">{open && <ExtLink className="uh-btn is-sm" href={open.href}>{open.label || 'Open'}</ExtLink>}</div>
                </div>
              );
            })}
          </div>
        </>
      )}
    </ModuleFrame>
  );
}

// ------------------------------------------------------------- since

const SINCE_LABELS = {
  meetings_summarized: ['meeting summarized', 'meetings summarized'],
  tasks_closed: ['task closed', 'tasks closed'],
  monitor_updates: ['watched topic update', 'watched topic updates']
};

export function SinceLastVisit({ mod, tz, nowIso, onRetry, lastGood, loading }) {
  const [open, setOpen] = useState(false);
  const cursor = mod.cursor ? cursorLabel(mod.cursor, tz, nowIso) : '';
  const counts = mod.counts || {};
  const capped = new Set(mod.counts_capped || []);
  const shown = Object.keys(SINCE_LABELS).filter(key => counts[key]);
  const empty = mod.cursor ? `Nothing changed since ${cursor}.` : (mod.note || 'This is your first visit, so there is nothing to compare yet.');
  return (
    <ModuleFrame
      mod={mod}
      tz={tz}
      count={cursor}
      emptyText={empty}
      onRetry={onRetry}
      lastGood={lastGood}
      loading={loading}
      metaAct={mod.status === 'ok' && (mod.items || []).length > 0}
      meta={mod.status === 'ok' && (mod.items || []).length > 0 ? (
        <button type="button" className="uh-lnk" aria-expanded={open} aria-controls="uh-since-list" onClick={() => setOpen(v => !v)}>
          {open ? 'Show less' : 'Show all'}
        </button>
      ) : undefined}
    >
      {mod.status === 'ok' && (
        <>
          <div className="uh-since-line uh-tnum">
            {shown.map(key => (
              <span key={key}>
                <span className="uh-since-n">{formatNumber(counts[key])}{capped.has(key) ? '+' : ''}</span>
                <span className="uh-since-l">{counts[key] === 1 ? SINCE_LABELS[key][0] : SINCE_LABELS[key][1]}</span>
              </span>
            ))}
          </div>
          {open && (
            <div className="uh-list uh-since-list" id="uh-since-list">
              {(mod.items || []).map(item => {
                const app = itemApp(item);
                return (
                  <div key={item.id} className="uh-row is-compact" style={{ '--uh-ac': hueVar(appInfo(app).hue) }}>
                    <AppMark app={app} />
                    <div className="uh-what">
                      <div className="uh-t">{item.title}</div>
                      <div className="uh-s"><TypePill>{itemType(item, 'since_last_visit')}</TypePill>{appInfo(app).label}{' · '}{whenLabel(item.at, tz, nowIso)}</div>
                    </div>
                    <div className="uh-acts">{item.href && <ExtLink className="uh-btn is-sm" href={item.href}>Open</ExtLink>}</div>
                  </div>
                );
              })}
            </div>
          )}
        </>
      )}
    </ModuleFrame>
  );
}

// ------------------------------------------------------------- your apps

function ConnectPanel({ tile }) {
  const [copied, setCopied] = useState('');
  const ai = tile.connect_ai || {};
  const config = useMemo(() => JSON.stringify(ai.client_config || {}, null, 2), [ai.client_config]);
  const copy = async (which, value) => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(which);
    } catch {
      setCopied(`${which}-failed`);
    }
    setTimeout(() => setCopied(''), 1800);
  };
  const label = which => (copied === which ? 'Copied' : copied === `${which}-failed` ? 'Select and copy' : 'Copy');
  const links = [...(ai.desktop || []), ...(ai.mobile || [])];
  return (
    <div className="uh-connect" role="region" aria-labelledby="uh-connect-title" id="uh-connect">
      <div className="uh-connect-head">
        <div className="uh-eyebrow"><span>Connect your AI</span></div>
        <h3 className="uh-connect-title" id="uh-connect-title">Connect your AI to {tile.name}</h3>
        <p>Use this endpoint with an MCP client you control. Sign in or paste a {tile.name} token when the client asks. Nothing here is a secret.</p>
      </div>
      <div className="uh-connect-cols">
        {ai.claude_code_command && (
          <div className="uh-connect-box">
            <div className="uh-connect-bh"><b>Claude Code</b><button type="button" className="uh-btn is-sm" onClick={() => copy('cc', ai.claude_code_command)} aria-label={`Copy the Claude Code command for ${tile.name}`}>{label('cc')}</button></div>
            <pre className="uh-pre" tabIndex={0}>{ai.claude_code_command}</pre>
            <div className="uh-hint" style={{ marginTop: 8 }}>Run in your terminal. The client opens a sign-in the first time.</div>
          </div>
        )}
        <div className="uh-connect-box">
          <div className="uh-connect-bh"><b>Other MCP clients</b><button type="button" className="uh-btn is-sm" onClick={() => copy('json', config)} aria-label={`Copy the MCP client settings for ${tile.name}`}>{label('json')}</button></div>
          <pre className="uh-pre" tabIndex={0}>{config}</pre>
        </div>
        {(ai.chatgpt_url || ai.mcp_url) && (
          <div className="uh-connect-box">
            <div className="uh-connect-bh"><b>ChatGPT connector</b><button type="button" className="uh-btn is-sm" onClick={() => copy('url', ai.chatgpt_url || ai.mcp_url)} aria-label={`Copy the connector address for ${tile.name}`}>{label('url')}</button></div>
            <pre className="uh-pre" tabIndex={0}>{ai.chatgpt_url || ai.mcp_url}</pre>
            <div className="uh-hint" style={{ marginTop: 8 }}>Settings, Connectors, developer mode.</div>
            {links.length > 0 && (
              <div className="uh-connect-links">
                {links.map(link => <ExtLink key={`${link.label}-${link.url}`} href={link.url}>{link.label}</ExtLink>)}
              </div>
            )}
          </div>
        )}
      </div>
      <span className="uh-sr" role="status">{copied && !copied.endsWith('failed') ? 'Copied to the clipboard.' : ''}</span>
    </div>
  );
}

function tileState(tile) {
  const live = tile.live || {};
  if (live.status === 'unavailable') return { text: live.reason === 'reauth' ? 'Sign in again' : 'Unavailable', down: true, note: live.note };
  if (live.status === 'not_set_up') return { text: 'Not linked', down: true, note: live.note };
  if (tile.state === 'needs_first_open') return { text: 'Open it once to finish setup', down: false };
  return { text: 'Ready', down: false };
}

export function AppsGrid({ mod, tz, onRetry, lastGood, loading, columns = 3 }) {
  const [active, setActive] = useState(null);
  const tiles = mod.items || [];
  const activeIndex = tiles.findIndex(tile => tile.slug === active);
  const panelAfter = activeIndex < 0 ? -1 : Math.min(tiles.length - 1, Math.floor(activeIndex / columns) * columns + columns - 1);
  return (
    <ModuleFrame mod={mod} tz={tz} count={tiles.length ? `${tiles.length} entitled` : ''} onRetry={onRetry} lastGood={lastGood} loading={loading}
      meta={<><span className="uh-src">Numbers from each app</span><AsOf iso={mod.as_of} tz={tz} /></>}
    >
      {mod.status === 'ok' && (
        <div className="uh-apps uh-tnum" id="uh-apps">
          {tiles.map((tile, index) => {
            const key = appKey(tile.slug);
            const info = appInfo(key);
            const state = tileState(tile);
            const [first, ...more] = tile.numbers || [];
            const isActive = active === tile.slug;
            return (
              <React.Fragment key={tile.slug}>
                <div className={`uh-tile${isActive ? ' is-active' : ''}`} style={{ '--uh-ac': hueVar(info.hue) }} data-app={tile.slug}>
                  <div className="uh-tile-head">
                    <span className="uh-tile-name"><AppMark app={key} small /><span>{tile.name}</span></span>
                    <span className={`uh-tile-state${state.down ? ' is-down' : ''}`}>{state.text}</span>
                  </div>
                  {first ? (
                    <div className="uh-tile-num">
                      <ExtLink href={first.href}>{formatNumber(first.value)}<span className="uh-tile-numlabel">{first.label}</span></ExtLink>
                    </div>
                  ) : (
                    <div className="uh-tile-purpose">{state.note || tile.purpose || ''}</div>
                  )}
                  {more.length > 0 && (
                    <div className="uh-tile-more">
                      {more.map((n, i) => (
                        <React.Fragment key={n.label}>{i > 0 && ' · '}<ExtLink href={n.href}>{formatNumber(n.value)} {n.label}</ExtLink></React.Fragment>
                      ))}
                    </div>
                  )}
                  <div className="uh-tile-foot">
                    {tile.open ? <ExtLink className="uh-btn is-sm" href={tile.open} aria-label={`Open ${tile.name}`}>Open</ExtLink> : <span />}
                    {tile.connect_ai && (
                      <button
                        type="button"
                        className="uh-btn is-sm is-quiet"
                        aria-expanded={isActive}
                        aria-controls={isActive ? 'uh-connect' : undefined}
                        onClick={() => setActive(isActive ? null : tile.slug)}
                      >
                        Connect your AI
                      </button>
                    )}
                  </div>
                </div>
                {panelAfter === index && activeIndex >= 0 && <ConnectPanel tile={tiles[activeIndex]} />}
              </React.Fragment>
            );
          })}
        </div>
      )}
    </ModuleFrame>
  );
}

// ------------------------------------------------------------- money

export function Money({ mod, tz, onRetry, lastGood, loading }) {
  const cash = mod.cash || {};
  const invoiced = mod.invoiced_not_due || null;
  const runway = parseAmount(mod.runway_months);
  const burn = formatMoney(mod.monthly_burn);
  const screen = (mod.source || []).find(source => source.url)?.url;
  const bank = mod.upstream_as_of || mod.as_of;
  const priorities = mod.items || [];
  return (
    <ModuleFrame mod={mod} tz={tz} count="visible to org managers" onRetry={onRetry} lastGood={lastGood} loading={loading}
      meta={<><span className="uh-src">Accounting-Ops, CFO brief</span>{bank && <span className="uh-asof">bank feed {hhmm(bank, tz)}</span>}</>}
    >
      {mod.status === 'ok' && (
        <>
          <div className="uh-kpis uh-tnum">
            <div className="uh-kpi">
              {cash.configured === false ? (
                <><div className="uh-kpi-v">Not connected</div><div className="uh-kpi-k">No bank account is linked to Accounting-Ops yet.</div></>
              ) : (
                <>
                  <div className="uh-kpi-v">{formatMoney(cash.net_total) || '–'}</div>
                  <div className="uh-kpi-k">cash, net of what you owe</div>
                  {cash.headline?.text && <div className="uh-kpi-d">{cash.headline.text}</div>}
                </>
              )}
            </div>
            <div className="uh-kpi">
              <div className="uh-kpi-v">{runway !== null ? `${runway} mo` : '–'}</div>
              <div className="uh-kpi-k">runway at the current burn</div>
              {burn && <div className="uh-kpi-d">{burn} a month</div>}
            </div>
            <div className="uh-kpi">
              <div className="uh-kpi-v">{invoiced ? formatMoney(invoiced.amount, invoiced.currency) : '–'}</div>
              <div className="uh-kpi-k">invoiced, not yet due</div>
              {invoiced && <div className="uh-kpi-d">{plural(invoiced.count || 0, 'invoice', 'invoices')}{invoiced.complete === false ? ', more not counted' : ''}</div>}
            </div>
          </div>
          {priorities.length > 0 && (
            <div className="uh-list uh-money-list">
              {priorities.map(item => (
                <div key={item.id} className="uh-row is-compact" style={{ '--uh-ac': hueVar('green') }}>
                  <AppMark app="accounting-ops" />
                  <div className="uh-what">
                    <div className="uh-t">{item.title}</div>
                    <div className="uh-s">{item.detail?.text || 'Accounting-Ops'}</div>
                  </div>
                  <div className="uh-acts">{openAction(item) && <ExtLink className="uh-btn is-sm" href={openAction(item).href}>{openAction(item).label || 'Open'}</ExtLink>}</div>
                </div>
              ))}
            </div>
          )}
          <p className="uh-money-summary">
            {mod.summary_line?.text ? `${mod.summary_line.text} ` : ''}
            {screen && <ExtLink className="uh-link" href={screen}>Open Accounting-Ops</ExtLink>}
          </p>
        </>
      )}
    </ModuleFrame>
  );
}

// ------------------------------------------------------------- watched topics

export function WatchedTopics({ mod, tz, nowIso, onRetry, lastGood, loading }) {
  const items = mod.items || [];
  return (
    <ModuleFrame mod={mod} tz={tz} count={items.length ? String(items.length) : ''} onRetry={onRetry} lastGood={lastGood} loading={loading}>
      {mod.status === 'ok' && items.map(topic => {
        const open = openAction(topic);
        const ran = topic.last_run_at ? `run ${whenLabel(topic.last_run_at, tz, nowIso)}` : 'no run yet';
        return (
          <div key={topic.monitor_id || topic.title} className={`uh-topic${topic.changed ? ' is-changed' : ''}`}>
            <div className="uh-topic-t">
              <span className="uh-topic-dot" aria-hidden="true" />
              <ExtLink className="uh-topic-name" href={topic.href}>{topic.title}</ExtLink>
              <span className="uh-topic-nc">{topic.changed ? 'changed' : 'no change'}</span>
            </div>
            {topic.changed && (
              <div className="uh-brief">
                {topic.drift_line?.text && <div className="uh-brief-q">{topic.drift_line.text}</div>}
                <div className="uh-brief-src">Center Deep Research{topic.cadence ? ` · ${topic.cadence} monitor` : ''}{' · '}{ran}</div>
                {open && <div className="uh-acts"><ExtLink className="uh-btn is-sm" href={open.href}>{open.label || 'Open run'}</ExtLink></div>}
              </div>
            )}
          </div>
        );
      })}
    </ModuleFrame>
  );
}

// ------------------------------------------------------------- usage

const SERVICE_NAMES = { llm: 'Chat and agents', embeddings: 'Embeddings', tts: 'Voice', stt: 'Transcription', image: 'Images' };

export function Usage({ mod, tz, onRetry, lastGood, loading }) {
  const credits = mod.credits || {};
  const pool = credits.pool || null;
  const used = parseAmount(pool?.used);
  const total = parseAmount(pool?.total);
  const pct = used !== null && total ? Math.min(100, Math.round((used / total) * 100)) : null;
  const screen = (mod.source || []).find(source => source.url)?.url;
  const services = (mod.services || []).filter(s => s && s.credits);
  return (
    <ModuleFrame mod={mod} tz={tz} count="org managers only" onRetry={onRetry} lastGood={lastGood} loading={loading}
      meta={<><span className="uh-src">Ops-Center billing</span><AsOf iso={mod.as_of} tz={tz} /></>}
    >
      {mod.status === 'ok' && (
        <div className="uh-tnum">
          <div className="uh-usage-u">
            <span><b>{formatNumber(credits.last_24_hours ?? 0)}</b> credits in the last 24 hours</span>
            <span><b>{formatNumber(credits.last_30_days ?? 0)}</b> in 30 days</span>
          </div>
          {pct !== null && (
            <>
              <div className="uh-bar" role="img" aria-label={`${formatNumber(used)} of ${formatNumber(total)} credits used`}>
                <i className="uh-bar-fill" style={{ width: `${Math.max(pct, used > 0 ? 2 : 0)}%` }} />
              </div>
              <div className="uh-usage-u" style={{ marginTop: 6 }}>
                <span><b>{formatNumber(used)}</b> of {formatNumber(total)} credits used</span>
                <span>{formatNumber(pool.available)} left</span>
              </div>
            </>
          )}
          <div className="uh-foot">
            {typeof mod.people_using_ai_30_days === 'number' && <span>{plural(mod.people_using_ai_30_days, 'person', 'people')} used AI in 30 days</span>}
            {services.length > 0 && <span>{services.map(s => `${SERVICE_NAMES[s.service] || s.service} ${formatNumber(s.credits)}`).join(' · ')}</span>}
            {screen && <ExtLink className="uh-link uh-push" href={screen}>Open billing</ExtLink>}
          </div>
        </div>
      )}
    </ModuleFrame>
  );
}

export const MODULE_COMPONENTS = {
  needs_you: NeedsYou,
  today: Today,
  recent_meetings: Meetings,
  since_last_visit: SinceLastVisit,
  apps: AppsGrid,
  money: Money,
  watched_topics: WatchedTopics,
  usage: Usage
};

export { Icon };
