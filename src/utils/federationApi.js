export async function fetchFederationJson(url, options = {}) {
  const headers = new Headers(options.headers || {});
  const token = localStorage.getItem('authToken');

  if (token && !headers.has('Authorization')) {
    headers.set('Authorization', `Bearer ${token}`);
  }

  const response = await fetch(url, {
    credentials: 'include',
    ...options,
    headers,
  });

  const contentType = response.headers.get('content-type') || '';
  const payload = contentType.includes('application/json')
    ? await response.json()
    : await response.text();

  if (!response.ok) {
    const message = typeof payload === 'string'
      ? payload
      : payload?.detail || payload?.message || payload?.error;
    throw new Error(message || `Request failed (${response.status})`);
  }

  return payload;
}

export function federationTimeAgo(value) {
  if (!value) return 'Unknown';

  const seconds = Math.floor((Date.now() - new Date(value).getTime()) / 1000);
  if (seconds < 60) return `${seconds}s ago`;

  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;

  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;

  return `${Math.floor(hours / 24)}d ago`;
}

export function endpointWithPath(endpoint, path) {
  if (!endpoint) return path || '-';
  if (!path) return endpoint;

  const base = endpoint.endsWith('/') ? endpoint.slice(0, -1) : endpoint;
  const suffix = path.startsWith('/') ? path : `/${path}`;
  return `${base}${suffix}`;
}

export function getEndpointHost(endpoint, fallback = 'unknown-host') {
  try {
    return new URL(endpoint).hostname;
  } catch (_error) {
    return fallback;
  }
}
