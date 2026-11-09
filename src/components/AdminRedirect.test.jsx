import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation, useNavigate } from 'react-router-dom';
import { beforeEach, describe, expect, test } from 'vitest';
import AdminRedirect from './AdminRedirect';
import { AdminRouteGuard } from '../App';

function LocationProbe() {
  const location = useLocation();
  const navigate = useNavigate();

  return (
    <>
      <output data-testid="location">{location.pathname}</output>
      <button type="button" onClick={() => navigate(-1)}>Back</button>
    </>
  );
}

function renderRedirect(userInfo, initialEntries = ['/admin/']) {
  localStorage.getItem.mockImplementation((key) => (
    key === 'userInfo' ? JSON.stringify(userInfo || {}) : null
  ));

  return render(
    <MemoryRouter initialEntries={initialEntries} initialIndex={initialEntries.length - 1}>
      <Routes>
        <Route path="/admin/*" element={<AdminRedirect />} />
        <Route path="/dashboard" element={<LocationProbe />} />
        <Route path="/admin/dashboard" element={<LocationProbe />} />
      </Routes>
    </MemoryRouter>
  );
}

function renderGuard(path, userInfo) {
  localStorage.getItem.mockImplementation((key) => (
    key === 'userInfo' ? JSON.stringify(userInfo || {}) : null
  ));

  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route
          path="/admin/*"
          element={(
            <AdminRouteGuard>
              <span data-testid="guarded-admin">allowed</span>
            </AdminRouteGuard>
          )}
        />
        <Route path="/dashboard" element={<span data-testid="guarded-home">home</span>} />
      </Routes>
    </MemoryRouter>
  );
}

beforeEach(() => {
  localStorage.getItem.mockReset();
});

describe('AdminRedirect', () => {
  test.each([
    ['anonymous', {}, '/dashboard'],
    ['member', { role: 'user', org_role: 'member' }, '/dashboard'],
    ['organization owner', { role: 'user', org_role: 'owner' }, '/dashboard'],
    ['platform admin', { role: 'platform_admin' }, '/admin/dashboard']
  ])('routes %s to the correct destination', async (_label, userInfo, destination) => {
    renderRedirect(userInfo);

    await waitFor(() => {
      expect(screen.getByTestId('location')).toHaveTextContent(destination);
    });
  });

  test('replaces /admin in history so browser back returns home without a loop', async () => {
    renderRedirect({}, ['/dashboard', '/admin/']);

    await waitFor(() => {
      expect(screen.getByTestId('location')).toHaveTextContent('/dashboard');
    });

    fireEvent.click(screen.getByRole('button', { name: 'Back' }));

    await waitFor(() => {
      expect(screen.getByTestId('location')).toHaveTextContent('/dashboard');
    });
  });
});

describe('AdminRouteGuard', () => {
  test('blocks an organization owner from a platform route', async () => {
    renderGuard('/admin/infra/services', { role: 'user', org_role: 'owner' });

    await waitFor(() => {
      expect(screen.getByTestId('guarded-home')).toBeInTheDocument();
    });
    expect(screen.queryByTestId('guarded-admin')).not.toBeInTheDocument();
  });

  test('blocks a member from the organization manager route', async () => {
    renderGuard('/admin/org/team', { role: 'user', org_role: 'member' });

    await waitFor(() => {
      expect(screen.getByTestId('guarded-home')).toBeInTheDocument();
    });
  });

  test('allows a platform administrator to open the infrastructure route directly', async () => {
    renderGuard('/admin/infra/services', { role: 'platform_admin' });

    expect(await screen.findByTestId('guarded-admin')).toBeInTheDocument();
  });

  test('sends a direct /admin visit from an organization user back home', async () => {
    renderGuard('/admin', { role: 'user', org_role: 'owner' });

    await waitFor(() => {
      expect(screen.getByTestId('guarded-home')).toBeInTheDocument();
    });
  });
});
