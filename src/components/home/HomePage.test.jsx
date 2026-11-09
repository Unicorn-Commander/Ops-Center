import React from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import golden from '../../../backend/tests/home/fixtures/golden_state_actions_off.json';
import { ThemeProvider } from '../../contexts/ThemeContext';
import { BrandingProvider } from '../../contexts/BrandingContext';
import { OrganizationProvider } from '../../contexts/OrganizationContext';
import HomePage from '../../pages/HomePage';
import DashboardHome from '../../pages/DashboardHome';
import { resetCsrfToken } from './homeApi';

// The golden document is the backend's own fixture (fictional Rivergreen Coffee Co.).
const ORG = golden.organization.id;
const OTHER_ORG = '7c1d2e3f-0a9b-4c8d-9e7f-6a5b4c3d2e10';

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

const offer = (source, id, action, label, note) => ({
  id: action, label, method: 'POST', href: `/api/v1/home/actions/${source}/${id}/${action}`, ...(note ? { note } : {})
});

/** The golden document with the actions the backend offers when HOME_ACTIONS_ENABLED is on. */
function withActions(doc) {
  for (const mod of doc.modules) {
    for (const item of mod.items || []) {
      const id = item.id || '';
      if (mod.id === 'needs_you' && id.startsWith('eo:draft:') && item.to && !item.sends_at) {
        item.actions.push(offer('email-ops', id, 'approve', 'Approve', 'Sends the email now'), offer('email-ops', id, 'reject', 'Reject'));
      }
      if (mod.id === 'needs_you' && id.startsWith('ao:approval:') && /bank transaction/.test(item.title)) {
        item.actions.push(offer('accounting-ops', id, 'approve', 'Approve'), offer('accounting-ops', id, 'reject', 'Reject'));
      }
      if (mod.id === 'today' && id === 'po:task:c3d4e5f6-a7b8-4c9d-8e0f-2a3b4c5d6e88') {
        item.actions.push(offer('project-ops', id, 'done', 'Mark done'));
      }
    }
  }
  return doc;
}

const EMAIL_ID = 'eo:draft:3f6c2a1e-8b4d-4c2a-9e1f-5a7b8c9d0e11';

function memoryStorage(seed = {}) {
  const data = { ...seed };
  return {
    getItem: key => (key in data ? data[key] : null),
    setItem: (key, value) => { data[key] = String(value); },
    removeItem: key => { delete data[key]; },
    clear: () => { Object.keys(data).forEach(k => delete data[k]); },
    data
  };
}

function json(body, status = 200, headers = {}) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
    headers: { get: name => headers[name] ?? headers[name.toLowerCase()] ?? null }
  };
}

let calls;
let routes;
let storage;

function installFetch() {
  calls = [];
  global.fetch = vi.fn(async (input, options = {}) => {
    const url = String(input);
    const method = (options.method || 'GET').toUpperCase();
    calls.push({ url, method, headers: options.headers || {}, body: options.body });
    for (const [match, handler] of routes) {
      if (typeof match === 'string' ? url.startsWith(match) : match.test(url)) {
        const out = await handler({ url, method, headers: options.headers || {} });
        if (out) return out;
      }
    }
    return json({ detail: 'Not Found' }, 404);
  });
}

function baseRoutes(orgs = [{ id: ORG, name: 'Rivergreen Coffee Co.', role: 'owner' }]) {
  return [
    ['/api/v1/branding/config', () => json({ company_name: 'Unicorn Commander' })],
    ['/api/v1/org/my-orgs', () => json(orgs)],
    ['/api/v1/auth/csrf-token', () => json({ csrf_token: 'test-csrf' })]
  ];
}

function renderHome(doc, props = {}) {
  return render(
    <ThemeProvider>
      <BrandingProvider>
        <OrganizationProvider>
          <HomePage initialDoc={doc} fetchImpl={global.fetch} onOff={props.onOff || (() => {})} />
        </OrganizationProvider>
      </BrandingProvider>
    </ThemeProvider>
  );
}

beforeEach(() => {
  storage = memoryStorage({ 'uc.home.tourSeen': '1', userInfo: JSON.stringify({ email: 'mara@rivergreen.example' }) });
  Object.defineProperty(window, 'localStorage', { value: storage, configurable: true });
  routes = baseRoutes();
  installFetch();
  resetCsrfToken();
  window.open = vi.fn();
});

