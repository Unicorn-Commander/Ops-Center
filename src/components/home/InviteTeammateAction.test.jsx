import React from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, test, vi } from 'vitest';
import { canInviteFromOrganization, default as InviteTeammateAction } from './InviteTeammateAction';

describe('InviteTeammateAction', () => {
  test('is visible to owners and admins but not members', () => {
    expect(canInviteFromOrganization({ id: 'org-fictional' }, 'owner')).toBe(true);
    expect(canInviteFromOrganization({ id: 'org-fictional' }, 'admin')).toBe(true);
    expect(canInviteFromOrganization({ id: 'org-fictional' }, 'member')).toBe(false);
    expect(canInviteFromOrganization({ id: 'org-fictional' }, 'billing_admin')).toBe(false);

    render(
      <InviteTeammateAction organization={{ id: 'org-fictional', name: 'Fictional Lantern Labs', role: 'member' }} />
    );
    expect(screen.queryByRole('button', { name: 'Invite a teammate' })).not.toBeInTheDocument();
  });

  test('explains the email invitation and the seat limit in plain words', async () => {
    const user = userEvent.setup();
    const fetchImpl = vi.fn()
      .mockResolvedValueOnce({
        ok: false,
        status: 402,
        json: async () => ({
          detail: 'Organization has reached its seat limit (5/5).',
          seats_used: 5,
          max_seats: 5,
          add_seat_url: '/api/v1/billing/seats'
        })
      })
      .mockResolvedValueOnce({
        ok: false,
        status: 409,
        json: async () => ({ detail: 'An invitation for this email is already pending.' })
      });

    render(
      <InviteTeammateAction
        organization={{ id: 'org-fictional', name: 'Fictional Lantern Labs', role: 'owner' }}
        fetchImpl={fetchImpl}
      />
    );

    expect(screen.getByText(/Send an invitation by email/i)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Invite a teammate' }));
    await user.type(screen.getByLabelText('Email'), 'mira@example.com');
    await user.click(screen.getByRole('button', { name: 'Send invitation' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'This organization is using 5 of 5 seats. Add a seat before inviting someone else.'
    );

    await user.click(screen.getByRole('button', { name: 'Send invitation' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'An invitation for that email is already waiting. They join when they sign in.'
    );
  });

  test('shows the organization named in the immediate invitation response', async () => {
    const user = userEvent.setup();
    const fetchImpl = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        pending: false,
        message: 'We emailed mira@example.com an invitation and added them to Fictional Lantern Labs.'
      })
    });

    render(
      <InviteTeammateAction
        organization={{ id: 'org-fictional', name: 'Fictional Lantern Labs', role: 'owner' }}
        fetchImpl={fetchImpl}
      />
    );

    await user.click(screen.getByRole('button', { name: 'Invite a teammate' }));
    await user.type(screen.getByLabelText('Email'), 'mira@example.com');
    await user.click(screen.getByRole('button', { name: 'Send invitation' }));

    expect(await screen.findByRole('status')).toHaveTextContent(
      'We emailed mira@example.com an invitation and added them to Fictional Lantern Labs.'
    );
  });
});
