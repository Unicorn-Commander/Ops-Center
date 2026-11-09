import React, { useEffect, useLayoutEffect, useRef, useState } from 'react';
import Icon from './homeIcons';
import { appInfo, hhmm, hueVar, MODULES, EMPTY_TEXT } from './homeModel';

/** A link to an app screen: a new tab in the person's own session (DESIGN l). */
export function ExtLink({ href, className = '', children, ...rest }) {
  if (!href) return <span className={className}>{children}</span>;
  return (
    <a href={href} target="_blank" rel="noopener noreferrer" className={`no-accent ${className}`.trim()} {...rest}>
      {children}
    </a>
  );
}

export function TypePill({ children }) {
  return <span className="uh-type">{children}</span>;
}

export function AppMark({ app, icon, small = false }) {
  const info = appInfo(app);
  return (
    <span className={`uh-mark${small ? ' is-sm' : ''}`} style={{ '--uh-ac': hueVar(info.hue) }} aria-hidden="true">
      <Icon name={icon || info.icon} />
    </span>
  );
}

/** Briefly marks a value that changed on a refresh (the as-of times). */
function useBump(value) {
  const [bump, setBump] = useState(false);
  const first = useRef(true);
  useEffect(() => {
    if (first.current) {
      first.current = false;
      return undefined;
    }
    setBump(true);
    const timer = setTimeout(() => setBump(false), 1200);
    return () => clearTimeout(timer);
  }, [value]);
  return bump;
}

export function AsOf({ iso, tz, prefix = 'as of' }) {
  const label = iso ? `${prefix} ${hhmm(iso, tz)}` : '';
  const bump = useBump(label);
  if (!label) return null;
  return <span className={`uh-asof${bump ? ' is-bump' : ''}`}>{label}</span>;
}

/** The apps that fed a module, in words: "Email-Ops, Accounting-Ops, Project-Ops". */
export function sourceLabels(mod) {
  const labels = [];
  for (const source of mod?.source || []) {
    const label = source?.label || appInfo(source?.app).label;
    if (label && !labels.includes(label)) labels.push(label);
  }
  return labels;
}

function downSentence(mod) {
  const down = (mod.source || []).filter(source => source.status === 'unavailable');
  const labels = [...new Set(down.map(source => source.label))];
  const who = labels.length ? labels.join(' and ') : 'This source';
  if (mod.reason === 'reauth') return 'Sign in again to refresh this.';
  if (mod.reason === 'timeout') return `${who} did not answer in time.`;
  return `${who} ${labels.length > 1 ? 'are' : 'is'} not answering.`;
}

function notSetUpSentence(mod) {
  const notes = [...new Set((mod.source || []).map(source => source.note).filter(Boolean))];
  if (notes.length) return notes.join(' ');
  const labels = sourceLabels(mod);
  return `${labels.join(' and ') || 'This app'} is not linked to this organization's home yet.`;
}

function Skeleton() {
  return (
    <div className="uh-sk" aria-hidden="true">
      <i className="uh-sk-bar is-w4" />
      <i className="uh-sk-bar is-w1" />
      <i className="uh-sk-bar is-w3" />
      <i className="uh-sk-bar is-w2" />
    </div>
  );
}

/**
 * The frame every module shares (DESIGN c): the section colour, a title with
 * its chip, the source apps and the module's own as-of on the right, a body,
 * and the four designed states. Loading and unavailable keep the module's
 * last measured height, so the page never jumps.
 */
export function ModuleFrame({
  mod, tz, count, meta, metaAct = false, asOf, children, emptyText, onRetry, lastGood, className = '', loading = false, headExtra
}) {
  const spec = MODULES[mod.id] || {};
  const ref = useRef(null);
  const height = useRef(0);
  const status = loading ? 'loading' : mod.status;
  const titleId = `uh-h-${mod.id}`;

  useLayoutEffect(() => {
    if (ref.current && (status === 'ok' || status === 'empty')) {
      height.current = ref.current.getBoundingClientRect().height;
    }
  });

  const keepHeight = (status === 'loading' || status === 'unavailable') && height.current
    ? { minHeight: `${Math.round(height.current)}px` }
    : undefined;
  const labels = sourceLabels(mod);
  const partialDown = mod.partial
    ? [...new Set((mod.source || []).filter(s => s.status === 'unavailable').map(s => s.label))]
    : [];

  let body;
  if (status === 'loading') {
    body = <><Skeleton /><span className="uh-sr">{`Loading ${spec.title || mod.title}`}</span></>;
  } else if (status === 'unavailable') {
    body = (
      <div className="uh-downbox" role="status">
        <p>
          {downSentence(mod)}
          {lastGood ? ` Last good read ${hhmm(lastGood, tz)}.` : ''}
          {mod.reason === 'reauth' && <> <a className="uh-link no-accent" href="/admin/login?next=%2Fdashboard">Sign in</a></>}
        </p>
        {mod.reason !== 'reauth' && onRetry && <button type="button" className="uh-btn is-sm" onClick={onRetry}>Retry</button>}
      </div>
    );
  } else if (status === 'not_set_up') {
    const link = (mod.source || []).find(source => source.url)?.url;
    body = (
      <div className="uh-emptybox">
        <p>
          {notSetUpSentence(mod)}
          {link && <> <ExtLink className="uh-link" href={link}>Open the app</ExtLink></>}
        </p>
      </div>
    );
  } else if (status === 'empty' && !children) {
    body = <p className="uh-empty">{emptyText || mod.note || EMPTY_TEXT[mod.id] || 'Nothing here yet.'}</p>;
  } else {
    body = children;
  }

  return (
    <article
      ref={ref}
      id={`uh-mod-${mod.id}`}
      className={`uh-mod ${className}`.trim()}
      style={{ '--uh-sc': hueVar(spec.hue), ...keepHeight }}
      aria-labelledby={titleId}
      aria-busy={status === 'loading' ? 'true' : undefined}
      data-module={mod.id}
      data-status={status}
    >
      <header className="uh-mod-head">
        <h2 className="uh-mod-title" id={titleId}>
          <span className="uh-chip" aria-hidden="true"><Icon name={spec.icon} /></span>
          <span>{spec.title || mod.title}</span>
          {count !== undefined && count !== null && count !== '' && status !== 'loading' && status !== 'unavailable'
            && <span className="uh-count uh-tnum">{count}</span>}
        </h2>
        <div className={`uh-meta uh-tnum${metaAct ? ' is-act' : ''}`}>
          {status === 'loading' && <span>Loading from {labels.join(', ') || 'your apps'}</span>}
          {status === 'unavailable' && <><span className="uh-src">{labels.join(', ')}</span><span className="uh-down">unavailable</span></>}
          {status !== 'loading' && status !== 'unavailable' && (meta || (
            <>
              {labels.length > 0 && <span className="uh-src">{labels.join(', ')}</span>}
              <AsOf iso={asOf || mod.as_of} tz={tz} />
            </>
          ))}
          {headExtra}
        </div>
      </header>
      {partialDown.length > 0 && status === 'ok' && (
        <p className="uh-partial" role="status">
          {`${partialDown.join(' and ')} did not answer, so ${partialDown.length > 1 ? 'their' : 'its'} items are missing here.`}
        </p>
      )}
      {body}
    </article>
  );
}

