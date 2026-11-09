import { describe, expect, test, vi } from 'vitest';
import {
  advanceDashboardCursor,
  fetchDashboardActivity,
  filterActivitySince,
  latestActivityTimestamp,
  resolveActivityOrigins
} from './dashboardActivityAdapter';

const ORG_ID = 'org-fictional-alpha';

function response(body, ok = true, status = 200) {
  return { ok, status, json: vi.fn().mockResolvedValue(body) };
}

describe('dashboard activity adapter', () => {
  test('filters older activity and a foreign ops-center org id', () => {
    const items = filterActivitySince([
      { timestamp: '2026-11-08T12:00:00Z', org_id: ORG_ID },
      { timestamp: '2026-11-08T11:00:00Z', org_id: ORG_ID },
      { timestamp: '2026-11-08T13:00:00Z', org_id: 'org-fictional-beta' },
      { timestamp: '2026-11-08T13:30:00Z', workspace_id: 'other-workspace' },
      { timestamp: '2026-11-08T13:40:00Z', organization_id: 7 }
    ], '2026-11-08T11:30:00Z', ORG_ID);

    expect(items.map(item => item.timestamp)).toEqual([
      '2026-11-08T13:40:00Z',
      '2026-11-08T13:30:00Z',
      '2026-11-08T12:00:00Z'
    ]);
  });

  test('an invalid cursor shows nothing', () => {
    expect(filterActivitySince([
      { timestamp: '2026-11-08T12:00:00Z', org_id: ORG_ID }
    ], 'not-a-time', ORG_ID)).toEqual([]);
  });

  test('keeps a first visit from both apps and uses the real routes', async () => {
    const fetchImpl = vi.fn()
      .mockResolvedValueOnce(response({ events: [
        {
          action: 'Task completed',
          timestamp: '2026-11-08T12:00:00Z',
          workspaceId: 'workspace-other',
          project: { id: 'proj-1', title: 'Lantern' }
        }
      ] }))
      .mockResolvedValueOnce(response([
        { id: 'meeting-1', name: 'Fictional planning', created_at: '2026-11-08T13:00:00Z', organization_id: 7 }
      ]));

    const result = await fetchDashboardActivity({
      orgId: ORG_ID,
      fetchImpl,
      projectBaseUrl: 'https://project.example.com',
      meetingBaseUrl: 'https://meeting.example.com'
    });

    expect(result.complete).toBe(true);
    expect(result.items.map(item => item.source)).toEqual(['meeting-ops', 'project-ops']);
    expect(result.items[0].href).toBe('https://meeting.example.com/#/sessions/meeting-1');
    expect(result.items[1].href).toBe('https://project.example.com/dashboard/projects/proj-1');
    expect(result.items[1].label).toBe('Task completed: Lantern');
    const urls = fetchImpl.mock.calls.map(call => call[0]);
    expect(urls).toEqual([
      'https://project.example.com/api/v1/dashboard/recent-activity?limit=20',
      'https://meeting.example.com/api/analytics/sessions?limit=20'
    ]);
    expect(urls.join(' ')).not.toMatch(/digest|force=true|@/);
  });

  test('falls back to role-safe project and task routes after a 403', async () => {
    const fetchImpl = vi.fn(async (url) => {
      if (String(url).includes('recent-activity')) return response({}, false, 403);
      if (String(url).includes('project-statistics')) {
        return response({ recentProjects: [
          { id: 'proj-1', title: 'Lantern', createdAt: '2026-11-08T12:00:00Z' }
        ] });
      }
      if (String(url).includes('my-tasks')) {
        return response([
          { id: 'task-1', title: 'Write the brief', updatedAt: '2026-11-08T12:30:00Z' }
        ]);
      }
      if (String(url).includes('analytics/sessions')) return response([]);
      throw new Error(String(url));
    });

    const result = await fetchDashboardActivity({
      orgId: ORG_ID,
      fetchImpl,
      projectBaseUrl: 'https://project.example.com',
      meetingBaseUrl: 'https://meeting.example.com'
    });

    const urls = fetchImpl.mock.calls.map(call => String(call[0]));
    expect(urls).toContain('https://project.example.com/api/v1/dashboard/project-statistics');
    expect(urls).toContain('https://project.example.com/api/v1/tasks/my-tasks');
    expect(urls.filter(url => url.includes('project-statistics') || url.includes('my-tasks')).every(url => !url.includes('?'))).toBe(true);
    expect(result.items.map(item => item.href)).toEqual([
      'https://project.example.com/dashboard/my-tasks',
      'https://project.example.com/dashboard/projects/proj-1'
    ]);
  });

  test('returns partial results when Meeting-Ops is unavailable', async () => {
    const fetchImpl = vi.fn()
      .mockResolvedValueOnce(response({ events: [
        { action: 'Project update', timestamp: '2026-11-08T12:00:00Z', org_id: ORG_ID }
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

  test('advances only after render and sends credentials', async () => {
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

  test('uses production hosts outside the dogfood ring', () => {
    const prod = resolveActivityOrigins('ops.unicorncommander.ai');
    const dogfood = resolveActivityOrigins('ops.magicunicorn.dev');
    expect(prod.projectApi).toBe('https://api.projectops.unicorncommander.ai');
    expect(prod.meetingWeb).toBe('https://meeting-ops.unicorncommander.ai');
    expect(dogfood.projectApi).toBe('https://api.projectops.magicunicorn.dev');
    expect(dogfood.meetingApi).toBe('https://meetingops.magicunicorn.dev');
    expect(JSON.stringify({ prod, dogfood })).not.toMatch(/@/);
  });

  test('finds the newest rendered activity for cursor advancement', () => {
    expect(latestActivityTimestamp([
      { timestamp: '2026-11-08T12:00:00.000Z' },
      { timestamp: '2026-11-08T13:00:00.000Z' }
    ])).toBe('2026-11-08T13:00:00.000Z');
  });
});
