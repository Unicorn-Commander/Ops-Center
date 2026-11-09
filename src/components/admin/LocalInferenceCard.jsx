/**
 * LocalInferenceCard - the private inference the fleet runs, and the providers this server manages.
 *
 * Fleet: GET /api/v1/fleet/inference (admin only), from the fleet map snapshot. Model-serving
 * containers and units grouped by host, each host labelled Private (Owned) or Private (Leased),
 * with Docker's own health where the container has a healthcheck. The snapshot cannot say which
 * model a service has loaded or whether it answers, so the card says what it can tell: kinds come
 * from a known model-server image, or (dashed outline) from the service name.
 *
 * Managed here: GET /api/v1/local-inference/status and /providers, the Ops-Center local inference
 * module (Ollama, vLLM, llama.cpp endpoints this server talks to), refreshed every 30 seconds as
 * before. It sits under its own heading, so "module off" is never read as "no private inference".
 */

import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Link } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import {
  ServerStackIcon,
  CubeIcon,
  CheckCircleIcon,
  XCircleIcon,
  ExclamationTriangleIcon,
  ArrowPathIcon,
  ChevronDownIcon,
  CpuChipIcon,
  CircleStackIcon,
  SparklesIcon,
  MapIcon
} from '@heroicons/react/24/outline';
import {
  FLEET_INFERENCE_ENDPOINT,
  FLEET_MAP_PAGE,
  FLEET_REFRESH_MS,
  ago,
  absoluteTime,
  fetchFleetSummary,
  notConnectedLines,
  plural,
  snapshotLine,
} from './fleetSnapshot';

// Provider icons and colors
const PROVIDER_CONFIG = {
  ollama: {
    name: 'Ollama',
    color: 'from-blue-500 to-cyan-500',
    textColor: 'text-blue-400',
    bgColor: 'bg-blue-500/20',
    icon: CubeIcon
  },
  vllm: {
    name: 'vLLM',
    color: 'from-purple-500 to-pink-500',
    textColor: 'text-purple-400',
    bgColor: 'bg-purple-500/20',
    icon: SparklesIcon
  },
  'llama.cpp': {
    name: 'llama.cpp',
    color: 'from-orange-500 to-yellow-500',
    textColor: 'text-orange-400',
    bgColor: 'bg-orange-500/20',
    icon: CpuChipIcon
  },
  'llama-cpp': {
    name: 'llama.cpp',
    color: 'from-orange-500 to-yellow-500',
    textColor: 'text-orange-400',
    bgColor: 'bg-orange-500/20',
    icon: CpuChipIcon
  },
  llamacpp: {
    name: 'llama.cpp',
    color: 'from-orange-500 to-yellow-500',
    textColor: 'text-orange-400',
    bgColor: 'bg-orange-500/20',
    icon: CpuChipIcon
  }
};

