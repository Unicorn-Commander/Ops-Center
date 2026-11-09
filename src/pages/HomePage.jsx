import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import '../styles/home.css';
import { useTheme } from '../contexts/ThemeContext';
import { useBranding } from '../contexts/BrandingContext';
import { useOrganization } from '../contexts/OrganizationContext';
import { isPlatformAdminRole } from '../config/routes';
import useHomeState from '../components/home/useHomeState';
import HomeTopBar, { signOut } from '../components/home/HomeTopBar';
import { CommandPalette, HowItWorks, ShortcutsDialog } from '../components/home/HomeOverlays';
import { MODULE_COMPONENTS } from '../components/home/HomeModules';
import { useFitTitles } from '../components/home/HomeParts';
import { paletteIndex } from '../components/home/homeScreens';
import { DEFAULT_APPEARANCE, normalizeAppearance, themeVars } from '../components/home/homeTokens';
import {
  greeting, hhmm, layoutModules, longDate, MODULES, roleName, sinceSentence, splitStatusText
} from '../components/home/homeModel';

const TOUR_KEY = 'uc.home.tourSeen';
// The brand mark, cropped to its drawn box so it reads at 28 px (the mock's crop of
// magic_unicorn_logo.png). A logo configured for the deployment wins over it.
const FALLBACK_LOGO = '/logos/uc-mark.webp';
const DEFAULT_BRANDING_LOGO = '/logos/ops-center-logo.png';

function readFlag(key) {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeFlag(key, value) {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // ignore: the tour then shows again next visit
  }
}

function readUserInfo() {
  try {
    return JSON.parse(window.localStorage.getItem('userInfo') || '{}');
  } catch {
    return {};
  }
}

/** "system" follows prefers-color-scheme and updates live (DESIGN k). */
function useResolvedMode(mode) {
  const query = typeof window !== 'undefined' && window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;
  const [prefersDark, setPrefersDark] = useState(Boolean(query?.matches));
  useEffect(() => {
    if (!query) return undefined;
    const onChange = () => setPrefersDark(query.matches);
    query.addEventListener?.('change', onChange);
    return () => query.removeEventListener?.('change', onChange);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  if (mode === 'system') return prefersDark ? 'dark' : 'light';
  return mode;
}

function isTyping() {
  const el = document.activeElement;
  if (!el) return false;
  return /^(input|textarea|select)$/i.test(el.tagName) || el.isContentEditable;
}

const LIVE_WORDS = { live: 'live', paused: 'paused, tab hidden', cached: 'updating' };

function StatusLine({ doc, live, tz }) {
  const sl = doc.status_line || {};
  const nowIso = doc.generated_at;
  const { lead, rest } = splitStatusText(sl.text);
  const since = (doc.modules || []).find(mod => mod.id === 'since_last_visit');
  const sub = sinceSentence(since, tz, nowIso);
  const role = roleName(doc.person?.role);
  const dots = (sl.dots || []).filter(dot => MODULES[dot.module]);
  const lit = dots.filter(dot => dot.lit).length;
  const asOf = sl.as_of || doc.generated_at;
  const liveText = live === 'stale' ? `stale since ${hhmm(asOf, tz)}` : live === 'cached' ? `saved ${hhmm(asOf, tz)}, updating` : LIVE_WORDS[live] || 'live';
  const [announce, setAnnounce] = useState('');
  const first = useRef(true);
  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    setAnnounce(sl.text || '');
  }, [sl.text]);
  return (
    <div className="uh-status">
      <div className="uh-eyebrow">
        <span>Organization home</span>
        {longDate(nowIso, tz) && <span>{longDate(nowIso, tz)}</span>}
        {role && <span>{role}</span>}
      </div>
      <h1 className="uh-h1" id="uh-status-line">
        {greeting(doc.person?.display_name, tz, nowIso)}{' '}
        {lead && <span className="uh-status-n">{lead}</span>}{rest}
      </h1>
      {sub && <div className="uh-status-sub">{sub}</div>}
      <div className="uh-pips uh-tnum">
        {dots.length > 0 && (
          <span role="img" aria-label={`${lit} of ${dots.length} sections have something for you`} style={{ display: 'inline-flex', gap: 8 }}>
            {dots.map(dot => (
              <span
                key={dot.module}
                className={`uh-pip${dot.lit ? ' is-on' : ''}${dot.status === 'unavailable' ? ' is-down' : ''}`}
                title={`${MODULES[dot.module].title}: ${dot.status === 'unavailable' ? 'unavailable' : dot.lit ? 'something for you' : 'nothing new'}`}
              />
            ))}
          </span>
        )}
        <span className="uh-asof">as of {hhmm(asOf, tz)}</span>
        <span className="uh-live" title="Refreshes every 60 seconds while this tab is visible, and as soon as you come back to it">
          <i className="uh-live-dot" aria-hidden="true" />
          <span className="uh-live-text">{liveText}</span>
        </span>
      </div>
      <div className="uh-sr" aria-live="polite">{announce}</div>
    </div>
  );
}

