import { describe, expect, test } from 'vitest';
import {
  getAccessibleRoutes,
  getRouteByPath,
  getNavigationStructure,
  hasRouteAccess,
  isOrgManagerRole,
  isPlatformAdminRole,
  routes
} from './routes';

const navigationEntries = (userRole, orgRole) => {
  const nav = getNavigationStructure();
  const personalEntries = Object.values(nav.personal).flatMap(entry => (
    entry.path ? [entry] : Object.values(entry.children || {})
  ));
  return [
    ...personalEntries,
    ...Object.values(nav.organization.children),
    ...Object.values(nav.system.children).flatMap(section => Object.values(section.children || {}))
  ].filter(entry => entry.nav !== false && hasRouteAccess(entry, userRole, orgRole));
};

describe('canonical home and route access', () => {
  test('uses /dashboard as the home for every supported role', () => {
    expect(getRouteByPath('/dashboard')).toBe(routes.personal.dashboard);
    expect(hasRouteAccess(routes.personal.dashboard, 'viewer')).toBe(true);
    expect(hasRouteAccess(routes.personal.dashboard, 'user', 'owner')).toBe(true);
    expect(hasRouteAccess(routes.personal.dashboard, 'platform_admin')).toBe(true);
  });

  test('recognizes all platform administrator role names', () => {
    expect(isPlatformAdminRole('admin')).toBe(true);
    expect(isPlatformAdminRole('super_admin')).toBe(true);
    expect(isPlatformAdminRole('platform_admin')).toBe(true);
    expect(isPlatformAdminRole('system_admin')).toBe(true);
    expect(isPlatformAdminRole('user')).toBe(false);
  });

  test('recognizes an organization manager without granting platform access', () => {
    expect(isOrgManagerRole('owner')).toBe(true);
    expect(isOrgManagerRole('manager')).toBe(true);
    expect(isOrgManagerRole('admin')).toBe(true);
    expect(isOrgManagerRole('member')).toBe(false);

    expect(hasRouteAccess(routes.organization.children.team, 'user', 'manager')).toBe(true);
    expect(hasRouteAccess(routes.system.children.aiModels.children.overview, 'user', 'manager')).toBe(false);
    expect(hasRouteAccess(routes.system.children.peopleAccess.children.users, 'user', 'manager')).toBe(false);
  });

  test('protects the infrastructure dashboard itself, not just its menu item', () => {
    expect(hasRouteAccess(routes.personal.adminDashboard, 'user', 'owner')).toBe(false);
    expect(hasRouteAccess(routes.personal.adminDashboard, 'admin')).toBe(true);
    expect(hasRouteAccess(routes.personal.adminDashboard, 'platform_admin')).toBe(true);
  });
});

describe('role-scoped menu entries', () => {
  test('members get personal navigation but no organization or platform menus', () => {
    const paths = navigationEntries('user', 'member').map(entry => entry.path);

    expect(paths).toContain('/dashboard');
    expect(paths).toContain('/admin/my-dashboard');
    expect(paths).toContain('/admin/account/profile');
    expect(paths).not.toContain('/admin/org/team');
    expect(paths).not.toContain('/admin/people/users');
    expect(paths).not.toContain('/admin/infra/services');
  });

  test('organization managers get organization routes and no global administration', () => {
    const paths = navigationEntries('user', 'owner').map(entry => entry.path);

    expect(paths).toContain('/admin/org/team');
    expect(paths).toContain('/admin/org/roles');
    expect(paths).toContain('/admin/org/settings');
    expect(paths).toContain('/admin/org/billing');
    expect(paths).not.toContain('/admin/people/organizations');
    expect(paths).not.toContain('/admin/ai');
    expect(paths).not.toContain('/admin/infra/services');
  });

  test('platform administrators get the Admin Console entry and system menus', () => {
    const paths = navigationEntries('platform_admin', null).map(entry => entry.path);

    expect(paths).toContain('/dashboard');
    expect(paths).toContain('/admin/dashboard');
    expect(paths).toContain('/admin/people/users');
    expect(paths).toContain('/admin/ai');
    expect(paths).toContain('/admin/infra/services');
  });

  test('accessible route filtering never exposes infrastructure to an owner', () => {
    const paths = getAccessibleRoutes('user', 'owner').map(route => route.path);
    expect(paths).toContain('/admin/org/team');
    expect(paths).not.toContain('/admin/infra/services');
    expect(paths).not.toContain('/admin/people/users');
  });
});
