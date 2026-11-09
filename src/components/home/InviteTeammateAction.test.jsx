import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, expect, test, vi } from 'vitest';
import { canInviteFromOrganization, default as InviteTeammateAction } from './InviteTeammateAction';

function renderAction(organization) {
  return render(
    <InviteTeammateAction
      organization={organization}
      role={organization?.role}
      fetchImpl={vi.fn()}
    />
  );
}

describe('InviteTeammateAction', () => {
  test('is visible to owners and admins but not members', () => {
    expect(canInviteFromOrganization({ id: 'org-fictional' }, 'owner')).toBe(true);
    expect(canInviteFromOrganization({ id: 'org-fictional' }, 'admin')).toBe(true);
    expect(canInviteFromOrganization({ id: 'org-fictional' }, 'member')).toBe(false);

    renderAction({ id: 'org-fictional', name: 'Fictional Lantern Labs', role: 'member' });
    expect(screen.queryByRole('button', { name: 'Invite a teammate' })).not.toBeInTheDocument();
  });

  test('explains the pending sign-in behavior to an owner', () => {
    renderAction({ id: 'org-fictional', name: 'Fictional Lantern Labs', role: 'owner' });

    expect(screen.getByRole('button', { name: 'Invite a teammate' })).toBeInTheDocument();
    expect(screen.getByText(/join this organization the first time they sign in/i)).toBeInTheDocument();
  });
});