/**
 * The signed-in home (User Home design, round 3.1). Renders the home-state
 * document: every module it provides, in the design's order, each with its
 * own as-of and its loading, empty, not set up and unavailable states.
 */
export default function HomePage({ initialDoc, fromCache = false, onOff, prepare, fetchImpl = globalThis.fetch }) {
  const theme = useTheme();
  const appearance = normalizeAppearance(theme.appearance || DEFAULT_APPEARANCE);
  const setAppearance = theme.setAppearance || (() => {});
  const resolvedMode = useResolvedMode(appearance.mode);
  const vars = useMemo(() => themeVars({ ...appearance, mode: resolvedMode }), [appearance.family, appearance.font, resolvedMode]); // eslint-disable-line react-hooks/exhaustive-deps
  const { branding, error: brandingError } = useBranding() || {};
  const orgs = useOrganization();
  const { doc, live, retry } = useHomeState({ initialDoc, fromCache, onOff, prepare, fetchImpl });
  const [openMenu, setOpenMenu] = useState(null);
  const [keyboardOpen, setKeyboardOpen] = useState(false);
  const [overlay, setOverlay] = useState(() => (readFlag(TOUR_KEY) === '1' ? null : { kind: 'tour', step: 0, first: true }));
  const [currentId, setCurrentId] = useState(null);
  const [retrying, setRetrying] = useState(() => new Set());
  const rootRef = useRef(null);
  const lastGood = useRef({});
  const tz = doc?.timezone || 'UTC';
  const nowIso = doc?.generated_at;
  const userInfo = useMemo(readUserInfo, []);
  const isPlatformAdmin = isPlatformAdminRole([userInfo.role, ...(Array.isArray(userInfo.roles) ? userInfo.roles : [])]);
  const brandName = (!brandingError && branding?.company_name) || 'Unicorn Commander';
  const configuredLogo = !brandingError && branding?.logo_url && branding.logo_url !== DEFAULT_BRANDING_LOGO
    && !/magic_unicorn_logo|uc-logo-\d+/.test(branding.logo_url) ? branding.logo_url : null;
  const brandLogo = configuredLogo || FALLBACK_LOGO;

  // The last good read of each module, for its unavailable sentence.
  for (const mod of doc?.modules || []) {
    if (mod.status === 'ok' || mod.status === 'empty') lastGood.current[mod.id] = mod.as_of;
  }

  const { main, side } = useMemo(() => layoutModules(doc), [doc]);
  useFitTitles(rootRef, [doc, resolvedMode, appearance.font]);

  // Page title and the area around the page follow the theme while the home is open.
  useEffect(() => {
    const previousTitle = document.title;
    const previousBg = document.body.style.backgroundColor;
    document.title = ['Home', doc?.organization?.name, brandName].filter(Boolean).join(' · ');
    document.body.style.backgroundColor = vars['--uh-bg'];
    return () => {
      document.title = previousTitle;
      document.body.style.backgroundColor = previousBg;
    };
  }, [doc?.organization?.name, brandName, vars]);

  const closeOverlay = useCallback(() => {
    setOverlay(current => {
      if (current?.kind === 'tour') writeFlag(TOUR_KEY, '1');
      return null;
    });
  }, []);

  const openPalette = useCallback(() => { setOpenMenu(null); setOverlay({ kind: 'palette' }); }, []);
  const openTour = useCallback(() => { setOpenMenu(null); setOverlay({ kind: 'tour', step: 0 }); }, []);
  const openShortcuts = useCallback(() => { setOpenMenu(null); setOverlay({ kind: 'keys' }); }, []);
  const switchOrg = useCallback((orgId) => {
    setOpenMenu(null);
    orgs?.switchOrganization?.(orgId);
  }, [orgs]);

  // Keyboard (DESIGN l): only shortcuts that are implemented are hinted on the page.
  useEffect(() => {
    const onKey = (event) => {
      const mod = event.metaKey || event.ctrlKey;
      const key = event.key;
      if (mod && key.toLowerCase() === 'k') {
        event.preventDefault();
        setOverlay(current => (current?.kind === 'palette' ? null : { kind: 'palette' }));
        setOpenMenu(null);
        return;
      }
      if (mod && key === '.') {
        event.preventDefault();
        setOverlay(null);
        setKeyboardOpen(true);
        setOpenMenu(current => (current === 'apps' ? null : 'apps'));
        return;
      }
      if (overlay || mod || event.altKey || isTyping()) return;
      if (key === 'Escape') {
        setOpenMenu(null);
        return;
      }
      if (key === '?') {
        event.preventDefault();
        const narrow = window.matchMedia?.('(max-width: 480px)').matches;
        if (narrow) openShortcuts();
        else {
          setKeyboardOpen(true);
          setOpenMenu(current => (current === 'help' ? null : 'help'));
        }
        return;
      }
      if (openMenu) return;
      const lower = key.toLowerCase();
      if (lower !== 'j' && lower !== 'k' && lower !== 'a' && lower !== 'o') return;
      const rows = Array.from(document.querySelectorAll('#uh-needs-list [data-item]:not(.is-leaving)'));
      if (!rows.length) return;
      const index = rows.findIndex(row => row.getAttribute('data-item') === currentId);
      if (lower === 'j' || lower === 'k') {
        event.preventDefault();
        const next = index < 0 ? 0 : Math.min(rows.length - 1, Math.max(0, index + (lower === 'j' ? 1 : -1)));
        rows[next].focus();
        setCurrentId(rows[next].getAttribute('data-item'));
        return;
      }
      if (index < 0) return;
      const row = rows[index];
      if (lower === 'a') row.querySelector('[data-primary-action]')?.click();
      if (lower === 'o') row.querySelector('a.uh-btn')?.click();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [overlay, openMenu, currentId, openShortcuts]);

  // A menu opened with the mouse keeps focus on its button; one opened from the keyboard moves focus in.
  useEffect(() => {
    if (!openMenu) setKeyboardOpen(false);
  }, [openMenu]);

  const paletteEntries = useMemo(() => {
    const commands = [
      { id: 'cmd:appearance', label: 'Appearance', sub: 'Theme, mode, section colour and typeface', run: () => setOpenMenu(window.matchMedia?.('(max-width: 480px)').matches ? 'appear-sheet' : 'appear') },
      { id: 'cmd:tour', label: 'How it works', sub: 'Help · 5 steps', run: openTour },
      { id: 'cmd:keys', label: 'Keyboard shortcuts', sub: 'Help', run: openShortcuts }
    ];
    for (const org of orgs?.organizations || []) {
      if (String(org.id) !== String(doc?.organization?.id)) {
        commands.push({ id: `cmd:org:${org.id}`, label: `Switch to ${org.name}`, sub: 'Organization', run: () => switchOrg(org.id) });
      }
    }
    return paletteIndex(doc, { commands });
  }, [doc, orgs?.organizations, openTour, openShortcuts, switchOrg]);

  const runEntry = useCallback((entry) => {
    if (entry.run) entry.run();
    else if (entry.href) window.open(entry.href, '_blank', 'noopener,noreferrer');
  }, []);

  const retryModule = async (id) => {
    setRetrying(current => new Set(current).add(id));
    try {
      await retry();
    } finally {
      setRetrying(current => {
        const next = new Set(current);
        next.delete(id);
        return next;
      });
    }
  };

  if (!doc) return null;

  const renderModule = (mod) => {
    const Component = MODULE_COMPONENTS[mod.id];
    if (!Component) return null;
    return (
      <Component
        key={mod.id}
        mod={mod}
        tz={tz}
        nowIso={nowIso}
        fetchImpl={fetchImpl}
        onRetry={() => retryModule(mod.id)}
        onResolved={retry}
        loading={retrying.has(mod.id)}
        lastGood={mod.status === 'unavailable' ? lastGood.current[mod.id] : null}
        currentId={currentId}
        setCurrentId={setCurrentId}
      />
    );
  };

  return (
    <div
      ref={rootRef}
      className="uh"
      data-family={appearance.family}
      data-mode={resolvedMode}
      data-intensity={appearance.intensity}
      data-font={appearance.font}
      data-live={live}
      style={vars}
    >
      <a className="uh-skip no-accent" href="#uh-main">Skip to your day</a>
      <HomeTopBar
        doc={doc}
        orgs={orgs}
        onSwitchOrg={switchOrg}
        openMenu={openMenu}
        setOpenMenu={setOpenMenu}
        keyboardOpen={keyboardOpen}
        brandName={brandName}
        brandLogo={brandLogo}
        fallbackLogo={FALLBACK_LOGO}
        appearance={appearance}
        resolvedMode={resolvedMode}
        setAppearance={setAppearance}
        onOpenPalette={openPalette}
        onOpenTour={openTour}
        onOpenShortcuts={openShortcuts}
        isPlatformAdmin={isPlatformAdmin}
        onSignOut={() => signOut(fetchImpl)}
      />
      <main className="uh-page" id="uh-main" tabIndex={-1}>
        <div className={`uh-grid${side.length ? '' : ' is-single'}`}>
          <section className="uh-main" aria-label="Your day">
            <StatusLine doc={doc} live={live} tz={tz} />
            {main.map(renderModule)}
          </section>
          {side.length > 0 && (
            <aside className="uh-side" aria-label={side.map(mod => MODULES[mod.id].title).join(' and ')}>
              {side.map(renderModule)}
            </aside>
          )}
        </div>
      </main>
      {overlay?.kind === 'palette' && <CommandPalette entries={paletteEntries} onClose={closeOverlay} onRun={runEntry} />}
      {overlay?.kind === 'tour' && <HowItWorks start={overlay.step || 0} onClose={closeOverlay} />}
      {overlay?.kind === 'keys' && <ShortcutsDialog onClose={closeOverlay} />}
    </div>
  );
}
