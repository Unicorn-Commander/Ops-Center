import React from 'react';
import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, test } from 'vitest';
import { OrganizationProvider, useOrganization } from './OrganizationContext';

// Fictional organizations. Alder is first by name, the org the page falls back
// to when it has nothing better; Birch is the one the backend serves.
const ALDER = { id: '00000000-0000-4000-8000-0000000000a1', name: 'Alder Fictional Remodeling', role: 'member' };
const BIRCH = { id: '00000000-0000-4000-8000-0000000000b2', name: 'Birch Fictional Studio', role: 'owner' };
const NOT_LISTED_ID = '00000000-0000-4000-8000-0000000000c3';

function orgListResponse(orgs, currentOrgHeader) {
  const headers = new Headers({ 'Content-Type': 'application/json' });
  if (currentOrgHeader) headers.set('X-Current-Org-Id', currentOrgHeader);
  return { ok: true, status: 200, headers, json: async () => orgs };
}

function CurrentOrganization() {
  const { currentOrg, loading } = useOrganization();
  if (loading) return <p>Loading organizations</p>;
  return <p data-testid="current-org">{currentOrg ? currentOrg.name : 'No organization'}</p>;
}

function renderWithSavedOrg(savedOrgId, response) {
  localStorage.getItem.mockImplementation(key => (key === 'currentOrgId' ? savedOrgId : null));
  global.fetch.mockImplementation(async url => {
    if (String(url).endsWith('/api/v1/org/my-orgs')) return response;
    throw new Error(`unexpected request: ${url}`);
  });
  render(
    <OrganizationProvider>
      <CurrentOrganization />
    </OrganizationProvider>
  );
}

describe('OrganizationProvider follows the organization the backend serves', () => {
  beforeEach(() => {
    localStorage.getItem.mockReset();
    localStorage.setItem.mockReset();
    global.fetch.mockReset();
  });

  test('adopts the X-Current-Org-Id organization over a stale saved one', async () => {
    renderWithSavedOrg(ALDER.id, orgListResponse([ALDER, BIRCH], BIRCH.id));

    expect(await screen.findByTestId('current-org')).toHaveTextContent(BIRCH.name);
    expect(localStorage.setItem).toHaveBeenCalledWith('currentOrgId', BIRCH.id);
  });

  test('keeps the saved organization when the response has no header', async () => {
    renderWithSavedOrg(BIRCH.id, orgListResponse([ALDER, BIRCH]));

    expect(await screen.findByTestId('current-org')).toHaveTextContent(BIRCH.name);
    expect(localStorage.setItem).not.toHaveBeenCalled();
  });

  test('ignores a header that names an organization outside the list', async () => {
    renderWithSavedOrg(BIRCH.id, orgListResponse([ALDER, BIRCH], NOT_LISTED_ID));

    expect(await screen.findByTestId('current-org')).toHaveTextContent(BIRCH.name);
    expect(localStorage.setItem).not.toHaveBeenCalled();
  });
});
