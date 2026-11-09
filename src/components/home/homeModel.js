/**
 * What the home knows about apps, modules and items, and how it words times,
 * counts and money. Everything shown comes from the home-state document
 * (GET /api/v1/home/state, schema uc.home.state/1); this file only decides
 * colour, icon, label and phrasing. Nothing here invents a number.
 */

export const STATE_SCHEMA = 'uc.home.state/1';

// App colour and icon (DESIGN k: Project-Ops blue, Meeting-Ops violet, Email-Ops
// teal, Customer-Ops amber, Accounting-Ops green, Center Deep Research rose,
// Outreach coral). Keys are the document's app keys; catalog slugs map below.
export const APPS = {
  'project-ops': { label: 'Project-Ops', hue: 'blue', icon: 'task' },
  'meeting-ops': { label: 'Meeting-Ops', hue: 'violet', icon: 'meet' },
  'email-ops': { label: 'Email-Ops', hue: 'teal', icon: 'mail' },
  'customer-ops': { label: 'Customer-Ops', hue: 'amber', icon: 'handshake' },
  'accounting-ops': { label: 'Accounting-Ops', hue: 'green', icon: 'wallet' },
  'center-deep': { label: 'Center Deep Research', hue: 'rose', icon: 'topic' },
  outreach: { label: 'Outreach', hue: 'coral', icon: 'phone' },
  'ops-center': { label: 'Ops-Center', hue: 'indigo', icon: 'apps' }
};

const SLUG_TO_APP = {
  'center-deep-research': 'center-deep',
  'center-deep': 'center-deep'
};

const CODE_TO_APP = { po: 'project-ops', mo: 'meeting-ops', eo: 'email-ops', co: 'customer-ops', ao: 'accounting-ops', cdr: 'center-deep' };

export function appKey(value) {
  const key = String(value || '').toLowerCase();
  return SLUG_TO_APP[key] || key;
}

export function appInfo(value) {
  const key = appKey(value);
  return APPS[key] || { label: humanize(key) || 'App', hue: 'slate', icon: 'apps' };
}

export function itemApp(item) {
  if (item?.app) return appKey(item.app);
  const code = String(item?.id || '').split(':')[0];
  return CODE_TO_APP[code] || '';
}

export function hueVar(hue) {
  return `var(--uh-h-${hue || 'slate'})`;
}

// Modules, in DESIGN section b's round-three order. Only modules the document
// provides are rendered; ids the backend does not send yet (email, agents,
// calls, pipeline, walkthroughs, team, assistant) have no entry here.
export const MODULES = {
  needs_you: { title: 'Needs you', hue: 'amber', icon: 'inbox', column: 'main', order: 1 },
  today: { title: 'Today', hue: 'blue', icon: 'clock', column: 'main', order: 2 },
  recent_meetings: { title: 'Meetings', hue: 'violet', icon: 'meet', column: 'main', order: 3 },
  since_last_visit: { title: 'Since you were last here', hue: 'slate', icon: 'history', column: 'main', order: 5 },
  apps: { title: 'Your apps', hue: 'violet', icon: 'apps', column: 'main', order: 6 },
  money: { title: 'Money', hue: 'green', icon: 'wallet', column: 'main', order: 7 },
  watched_topics: { title: 'Watched topics', hue: 'rose', icon: 'topic', column: 'side', order: 3 },
  usage: { title: 'Usage', hue: 'teal', icon: 'cpu', column: 'side', order: 5 }
};

// One plain sentence per module for its empty state (DESIGN c).
export const EMPTY_TEXT = {
  needs_you: 'Nothing needs you.',
  today: 'Nothing due today.',
  recent_meetings: 'No meetings yet. Record one in Meeting-Ops or import a recording.',
  apps: 'No apps are entitled to this organization yet. Ask your org manager.',
  watched_topics: 'You are not watching any topics yet. Start one in Center Deep Research.',
  money: 'Accounting-Ops is not connected to a bank yet.',
  usage: 'No usage yet this month.'
};

export function isValidState(doc) {
  return Boolean(doc && typeof doc === 'object' && doc.schema === STATE_SCHEMA && Array.isArray(doc.modules));
}

/** The modules the page renders, split by column, in the design's order. */
export function layoutModules(doc) {
  const main = [];
  const side = [];
  for (const mod of doc?.modules || []) {
    const spec = MODULES[mod?.id];
    if (!spec) continue;
    if (mod.status === 'not_entitled' || mod.status === 'no_access') continue;
    (spec.column === 'side' ? side : main).push(mod);
  }
  const byOrder = (a, b) => MODULES[a.id].order - MODULES[b.id].order;
  return { main: main.sort(byOrder), side: side.sort(byOrder) };
}

// ------------------------------------------------------------------ items

