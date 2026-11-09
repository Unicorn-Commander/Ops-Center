/**
 * GPUStatusCard against real backend output for a fictional fleet.
 *
 * __fixtures__/fleetSummaries.fictional.json is fleet_gpus.gpu_summary and
 * inference_summary run on backend/tests/fleet/fleetkit.py (fictional *.example
 * hosts, 192.0.2.0/24), four minutes after the snapshot was taken.
 */
import React from 'react';
import { render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, test, vi } from 'vitest';
import GPUStatusCard from './GPUStatusCard';
import fixtures from './__fixtures__/fleetSummaries.fictional.json';

const MODULE_OFF = {
  status: 503,
  body: { detail: 'GPU services management disabled on this instance (GPU_SERVICES_ENABLED=false)' },
};

function jsonResponse(body, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => body };
}

function fetchFor({ fleet = fixtures.gpus, fleetStatus = 200, local = MODULE_OFF } = {}) {
  return vi.fn(async (url) => {
    const address = String(url);
    if (address.includes('/api/v1/fleet/gpus')) return jsonResponse(fleet, fleetStatus);
    if (address.includes('/api/v1/gpu-services/status')) return jsonResponse(local.body, local.status);
    return jsonResponse({ detail: 'Not Found' }, 404);
  });
}

function renderCard(fetchImpl) {
  return render(
    <MemoryRouter>
      <GPUStatusCard fetchImpl={fetchImpl} />
    </MemoryRouter>
  );
}

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

