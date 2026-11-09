/**
 * GPUStatusCard - every GPU in the fleet, plus this server's own GPUs when it has them.
 *
 * Fleet: GET /api/v1/fleet/gpus (admin only), built from the fleet map snapshot the
 * collector pushes about every 5 minutes. Shows "N GPUs across M hosts", dedicated VRAM,
 * VRAM in use and busy GPUs (only when the collector reports them), and one row per GPU
 * host with each GPU, ownership, stale markers and last-seen times. With no snapshot the
 * card says the fleet map is not connected; it never reads "Disabled".
 *
 * This server: GET /api/v1/gpu-services/status (nvidia-smi through the GPU services
 * module). When the module is on, its per-GPU memory, utilization and temperature detail
 * stays below the fleet and refreshes every 5 seconds. When it is off
 * (GPU_SERVICES_ENABLED=false, as on a web host without a GPU), one quiet line says so and
 * the module is checked again once a minute.
 */

import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Link } from 'react-router-dom';
import { motion } from 'framer-motion';
import {
  CpuChipIcon,
  FireIcon,
  ArrowPathIcon,
  MapIcon,
} from '@heroicons/react/24/outline';
import ProgressBar from './ProgressBar';
import StatusIndicator from './StatusIndicator';
import {
  FLEET_GPUS_ENDPOINT,
  FLEET_MAP_PAGE,
  FLEET_REFRESH_MS,
  ago,
  absoluteTime,
  fetchFleetSummary,
  formatMiB,
  notConnectedLines,
  plural,
  snapshotLine,
} from './fleetSnapshot';

// This server's GPUs, through the GPU services module (nvidia-smi on the Ops-Center host).
const GPU_API_ENDPOINT = '/api/v1/gpu-services/status';
const LOCAL_REFRESH_MS = 5000;

const FLEET_STATE_CHIP = {
  ok: { text: 'Current', className: 'bg-green-500/20 text-green-300' },
  stale: { text: 'Stale', className: 'bg-amber-500/20 text-amber-300' },
  not_connected: { text: 'Not connected', className: 'bg-gray-500/20 text-gray-300' },
};

const OWNERSHIP_TITLE = {
  tag: 'Ownership set in the fleet map',
  site: 'The fleet map describes this host as a rented server',
  default: 'No ownership tag in the fleet map, so Owned is assumed',
};

// Format MB (MiB) for the local nvidia-smi detail.
const formatMB = (mb) => {
  if (!mb && mb !== 0) return 'N/A';
  if (mb >= 1024) {
    return `${(mb / 1024).toFixed(1)} GB`;
  }
  return `${mb} MB`;
};

const getUsageColor = (percent) => {
  if (percent > 90) return 'text-red-400';
  if (percent > 70) return 'text-yellow-400';
  return 'text-green-400';
};

const getTemperatureColor = (temp) => {
  if (!temp && temp !== 0) return 'text-gray-400';
  if (temp > 80) return 'text-red-400';
  if (temp > 65) return 'text-yellow-400';
  return 'text-green-400';
};

const isNumber = (value) => typeof value === 'number' && !Number.isNaN(value);

async function fetchLocalGpus(fetchImpl) {
  try {
    const response = await fetchImpl(GPU_API_ENDPOINT, {
      credentials: 'include',
      headers: { Accept: 'application/json' },
    });
    if (response.ok) {
      const data = await response.json();
      // /status returns { gpu_info: {...}, ... }; /gpu returns the info itself.
      const info = data && data.gpu_info !== undefined ? data.gpu_info : data;
      return { state: 'on', info: info || null };
    }
    const body = await response.json().catch(() => ({}));
    const detail = typeof body.detail === 'string' ? body.detail : '';
    if (response.status === 503 && /disabled/i.test(detail)) return { state: 'off' };
    if (response.status === 404) return { state: 'on', info: null };
    if (response.status === 401) return { state: 'error', detail: 'sign in again' };
    return { state: 'error', detail: `HTTP ${response.status}` };
  } catch (err) {
    return { state: 'error', detail: 'the server could not be reached' };
  }
}

function gpuName(gpu) {
  const model = gpu.model || 'Unnamed GPU';
  if (gpu.vendor && !model.toLowerCase().includes(gpu.vendor.toLowerCase())) {
    return `${gpu.vendor} ${model}`;
  }
  return model;
}

function Tile({ label, value, sub }) {
  return (
    <div className="rounded-xl bg-white/5 border border-white/10 px-3 py-2 min-w-0">
      <p className="text-xs text-gray-400">{label}</p>
      <p className="text-lg font-semibold text-white truncate">{value}</p>
      {sub && <p className="text-xs text-gray-500 truncate" title={sub}>{sub}</p>}
    </div>
  );
}

