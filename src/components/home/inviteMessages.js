export const INVITE_PENDING_MESSAGE = 'Invitation is pending. They join this organization the first time they sign in.';

export const DUPLICATE_MEMBER_MESSAGE = 'That email is already a member of this organization.';

export const DUPLICATE_PENDING_MESSAGE = 'An invitation for that email is already waiting. They join when they sign in.';

export function inviteSentMessage(email, organizationName) {
  return `We emailed ${email} an invitation and added them to ${organizationName || 'this organization'}.`;
}

export function inviteErrorMessage(status, errorDetails = {}) {
  const detail = typeof errorDetails.detail === 'string' ? errorDetails.detail : '';
  if (status === 409) return DUPLICATE_PENDING_MESSAGE;
  if (status === 400) return DUPLICATE_MEMBER_MESSAGE;
  if (status === 402) {
    if (detail.startsWith('Solo')) return detail;
    const used = Number(errorDetails.seats_used);
    const max = Number(errorDetails.max_seats);
    if (Number.isFinite(used) && Number.isFinite(max)) {
      return `This organization is using ${used} of ${max} seats. Add a seat before inviting someone else.`;
    }
    return 'This organization is using all of its seats. Add a seat before inviting someone else.';
  }
  return detail || 'The invitation could not be sent. Try again.';
}