/** The short type label on a row (DESIGN c): what kind of thing it is. */
export function itemType(item, moduleId) {
  const [code, kind] = String(item?.id || '').split(':');
  if (moduleId === 'needs_you') {
    if (code === 'eo') return item.to ? 'Draft' : 'Approval';
    if (code === 'ao') return 'Approval';
    if (code === 'po' && kind === 'triage') {
      return /meeting/i.test(item?.proposed_by?.name || '') ? 'Action item' : 'Proposal';
    }
    return 'Review';
  }
  if (moduleId === 'today') {
    if (item.kind === 'follow_up') return 'Follow-up';
    if (item.overdue) return 'Overdue';
    return item.all_day ? 'Task' : 'Due';
  }
  if (moduleId === 'recent_meetings') {
    if (item.has_summary) return 'Summary';
    if (item.status === 'processing') return 'Processing';
    return 'Recording';
  }
  if (moduleId === 'since_last_visit') {
    return { meeting_summarized: 'Summary', task_closed: 'Done', monitor_update: 'Update' }[item.kind] || 'Change';
  }
  return humanize(item?.kind || '') || 'Item';
}

/** "agent:categorizer" becomes "categorizer (agent)"; other names stay as given. */
export function proposerName(proposedBy) {
  const name = String(proposedBy?.name || '').trim();
  if (!name) return { name: '', agent: false };
  if (/^agent:/i.test(name)) return { name: name.replace(/^agent:/i, '').replace(/[_-]+/g, ' ').trim(), agent: true };
  return { name, agent: false };
}

export function openAction(item) {
  return (item?.actions || []).find(action => action?.id === 'open' && action.href) || null;
}

/** Offered home actions: only what the item's own actions list carries. */
export function offeredActions(item) {
  return (item?.actions || []).filter(action => action && action.method === 'POST' && typeof action.href === 'string'
    && action.href.startsWith('/api/v1/home/actions/'));
}

export const PRIMARY_ACTIONS = new Set(['approve', 'accept', 'done']);

// What a row says while its action is with the app (DESIGN h, wow moment 2).
export function pendingText(item, action) {
  if (action.id === 'approve' && itemApp(item) === 'email-ops') return 'Sending now';
  return {
    approve: 'Approving', accept: 'Accepting', reject: 'Rejecting', done: 'Marking done'
  }[action.id] || 'Working';
}

// ------------------------------------------------------------------ words

