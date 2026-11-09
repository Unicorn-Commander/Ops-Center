import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, expect, test, vi } from 'vitest';
import HomeActivitySpine from './HomeActivitySpine';

// Fictional organizations. Alder is first by name; Birch is the one the backend serves.
const ALDER = { id: '00000000-0000-4000-8000-0000000000a1', name: 'Alder Fictional Remodeling', role: 'member' };
const BIRCH = { id: '00000000-0000-4000-8000-0000000000b2', name: 'Birch Fictional Studio', role: 'member' };
const NOT_LISTED_ID = '00000000-0000-4000-8000-0000000000c3';

function orgListFetch(currentOrgHeader) {
  return vi.fn(async url => {
    if (String(url).endsWith('/api/v1/org/my-orgs')) {
      const headers = new Headers({ 'Content-Type': 'application/json' });
      if (currentOrgHeader) headers.set('X-Current-Org-Id', currentOrgHeader);
      return { ok: true, status: 200, headers, json: async () => [ALDER, BIRCH] };
    }
    return { ok: false, status: 404, json: async () => ({}) };
  });
}

function renderSpine({ savedOrgId, currentOrgHeader }) {
  const storage = { getItem: key => (key === 'currentOrgId' ? savedOrgId : null), setItem: vi.fn() };
  render(<HomeActivitySpine fetchImpl={orgListFetch(currentOrgHeader)} storage={storage} />);
}

describe('HomeActivitySpine names the organization the backend serves', () => {
  test('the workspace header and switcher follow X-Current-Org-Id over a stale saved org', async () => {
    renderSpine({ savedOrgId: ALDER.id, currentOrgHeader: BIRCH.id });

    expect(await screen.findByRole('heading', { name: BIRCH.name })).toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: 'Organization' })).toHaveValue(BIRCH.id);
  });

  test('keeps the saved organization when the response has no header', async () => {
    renderSpine({ savedOrgId: BIRCH.id, currentOrgHeader: null });

    expect(await screen.findByRole('heading', { name: BIRCH.name })).toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: 'Organization' })).toHaveValue(BIRCH.id);
  });

  test('ignores a header that names an organization outside the list', async () => {
    renderSpine({ savedOrgId: BIRCH.id, currentOrgHeader: NOT_LISTED_ID });

    expect(await screen.findByRole('heading', { name: BIRCH.name })).toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: 'Organization' })).toHaveValue(BIRCH.id);
  });
});
