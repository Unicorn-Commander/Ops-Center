import React from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, test, vi } from 'vitest';
import HomeActivitySpine from './HomeActivitySpine';

const ORG_ALPHA = { id: 'org-fictional-alpha', name: 'Fictional Lantern Labs', role: 'owner' };
const ORG_BETA = { id: 'org-fictional-beta', name: 'Fictional Northwind', role: 'member' };

function jsonResponse(body, ok = true, status = 200) {
  return { ok, status, json: async () => body };
}

function activityFetch({ organizations, meetingOk = true, projectItem = null }) {
  const calls = [];
  const fetchImpl = vi.fn(async (url, options = {}) => {
    const address = String(url);
    const method = options.method || 'GET';
    calls.push({ address, method, body: options.body });
    if (address.includes('/users/me/organizations')) {
      return jsonResponse({ organizations, current_org_id: organizations[0]?.id });
    }
    if (address.includes('/my-orgs')) return jsonResponse(organizations);
    if (address.includes('dashboard-cursor') && method === 'PUT') {
      return jsonResponse({ last_seen_at: '2026-11-08T13:00:00.000Z', advanced: true });
    }
    if (address.includes('dashboard-cursor')) {
      return jsonResponse({ last_seen_at: null, server_now: '2026-11-08T13:05:00.000Z' });
    }
    if (address.includes('recent-activity')) {
      return jsonResponse(projectItem ? { events: [projectItem] } : { events: [] });
    }
    if (address.includes('analytics/sessions')) {
      return meetingOk
        ? jsonResponse([])
        : jsonResponse({ detail: 'down' }, false, 503);
    }
    if (address.includes('switch-org')) return jsonResponse({ success: true });
    return jsonResponse({}, false, 404);
  });
  return { fetchImpl, calls };
}

describe('HomeActivitySpine', () => {
  test('hides the organization switcher and the invite control for a single-org member', async () => {
    const { fetchImpl } = activityFetch({
      organizations: [{ ...ORG_ALPHA, role: 'member' }]
    });

    render(<HomeActivitySpine fetchImpl={fetchImpl} storage={{ getItem: () => null, setItem: () => {} }} />);

    expect(await screen.findByRole('heading', { name: 'Here is recent activity' })).toBeInTheDocument();
    expect(screen.queryByRole('combobox', { name: 'Organization' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Invite a teammate' })).not.toBeInTheDocument();
  });

  test('shows the organization switcher and invite control for an owner with two organizations', async () => {
    const user = userEvent.setup();
    const reload = vi.fn();
    const storage = { getItem: () => null, setItem: vi.fn() };
    const { fetchImpl } = activityFetch({ organizations: [ORG_ALPHA, ORG_BETA] });

    render(<HomeActivitySpine fetchImpl={fetchImpl} storage={storage} reload={reload} />);

    const switcher = await screen.findByRole('combobox', { name: 'Organization' });
    expect(switcher).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Invite a teammate' })).toBeInTheDocument();

    await user.selectOptions(switcher, ORG_BETA.id);
    expect(fetchImpl).toHaveBeenCalledWith(
      '/api/v1/users/me/switch-org',
      expect.objectContaining({ method: 'POST' })
    );
    expect(reload).toHaveBeenCalled();
  });

  test('shows a partial failure and does not advance the cursor', async () => {
    const projectItem = {
      action: 'Updated the brief',
      timestamp: '2026-11-08T12:00:00.000Z',
      project: { id: 'proj-1', title: 'Lantern' }
    };
    const { fetchImpl, calls } = activityFetch({
      organizations: [ORG_ALPHA],
      meetingOk: false,
      projectItem
    });

    render(<HomeActivitySpine fetchImpl={fetchImpl} storage={{ getItem: () => null, setItem: () => {} }} />);

    expect(await screen.findByText('Updated the brief: Lantern')).toBeInTheDocument();
    expect(screen.getByText('Meeting-Ops is unavailable right now.')).toBeInTheDocument();
    expect(calls.some(call => call.address.includes('dashboard-cursor') && call.method === 'PUT')).toBe(false);
  });

  test('tells the person to refresh when the organization list cannot be loaded', async () => {
    const fetchImpl = vi.fn(async () => jsonResponse({}, false, 503));
    const reload = vi.fn();
    render(
      <HomeActivitySpine
        fetchImpl={fetchImpl}
        reload={reload}
        storage={{ getItem: () => null, setItem: () => {} }}
      />
    );

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'We could not load your organization. Refresh the page to try again.'
    );
    expect(screen.queryByRole('button', { name: 'Invite a teammate' })).not.toBeInTheDocument();
  });
});
