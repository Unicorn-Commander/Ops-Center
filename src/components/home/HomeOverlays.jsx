import React, { useEffect, useMemo, useRef, useState } from 'react';
import Icon from './homeIcons';
import { filterPalette } from './homeScreens';
import { appInfo, hueVar } from './homeModel';
import { MOD_KEY } from './HomeTopBar';

/** A modal layer: focus moves in, Tab stays inside, Escape and a click outside close it, focus returns. */
function Overlay({ label, labelledBy, onClose, className = '', children, initialFocus }) {
  const boxRef = useRef(null);
  const returnTo = useRef(typeof document !== 'undefined' ? document.activeElement : null);
  useEffect(() => {
    const box = boxRef.current;
    const focusables = () => Array.from(box?.querySelectorAll('button:not([disabled]), [href], input, [tabindex]:not([tabindex="-1"])') || []);
    (initialFocus?.current || focusables()[0])?.focus();
    const onKey = (event) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        event.stopPropagation();
        onClose();
      } else if (event.key === 'Tab') {
        const list = focusables();
        if (!list.length) return;
        const first = list[0];
        const last = list[list.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }
    };
    box?.addEventListener('keydown', onKey);
    const opener = returnTo.current;
    return () => {
      box?.removeEventListener('keydown', onKey);
      if (opener && typeof opener.focus === 'function') opener.focus();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return (
    <div className={`uh-overlay ${className}`.trim()} onMouseDown={event => { if (event.target === event.currentTarget) onClose(); }}>
      <div ref={boxRef} role="dialog" aria-modal="true" aria-label={label} aria-labelledby={labelledBy} className="uh-overlay-inner">
        {children}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ palette

export function CommandPalette({ entries, onClose, onRun }) {
  const [query, setQuery] = useState('');
  const [index, setIndex] = useState(0);
  const inputRef = useRef(null);
  const results = useMemo(() => filterPalette(entries, query), [entries, query]);
  useEffect(() => setIndex(0), [query]);
  const choose = (entry) => {
    if (!entry) return;
    onClose();
    onRun(entry);
  };
  const onKeyDown = (event) => {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      if (!results.length) return;
      setIndex(i => (event.key === 'ArrowDown' ? (i + 1) % results.length : (i - 1 + results.length) % results.length));
    } else if (event.key === 'Enter') {
      event.preventDefault();
      choose(results[index]);
    }
  };
  const active = results[index] ? `uh-pal-${index}` : undefined;
  return (
    <Overlay label="Search, or jump to a screen" onClose={onClose} initialFocus={inputRef}>
      <div className="uh-palette-box">
        <div className="uh-palette-in">
          <Icon name="search" />
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={event => setQuery(event.target.value)}
            onKeyDown={onKeyDown}
            placeholder="Type a screen, a record or an app"
            aria-label="Search"
            role="combobox"
            aria-expanded="true"
            aria-controls="uh-pal-list"
            aria-activedescendant={active}
            aria-autocomplete="list"
            autoComplete="off"
          />
        </div>
        <ul className="uh-palette-list" id="uh-pal-list" role="listbox" aria-label="Results">
          {results.map((entry, i) => (
            <li
              key={entry.id}
              id={`uh-pal-${i}`}
              role="option"
              aria-selected={i === index}
              className="uh-palette-opt"
              onMouseEnter={() => setIndex(i)}
              onMouseDown={event => { event.preventDefault(); choose(entry); }}
            >
              <i className="uh-sq" style={{ '--uh-ac': hueVar(entry.app ? appInfo(entry.app).hue : 'slate') }} aria-hidden="true" />
              <span>{entry.label}</span>
              <span className="uh-mi-sub">{entry.sub}</span>
            </li>
          ))}
        </ul>
        {results.length === 0 && <div className="uh-palette-none" role="status">Nothing on the home matches. Try an app or a screen name.</div>}
        <div className="uh-palette-foot" aria-hidden="true">
          <span><span className="uh-kbd">↑</span> <span className="uh-kbd">↓</span> move</span>
          <span><span className="uh-kbd">↵</span> open</span>
          <span><span className="uh-kbd">esc</span> close</span>
        </div>
      </div>
    </Overlay>
  );
}

// ------------------------------------------------------------------ how it works

export const TOUR_STEPS = [
  {
    title: 'The home shows what needs you',
    body: 'The first line says whether anything needs you. Below it: the short list that does, your day in time order, your meetings, what changed since your last visit and your apps with live numbers. Every number comes from the app that owns it, and the page refreshes itself every minute while you are looking at it.',
    fig: <><b>Nothing needs you.</b> <span className="uh-muted">is a complete state. When the list is empty, the page is calm.</span></>
  },
  {
    title: 'Act without leaving',
    body: 'Approve a draft, accept a proposed task or mark a task done right in the list. The app that owns the item does the work, and the row shows what it answered. Nothing is sent, paid or deleted without your tap.',
    fig: <><span className="uh-muted">Approve on an email draft:</span> Sending now, then the answer from Email-Ops.</>
  },
  {
    title: 'Jump straight to a screen',
    body: 'Apps in the top bar lists your organization\'s apps and their most useful screens. Each link opens that screen in your own session, in a new tab. Or press the shortcut and type the screen\'s name.',
    fig: <><span className="uh-kbd">{MOD_KEY}.</span> opens Apps. <span className="uh-kbd">{MOD_KEY}K</span> opens search. Type <b>approvals</b> to find every approvals screen.</>
  },
  {
    title: 'Switch organization',
    body: 'If you belong to more than one organization, its name in the top bar is a switcher. Switching changes everything on this page. People in one organization see the name with no menu.',
    fig: <><span className="uh-muted">Top bar:</span> the organization name, then Apps.</>
  },
  {
    title: 'Connect your own AI',
    body: 'Each app tile has Connect your AI. It gives your own assistant, like Claude Code or ChatGPT, a connection to that app with your permissions. Nothing on that panel is a secret.',
    fig: <><span className="uh-muted">Your apps:</span> Connect your AI, then copy the command for your client.</>
  }
];

export function HowItWorks({ start = 0, onClose }) {
  const [step, setStep] = useState(start);
  const s = TOUR_STEPS[step];
  const last = step === TOUR_STEPS.length - 1;
  return (
    <Overlay labelledBy="uh-tour-title" onClose={onClose}>
      <div className="uh-tour-box">
        <div className="uh-tour-steps" aria-hidden="true">
          {TOUR_STEPS.map((_, k) => <i key={k} className={k <= step ? 'is-done' : ''} />)}
        </div>
        <div className="uh-eyebrow"><span>How it works</span><span>{step + 1} of {TOUR_STEPS.length}</span></div>
        <h2 className="uh-tour-title" id="uh-tour-title">{s.title}</h2>
        <p className="uh-tour-body">{s.body}</p>
        <div className="uh-tour-fig">{s.fig}</div>
        <div className="uh-tour-acts">
          <button type="button" className="uh-btn is-quiet" onClick={onClose}>Skip</button>
          <div className="uh-r">
            <button type="button" className="uh-btn" onClick={() => setStep(v => Math.max(0, v - 1))} disabled={step === 0} aria-disabled={step === 0}>Back</button>
            <button type="button" className="uh-btn is-primary" onClick={() => (last ? onClose() : setStep(v => v + 1))}>{last ? 'Done' : 'Next'}</button>
          </div>
        </div>
      </div>
    </Overlay>
  );
}

// ------------------------------------------------------------------ shortcuts

export function ShortcutsDialog({ onClose }) {
  const rows = [
    [`${MOD_KEY}K`, 'Search, or jump to a screen'],
    [`${MOD_KEY}.`, 'Open Apps'],
    ['?', 'Help'],
    ['J  K', 'Move down and up in Needs you'],
    ['A', 'The selected row\'s main action (Approve, Accept or Mark done)'],
    ['O', 'Open the selected row in its app'],
    ['esc', 'Close a menu or this window']
  ];
  return (
    <Overlay labelledBy="uh-keys-title" onClose={onClose}>
      <div className="uh-tour-box">
        <h2 className="uh-tour-title" id="uh-keys-title">Keyboard shortcuts</h2>
        <div className="uh-keys">
          {rows.map(([keys, what]) => (
            <React.Fragment key={keys}>
              <span>{keys.split('  ').map(k => <span key={k} className="uh-kbd" style={{ marginRight: 4 }}>{k}</span>)}</span>
              <span>{what}</span>
            </React.Fragment>
          ))}
        </div>
        <div className="uh-tour-acts"><span /><button type="button" className="uh-btn is-primary" onClick={onClose}>Done</button></div>
      </div>
    </Overlay>
  );
}