afterEach(() => {
  vi.useRealTimers();
});

describe('the home renders the state document', () => {
  test('modules come in the design order, and a module the document does not provide does not render', () => {
    const { container } = renderHome(clone(golden));
    const main = Array.from(container.querySelectorAll('.uh-main [data-module]')).map(el => el.getAttribute('data-module'));
    const side = Array.from(container.querySelectorAll('.uh-side [data-module]')).map(el => el.getAttribute('data-module'));
    expect(main).toEqual(['needs_you', 'today', 'recent_meetings', 'since_last_visit', 'apps', 'money']);
    expect(side).toEqual(['watched_topics', 'usage']);
    for (const absent of ['Email', 'Agents at work', 'Calls and texts', 'Team', 'Customers and pipeline', 'Walkthroughs']) {
      expect(screen.queryByRole('heading', { name: new RegExp(`^${absent}`) })).not.toBeInTheDocument();
    }
  });

  test('a member sees no Money and no Usage when the document leaves them out', () => {
    const doc = clone(golden);
    doc.person.role = 'member';
    doc.modules = doc.modules.filter(mod => !['money', 'usage'].includes(mod.id));
    const { container } = renderHome(doc);
    expect(container.querySelector('[data-module="money"]')).toBeNull();
    expect(container.querySelector('[data-module="usage"]')).toBeNull();
    expect(screen.getByText('Member')).toBeInTheDocument();
  });

  test('the status line is the server sentence with the count picked out, in the document timezone', () => {
    renderHome(clone(golden));
    const h1 = screen.getByRole('heading', { level: 1 });
    expect(h1).toHaveTextContent('Good morning, Mara. Eight things need you, and five are due today.');
    expect(within(h1).getByText('Eight things')).toHaveClass('uh-status-n');
    expect(screen.getByText('Monday 9 November')).toBeInTheDocument();
    expect(screen.getByText('Two meetings were summarized, one task was closed and two watched topics changed since Friday.')).toBeInTheDocument();
  });

  test('"Nothing needs you" is a complete state', () => {
    const doc = clone(golden);
    const needs = doc.modules.find(mod => mod.id === 'needs_you');
    needs.status = 'empty';
    needs.items = [];
    needs.count = 0;
    doc.status_line.text = 'Nothing needs you.';
    doc.status_line.needs_you_count = 0;
    renderHome(doc);
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Good morning, Mara. Nothing needs you.');
    const module = screen.getByRole('article', { name: /Needs you/ });
    expect(within(module).getByText('Nothing needs you.')).toBeInTheDocument();
  });

  test('every module shows its own as-of; Money shows the bank feed time', () => {
    const { container } = renderHome(clone(golden));
    for (const id of ['needs_you', 'today', 'recent_meetings', 'apps', 'watched_topics', 'usage']) {
      expect(container.querySelector(`[data-module="${id}"] .uh-asof`)).toHaveTextContent('as of 10:00');
    }
    expect(container.querySelector('[data-module="money"] .uh-meta')).toHaveTextContent('bank feed 09:59');
  });

  test('rows link to their app in a new tab; with actions off there are no action buttons', () => {
    renderHome(clone(golden));
    const module = screen.getByRole('article', { name: /Needs you/ });
    expect(within(module).queryByRole('button', { name: 'Approve' })).not.toBeInTheDocument();
    const review = within(module).getAllByRole('link', { name: 'Review' })[0];
    expect(review).toHaveAttribute('href', 'https://mail-ops.example.com/agent-inbox');
    expect(review).toHaveAttribute('target', '_blank');
    expect(review).toHaveAttribute('rel', 'noopener noreferrer');
  });

  test('UI copy has no em dashes and no exclamation marks', () => {
    const { container } = renderHome(withActions(clone(golden)));
    expect(container.textContent).not.toMatch(/—/);
    expect(container.textContent).not.toMatch(/!/);
  });
});

