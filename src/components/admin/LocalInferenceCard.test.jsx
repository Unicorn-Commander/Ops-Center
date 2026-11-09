/**
 * LocalInferenceCard against real backend output for a fictional fleet
 * (__fixtures__/fleetSummaries.fictional.json, see GPUStatusCard.test.jsx), with the
 * Ops-Center provider endpoints mocked as before.
 */
import React from 'react';
import { render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, test, vi } from 'vitest';
import LocalInferenceCard from './LocalInferenceCard';
import fixtures from './__fixtures__/fleetSummaries.fictional.json';

const MODULE_OFF = { enabled: false, active_providers: [], detected_providers: [], total_providers: 0, gpu_available: false };

function jsonResponse(body, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => body };
}

function fetchFor({
  fleet = fixtures.inference,
  moduleStatus = MODULE_OFF,
  moduleCode = 200,
  providers = { providers: [], total: 0 },
} = {}) {
  return vi.fn(async (url) => {
    const address = String(url);
    if (address.includes('/api/v1/fleet/inference')) return jsonResponse(fleet);
    if (address.includes('/api/v1/local-inference/status')) return jsonResponse(moduleStatus, moduleCode);
    if (address.includes('/api/v1/local-inference/providers')) return jsonResponse(providers, moduleCode);
    return jsonResponse({ detail: 'Not Found' }, 404);
  });
}

function renderCard(fetchImpl) {
  return render(
    <MemoryRouter>
      <LocalInferenceCard fetchImpl={fetchImpl} />
    </MemoryRouter>
  );
}

describe('LocalInferenceCard', () => {
  test('shows the private inference the fleet runs, grouped by host and labelled', async () => {
    const fetchImpl = fetchFor();
    const { container } = renderCard(fetchImpl);

    expect(await screen.findByText('9 services on 5 hosts, private')).toBeInTheDocument();
    expect(fetchImpl).toHaveBeenCalledWith('/api/v1/fleet/inference', expect.objectContaining({ credentials: 'include' }));
    const fleet = screen.getByTestId('fleet-inference');
    expect(within(fleet).getByText('Private (Owned): 8')).toBeInTheDocument();
    expect(within(fleet).getByText('Private (Leased): 1')).toBeInTheDocument();
    expect(within(fleet).getByText('Language model 3')).toBeInTheDocument();

    const hosts = screen.getAllByTestId('fleet-inference-host');
    expect(hosts).toHaveLength(5);
    const gpuA = hosts.find((h) => within(h).queryByText('gpu-a.example'));
    expect(within(gpuA).getByText('Private (Owned)')).toBeInTheDocument();
    expect(within(gpuA).getByText('2 GPUs')).toBeInTheDocument();
    expect(within(gpuA).getByText('3 services, 1 healthy')).toBeInTheDocument();
    const chat = within(gpuA).getByText('chat-llama').closest('[data-testid="fleet-inference-service"]');
    expect(chat).toHaveTextContent('llama.cpp');
    expect(chat).toHaveAttribute('title', 'Language model, llama.cpp: healthy; known model-server image');
    const unit = within(gpuA).getByText('demo-tts.service').closest('[data-testid="fleet-inference-service"]');
    expect(unit.className).toContain('border-dashed');
    expect(unit).toHaveAttribute('title', 'Text to speech: active systemd unit; kind read from the name');

    const vps = hosts.find((h) => within(h).queryByText('vps-1.example'));
    expect(within(vps).getByText('Private (Leased)')).toBeInTheDocument();
    expect(within(vps).getByText('no GPU')).toBeInTheDocument();
    const gpuB = hosts.find((h) => within(h).queryByText('gpu-b.example'));
    expect(within(gpuB).getByText(', 1 unhealthy')).toBeInTheDocument();

    expect(screen.queryByText('stt-proxy')).not.toBeInTheDocument();
    expect(screen.queryByText('edge-litellm')).not.toBeInTheDocument();
    expect(screen.getByText(
      'Not counted as services: 1 metrics exporter, 1 firewall unit, 1 gateway, 2 proxies or adapters.'
    )).toBeInTheDocument();
    expect(screen.getByText(/does not say which model is loaded or whether it answers/)).toBeInTheDocument();

    const managed = screen.getByTestId('managed-providers');
    expect(within(managed).getByText('Providers managed by this server')).toBeInTheDocument();
    expect(within(managed).getByText('Module off')).toBeInTheDocument();
    expect(within(managed).getByText(/No providers are registered here/)).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/disabled/i);
  });

  test('keeps the providers this server manages', async () => {
    const providers = {
      providers: [{
        name: 'ollama', display_name: 'Ollama', status: 'healthy', enabled: true,
        url: 'http://192.0.2.20:11434', models: [{ name: 'fictional-model:7b' }],
      }],
      total: 1,
    };
    renderCard(fetchFor({ moduleStatus: { ...MODULE_OFF, enabled: true }, providers }));

    const managed = await screen.findByTestId('managed-providers');
    expect(await within(managed).findByText('Ollama')).toBeInTheDocument();
    expect(within(managed).getByText('Healthy')).toBeInTheDocument();
    expect(within(managed).getByText('Module on')).toBeInTheDocument();
    expect(within(managed).getByText('1 provider')).toBeInTheDocument();
    expect(within(managed).getByText('http://192.0.2.20:11434')).toBeInTheDocument();
  });

  test('no snapshot reads as not connected; provider management still answers', async () => {
    const { container } = renderCard(fetchFor({ fleet: fixtures.inference_not_connected }));

    expect(await screen.findByTestId('fleet-not-connected')).toBeInTheDocument();
    expect(screen.getByTestId('inference-card-subtitle')).toHaveTextContent('Fleet map not connected');
    expect(screen.getByText(/Ingest is not set up on this server/)).toBeInTheDocument();
    expect(await screen.findByText('Module off')).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/disabled/i);
  });

  test('without the provider module the fleet still shows', async () => {
    renderCard(fetchFor({ moduleCode: 404, moduleStatus: { detail: 'Not Found' } }));

    expect(await screen.findByText('Provider management is not available on this server.')).toBeInTheDocument();
    expect(screen.getAllByTestId('fleet-inference-host')).toHaveLength(5);
    expect(screen.queryByText(/Module (on|off)/)).not.toBeInTheDocument();
  });
});