function FleetSummary({ doc }) {
  const t = doc.totals;
  const kinds = t.integrated_gpus > 0
    ? `${t.integrated_gpus} integrated`
    : (t.discrete_gpus === t.gpus ? 'all discrete' : `${t.discrete_gpus} discrete`);
  const inUseKnown = isNumber(t.vram_used_mib);
  const busyKnown = isNumber(t.gpus_busy);
  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mb-4" data-testid="fleet-gpu-totals">
      <Tile label="GPUs" value={t.gpus} sub={kinds} />
      <Tile label="VRAM" value={formatMiB(t.vram_total_mib) || 'Not reported'} sub="dedicated only" />
      <Tile
        label="VRAM in use"
        value={inUseKnown ? formatMiB(t.vram_used_mib) : 'Not reported'}
        sub={inUseKnown ? `${t.vram_used_reported_gpus} of ${t.gpus} GPUs report it` : 'no usage figures in the snapshot'}
      />
      <Tile
        label="Busy"
        value={busyKnown ? `${t.gpus_busy} of ${t.utilization_reported_gpus}` : 'Not reported'}
        sub={busyKnown ? `at ${doc.busy_threshold_pct}% load or more` : 'no load figures in the snapshot'}
      />
    </div>
  );
}

function GpuLine({ gpu }) {
  const name = gpuName(gpu);
  let memory;
  if (gpu.kind === 'integrated') {
    memory = isNumber(gpu.shared_memory_gib)
      ? `shares ${gpu.shared_memory_gib} GB system memory`
      : 'shares system memory';
  } else {
    memory = formatMiB(gpu.vram_total_mib) || 'memory not reported';
  }
  const facts = [];
  if (isNumber(gpu.vram_used_mib)) facts.push(`${formatMiB(gpu.vram_used_mib)} in use`);
  if (isNumber(gpu.utilization_pct)) facts.push(`${gpu.utilization_pct}% load`);
  if (isNumber(gpu.temperature_c)) facts.push(`${gpu.temperature_c}°C`);
  if (Array.isArray(gpu.processes) && gpu.processes.length > 0) {
    facts.push(plural(gpu.processes.length, 'process', 'processes'));
  }
  return (
    <li className="py-1.5" data-testid="fleet-gpu">
      <div className="flex items-baseline gap-2 text-sm min-w-0">
        <span className="text-xs text-gray-500 w-11 shrink-0">GPU {gpu.index}</span>
        <span className="text-white truncate" title={name}>{name}</span>
        {gpu.kind === 'integrated' && (
          <span className="text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded bg-indigo-500/20 text-indigo-300 shrink-0">
            integrated
          </span>
        )}
        {gpu.busy === true && (
          <span className="text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded bg-green-500/20 text-green-300 shrink-0">
            busy
          </span>
        )}
        <span className="ml-auto text-xs text-gray-400 shrink-0">{memory}</span>
      </div>
      {facts.length > 0 && <p className="pl-[3.25rem] text-xs text-gray-400">{facts.join(', ')}</p>}
      {(gpu.notes || []).map((note) => (
        <p key={note} className="pl-[3.25rem] text-xs text-gray-500 line-clamp-2" title={note}>
          {note}
        </p>
      ))}
    </li>
  );
}

function HostRow({ host }) {
  return (
    <li
      className={`rounded-xl border px-3 py-2 ${host.stale ? 'border-amber-500/40 bg-amber-500/5' : 'border-white/10 bg-white/5'}`}
      data-testid="fleet-gpu-host"
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-semibold text-white">{host.name}</span>
        <span
          className="text-xs px-2 py-0.5 rounded-full bg-white/10 text-gray-300"
          title={OWNERSHIP_TITLE[host.ownership_basis] || undefined}
        >
          {host.ownership}
        </span>
        {host.stale && (
          <span className="text-xs px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-300">Stale</span>
        )}
        <span className="ml-auto text-xs text-gray-400" title={absoluteTime(host.last_seen)}>
          Seen {ago(host.age_seconds)}
        </span>
      </div>
      <ul className="mt-1 divide-y divide-white/5">
        {host.gpus.map((gpu, i) => <GpuLine key={`${gpu.index}-${i}`} gpu={gpu} />)}
      </ul>
      {Array.isArray(host.notes) && host.notes.length > 0 && (
        <p className="mt-1 text-xs text-gray-500 line-clamp-2" title={host.notes.join('\n')}>
          Host notes: {host.notes.join('; ')}
        </p>
      )}
    </li>
  );
}

function NotConnected({ doc }) {
  return (
    <div className="rounded-xl border border-white/10 bg-white/5 p-4" data-testid="fleet-not-connected">
      <p className="text-sm font-medium text-white">Fleet map not connected</p>
      {notConnectedLines(doc).map((line) => (
        <p key={line} className="mt-1 text-xs text-gray-400">{line}</p>
      ))}
    </div>
  );
}

