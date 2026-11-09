import React, { useState } from 'react';
import { UserPlusIcon } from '@heroicons/react/24/outline';
import { INVITE_PENDING_MESSAGE, inviteErrorMessage, inviteSentMessage } from './inviteMessages';

export function canInviteFromOrganization(organization, role) {
  const currentRole = role || organization?.role || organization?.org_role;
  return Boolean(organization && ['owner', 'admin'].includes(currentRole));
}

export default function InviteTeammateAction({
  className = '',
  organization = null,
  role = null,
  fetchImpl = globalThis.fetch
}) {
  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState('');
  const [inviteRole, setInviteRole] = useState('member');
  const [submitting, setSubmitting] = useState(false);
  const [notice, setNotice] = useState(null);

  if (!canInviteFromOrganization(organization, role)) {
    return null;
  }

  function closeDialog() {
    setOpen(false);
    setNotice(null);
    setSubmitting(false);
  }

  async function submitInvite(event) {
    event.preventDefault();
    setSubmitting(true);
    setNotice(null);
    try {
      const response = await fetchImpl(
        `/api/v1/org/${encodeURIComponent(organization.id)}/members`,
        {
          method: 'POST',
          credentials: 'include',
          headers: {
            Accept: 'application/json',
            'Content-Type': 'application/json'
          },
          body: JSON.stringify({ email, role: inviteRole })
        }
      );
      const result = await response.json().catch(() => ({}));
      const errorDetails = result.detail && typeof result.detail === 'object' ? result.detail : result;
      if (!response.ok) {
        setNotice({ tone: 'error', text: inviteErrorMessage(response.status, errorDetails) });
        return;
      }
      setEmail('');
      setNotice({
        tone: 'success',
        text: result.pending === false
          ? (result.message || inviteSentMessage(email, organization.name))
          : INVITE_PENDING_MESSAGE
      });
    } catch {
      setNotice({ tone: 'error', text: 'The invitation could not be sent. Try again.' });
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <aside className={`rounded-2xl border border-cyan-200/20 bg-cyan-300/10 p-5 ${className}`}>
      <div className="flex items-start gap-3">
        <UserPlusIcon className="mt-0.5 h-6 w-6 flex-none text-cyan-200" aria-hidden="true" />
        <div className="min-w-0 flex-1">
          <h2 className="text-base font-semibold text-white">Invite a teammate</h2>
          <p className="mt-1 text-sm text-slate-300">
            Send an invitation by email and choose their role in this organization.
          </p>
          <button
            type="button"
            onClick={() => setOpen(true)}
            className="mt-4 inline-flex items-center rounded-lg bg-cyan-300 px-4 py-2 text-sm font-semibold text-slate-950 transition hover:bg-cyan-200 focus:outline-none focus:ring-2 focus:ring-cyan-200 focus:ring-offset-2 focus:ring-offset-slate-950"
          >
            Invite a teammate
          </button>
        </div>
      </div>

      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div
            role="dialog"
            aria-labelledby="invite-teammate-title"
            className="w-full max-w-md rounded-xl border border-white/10 bg-slate-950 p-6 text-white"
          >
            <h3 id="invite-teammate-title" className="text-xl font-semibold">Invite a teammate</h3>
            <p className="mt-2 text-sm text-slate-300">
              Send an invitation by email and choose their role in this organization.
            </p>
            <form className="mt-4 space-y-4" onSubmit={submitInvite}>
              <div>
                <label htmlFor="invite-teammate-email" className="mb-2 block text-sm font-medium text-slate-200">
                  Email
                </label>
                <input
                  id="invite-teammate-email"
                  type="email"
                  required
                  value={email}
                  onChange={event => setEmail(event.target.value)}
                  className="w-full rounded-lg border border-white/15 bg-slate-900 px-4 py-2 text-white"
                  autoComplete="email"
                />
              </div>
              <div>
                <label htmlFor="invite-teammate-role" className="mb-2 block text-sm font-medium text-slate-200">
                  Role
                </label>
                <select
                  id="invite-teammate-role"
                  value={inviteRole}
                  onChange={event => setInviteRole(event.target.value)}
                  className="w-full rounded-lg border border-white/15 bg-slate-900 px-4 py-2 text-white"
                >
                  <option value="member">Member</option>
                  <option value="admin">Admin</option>
                </select>
              </div>
              {notice && (
                <p role={notice.tone === 'error' ? 'alert' : 'status'} className="text-sm text-slate-100">
                  {notice.text}
                </p>
              )}
              <div className="flex gap-3">
                <button
                  type="button"
                  onClick={closeDialog}
                  className="flex-1 rounded-lg bg-slate-700 px-4 py-2 text-sm font-medium text-white"
                >
                  Close
                </button>
                <button
                  type="submit"
                  disabled={submitting || !email}
                  className="flex-1 rounded-lg bg-cyan-300 px-4 py-2 text-sm font-semibold text-slate-950 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {submitting ? 'Sending the invitation...' : 'Send invitation'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </aside>
  );
}
