import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { describe, expect, test, vi } from 'vitest';
import { useDashboardActivity } from './useDashboardActivity';

function Probe(props) {
  const state = useDashboardActivity(props);
  return (
    <div>
      <span data-testid="items">{state.items.map(item => item.label).join('|')}</span>
      <span data-testid="loading">{String(state.loading)}</span>
    </div>
  );
}

const item = {
  source: 'project-ops',
  label: 'Fictional task completed',
  timestamp: '2026-11-08T13:00:00.000Z',
  href: 'https://project.example.com/dashboard'
};

describe('useDashboardActivity', () => {
  test('loads a first visit and advances the cursor after items render', async () => {
    const cursorReader = vi.fn().mockResolvedValue(null);
    const activityAdapter = vi.fn().mockResolvedValue({
      items: [item],
      complete: true,
      sourceStatus: { 'project-ops': 'ready', 'meeting-ops': 'ready' },
      errors: {}
    });
    const cursorWriter = vi.fn().mockResolvedValue(item.timestamp);

    render(
      <Probe
        orgId="org-fictional-alpha"
        cursorReader={cursorReader}
        activityAdapter={activityAdapter}
        cursorWriter={cursorWriter}
      />
    );

    await waitFor(() => expect(screen.getByTestId('items')).toHaveTextContent(item.label));
    await waitFor(() => expect(cursorWriter).toHaveBeenCalledWith(
      'org-fictional-alpha',
      item.timestamp
    ));
    expect(cursorReader).toHaveBeenCalledWith('org-fictional-alpha');
  });

  test('does not advance when one upstream is unavailable', async () => {
    const cursorWriter = vi.fn();
    const activityAdapter = vi.fn().mockResolvedValue({
      items: [item],
      complete: false,
      sourceStatus: { 'project-ops': 'ready', 'meeting-ops': 'unavailable' },
      errors: { 'meeting-ops': 'unavailable' }
    });

    render(
      <Probe
        orgId="org-fictional-alpha"
        cursorReader={vi.fn().mockResolvedValue(null)}
        activityAdapter={activityAdapter}
        cursorWriter={cursorWriter}
      />
    );

    await waitFor(() => expect(screen.getByTestId('items')).toHaveTextContent(item.label));
    expect(cursorWriter).not.toHaveBeenCalled();
  });

  test('reloads cursor and activity when the active organization changes', async () => {
    const cursorReader = vi.fn()
      .mockResolvedValueOnce('2026-11-08T10:00:00.000Z')
      .mockResolvedValueOnce(null);
    const activityAdapter = vi.fn()
      .mockResolvedValueOnce({ items: [], complete: true, sourceStatus: {}, errors: {} })
      .mockResolvedValueOnce({ items: [item], complete: true, sourceStatus: {}, errors: {} });
    const cursorWriter = vi.fn().mockResolvedValue(item.timestamp);
    const { rerender } = render(
      <Probe
        orgId="org-fictional-alpha"
        cursorReader={cursorReader}
        activityAdapter={activityAdapter}
        cursorWriter={cursorWriter}
      />
    );

    await waitFor(() => expect(activityAdapter).toHaveBeenCalledWith(
      expect.objectContaining({ orgId: 'org-fictional-alpha', cursor: '2026-11-08T10:00:00.000Z' })
    ));

    rerender(
      <Probe
        orgId="org-fictional-beta"
        cursorReader={cursorReader}
        activityAdapter={activityAdapter}
        cursorWriter={cursorWriter}
      />
    );

    await waitFor(() => expect(activityAdapter).toHaveBeenCalledWith(
      expect.objectContaining({ orgId: 'org-fictional-beta', cursor: null })
    ));
    expect(cursorWriter).toHaveBeenCalledWith('org-fictional-beta', item.timestamp);
  });
});