// Status pill component
function StatusPill({ status }) {
  const normalizedStatus = status?.toLowerCase() || 'unknown';

  const config = {
    healthy: { color: 'bg-green-500', text: 'Healthy', Icon: CheckCircleIcon },
    up: { color: 'bg-green-500', text: 'Up', Icon: CheckCircleIcon },
    running: { color: 'bg-green-500', text: 'Running', Icon: CheckCircleIcon },
    active: { color: 'bg-green-500', text: 'Active', Icon: CheckCircleIcon },
    down: { color: 'bg-red-500', text: 'Down', Icon: XCircleIcon },
    error: { color: 'bg-red-500', text: 'Error', Icon: XCircleIcon },
    unhealthy: { color: 'bg-red-500', text: 'Unhealthy', Icon: XCircleIcon },
    stopped: { color: 'bg-gray-500', text: 'Stopped', Icon: ExclamationTriangleIcon },
    unknown: { color: 'bg-gray-500', text: 'Unknown', Icon: ExclamationTriangleIcon },
    not_detected: { color: 'bg-gray-500', text: 'Not Detected', Icon: ExclamationTriangleIcon }
  };

  const { color, text, Icon } = config[normalizedStatus] || config.unknown;

  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${color} text-white`}>
      <Icon className="h-3 w-3" />
      {text}
    </span>
  );
}

// Format bytes to human readable
function formatBytes(bytes) {
  if (!bytes || bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

// Format VRAM usage
function formatVRAM(vram) {
  if (!vram) return null;
  if (typeof vram === 'number') {
    return formatBytes(vram);
  }
  if (typeof vram === 'string') {
    return vram;
  }
  return null;
}

// Check if provider is healthy
function isProviderHealthy(provider) {
  const status = (provider.status || provider.health || '').toLowerCase();
  return ['healthy', 'up', 'running', 'active'].includes(status);
}

// Provider card component
function ProviderRow({ provider, isExpanded, onToggle }) {
  const providerId = (provider.id || provider.type || provider.name || '').toLowerCase();
  const config = PROVIDER_CONFIG[providerId] || {
    name: provider.name || provider.type || provider.id || 'Unknown',
    color: 'from-gray-500 to-gray-600',
    textColor: 'text-gray-400',
    bgColor: 'bg-gray-500/20',
    icon: CubeIcon
  };

  const Icon = config.icon;
  const hasModels = provider.models && provider.models.length > 0;
  const modelCount = provider.models?.length || 0;
  const isHealthy = isProviderHealthy(provider);

  return (
    <div className={`border rounded-lg overflow-hidden ${
      isHealthy ? 'border-green-500/30 bg-green-500/5' : 'border-white/10 bg-white/5'
    }`}>
      {/* Provider header */}
      <div
        className={`flex items-center gap-3 px-4 py-3 ${hasModels ? 'cursor-pointer hover:bg-white/5' : ''} transition-colors`}
        onClick={() => hasModels && onToggle()}
      >
        {/* Provider icon */}
        <div className={`w-8 h-8 bg-gradient-to-br ${config.color} rounded-lg flex items-center justify-center shadow-lg flex-shrink-0`}>
          <Icon className="h-4 w-4 text-white" />
        </div>

        {/* Provider name */}
        <div className="flex-1 min-w-0">
          <span className="text-sm font-medium text-white">{config.name}</span>
          {provider.url && (
            <p className="text-xs text-gray-500 truncate">{provider.url}</p>
          )}
        </div>

        {/* Model count badge */}
        {modelCount > 0 && (
          <span className={`text-xs ${config.bgColor} ${config.textColor} px-2 py-0.5 rounded-full`}>
            {modelCount} model{modelCount !== 1 ? 's' : ''}
          </span>
        )}

        {/* Status */}
        <StatusPill status={provider.status || provider.health} />

        {/* Expand icon */}
        {hasModels && (
          <motion.div
            animate={{ rotate: isExpanded ? 180 : 0 }}
            transition={{ duration: 0.2 }}
          >
            <ChevronDownIcon className="h-4 w-4 text-gray-500" />
          </motion.div>
        )}
      </div>

      {/* Models list (expanded) */}
      <AnimatePresence>
        {isExpanded && hasModels && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="border-t border-white/5 bg-black/20"
          >
            <div className="p-3 space-y-2">
              {provider.models.map((model, idx) => (
                <div
                  key={model.id || model.name || idx}
                  className="flex items-center gap-3 px-3 py-2 rounded-lg bg-white/5"
                >
                  <CircleStackIcon className="h-4 w-4 text-gray-500 flex-shrink-0" />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-white truncate">{model.name || model.id}</p>
                    {model.context_length && (
                      <p className="text-xs text-gray-500">{model.context_length.toLocaleString()} ctx</p>
                    )}
                  </div>
                  {(model.vram || model.vram_usage) && (
                    <span className="text-xs text-gray-400 bg-gray-700/50 px-2 py-0.5 rounded">
                      {formatVRAM(model.vram || model.vram_usage)} VRAM
                    </span>
                  )}
                  {model.loaded && (
                    <span className="text-xs text-green-400 bg-green-500/20 px-2 py-0.5 rounded">
                      Loaded
                    </span>
                  )}
                </div>
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}


// ---------------------------------------------------------------- private inference in the fleet
const HEALTH_DOT = {
  healthy: 'bg-green-400',
  unhealthy: 'bg-red-400',
  starting: 'bg-amber-400',
};

const HEALTH_TEXT = {
  healthy: 'healthy',
  unhealthy: 'unhealthy',
  starting: 'starting',
  running: 'running, no health check',
  active: 'active systemd unit',
};

const NOT_COUNTED = {
  gateway: ['gateway', 'gateways'],
  proxy: ['proxy or adapter', 'proxies or adapters'],
  firewall: ['firewall unit', 'firewall units'],
  exporter: ['metrics exporter', 'metrics exporters'],
};

function notCountedLine(notCounted) {
  const parts = Object.entries(notCounted || {})
    .filter(([, count]) => count > 0)
    .map(([key, count]) => {
      const [one, many] = NOT_COUNTED[key] || [key, key];
      return plural(count, one, many);
    });
  return parts.length ? `Not counted as services: ${parts.join(', ')}.` : null;
}

function ServiceChip({ service }) {
  const health = HEALTH_TEXT[service.health] || service.health;
  const basis = service.basis === 'name' ? 'kind read from the name' : 'known model-server image';
  const title = `${service.kind}${service.engine ? `, ${service.engine}` : ''}: ${health}; ${basis}`;
  return (
    <span
      title={title}
      data-testid="fleet-inference-service"
      className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-white/5 text-gray-200 border ${
        service.basis === 'name' ? 'border-dashed border-white/25' : 'border-white/10'
      }`}
    >
      <span aria-hidden="true" className={`h-1.5 w-1.5 rounded-full ${HEALTH_DOT[service.health] || 'bg-gray-400'}`} />
      {service.name}
      {service.engine && <span className="text-gray-500">{service.engine}</span>}
      <span className="sr-only">, {health}</span>
    </span>
  );
}