/**
 * Title attributes only on lines that are actually cut (DESIGN c, row lines):
 * a row's title and secondary line end in an ellipsis and carry the full text
 * in a title attribute when, and only when, they are truncated.
 */
export function useFitTitles(rootRef, deps = []) {
  useEffect(() => {
    const root = rootRef.current;
    if (!root) return undefined;
    let frame = 0;
    const fit = () => {
      frame = 0;
      root.querySelectorAll('.uh-t, .uh-s, .uh-topic-name, .uh-an-name').forEach(el => {
        if (el.scrollWidth > el.clientWidth + 1) {
          const text = Array.from(el.childNodes)
            .map(node => (node.nodeType === 1 && node.classList.contains('uh-type') ? '' : node.textContent))
            .join('')
            .replace(/\s+/g, ' ')
            .trim();
          el.setAttribute('title', text);
        } else {
          el.removeAttribute('title');
        }
      });
    };
    const request = () => {
      if (!frame) frame = requestAnimationFrame(fit);
    };
    request();
    window.addEventListener('resize', request);
    if (document.fonts?.ready) document.fonts.ready.then(request).catch(() => {});
    return () => {
      window.removeEventListener('resize', request);
      if (frame) cancelAnimationFrame(frame);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
}

/**
 * Rows keep their places on a refresh (DESIGN m): rows that are new since the
 * last document slide in at the top of their list, rows that left fade out
 * and are removed after 350 ms, and nothing else is reordered.
 */
export function useRowPresence(items, keyOf) {
  const [rows, setRows] = useState(() => items.map(item => ({ key: keyOf(item), item, state: 'stay' })));
  const known = useRef(new Set(items.map(keyOf)));
  const timers = useRef([]);

  useEffect(() => {
    setRows(previous => {
      const incoming = new Map(items.map(item => [keyOf(item), item]));
      const next = [];
      const added = [];
      for (const item of items) {
        const key = keyOf(item);
        if (!previous.some(row => row.key === key) && !known.current.has(key)) added.push({ key, item, state: 'new' });
      }
      for (const row of previous) {
        if (incoming.has(row.key)) next.push({ ...row, item: incoming.get(row.key), state: row.state === 'leaving' ? 'stay' : row.state });
        else if (row.state !== 'leaving') next.push({ ...row, state: 'leaving' });
        else next.push(row);
      }
      for (const item of items) {
        const key = keyOf(item);
        if (!next.some(row => row.key === key) && !added.some(row => row.key === key)) next.push({ key, item, state: 'stay' });
      }
      added.forEach(row => known.current.add(row.key));
      const result = [...added, ...next];
      const same = result.length === previous.length
        && result.every((row, i) => row.key === previous[i].key && row.state === previous[i].state && row.item === previous[i].item);
      return same ? previous : result;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [items]);

  useEffect(() => {
    const leaving = rows.filter(row => row.state === 'leaving');
    const fresh = rows.filter(row => row.state === 'new');
    if (!leaving.length && !fresh.length) return undefined;
    if (leaving.length) {
      timers.current.push(setTimeout(() => setRows(cur => cur.filter(row => row.state !== 'leaving')), 350));
    }
    if (fresh.length) {
      timers.current.push(setTimeout(() => setRows(cur => cur.map(row => (row.state === 'new' ? { ...row, state: 'stay' } : row))), 2600));
    }
    return undefined;
  }, [rows]);

  useEffect(() => () => timers.current.forEach(clearTimeout), []);
  return rows;
}