describe('module states', () => {
  test('empty, not set up, unavailable with a retry, and reauth each say so in one sentence', async () => {
    const doc = clone(golden);
    const today = doc.modules.find(mod => mod.id === 'today');
    Object.assign(today, { status: 'empty', items: [] });
    const meetings = doc.modules.find(mod => mod.id === 'recent_meetings');
    Object.assign(meetings, { status: 'unavailable', reason: 'timeout' });
    meetings.source.forEach(s => Object.assign(s, { status: 'unavailable', reason: 'timeout' }));
    const topics = doc.modules.find(mod => mod.id === 'watched_topics');
    topics.status = 'not_set_up';
    topics.source.forEach(s => Object.assign(s, { status: 'not_set_up', note: 'Center Deep Research is not connected to the home on this ring yet.' }));
    const money = doc.modules.find(mod => mod.id === 'money');
    Object.assign(money, { status: 'unavailable', reason: 'reauth' });

    routes.push(['/api/v1/home/state', () => new Promise(() => {})]);
    renderHome(doc);
    expect(within(screen.getByRole('article', { name: /^Today/ })).getByText('Nothing due today.')).toBeInTheDocument();
    const meetingsBox = screen.getByRole('article', { name: /^Meetings/ });
    expect(within(meetingsBox).getByText(/Meeting-Ops did not answer in time\./)).toBeInTheDocument();
    expect(within(screen.getByRole('article', { name: /^Watched topics/ })).getByText(/not connected to the home on this ring yet/)).toBeInTheDocument();
    const moneyBox = screen.getByRole('article', { name: /^Money/ });
    expect(within(moneyBox).getByText(/Sign in again to refresh this\./)).toBeInTheDocument();
    expect(within(moneyBox).queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument();

    // Retry shows the loading state while the read is on its way.
    fireEvent.click(within(meetingsBox).getByRole('button', { name: 'Retry' }));
    await waitFor(() => expect(meetingsBox).toHaveAttribute('aria-busy', 'true'));
    expect(within(meetingsBox).getByText('Loading Meetings')).toBeInTheDocument();
    expect(calls.some(c => c.url.startsWith('/api/v1/home/state'))).toBe(true);
  });

  const MODULE_IDS = golden.modules.map(mod => mod.id);
  const NAMES = {
    needs_you: 'Needs you', today: 'Today', since_last_visit: 'Since you were last here', apps: 'Your apps',
    recent_meetings: 'Meetings', watched_topics: 'Watched topics', money: 'Money', usage: 'Usage'
  };

  test.each(MODULE_IDS)('%s has its empty, not set up, unavailable and loading states', async (id) => {
    const states = [
      ['empty', mod => Object.assign(mod, { status: 'empty', items: [], count: 0, cursor: mod.cursor })],
      ['not_set_up', mod => { mod.status = 'not_set_up'; mod.source.forEach(src => Object.assign(src, { status: 'not_set_up', note: `${src.label} is not linked to this organization yet.` })); }],
      ['unavailable', mod => { Object.assign(mod, { status: 'unavailable', reason: 'error' }); mod.source.forEach(src => Object.assign(src, { status: 'unavailable', reason: 'error' })); }]
    ];
    for (const [state, change] of states) {
      const doc = clone(golden);
      change(doc.modules.find(mod => mod.id === id));
      const { container, unmount } = renderHome(doc);
      const box = container.querySelector(`[data-module="${id}"]`);
      expect(box).toHaveAttribute('data-status', state);
      expect(within(box).getByRole('heading', { level: 2, name: new RegExp(`^${NAMES[id]}`) })).toBeInTheDocument();
      if (state === 'empty') expect(box.querySelector('.uh-empty, .uh-since-line')).not.toBeNull();
      if (state === 'not_set_up') expect(within(box).getAllByText(/is not linked to this organization yet\./).length).toBeGreaterThan(0);
      if (state === 'unavailable') {
        expect(within(box).getByText(/is not answering\.|are not answering\./)).toBeInTheDocument();
        routes.push(['/api/v1/home/state', () => new Promise(() => {})]);
        fireEvent.click(within(box).getByRole('button', { name: 'Retry' }));
        await waitFor(() => expect(container.querySelector(`[data-module="${id}"]`)).toHaveAttribute('data-status', 'loading'));
        expect(container.querySelector(`[data-module="${id}"] .uh-sk`)).not.toBeNull();
        routes.pop();
      }
      unmount();
    }
  });

  test('a module whose sources partly answered says which app is missing', () => {
    const doc = clone(golden);
    const needs = doc.modules.find(mod => mod.id === 'needs_you');
    needs.partial = true;
    Object.assign(needs.source[1], { status: 'unavailable', reason: 'timeout' });
    renderHome(doc);
    expect(screen.getByText('Accounting-Ops did not answer, so its items are missing here.')).toBeInTheDocument();
  });
});

describe('acting on an item', () => {
  test('Approve on an email draft says "Sending now", then shows the receipt, then the row leaves', async () => {
    routes.push([/\/api\/v1\/home\/actions\//, () => json({
      schema: 'uc.home.action_receipt/1', outcome: 'done', message: 'Approved. Email-Ops handed it to the mail server.'
    })]);
    routes.push(['/api/v1/home/state', () => json(clone(golden))]);
    const { container } = renderHome(withActions(clone(golden)));
    const row = container.querySelector(`[data-item="${EMAIL_ID}"]`);
    fireEvent.click(within(row).getByRole('button', { name: /^Approve/ }));
    expect(await within(row).findByText('Sending now')).toBeInTheDocument();
    expect(await within(row).findByText('Approved. Email-Ops handed it to the mail server.')).toBeInTheDocument();

    const post = calls.find(c => c.method === 'POST');
    expect(post.url).toBe(`/api/v1/home/actions/email-ops/${EMAIL_ID}/approve`);
    expect(post.headers['Idempotency-Key']).toMatch(/^[0-9a-f-]{36}$/);
    expect(post.headers['X-CSRF-Token']).toBe('test-csrf');

    await waitFor(() => expect(container.querySelector(`[data-item="${EMAIL_ID}"]`)).toBeNull(), { timeout: 4000 });
    // The status line is the server's: the page reads the state again after a receipt.
    expect(calls.some(c => c.url.startsWith('/api/v1/home/state'))).toBe(true);
  });

  test('a refused receipt shows its message in the row, and the row stays with its buttons', async () => {
    routes.push([/\/api\/v1\/home\/actions\//, () => json({
      outcome: 'refused', message: 'Accounting-Ops did not allow this. Open it in Accounting-Ops to finish it.'
    })]);
    const { container } = renderHome(withActions(clone(golden)));
    const id = 'ao:approval:7d1e9f20-3c4b-4a5d-8e6f-1a2b3c4d5e66';
    const row = container.querySelector(`[data-item="${id}"]`);
    fireEvent.click(within(row).getByRole('button', { name: 'Approve' }));
    expect(await within(row).findByText('Accounting-Ops did not allow this. Open it in Accounting-Ops to finish it.')).toBeInTheDocument();
    // The receipt is also spoken through the page's polite live region.
    await waitFor(() => expect(container.querySelector('.uh > [aria-live="polite"][role="status"]')).toHaveTextContent('Accounting-Ops did not allow this.'));
    expect(within(row).getByRole('button', { name: 'Approve' })).toBeInTheDocument();
    expect(container.querySelector(`[data-item="${id}"]`)).not.toBeNull();
  });

  test('Try again after a problem resends the same click with the same Idempotency-Key', async () => {
    let attempt = 0;
    routes.push([/\/api\/v1\/home\/actions\//, () => {
      attempt += 1;
      if (attempt === 1) return json({ detail: 'The home cannot keep receipts right now, so nothing was sent to the app.', fix: 'Try again in a few minutes.' }, 503);
      return json({ outcome: 'done', message: 'Approved. Email-Ops handed it to the mail server.' });
    }]);
    const { container } = renderHome(withActions(clone(golden)));
    const row = container.querySelector(`[data-item="${EMAIL_ID}"]`);
    fireEvent.click(within(row).getByRole('button', { name: /^Approve/ }));
    fireEvent.click(await within(row).findByRole('button', { name: 'Try again' }));
    expect(await within(row).findByText('Approved. Email-Ops handed it to the mail server.')).toBeInTheDocument();
    const posts = calls.filter(c => c.method === 'POST');
    expect(posts).toHaveLength(2);
    expect(posts[1].headers['Idempotency-Key']).toBe(posts[0].headers['Idempotency-Key']);
  });

  test('a new click gets a new Idempotency-Key, and an in-progress answer is polled with the same key', async () => {
    let attempt = 0;
    routes.push([/\/api\/v1\/home\/actions\//, () => {
      attempt += 1;
      if (attempt === 1) return json({ code: 'action_in_progress', detail: 'This action is still being sent to the app.' }, 409, { 'Retry-After': '0' });
      return json({ outcome: 'failed', message: 'Email-Ops had a problem, so nothing was sent. Try again in a moment.' });
    }]);
    const { container } = renderHome(withActions(clone(golden)));
    const row = container.querySelector(`[data-item="${EMAIL_ID}"]`);
    fireEvent.click(within(row).getByRole('button', { name: /^Approve/ }));
    expect(await within(row).findByText(/Email-Ops had a problem/, {}, { timeout: 3000 })).toBeInTheDocument();
    fireEvent.click(within(row).getByRole('button', { name: /^Approve/ }));
    await waitFor(() => expect(calls.filter(c => c.method === 'POST')).toHaveLength(3));
    const keys = calls.filter(c => c.method === 'POST').map(c => c.headers['Idempotency-Key']);
    expect(keys[1]).toBe(keys[0]);
    expect(keys[2]).not.toBe(keys[0]);
  });

  test('a double click sends one request', async () => {
    let release;
    routes.push([/\/api\/v1\/home\/actions\//, () => new Promise(resolve => { release = () => resolve(json({ outcome: 'done', message: 'Approved. Email-Ops handed it to the mail server.' })); })]);
    const { container } = renderHome(withActions(clone(golden)));
    const row = container.querySelector(`[data-item="${EMAIL_ID}"]`);
    const approve = within(row).getByRole('button', { name: /^Approve/ });
    fireEvent.click(approve);
    fireEvent.click(approve);
    await waitFor(() => expect(release).toBeDefined());
    release();
    expect(await within(row).findByText('Approved. Email-Ops handed it to the mail server.')).toBeInTheDocument();
    expect(calls.filter(c => c.method === 'POST')).toHaveLength(1);
  });

  test('Mark done on a task due today goes to the action route the item names', async () => {
    routes.push([/\/api\/v1\/home\/actions\//, () => json({ outcome: 'done', message: 'Marked done in Project-Ops.' })]);
    renderHome(withActions(clone(golden)));
    const today = screen.getByRole('article', { name: /^Today/ });
    fireEvent.click(within(today).getByRole('button', { name: 'Mark done' }));
    expect(await within(today).findByText('Marking done')).toBeInTheDocument();
    expect(await within(today).findByText('Marked done in Project-Ops.')).toBeInTheDocument();
    expect(calls.find(c => c.method === 'POST').url).toBe('/api/v1/home/actions/project-ops/po:task:c3d4e5f6-a7b8-4c9d-8e0f-2a3b4c5d6e88/done');
  });
});

describe('navigation', () => {
  test('one organization is a static label; two make a menu that switches with the shipped route', async () => {
    const { unmount } = renderHome(clone(golden));
    await waitFor(() => expect(calls.some(c => c.url.startsWith('/api/v1/org/my-orgs'))).toBe(true));
    expect(screen.queryByRole('button', { name: /Switch organization/ })).not.toBeInTheDocument();
    expect(screen.getByTitle('You belong to one organization.')).toHaveTextContent('Rivergreen Coffee Co.');
    unmount();

    routes = [...baseRoutes([{ id: ORG, name: 'Rivergreen Coffee Co.', role: 'owner' }, { id: OTHER_ORG, name: 'Harbor Lane Bakehouse', role: 'member' }]),
      ['/api/v1/users/me/switch-org', () => json({ ok: true })]];
    renderHome(clone(golden));
    const button = await screen.findByRole('button', { name: /Switch organization/ });
    fireEvent.click(button);
    const menu = screen.getByRole('menu', { name: 'Your organizations' });
    expect(within(menu).getByRole('menuitemradio', { name: /Rivergreen Coffee Co\./ })).toHaveAttribute('aria-checked', 'true');
    fireEvent.click(within(menu).getByRole('menuitemradio', { name: /Harbor Lane Bakehouse/ }));
    await waitFor(() => expect(calls.some(c => c.url === '/api/v1/users/me/switch-org' && c.method === 'POST')).toBe(true));
  });

  test('the Apps menu lists only entitled apps and only catalogued screens the document carries', () => {
    renderHome(clone(golden));
    fireEvent.click(screen.getByRole('button', { name: /^Apps/ }));
    const menu = screen.getByRole('menu', { name: 'Apps' });
    const links = within(menu).getAllByRole('menuitem').map(a => [a.textContent, a.getAttribute('href')]);
    expect(links).toContainEqual(['My tasks', 'https://projectops.example.com/dashboard/my-tasks']);
    expect(links).toContainEqual(['Triage proposals', 'https://projectops.example.com/dashboard/triage']);
    expect(links).toContainEqual(['Agent inbox', 'https://mail-ops.example.com/agent-inbox']);
    expect(links).toContainEqual(['Approvals', 'https://ledger.example.com/approvals']);
    expect(links).toContainEqual(['Sessions', 'https://meetings.example.com/#/sessions']);
    // Center Deep Research is not among this organization's apps, so it is not listed.
    expect(within(menu).queryByText(/Center Deep Research/)).not.toBeInTheDocument();
    expect(links.every(([, href]) => href.startsWith('https://') || href === '#uh-mod-apps')).toBe(true);
  });

  test('the palette opens with Ctrl+K, filters, moves with the arrows, opens with Enter and closes with Escape', async () => {
    renderHome(clone(golden));
    fireEvent.keyDown(document, { key: 'k', ctrlKey: true });
    const input = await screen.findByRole('combobox', { name: 'Search' });
    await waitFor(() => expect(input).toHaveFocus());
    fireEvent.change(input, { target: { value: 'approv' } });
    const options = screen.getAllByRole('option');
    expect(options[0]).toHaveAttribute('aria-selected', 'true');
    expect(options.map(o => o.textContent)).toContain('ApprovalsAccounting-Ops · screen');
    fireEvent.keyDown(input, { key: 'ArrowDown' });
    expect(screen.getAllByRole('option')[1]).toHaveAttribute('aria-selected', 'true');
    fireEvent.keyDown(input, { key: 'ArrowUp' });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(window.open).toHaveBeenCalledWith(expect.stringMatching(/^https:\/\//), '_blank', 'noopener,noreferrer');
    expect(screen.queryByRole('combobox', { name: 'Search' })).not.toBeInTheDocument();

    fireEvent.keyDown(document, { key: 'k', metaKey: true });
    const again = await screen.findByRole('combobox', { name: 'Search' });
    fireEvent.keyDown(again, { key: 'Escape' });
    expect(screen.queryByRole('combobox', { name: 'Search' })).not.toBeInTheDocument();
  });

  test('Cmd or Ctrl+period opens Apps with focus on its first link, and Escape closes it', async () => {
    renderHome(clone(golden));
    fireEvent.keyDown(document, { key: '.', metaKey: true });
    const menu = await screen.findByRole('menu', { name: 'Apps' });
    await waitFor(() => expect(within(menu).getAllByRole('menuitem')[0]).toHaveFocus());
    fireEvent.keyDown(menu, { key: 'ArrowDown' });
    expect(within(menu).getAllByRole('menuitem')[1]).toHaveFocus();
    fireEvent.keyDown(menu, { key: 'Escape' });
    expect(screen.queryByRole('menu', { name: 'Apps' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^Apps/ })).toHaveFocus();
  });

  test('How it works opens once on a first visit and not again after Done', () => {
    storage.removeItem('uc.home.tourSeen');
    const { unmount } = renderHome(clone(golden));
    expect(screen.getByRole('heading', { name: 'The home shows what needs you' })).toBeInTheDocument();
    for (let i = 0; i < 4; i += 1) fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    fireEvent.click(screen.getByRole('button', { name: 'Done' }));
    expect(storage.getItem('uc.home.tourSeen')).toBe('1');
    unmount();
    renderHome(clone(golden));
    expect(screen.queryByRole('heading', { name: 'The home shows what needs you' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Help' }));
    fireEvent.click(screen.getByRole('menuitem', { name: /How it works/ }));
    expect(screen.getByRole('heading', { name: 'The home shows what needs you' })).toBeInTheDocument();
  });

  test('J and K move through Needs you, A takes the main action and O opens the row', async () => {
    routes.push([/\/api\/v1\/home\/actions\//, () => json({ outcome: 'done', message: 'Approved. Email-Ops handed it to the mail server.' })]);
    const { container } = renderHome(withActions(clone(golden)));
    fireEvent.keyDown(document, { key: 'j' });
    const rows = () => Array.from(container.querySelectorAll('#uh-needs-list [data-item]'));
    await waitFor(() => expect(rows()[0]).toHaveClass('is-current'));
    fireEvent.keyDown(document, { key: 'j' });
    await waitFor(() => expect(rows()[1]).toHaveClass('is-current'));
    fireEvent.keyDown(document, { key: 'k' });
    await waitFor(() => expect(rows()[0]).toHaveClass('is-current'));
    const click = vi.fn(event => event.preventDefault());
    rows()[0].querySelector('a.uh-btn').addEventListener('click', click);
    fireEvent.keyDown(document, { key: 'o' });
    expect(click).toHaveBeenCalled();
    fireEvent.keyDown(document, { key: 'a' });
    await waitFor(() => expect(calls.some(c => c.method === 'POST' && c.url.endsWith('/approve'))).toBe(true));
  });
});

describe('appearance', () => {
  test('family, mode and section colour apply to the page and persist', () => {
    const { container } = renderHome(clone(golden));
    const root = container.querySelector('.uh');
    expect(root).toHaveAttribute('data-family', 'pro');
    expect(root).toHaveAttribute('data-mode', 'light');
    expect(root).toHaveAttribute('data-intensity', 'vivid');
    expect(root.style.getPropertyValue('--uh-accent')).toBe('#3451d1');
    fireEvent.click(screen.getByRole('button', { name: 'Appearance' }));
    fireEvent.click(screen.getByRole('radio', { name: /Unicorn Galaxy/ }));
    fireEvent.click(screen.getByRole('radio', { name: 'Dark' }));
    fireEvent.click(screen.getByRole('radio', { name: 'Subtle' }));
    expect(root).toHaveAttribute('data-family', 'galaxy');
    expect(root).toHaveAttribute('data-mode', 'dark');
    expect(root).toHaveAttribute('data-intensity', 'subtle');
    expect(root.style.getPropertyValue('--uh-accent-2')).toBe('#f5c84b');
    expect(JSON.parse(storage.getItem('uc1-appearance'))).toEqual({ family: 'galaxy', mode: 'dark', intensity: 'subtle', font: 'plex' });
    // The matching original theme follows, so the choice is one theme system.
    expect(storage.getItem('uc1-theme')).toBe('galaxy');
  });
});

describe('live data', () => {
  test('reads again every 60 s while visible, pauses while hidden, reads at once on return and marks a failure stale', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let fail = false;
    routes.push(['/api/v1/home/state', () => (fail ? json({ detail: 'boom' }, 502) : json(clone(golden)))]);
    const { container } = renderHome(clone(golden));
    const reads = () => calls.filter(c => c.url.startsWith('/api/v1/home/state')).length;
    expect(reads()).toBe(0);
    expect(calls.find(c => c.url.startsWith('/api/v1/home/state'))).toBeUndefined();
    await act(async () => { vi.advanceTimersByTime(60000); });
    await waitFor(() => expect(reads()).toBe(1));
    expect(calls.find(c => c.url.startsWith('/api/v1/home/state')).url).toMatch(/[?&]tz=/);

    Object.defineProperty(document, 'visibilityState', { value: 'hidden', configurable: true });
    await act(async () => { document.dispatchEvent(new Event('visibilitychange')); });
    expect(container.querySelector('.uh-live-text')).toHaveTextContent('paused, tab hidden');
    await act(async () => { vi.advanceTimersByTime(120000); });
    expect(reads()).toBe(1);

    fail = true;
    Object.defineProperty(document, 'visibilityState', { value: 'visible', configurable: true });
    await act(async () => { document.dispatchEvent(new Event('visibilitychange')); });
    await waitFor(() => expect(reads()).toBe(2));
    await waitFor(() => expect(container.querySelector('.uh-live-text')).toHaveTextContent('stale since 10:00'));
  });

  test('a row that arrives on a refresh slides in at the top of its list', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const next = clone(golden);
    const needs = next.modules.find(mod => mod.id === 'needs_you');
    needs.items.unshift({
      id: 'eo:draft:9a8b7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d', app: 'email-ops', kind: 'approval', scope: 'mine',
      title: 'Reply to Lowcountry Events with the certificate', origin: 'third_party',
      proposed_by: { kind: 'agent', name: 'Email-Ops drafter' }, created_at: '2026-11-09T15:05:00Z',
      to: 'events@lowcountry.example', actions: [{ id: 'open', label: 'Review', href: 'https://mail-ops.example.com/agent-inbox' }]
    });
    needs.count += 1;
    routes.push(['/api/v1/home/state', () => json(next)]);
    const { container } = renderHome(clone(golden));
    await act(async () => { vi.advanceTimersByTime(60000); });
    await waitFor(() => expect(container.querySelector('#uh-needs-list [data-item]')).toHaveAttribute('data-item', 'eo:draft:9a8b7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d'));
    expect(container.querySelector('#uh-needs-list [data-item]')).toHaveClass('is-new');
    // The rows that were there keep their order below it.
    const ids = Array.from(container.querySelectorAll('#uh-needs-list [data-item]')).map(el => el.getAttribute('data-item'));
    expect(ids.slice(1)).toEqual(golden.modules[0].items.map(item => item.id));
    expect(container.querySelector('[data-module="needs_you"] .uh-count')).toHaveTextContent('9');
  });
});

describe('/dashboard chooses the home or the current dashboard', () => {
  function renderGate() {
    return render(
      <MemoryRouter initialEntries={['/dashboard']}>
        <ThemeProvider>
          <BrandingProvider>
            <DashboardHome fetchImpl={global.fetch} />
          </BrandingProvider>
        </ThemeProvider>
      </MemoryRouter>
    );
  }

  test('200 with a home-state document renders the new home', async () => {
    routes.push(['/api/v1/home/state', () => json(clone(golden))]);
    renderGate();
    expect(await screen.findByRole('heading', { level: 1, name: /Eight things need you/ })).toBeInTheDocument();
  });

  test.each([
    ['404, the flag off', () => json({ detail: 'Not Found' }, 404)],
    ['a failure', () => json({ detail: 'boom' }, 500)],
    ['a body that is not the document', () => json([])]
  ])('%s renders the current dashboard', async (_, answer) => {
    routes.push(['/api/v1/home/state', answer]);
    routes.push(['/api/v1/my-apps/authorized', () => json([])]);
    routes.push(['/api/v1/auth/session', () => json({ authenticated: true, user: { username: 'mara' } })]);
    renderGate();
    expect(await screen.findByRole('heading', { name: 'My Apps' }, { timeout: 4000 })).toBeInTheDocument();
    expect(document.querySelector('.uh')).toBeNull();
  });

  test('the last visit\'s time is sent to the cursor before the state is read, so the deltas stay put during a visit', async () => {
    storage.setItem('uc.home.seen', JSON.stringify({ [ORG]: { owner: 'mara@rivergreen.example', at: '2026-11-09T14:00:00Z' } }));
    routes.push([/\/dashboard-cursor$/, () => json({ advanced: true })]);
    routes.push(['/api/v1/home/state', () => json(clone(golden))]);
    renderGate();
    await screen.findByRole('heading', { level: 1, name: /Eight things/ });
    const put = calls.findIndex(c => c.method === 'PUT' && c.url === `/api/v1/org/${ORG}/dashboard-cursor`);
    const read = calls.findIndex(c => c.url.startsWith('/api/v1/home/state'));
    expect(put).toBeGreaterThanOrEqual(0);
    expect(put).toBeLessThan(read);
    expect(JSON.parse(calls[put].body)).toEqual({ last_seen_at: '2026-11-09T14:00:00Z', rendered: true });
    // This visit is remembered for the next one.
    await waitFor(() => expect(JSON.parse(storage.getItem('uc.home.seen'))[ORG].at).toBe(golden.generated_at));
  });
});