function LocalGpuDetail({ info }) {
  const { gpus, total_memory_mb, used_memory_mb } = info;
  const totalPercent = total_memory_mb > 0 ? (used_memory_mb / total_memory_mb) * 100 : 0;
  const anyHighUtil = gpus.some((g) => g.utilization_percent > 90);
  const anyHighMem = gpus.some((g) => (g.memory_used_mb / g.memory_total_mb) * 100 > 95);
  const anyHighTemp = gpus.some((g) => g.temperature && g.temperature > 80);
  let status = 'healthy';
  if (anyHighTemp || anyHighMem) status = 'critical';
  else if (anyHighUtil || totalPercent > 80) status = 'warning';

  return (
    <div className="mt-4 pt-4 border-t border-white/10" data-testid="local-gpu-detail">
      <div className="flex items-center justify-between mb-3">
        <p className="text-sm font-semibold text-white">This server</p>
        <StatusIndicator status={status} showLabel animate />
      </div>
      <div className="space-y-3">
        {gpus.map((gpu) => {
          const usagePercent = gpu.memory_total_mb > 0 ? (gpu.memory_used_mb / gpu.memory_total_mb) * 100 : 0;
          return (
            <div key={gpu.index} className="backdrop-blur-sm bg-white/5 rounded-xl p-4 border border-white/10">
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-semibold text-white">GPU {gpu.index}</span>
                  <span className="text-xs text-gray-400 truncate max-w-[180px]">{gpu.name}</span>
                </div>
                <div className="flex items-center gap-4">
                  <div className="flex items-center gap-1.5">
                    <span className="text-xs text-gray-500">Util:</span>
                    <span className={`text-xs font-medium ${getUsageColor(gpu.utilization_percent || 0)}`}>
                      {gpu.utilization_percent !== undefined ? `${gpu.utilization_percent}%` : 'N/A'}
                    </span>
                  </div>
                  {gpu.temperature !== undefined && (
                    <div className="flex items-center gap-1.5">
                      <FireIcon className={`h-3.5 w-3.5 ${getTemperatureColor(gpu.temperature)}`} />
                      <span className={`text-xs font-medium ${getTemperatureColor(gpu.temperature)}`}>
                        {gpu.temperature}°C
                      </span>
                    </div>
                  )}
                </div>
              </div>
              <ProgressBar value={gpu.memory_used_mb} max={gpu.memory_total_mb} type="vram" height="sm" showLabel={false} animated />
              <div className="flex justify-between mt-2 text-xs">
                <span className={getUsageColor(usagePercent)}>{formatMB(gpu.memory_used_mb)} used</span>
                <span className="text-gray-400">{formatMB(gpu.memory_free_mb)} free</span>
                <span className="text-gray-500">{formatMB(gpu.memory_total_mb)} total</span>
              </div>
            </div>
          );
        })}
      </div>
      {gpus.length > 1 && (
        <div className="mt-3 flex items-center justify-between">
          <span className="text-sm text-gray-400">Total VRAM on this server</span>
          <span className={`text-sm font-medium ${getUsageColor(totalPercent)}`}>
            {formatMB(used_memory_mb)} / {formatMB(total_memory_mb)} ({totalPercent.toFixed(1)}%)
          </span>
        </div>
      )}
      <p className="mt-2 text-xs text-gray-500">From nvidia-smi on this server, refreshed every 5 seconds.</p>
    </div>
  );
}

function LocalSection({ local }) {
  if (!local) return null;
  if (local.state === 'on' && local.info && Array.isArray(local.info.gpus) && local.info.gpus.length > 0) {
    return <LocalGpuDetail info={local.info} />;
  }
  let line;
  if (local.state === 'off') {
    line = 'This server runs without the GPU services module (GPU_SERVICES_ENABLED=false), so it shows no local GPU detail.';
  } else if (local.state === 'on') {
    line = 'This server: nvidia-smi found no GPU.';
  } else {
    line = `This server's own GPU status could not be read: ${local.detail}.`;
  }
  return <p className="mt-4 text-xs text-gray-500" data-testid="local-gpu-note">{line}</p>;
}