const WORDS = ['no', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten'];

export function countWord(value) {
  return WORDS[value] || String(value);
}

export function capitalize(text) {
  const s = String(text || '');
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export function humanize(value) {
  return String(value || '').replace(/[_-]+/g, ' ').replace(/\s+/g, ' ').trim().toLowerCase();
}

export function plural(value, one, many) {
  return `${value} ${value === 1 ? one : many}`;
}

/** The sub-line under the greeting, from Since you were last here (DESIGN m). */
export function sinceSentence(since, tz, now) {
  if (!since || since.status === 'unavailable' || !since.cursor) return '';
  const counts = since.counts || {};
  const parts = [];
  const m = counts.meetings_summarized;
  const t = counts.tasks_closed;
  const u = counts.monitor_updates;
  if (m) parts.push(`${countWord(m)} ${m === 1 ? 'meeting was' : 'meetings were'} summarized`);
  if (t) parts.push(`${countWord(t)} ${t === 1 ? 'task was' : 'tasks were'} closed`);
  if (u) parts.push(`${countWord(u)} watched ${u === 1 ? 'topic changed' : 'topics changed'}`);
  const when = sinceWhen(since.cursor, tz, now);
  if (!parts.length) return since.status === 'empty' ? `Nothing changed since ${when}.` : '';
  const list = parts.length === 1 ? parts[0] : `${parts.slice(0, -1).join(', ')} and ${parts[parts.length - 1]}`;
  return `${capitalize(list)} since ${when}.`;
}

function sinceWhen(iso, tz, now) {
  const day = dayName(iso, tz, now);
  return day === 'today' ? hhmm(iso, tz) : day;
}

/** "Good evening, Mara." in the document's timezone. */
export function greeting(displayName, tz, nowIso) {
  const hour = Number(partsOf(nowIso, tz).hour);
  const part = hour < 5 ? 'evening' : hour < 12 ? 'morning' : hour < 18 ? 'afternoon' : 'evening';
  const first = firstName(displayName);
  return first ? `Good ${part}, ${first}.` : `Good ${part}.`;
}

export function firstName(displayName) {
  const name = String(displayName || '').trim();
  if (!name || name.includes('@') || name.toLowerCase() === 'you') return '';
  return name.split(/\s+/)[0];
}

export function initials(displayName) {
  const name = String(displayName || '').trim();
  if (!name) return '?';
  if (name.includes('@')) return name[0].toUpperCase();
  const parts = name.split(/\s+/).filter(Boolean);
  return ((parts[0]?.[0] || '') + (parts.length > 1 ? parts[parts.length - 1][0] : '')).toUpperCase();
}

export const ROLE_NAMES = {
  owner: 'Owner',
  org_admin: 'Org admin',
  admin: 'Org admin',
  billing_admin: 'Billing admin',
  member: 'Member'
};

export function roleName(role) {
  return ROLE_NAMES[String(role || '').toLowerCase()] || '';
}

export function isManagerRole(role) {
  return ['owner', 'org_admin', 'admin'].includes(String(role || '').toLowerCase());
}

/**
 * The status line with its count picked out in the accent colour (DESIGN h,
 * the sentence). The words are the server's; only the emphasis is added.
 */
export function splitStatusText(text) {
  const s = String(text || '');
  const match = s.match(/^((?:[A-Z][a-z]+)(?: or more)? things?|Nothing)\b/);
  if (!match) return { lead: '', rest: s };
  return { lead: match[1], rest: s.slice(match[1].length) };
}

// ------------------------------------------------------------------ times

function safeZone(tz) {
  try {
    new Intl.DateTimeFormat('en-GB', { timeZone: tz || 'UTC' });
    return tz || 'UTC';
  } catch {
    return 'UTC';
  }
}

function partsOf(iso, tz) {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return {};
  const fmt = new Intl.DateTimeFormat('en-GB', {
    timeZone: safeZone(tz), year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hourCycle: 'h23', weekday: 'long'
  });
  const out = {};
  for (const part of fmt.formatToParts(date)) out[part.type] = part.value;
  return out;
}

export function hhmm(iso, tz) {
  const p = partsOf(iso, tz);
  return p.hour ? `${p.hour}:${p.minute}` : '';
}

function dayNumber(iso, tz) {
  const p = partsOf(iso, tz);
  if (!p.year) return null;
  return Date.UTC(Number(p.year), Number(p.month) - 1, Number(p.day)) / 86400000;
}

/** "today", "yesterday", a weekday within the last six days, else "6 Nov". */
export function dayName(iso, tz, nowIso) {
  const day = dayNumber(iso, tz);
  const today = dayNumber(nowIso, tz);
  if (day === null || today === null) return '';
  const diff = today - day;
  if (diff === 0) return 'today';
  if (diff === 1) return 'yesterday';
  if (diff === -1) return 'tomorrow';
  const p = partsOf(iso, tz);
  if (diff > 1 && diff < 7) return p.weekday;
  const month = new Intl.DateTimeFormat('en-GB', { timeZone: safeZone(tz), month: 'short' }).format(new Date(iso));
  return `${Number(p.day)} ${month}`;
}

/** A row's time: "17:20" today, "yesterday 17:20", else the day. */
export function whenLabel(iso, tz, nowIso) {
  if (!iso) return '';
  const day = dayName(iso, tz, nowIso);
  if (day === 'today') return hhmm(iso, tz);
  if (day === 'yesterday' || day === 'tomorrow') return `${day} ${hhmm(iso, tz)}`;
  return day;
}

/** "Thursday 18:12" for a cursor, "today 14:02" style for recent ones. */
export function cursorLabel(iso, tz, nowIso) {
  const day = dayName(iso, tz, nowIso);
  return `${day === 'today' ? 'today' : capitalize(day)} ${hhmm(iso, tz)}`.trim();
}

/** The eyebrow date: "Monday 9 November". */
export function longDate(iso, tz) {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '';
  return new Intl.DateTimeFormat('en-GB', { timeZone: safeZone(tz), weekday: 'long', day: 'numeric', month: 'long' })
    .format(date).replace(',', '');
}

export function durationLabel(seconds) {
  const s = Number(seconds);
  if (!Number.isFinite(s) || s <= 0) return '';
  const minutes = Math.max(1, Math.round(s / 60));
  if (minutes < 60) return `${minutes} min`;
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return m ? `${h} h ${m} min` : `${h} h`;
}

export function minutesBetween(a, b) {
  const x = new Date(a).getTime();
  const y = new Date(b).getTime();
  if (Number.isNaN(x) || Number.isNaN(y)) return null;
  return Math.abs(y - x) / 60000;
}

// ------------------------------------------------------------------ money

export function parseAmount(value) {
  if (value === null || value === undefined || value === '') return null;
  const n = Number(String(value).replace(/,/g, ''));
  return Number.isFinite(n) ? n : null;
}

export function formatMoney(value, currency = 'USD', { cents = false } = {}) {
  const n = parseAmount(value);
  if (n === null) return '';
  try {
    return new Intl.NumberFormat('en-US', {
      style: 'currency', currency: currency || 'USD',
      minimumFractionDigits: cents ? 2 : 0, maximumFractionDigits: cents ? 2 : 0
    }).format(n);
  } catch {
    return `${n.toLocaleString('en-US')} ${currency || ''}`.trim();
  }
}

export function formatNumber(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n.toLocaleString('en-US') : '';
}