function InferenceHost({ host }) {
  const groups = [];
  host.services.forEach((service) => {
    const last = groups[groups.length - 1];
    if (last && last[0] === service.kind) last[1].push(service);
    else groups.push([service.kind, [service]]);
  });
  const healthy = host.services.filter((s) => s.health === 'healthy').length;
  const unhealthy = host.services.filter((s) => s.health === 'unhealthy').length;
  return (
    <li
      className={`rounded-xl border px-3 py-2 ${host.stale ? 'border-amber-500/40 bg-amber-500/5' : 'border-white/10 bg-white/5'}`}
      data-testid="fleet-inference-host"
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-semibold text-white">{host.name}</span>
        <span className="text-xs px-2 py-0.5 rounded-full bg-emerald-500/15 text-emerald-300">{host.inference_label}</span>
        {host.stale && (
          <span className="text-xs px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-300">Stale</span>
        )}
        {host.gpus !== null && host.gpus !== undefined && (
          <span className="text-xs text-gray-400">{host.gpus === 0 ? 'no GPU' : plural(host.gpus, 'GPU')}</span>
        )}
        <span className="ml-auto text-xs text-gray-400" title={absoluteTime(host.last_seen)}>
          Seen {ago(host.age_seconds)}
        </span>
      </div>
      <p className="mt-0.5 text-xs text-gray-500">
        {plural(host.services.length, 'service')}
        {healthy > 0 && `, ${healthy} healthy`}
        {unhealthy > 0 && <span className="text-red-300">, {unhealthy} unhealthy</span>}
      </p>
      <dl className="mt-1 space-y-1">
        {groups.map(([kind, services]) => (
          <div key={kind} className="flex gap-2 text-xs">
            <dt className="w-28 shrink-0 pt-0.5 text-gray-400">{kind}</dt>
            <dd className="flex flex-wrap gap-1 min-w-0">
              {services.map((service) => (
                <ServiceChip key={`${service.source}:${service.name}`} service={service} />
              ))}
            </dd>
          </div>
        ))}
      </dl>
    </li>
  );
}

function FleetInference({ doc }) {
  const t = doc.totals;
  const notCounted = notCountedLine(doc.not_counted);
  if (t.services === 0) {
    return (
      <p className="text-sm text-gray-400" data-testid="fleet-inference">
        The fleet map shows no model-serving containers or units.
        {notCounted && <span className="block mt-1 text-xs text-gray-500">{notCounted}</span>}
      </p>
    );
  }
  return (
    <section data-testid="fleet-inference">
      <div className="flex flex-wrap gap-1.5 mb-3">
        {Object.entries(t.by_label).map(([label, count]) => (
          <span key={label} className="text-xs px-2 py-0.5 rounded-full bg-emerald-500/15 text-emerald-300">
            {label}: {count}
          </span>
        ))}
        {Object.entries(t.by_kind).map(([kind, count]) => (
          <span key={kind} className="text-xs px-2 py-0.5 rounded-full bg-white/10 text-gray-300">
            {kind} {count}
          </span>
        ))}
      </div>
      <ul className="space-y-2">
        {doc.hosts.map((host) => <InferenceHost key={host.id} host={host} />)}
      </ul>
      <div className="mt-3 space-y-1 text-xs text-gray-500">
        <p>
          Kinds come from a known model-server image (llama.cpp, vLLM, Ollama, Whisper, Kokoro and others) or,
          with a dashed outline, from the service name. Health is Docker&apos;s own check where the container
          has one. The snapshot does not say which model is loaded or whether it answers.
        </p>
        {notCounted && <p>{notCounted}</p>}
        <p>{snapshotLine(doc)}.</p>
      </div>
    </section>
  );
}

