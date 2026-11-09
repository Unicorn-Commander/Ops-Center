import React, { useEffect, useRef } from 'react';
import Icon from './homeIcons';
import { AppMark, ExtLink } from './HomeParts';
import { appScreens } from './homeScreens';
import { clearCache } from './homeApi';
import { FAMILIES, FAMILY_IDS, FONTS, familySwatch } from './homeTokens';
import { formatNumber, initials, isManagerRole, roleName } from './homeModel';

const IS_MAC = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent || '');
export const MOD_KEY = IS_MAC ? '⌘' : 'Ctrl+';

const MODE_NAMES = { system: 'match system', light: 'light', dark: 'dark', contrast: 'high contrast' };

/** Arrow keys, Home, End and Escape inside an open menu; focus the first item on open. */
function useMenuKeys(open, menuRef, onClose, focusFirst) {
  useEffect(() => {
    if (!open || !menuRef.current) return undefined;
    const menu = menuRef.current;
    const items = () => Array.from(menu.querySelectorAll('[role^="menuitem"], [role="radio"], a[href], button:not([disabled])'))
      .filter(el => el.offsetParent !== null || el === document.activeElement);
    if (focusFirst) {
      const first = items()[0];
      if (first) first.focus();
    }
    const onKey = (event) => {
      const list = items();
      const index = list.indexOf(document.activeElement);
      if (event.key === 'Escape') {
        event.preventDefault();
        event.stopPropagation();
        onClose(true);
      } else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault();
        if (!list.length) return;
        const next = event.key === 'ArrowDown' ? (index + 1) % list.length : (index - 1 + list.length) % list.length;
        list[next].focus();
      } else if (event.key === 'Home' || event.key === 'End') {
        event.preventDefault();
        if (list.length) list[event.key === 'Home' ? 0 : list.length - 1].focus();
      }
    };
    menu.addEventListener('keydown', onKey);
    return () => menu.removeEventListener('keydown', onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);
}

function MenuWrap({ id, label, open, onToggle, onClose, trigger, menuClass = '', role = 'menu', children, wrapClass = '', focusFirst }) {
  const menuRef = useRef(null);
  const triggerRef = useRef(null);
  const close = (refocus) => {
    onClose();
    if (refocus) triggerRef.current?.focus();
  };
  useMenuKeys(open, menuRef, close, focusFirst);
  return (
    <div className={`uh-menuwrap ${wrapClass}`.trim()}>
      {trigger({ ref: triggerRef, 'aria-haspopup': role === 'dialog' ? 'dialog' : 'menu', 'aria-expanded': open, 'aria-controls': open ? id : undefined, onClick: onToggle })}
      {open && (
        <div ref={menuRef} id={id} className={`uh-menu ${menuClass}`.trim()} role={role} aria-label={label}>
          {children}
        </div>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ org

function OrgSwitcher({ doc, orgs, open, onToggle, onClose, onSwitch, focusFirst }) {
  const name = doc?.organization?.name || 'Your organization';
  const list = orgs?.organizations || [];
  const currentId = String(doc?.organization?.id || orgs?.currentOrgId || '');
  if (list.length < 2) {
    // One organization: a static label, no chevron (DESIGN l).
    return (
      <div className="uh-menuwrap is-org">
        <span className="uh-tb is-static" title="You belong to one organization.">
          <span className="uh-orgdot" aria-hidden="true" />
          <span className="uh-orgname">{name}</span>
          <span className="uh-sr">. You belong to one organization.</span>
        </span>
      </div>
    );
  }
  return (
    <MenuWrap
      id="uh-org-menu" label="Your organizations" open={open} onToggle={onToggle} onClose={onClose} wrapClass="is-org" focusFirst={focusFirst}
      trigger={props => (
        <button type="button" className="uh-tb" {...props} aria-label={`Organization: ${name}. You belong to ${list.length} organizations. Switch organization`}>
          <span className="uh-orgdot" aria-hidden="true" />
          <span className="uh-orgname">{name}</span>
          <Icon name="chev" className="uh-chev" />
        </button>
      )}
    >
      <div className="uh-mh" aria-hidden="true">Your organizations</div>
      {list.map(org => {
        const current = String(org.id) === currentId;
        return (
          <button key={org.id} type="button" className="uh-mi" role="menuitemradio" aria-checked={current} onClick={() => (current ? onClose() : onSwitch(org.id))}>
            <span className="uh-mi-check" aria-hidden="true">{current ? '✓' : ''}</span>
            <span>{org.name}</span>
            <span className="uh-mi-sub">{roleName(org.role || org.org_role) || 'Member'}</span>
          </button>
        );
      })}
      <div className="uh-sep" />
      <div className="uh-note">Switching changes everything on this page: apps, counts and what needs you. Apps open in that organization&apos;s workspace where the app supports it.</div>
    </MenuWrap>
  );
}

// ------------------------------------------------------------------ apps

function AppsMenu({ doc, open, onToggle, onClose, focusFirst }) {
  const apps = appScreens(doc);
  return (
    <MenuWrap
      id="uh-apps-menu" label="Apps" open={open} onToggle={onToggle} onClose={onClose} menuClass="uh-appsmenu" focusFirst={focusFirst}
      trigger={props => (
        <button type="button" className="uh-tb is-apps" {...props} aria-label={`Apps. Keyboard shortcut ${MOD_KEY} period`}>
          <Icon name="grid" />
          <span className="uh-tb-label">Apps</span>
          <span className="uh-kbd" aria-hidden="true">{MOD_KEY}.</span>
        </button>
      )}
    >
      {apps.length === 0 ? (
        <div className="uh-note">No apps are listed for this organization right now.</div>
      ) : (
        <div className="uh-grid3">
          {apps.map(app => {
            const first = (app.tile.numbers || [])[0];
            return (
              <div key={app.slug} className="uh-ag">
                <div className="uh-an">
                  <AppMark app={app.key} small />
                  <span className="uh-an-name">{app.name}</span>
                  {first && <span className="uh-an-st uh-tnum">{formatNumber(first.value)} {first.label}</span>}
                </div>
                {app.open && <ExtLink className="uh-ag-link" href={app.open} role="menuitem">Open {app.name}</ExtLink>}
                {app.screens.map(screen => (
                  <ExtLink key={screen.label} className="uh-ag-link" href={screen.href} role="menuitem">{screen.label}</ExtLink>
                ))}
              </div>
            );
          })}
        </div>
      )}
      <div className="uh-appsfoot">
        <span>Each link opens that screen in your own session, in a new tab.</span>
        <a className="uh-link no-accent" href="#uh-mod-apps" role="menuitem" onClick={() => onClose()}>All apps and Connect your AI</a>
      </div>
    </MenuWrap>
  );
}

// ------------------------------------------------------------------ appearance

export function AppearancePanel({ appearance, resolvedMode, setAppearance }) {
  const radio = (key, value, label) => (
    <button key={value} type="button" role="radio" aria-checked={appearance[key] === value} onClick={() => setAppearance({ [key]: value })}>
      {label}
    </button>
  );
  return (
    <>
      <div className="uh-mh" id="uh-fam-label">Theme</div>
      <div className="uh-fams" role="radiogroup" aria-labelledby="uh-fam-label">
        {FAMILY_IDS.map(id => {
          const [a, b] = familySwatch(id, resolvedMode === 'dark' ? 'dark' : 'light');
          return (
            <button key={id} type="button" className="uh-fam" role="radio" aria-checked={appearance.family === id} onClick={() => setAppearance({ family: id })}>
              <span className="uh-sw" style={{ background: `linear-gradient(135deg, ${a} 50%, ${b} 50%)` }} aria-hidden="true" />
              <span><span className="uh-fn">{FAMILIES[id].name}</span><span className="uh-fd">{FAMILIES[id].desc}</span></span>
            </button>
          );
        })}
      </div>
      <div className="uh-row2"><span className="uh-lbl" id="uh-mode-label">Mode</span>
        <div className="uh-seg" role="radiogroup" aria-labelledby="uh-mode-label">
          {radio('mode', 'system', 'System')}{radio('mode', 'light', 'Light')}{radio('mode', 'dark', 'Dark')}{radio('mode', 'contrast', 'High contrast')}
        </div>
      </div>
      <div className="uh-row2"><span className="uh-lbl" id="uh-int-label">Section colour</span>
        <div className="uh-seg" role="radiogroup" aria-labelledby="uh-int-label">
          {radio('intensity', 'subtle', 'Subtle')}{radio('intensity', 'vivid', 'Vivid')}
        </div>
      </div>
      <div className="uh-row2"><span className="uh-lbl" id="uh-font-label">Typeface</span>
        <div className="uh-seg" role="radiogroup" aria-labelledby="uh-font-label">
          {Object.entries(FONTS).map(([id, face]) => radio('font', id, face.name))}
        </div>
      </div>
      <div className="uh-note" style={{ paddingTop: 12 }}>Remembered on this device. Every theme passes WCAG AA for text.</div>
    </>
  );
}

export function appearanceSummary(appearance) {
  return `${FAMILIES[appearance.family]?.name || 'Professional'}, ${MODE_NAMES[appearance.mode] || 'light'}`;
}

// ------------------------------------------------------------------ sign out

export async function signOut(fetchImpl = globalThis.fetch) {
  clearCache();
  try {
    window.localStorage.removeItem('uc.home.seen');
  } catch {
    // ignore
  }
  try {
    const response = await fetchImpl('/api/v1/auth/logout', { method: 'POST', credentials: 'include' });
    if (response.ok) {
      const data = await response.json().catch(() => ({}));
      ['user', 'token', 'authToken', 'userInfo'].forEach(key => { try { localStorage.removeItem(key); } catch { /* ignore */ } });
      if (data.logout_url || data.sso_logout_url) {
        window.location.href = data.logout_url || data.sso_logout_url;
        return;
      }
    }
  } catch {
    // fall through
  }
  ['user', 'token', 'authToken', 'userInfo'].forEach(key => { try { localStorage.removeItem(key); } catch { /* ignore */ } });
  window.location.href = '/auth/logout';
}

// ------------------------------------------------------------------ the bar

export default function HomeTopBar({
  doc, orgs, onSwitchOrg, openMenu, setOpenMenu, keyboardOpen, brandName, brandLogo, fallbackLogo,
  appearance, resolvedMode, setAppearance, onOpenPalette, onOpenTour, onOpenShortcuts, isPlatformAdmin, onSignOut
}) {
  const barRef = useRef(null);
  const toggle = id => setOpenMenu(current => (current === id ? null : id));
  const close = () => setOpenMenu(null);
  const role = doc?.person?.role;
  const name = doc?.person?.display_name || '';

  useEffect(() => {
    if (!openMenu) return undefined;
    const onDown = (event) => {
      if (barRef.current && !barRef.current.contains(event.target)) setOpenMenu(null);
    };
    document.addEventListener('mousedown', onDown);
    return () => document.removeEventListener('mousedown', onDown);
  }, [openMenu, setOpenMenu]);

  return (
    <header className="uh-top" role="banner" ref={barRef}>
      <a className="uh-brand no-accent" href="/dashboard" aria-label={`${brandName} home`}>
        <img src={brandLogo} alt="" onError={e => { if (fallbackLogo && e.currentTarget.src.indexOf(fallbackLogo) < 0) e.currentTarget.src = fallbackLogo; }} />
        <span className="uh-brand-word">{brandName}</span>
      </a>

      <OrgSwitcher doc={doc} orgs={orgs} open={openMenu === 'org'} onToggle={() => toggle('org')} onClose={close} onSwitch={onSwitchOrg} focusFirst={keyboardOpen} />
      <AppsMenu doc={doc} open={openMenu === 'apps'} onToggle={() => toggle('apps')} onClose={close} focusFirst={keyboardOpen} />

      <button type="button" className="uh-tb uh-search" onClick={onOpenPalette} aria-label={`Search, or jump to a screen. Keyboard shortcut ${MOD_KEY} K`}>
        <Icon name="search" />
        <span className="uh-search-label">Search, or jump to a screen</span>
        <span className="uh-kbd" aria-hidden="true">{MOD_KEY}K</span>
      </button>

      <MenuWrap
        id="uh-appear-menu" label="Appearance" role="dialog" open={openMenu === 'appear'} onToggle={() => toggle('appear')} onClose={close}
        wrapClass="uh-ph-hide" menuClass="is-right uh-appear" focusFirst={keyboardOpen}
        trigger={props => <button type="button" className="uh-iconbtn" {...props} aria-label="Appearance"><Icon name="palette" /></button>}
      >
        <AppearancePanel appearance={appearance} resolvedMode={resolvedMode} setAppearance={setAppearance} />
      </MenuWrap>

      <MenuWrap
        id="uh-help-menu" label="Help" open={openMenu === 'help'} onToggle={() => toggle('help')} onClose={close}
        wrapClass="uh-ph-hide" menuClass="is-right" focusFirst={keyboardOpen}
        trigger={props => <button type="button" className="uh-iconbtn" {...props} aria-label="Help"><Icon name="help" /></button>}
      >
        <button type="button" className="uh-mi" role="menuitem" onClick={() => { close(); onOpenTour(); }}>
          <span className="uh-mi-check" aria-hidden="true" />How it works<span className="uh-mi-sub">5 steps</span>
        </button>
        <button type="button" className="uh-mi" role="menuitem" onClick={() => { close(); onOpenShortcuts(); }}>
          <span className="uh-mi-check" aria-hidden="true" />Keyboard shortcuts<span className="uh-mi-sub"><span className="uh-kbd">?</span></span>
        </button>
      </MenuWrap>

      <MenuWrap
        id="uh-acct-menu" label="Account" open={openMenu === 'acct'} onToggle={() => toggle('acct')} onClose={close} menuClass="is-right" focusFirst={keyboardOpen}
        trigger={props => <button type="button" className="uh-avatar" {...props} aria-label={`Account menu for ${name || 'you'}`}>{initials(name)}</button>}
      >
        <div className="uh-note"><b>{name || 'Signed in'}</b><br />{[roleName(role), doc?.organization?.name].filter(Boolean).join(', ')}</div>
        <div className="uh-sep" />
        <button type="button" className="uh-mi" role="menuitem" onClick={() => setOpenMenu('appear-sheet')}>
          <span className="uh-mi-check" aria-hidden="true" />Appearance<span className="uh-mi-sub">{appearanceSummary(appearance)}</span>
        </button>
        {isManagerRole(role) && (
          <a className="uh-mi no-accent" role="menuitem" href="/admin/org/team"><span className="uh-mi-check" aria-hidden="true" />Invite a teammate</a>
        )}
        {isPlatformAdmin && (
          <a className="uh-mi no-accent" role="menuitem" href="/admin"><span className="uh-mi-check" aria-hidden="true" />Admin console</a>
        )}
        <div className="uh-sep uh-ph" />
        <button type="button" className="uh-mi uh-ph" role="menuitem" onClick={() => { close(); onOpenTour(); }}>
          <span className="uh-mi-check" aria-hidden="true" />How it works<span className="uh-mi-sub">5 steps</span>
        </button>
        <div className="uh-sep" />
        <button type="button" className="uh-mi" role="menuitem" onClick={() => { close(); onSignOut(); }}>
          <span className="uh-mi-check" aria-hidden="true" />Sign out
        </button>
      </MenuWrap>
      {openMenu === 'appear-sheet' && (
        <div className="uh-menu is-right uh-appear" role="dialog" aria-label="Appearance" id="uh-appear-sheet">
          <AppearancePanel appearance={appearance} resolvedMode={resolvedMode} setAppearance={setAppearance} />
          <div className="uh-row2"><span /><button type="button" className="uh-btn is-sm" onClick={close}>Done</button></div>
        </div>
      )}
    </header>
  );
}