describe('GPUStatusCard', () => {
  test('with the GPU services module off it counts the fleet and never says Disabled', async () => {
    const fetchImpl = fetchFor();
    const { container } = renderCard(fetchImpl);

    expect(await screen.findByText('5 GPUs across 3 hosts')).toBeInTheDocument();
    expect(fetchImpl).toHaveBeenCalledWith('/api/v1/fleet/gpus', expect.objectContaining({ credentials: 'include' }));
    expect(screen.getByText('Current')).toBeInTheDocument();

    const totals = screen.getByTestId('fleet-gpu-totals');
    expect(within(totals).getByText('85 GB')).toBeInTheDocument();
    expect(within(totals).getByText('1 integrated')).toBeInTheDocument();
    expect(within(totals).getAllByText('Not reported')).toHaveLength(2);

    const hosts = screen.getAllByTestId('fleet-gpu-host');
    expect(hosts).toHaveLength(3);
    expect(within(hosts[0]).getByText('gpu-b.example')).toBeInTheDocument();
    expect(within(hosts[0]).getByText('Owned')).toBeInTheDocument();
    expect(within(hosts[0]).getByText('Seen 4 min ago')).toBeInTheDocument();
    expect(within(hosts[0]).getAllByText('NVIDIA Tesla P40')).toHaveLength(2);
    expect(within(hosts[0]).getAllByText('22.5 GB')).toHaveLength(2);
    expect(within(hosts[0]).getByText('Tesla P40 #0: overnight batch jobs')).toBeInTheDocument();
    expect(within(hosts[0]).getByText(/Host notes: imaging workers/)).toBeInTheDocument();
    expect(within(hosts[0]).queryByText('Stale')).not.toBeInTheDocument();

    const apu = hosts[2];
    expect(within(apu).getByText('AMD Strix')).toBeInTheDocument();
    expect(within(apu).getByText('integrated')).toBeInTheDocument();
    expect(within(apu).getByText('shares 110 GB system memory')).toBeInTheDocument();

    expect(screen.getByTestId('local-gpu-note')).toHaveTextContent('runs without the GPU services module');
    expect(screen.getByText(/GPU inventory from 5 of 6 hosts/)).toBeInTheDocument();
    expect(screen.getByText(/usage, load and temperature are not in the snapshot/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Open the fleet map/ })).toHaveAttribute('href', '/admin/infra/fleet-map');
    expect(container.textContent).not.toMatch(/disabled/i);
  });

  test('a stale snapshot marks every host Stale with its last-seen time', async () => {
    const fleet = clone(fixtures.gpus);
    fleet.state = 'stale';
    fleet.stale = true;
    fleet.age_seconds = 7300;
    fleet.hosts.forEach((host) => {
      host.stale = true;
      host.age_seconds = 7300;
    });
    renderCard(fetchFor({ fleet }));

    const hosts = await screen.findAllByTestId('fleet-gpu-host');
    hosts.forEach((host) => {
      expect(within(host).getByText('Stale')).toBeInTheDocument();
      expect(within(host).getByText('Seen 2 h ago')).toBeInTheDocument();
    });
    expect(screen.getByText(/Fleet map snapshot is stale, taken 2 h ago/)).toBeInTheDocument();
  });

  test('no snapshot reads as not connected, with what ingest needs', async () => {
    const { container } = renderCard(fetchFor({ fleet: fixtures.not_connected }));

    expect(await screen.findByTestId('fleet-not-connected')).toBeInTheDocument();
    expect(screen.getByTestId('gpu-card-subtitle')).toHaveTextContent('Fleet map not connected');
    expect(screen.getByText(/Ingest is not set up on this server/)).toBeInTheDocument();
    expect(screen.getByText('Not connected')).toBeInTheDocument();
    expect(screen.queryByTestId('fleet-gpu-totals')).not.toBeInTheDocument();
    expect(container.textContent).not.toMatch(/disabled/i);
  });

  test('with the module on, this server keeps its own GPU detail as well', async () => {
    const local = {
      status: 200,
      body: {
        gpu_info: {
          gpus: [{
            index: 0, name: 'Fictional Accelerator 8G', memory_used_mb: 2048, memory_total_mb: 8192,
            memory_free_mb: 6144, utilization_percent: 12, temperature: 41,
          }],
          total_memory_mb: 8192, used_memory_mb: 2048, free_memory_mb: 6144,
        },
      },
    };
    renderCard(fetchFor({ local }));

    const detail = await screen.findByTestId('local-gpu-detail');
    expect(within(detail).getByText('This server')).toBeInTheDocument();
    expect(within(detail).getByText('Fictional Accelerator 8G')).toBeInTheDocument();
    expect(within(detail).getByText('41°C')).toBeInTheDocument();
    expect(screen.getByText('5 GPUs across 3 hosts')).toBeInTheDocument();
    expect(screen.queryByTestId('local-gpu-note')).not.toBeInTheDocument();
  });

  test('reported usage and load replace Not reported', async () => {
    const fleet = clone(fixtures.gpus);
    Object.assign(fleet.totals, {
      vram_used_mib: 40960, vram_used_reported_gpus: 2, gpus_busy: 1, utilization_reported_gpus: 2,
    });
    fleet.reported = { vram_used: true, utilization: true, temperature: true, processes: false };
    Object.assign(fleet.hosts[0].gpus[0], { vram_used_mib: 20480, utilization_pct: 85, temperature_c: 61, busy: true });
    renderCard(fetchFor({ fleet }));

    const totals = await screen.findByTestId('fleet-gpu-totals');
    expect(within(totals).getByText('40 GB')).toBeInTheDocument();
    expect(within(totals).getByText('1 of 2')).toBeInTheDocument();
    expect(within(totals).queryByText('Not reported')).not.toBeInTheDocument();
    expect(screen.getByText('20 GB in use, 85% load, 61°C')).toBeInTheDocument();
    expect(screen.getByText('busy')).toBeInTheDocument();
    expect(screen.queryByText(/not in the snapshot/)).not.toBeInTheDocument();
  });

  test('a refused fleet read says why, not Disabled', async () => {
    const { container } = renderCard(fetchFor({ fleet: { detail: 'Admin access required.' }, fleetStatus: 403 }));

    expect(await screen.findByTestId('fleet-error')).toHaveTextContent('The fleet map is for platform admins.');
    expect(screen.getByTestId('gpu-card-subtitle')).toHaveTextContent('Fleet summary unavailable');
    expect(container.textContent).not.toMatch(/disabled/i);
  });
});
