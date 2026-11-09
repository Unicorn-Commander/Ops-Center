import React from 'react';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, test, vi } from 'vitest';
import { BrandingProvider } from '../../contexts/BrandingContext';
import { ThemeProvider } from '../../contexts/ThemeContext';
import PublicLanding from '../../pages/PublicLanding';

function jsonResponse(body, ok = true, status = 200) {
  return { ok, status, json: async () => body };
}

function renderSignedInHome(organization) {
  global.fetch.mockImplementation(async (input, options = {}) => {
    const url = String(input);
    const method = options.method || 'GET';

    if (url.endsWith('/api/v1/branding/config')) {
      return jsonResponse({ company_name: 'Fictional Ops Center' });
    }
    if (url.endsWith('/api/v1/auth/session')) {
      return jsonResponse({ user: { username: 'fictional-user', role: 'user', roles: ['user'] } });
    }
    if (url.endsWith('/api/v1/my-apps/authorized')) {
      return jsonResponse([]);
    }
    if (url.endsWith('/api/v1/org/my-orgs')) {
      return jsonResponse([organization]);
    }
    if (url.includes('/dashboard-cursor') && method === 'PUT') {
      return jsonResponse({ last_seen_at: '2026-11-08T13:00:00.000Z', advanced: true });
    }
    if (url.includes('/dashboard-cursor')) {
      return jsonResponse({ last_seen_at: null, server_now: '2026-11-08T13:00:00.000Z' });
    }

    return jsonResponse([]);
  });

  return render(
    <MemoryRouter initialEntries={['/dashboard']}>
      <BrandingProvider>
        <ThemeProvider>
          <PublicLanding />
        </ThemeProvider>
      </BrandingProvider>
    </MemoryRouter>
  );
}

describe('signed-in home activity mount', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('shows the activity spine and invite action for an owner', async () => {
    renderSignedInHome({
      id: 'org-fictional-owner',
      name: 'Fictional Lantern Labs',
      role: 'owner'
    });

    expect(await screen.findByRole('region', { name: 'Workspace activity' })).toBeInTheDocument();
    expect(await screen.findByRole('button', { name: 'Invite a teammate' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'My Apps' })).toBeInTheDocument();
  });

  test('shows the activity spine without an invite action for a member', async () => {
    renderSignedInHome({
      id: 'org-fictional-member',
      name: 'Fictional Northwind',
      role: 'member'
    });

    expect(await screen.findByRole('region', { name: 'Workspace activity' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Invite a teammate' })).not.toBeInTheDocument();
  });
});
