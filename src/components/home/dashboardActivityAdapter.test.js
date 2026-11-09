import { describe, expect, test, vi } from 'vitest';
import {
  advanceDashboardCursor,
  fetchDashboardActivity,
  filterActivitySince,
  latestActivityTimestamp
} from './dashboardActivityAdapter';

const ORG_ID = 'org-fictional-alpha';

function response(body, ok = true, status = 200) {
  return { ok, status, json: vi.fn().mockResolvedValue(body) };
}

describe('dashboard activity adapter', () => {
  test('filters older and cross-org activity on a first-party cursor', () => {
    const items = filterActivitySince([
      { timestamp: '2026-11-08T12:00:00Z', org_id: ORG_ID },
      { timestamp: '2026-11-08T11:00:00Z', org_id: ORG_ID },
      { timestamp: '2026-11-08T13:00:00Z', org_id: 'org-fictional-beta' }
    ], '2026-11-08T11:30:00Z', ORG_ID);

    expect(items).toEqual([{ timestamp: '2026-11-08T12:00:00Z', org_id: ORG_ID }]);
  });

  test('keeps first-visit activity from both apps and returns newest first', async () => {
    const fetchImpl = vi.fn()
      .mockResolvedValueOnce(response({ events: [
        { action: 'Task completed', created_at: '2026-11-08T12:00:00Z', workspace_id: ORG_ID }
      ] }))
      .mockResolvedValueOnce(response({ sessions: [
        { id: 'meeting-1', name: 'Fictional planning', created_at: '2026-11-08T13:00:00Z', org_id: ORG_ID }
      ] }));

    const result = await fetchDashboardActivity({
      orgId: ORG_ID,
      fetchImpl,
      projectBaseUrl: 'https://project.example.com',
      meetingBaseUrl: 'https://meeting.example.com'
    });

    expect(result.complete).toBe(true);
    expect(result.items.map(item => item.source)).toEqual(['meeting-ops', 'project-ops']);
    expect(result.items[1].href).toBe('https://project.example.com/dashboard');
    expect(fetchImpl).toHaveBeenNthCalledWith(
      1,
      'https://project.example.com/api/v1/dashboard/recent-activity?limit=20',
      expect.objectContaining({ credentials: 'include' })
    );
  });

  test('returns partial results when Meeting-Ops is unavailable', async () => {
    const fetchImpl = vi.fn()
      .mockResolvedValueOnce(response({ events: [
        { action: 'Project update', created_at: '2026-11-08T12:00:00Z', org_id: ORG_ID }
      ] }))
      .mockResolvedValueOnce(response({ detail: 'down' }, false, 503));

    const result = await fetchDashboardActivity({
      orgId: ORG_ID,
      cursor: null,
      fetchImpl,
      projectBaseUrl: 'https://project.example.com',
      meetingBaseUrl: 'https://meeting.example.com'
    });

    expect(result.complete).toBe(false);
    expect(result.items).toHaveLength(1);
    expect(result.sourceStatus).toEqual({
      'project-ops': 'ready',
      'meeting-ops': 'unavailable'
    });
  });

  test('advances only with a valid timestamp and sends credentials', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(response({
      last_seen_at: '2026-11-08T13:00:00.000Z'
    }));

    const result = await advanceDashboardCursor(ORG_ID, '2026-11-08T13:00:00Z', fetchImpl);

    expect(result).toBe('2026-11-08T13:00:00.000Z');
    expect(fetchImpl).toHaveBeenCalledWith(
      `/api/v1/org/${ORG_ID}/dashboard-cursor`,
      expect.objectContaining({ method: 'PUT', credentials: 'include' })
    );
    expect(JSON.parse(fetchImpl.mock.calls[0][1].body)).toEqual({
      last_seen_at: '2026-11-08T13:00:00.000Z',
      rendered: true
    });
  });

  test('finds the newest rendered activity for cursor advancement', () => {
    expect(latestActivityTimestamp([
      { timestamp: '2026-11-08T12:00:00.000Z' },
      { timestamp: '2026-11-08T13:00:00.000Z' }
    ])).toBe('2026-11-08T13:00:00.000Z');
  });
});