export default function GPUStatusCard({
  glassStyles = {},
  className = '',
  fetchImpl,
}) {
  const fetcherRef = useRef(null);
  fetcherRef.current = fetchImpl || ((url, options) => fetch(url, options));
  const [fleet, setFleet] = useState(null);
  const [fleetError, setFleetError] = useState(null);
  const [local, setLocal] = useState(null);
  const [loading, setLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const localOn = useRef(false);

  const loadFleet = useCallback(async () => {
    const { data, error } = await fetchFleetSummary(fetcherRef.current, FLEET_GPUS_ENDPOINT);
    if (data) {
      setFleet(data);
      setFleetError(null);
    } else {
      setFleetError(error);
    }
  }, []);

  const loadLocal = useCallback(async () => {
    const result = await fetchLocalGpus(fetcherRef.current);
    localOn.current = result.state === 'on';
    setLocal(result);
  }, []);

  const refresh = useCallback(async (manual = false) => {
    if (manual) setIsRefreshing(true);
    await Promise.all([loadFleet(), loadLocal()]);
    setLoading(false);
    setIsRefreshing(false);
  }, [loadFleet, loadLocal]);

  useEffect(() => {
    refresh();
    const slow = setInterval(() => {
      loadFleet();
      if (!localOn.current) loadLocal();
    }, FLEET_REFRESH_MS);
    const fast = setInterval(() => {
      if (localOn.current) loadLocal();
    }, LOCAL_REFRESH_MS);
    return () => {
      clearInterval(slow);
      clearInterval(fast);
    };
  }, [refresh, loadFleet, loadLocal]);

  const connected = Boolean(fleet && fleet.available);
  const totals = connected ? fleet.totals : null;
  let subtitle = '';
  if (loading) subtitle = 'Loading...';
  else if (totals) subtitle = `${plural(totals.gpus, 'GPU')} across ${plural(totals.hosts_with_gpus, 'host')}`;
  else if (fleet) subtitle = 'Fleet map not connected';
  else if (fleetError) subtitle = 'Fleet summary unavailable';
  const chip = fleet ? FLEET_STATE_CHIP[fleet.state] : null;

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className={`${glassStyles.card || 'backdrop-blur-xl bg-white/10 border border-white/20'} rounded-2xl p-6 shadow-xl ${className}`}
    >
      <div className="flex items-center justify-between mb-5 gap-3">
        <div className="flex items-center gap-3 min-w-0">
          <div className={`w-10 h-10 bg-gradient-to-br from-purple-500 to-indigo-500 rounded-xl flex items-center justify-center shadow-lg ${loading ? 'animate-pulse' : ''}`}>
            <CpuChipIcon className="h-5 w-5 text-white" />
          </div>
          <div className="min-w-0">
            <h3 className="text-lg font-bold text-white">GPU Status</h3>
            <p className="text-sm text-gray-400 truncate" data-testid="gpu-card-subtitle">{subtitle}</p>
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {chip && <span className={`text-xs px-2 py-1 rounded-full ${chip.className}`}>{chip.text}</span>}
          <button
            onClick={() => refresh(true)}
            disabled={isRefreshing}
            className="p-2 rounded-lg bg-white/5 hover:bg-white/10 transition-colors disabled:opacity-50"
            title="Refresh"
            aria-label="Refresh GPU status"
          >
            <ArrowPathIcon className={`h-4 w-4 text-gray-400 ${isRefreshing ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {loading && (
        <div className="space-y-3">
          <div className="h-16 bg-gray-700/30 rounded-lg animate-pulse" />
          <div className="h-20 bg-gray-700/30 rounded-lg animate-pulse" />
        </div>
      )}

      {!loading && fleetError && (
        <p className="mb-3 text-xs text-amber-300" data-testid="fleet-error">{fleetError}</p>
      )}

      {!loading && fleet && !connected && <NotConnected doc={fleet} />}

      {!loading && totals && totals.gpus === 0 && (
        <p className="text-sm text-gray-400">The fleet map lists no GPUs on any host.</p>
      )}

      {!loading && totals && totals.gpus > 0 && (
        <>
          <FleetSummary doc={fleet} />
          <ul className="space-y-2">
            {fleet.hosts.map((host) => <HostRow key={host.id} host={host} />)}
          </ul>
        </>
      )}

      {!loading && <LocalSection local={local} />}

      {!loading && connected && (
        <div className="mt-4 pt-3 border-t border-white/5 space-y-1 text-xs text-gray-500">
          <p>
            {snapshotLine(fleet)}. GPU inventory from {fleet.hosts_inventoried} of {fleet.hosts_total} hosts in the map.
          </p>
          {fleet.reported && !fleet.reported.vram_used && !fleet.reported.utilization && (
            <p>The collector reports each GPU&apos;s model and memory size; usage, load and temperature are not in the snapshot.</p>
          )}
        </div>
      )}

      {!loading && (
        <Link
          to={FLEET_MAP_PAGE}
          className="mt-3 inline-flex items-center gap-1.5 text-xs text-blue-400 hover:text-blue-300"
        >
          <MapIcon className="h-3.5 w-3.5" />
          Open the fleet map
        </Link>
      )}
    </motion.div>
  );
}