export default function LocalInferenceCard({
  glassStyles = {},
  className = '',
  fetchImpl,
}) {
  const fetcherRef = useRef(null);
  fetcherRef.current = fetchImpl || ((url, options) => fetch(url, options));
  const [fleet, setFleet] = useState(null);
  const [fleetError, setFleetError] = useState(null);
  const [fleetLoading, setFleetLoading] = useState(true);
  const [moduleStatus, setModuleStatus] = useState(null);
  const [providers, setProviders] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [notConfigured, setNotConfigured] = useState(false);
  const [expandedProviders, setExpandedProviders] = useState({});
  const [lastRefresh, setLastRefresh] = useState(null);

  // The fleet's private inference, from the fleet map snapshot.
  const fetchFleet = useCallback(async () => {
    const { data, error: fleetFetchError } = await fetchFleetSummary(fetcherRef.current, FLEET_INFERENCE_ENDPOINT);
    if (data) {
      setFleet(data);
      setFleetError(null);
    } else {
      setFleetError(fleetFetchError);
    }
    setFleetLoading(false);
  }, []);

  // Providers managed by this server (the Ops-Center local inference module).
  const fetchData = useCallback(async () => {
    try {
      setError(null);

      // Fetch module status and providers in parallel
      const [statusRes, providersRes] = await Promise.allSettled([
        fetcherRef.current('/api/v1/local-inference/status', { credentials: 'include' }),
        fetcherRef.current('/api/v1/local-inference/providers', { credentials: 'include' })
      ]);

      // Handle status response
      if (statusRes.status === 'fulfilled') {
        if (statusRes.value.ok) {
          const statusData = await statusRes.value.json();
          setModuleStatus(statusData);
          setNotConfigured(false);
        } else if (statusRes.value.status === 404) {
          setNotConfigured(true);
          setModuleStatus(null);
        } else {
          // Non-404 error - module exists but returned error
          setNotConfigured(true);
        }
      } else {
        // Network error or module not available
        setNotConfigured(true);
      }

      // Handle providers response
      if (providersRes.status === 'fulfilled' && providersRes.value.ok) {
        const providersData = await providersRes.value.json();
        setProviders(Array.isArray(providersData) ? providersData : providersData.providers || []);
      } else {
        setProviders([]);
      }

      setLastRefresh(new Date());
    } catch (err) {
      console.error('Error fetching local inference data:', err);
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, []);

  // Providers every 30 seconds as before; the fleet snapshot once a minute.
  useEffect(() => {
    fetchFleet();
    fetchData();
    const providerInterval = setInterval(fetchData, 30000);
    const fleetInterval = setInterval(fetchFleet, FLEET_REFRESH_MS);
    return () => {
      clearInterval(providerInterval);
      clearInterval(fleetInterval);
    };
  }, [fetchFleet, fetchData]);

  const refreshAll = () => {
    fetchFleet();
    fetchData();
  };

  // Toggle provider expansion
  const toggleProvider = (providerId) => {
    setExpandedProviders(prev => ({
      ...prev,
      [providerId]: !prev[providerId]
    }));
  };

  // Calculate stats
  const healthyCount = providers.filter(p => isProviderHealthy(p)).length;
  const totalModels = providers.reduce((sum, p) => sum + (p.models?.length || 0), 0);

  // Module enabled status
  const moduleEnabled = moduleStatus?.enabled ?? false;

  const connected = Boolean(fleet && fleet.available);
  let subtitle = '';
  if (fleetLoading) subtitle = 'Loading...';
  else if (connected) {
    subtitle = `${plural(fleet.totals.services, 'service')} on ${plural(fleet.totals.hosts, 'host')}, private`;
  } else if (fleet) subtitle = 'Fleet map not connected';
  else if (fleetError) subtitle = 'Fleet summary unavailable';

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className={`${glassStyles.card || 'backdrop-blur-xl bg-white/10 border border-white/20'} rounded-2xl p-6 shadow-xl ${className}`}
    >
      {/* Header */}
      <div className="flex items-center justify-between mb-5 gap-3">
        <div className="flex items-center gap-3 min-w-0">
          <div className="w-10 h-10 bg-gradient-to-br from-indigo-500 to-purple-500 rounded-xl flex items-center justify-center shadow-lg">
            <ServerStackIcon className="h-5 w-5 text-white" />
          </div>
          <div className="min-w-0">
            <h3 className="text-lg font-bold text-white">Local Inference</h3>
            <p className="text-sm text-gray-400 truncate" data-testid="inference-card-subtitle">{subtitle}</p>
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {fleet && fleet.state === 'stale' && (
            <span className="text-xs px-2 py-1 rounded-full bg-amber-500/20 text-amber-300">Stale</span>
          )}
          <button
            onClick={refreshAll}
            disabled={loading || fleetLoading}
            className="p-2 rounded-lg bg-white/5 hover:bg-white/10 transition-colors disabled:opacity-50"
            title="Refresh"
            aria-label="Refresh local inference"
          >
            <ArrowPathIcon className={`h-4 w-4 text-gray-400 ${loading || fleetLoading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {/* Private inference in the fleet */}
      {fleetLoading && <div className="h-24 bg-gray-700/30 rounded-lg animate-pulse" />}
      {!fleetLoading && fleetError && (
        <p className="mb-3 text-xs text-amber-300" data-testid="fleet-error">{fleetError}</p>
      )}
      {!fleetLoading && fleet && !connected && (
        <div className="rounded-xl border border-white/10 bg-white/5 p-4" data-testid="fleet-not-connected">
          <p className="text-sm font-medium text-white">Fleet map not connected</p>
          {notConnectedLines(fleet).map((line) => (
            <p key={line} className="mt-1 text-xs text-gray-400">{line}</p>
          ))}
        </div>
      )}
      {!fleetLoading && connected && <FleetInference doc={fleet} />}
      {!fleetLoading && (
        <Link
          to={FLEET_MAP_PAGE}
          className="mt-3 inline-flex items-center gap-1.5 text-xs text-blue-400 hover:text-blue-300"
        >
          <MapIcon className="h-3.5 w-3.5" />
          Open the fleet map
        </Link>
      )}

      {/* Providers managed by this server */}
      <section className="mt-5 pt-4 border-t border-white/10" data-testid="managed-providers">
        <div className="flex items-center justify-between gap-2 mb-3">
          <div className="min-w-0">
            <p className="text-sm font-semibold text-white">Providers managed by this server</p>
            {!loading && !notConfigured && providers.length > 0 && (
              <p className="text-xs text-gray-400">
                {plural(providers.length, 'provider')}
                {healthyCount > 0 && <span className="text-green-400 ml-1">({healthyCount} healthy)</span>}
                {totalModels > 0 && <span className="text-gray-500 ml-1">, {plural(totalModels, 'model')}</span>}
              </p>
            )}
          </div>
          {!notConfigured && moduleStatus && (
            <span className={`text-xs px-2 py-1 rounded-full shrink-0 ${moduleEnabled ? 'bg-green-500/20 text-green-400' : 'bg-gray-500/20 text-gray-400'}`}>
              {moduleEnabled ? 'Module on' : 'Module off'}
            </span>
          )}
        </div>

        {/* Loading State */}
        {loading && providers.length === 0 && !notConfigured && (
          <div className="h-12 bg-gray-700/30 rounded-lg animate-pulse" />
        )}

        {/* Not Configured State */}
        {!loading && notConfigured && (
          <div className="flex items-center gap-2 text-xs text-gray-500">
            <CpuChipIcon className="h-4 w-4 shrink-0 text-gray-600" />
            <span>Provider management is not available on this server.</span>
          </div>
        )}

        {/* Error State */}
        {!loading && error && !notConfigured && (
          <div className="text-xs">
            <span className="text-red-400">{error}</span>
            <button onClick={fetchData} className="ml-2 text-blue-400 hover:text-blue-300">
              Try again
            </button>
          </div>
        )}

        {/* Empty State (no providers registered) */}
        {!loading && !error && !notConfigured && providers.length === 0 && (
          <p className="text-xs text-gray-500">
            No providers are registered here. Ollama, vLLM or llama.cpp endpoints added to Ops-Center appear in this list.
          </p>
        )}

        {/* Providers List */}
        {!loading && !error && !notConfigured && providers.length > 0 && (
          <div className="space-y-2">
            <AnimatePresence>
              {providers.map((provider, index) => {
                const providerId = provider.id || provider.name || provider.type || `provider-${index}`;
                return (
                  <motion.div
                    key={providerId}
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -10 }}
                    transition={{ delay: index * 0.05 }}
                  >
                    <ProviderRow
                      provider={provider}
                      isExpanded={expandedProviders[providerId]}
                      onToggle={() => toggleProvider(providerId)}
                    />
                  </motion.div>
                );
              })}
            </AnimatePresence>
          </div>
        )}

        {/* Last refresh timestamp */}
        {lastRefresh && !notConfigured && (
          <p className="text-xs text-gray-600 mt-3">
            Providers checked {lastRefresh.toLocaleTimeString()}
          </p>
        )}
      </section>
    </motion.div>
  );
}
