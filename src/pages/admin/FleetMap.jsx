/**
 * Fleet Map — live topology of every host, container, route and link in the
 * fleet, as collected by ~/Projects/fleet-map (collect.sh -> build.py) on
 * bigboy every 5 minutes and pushed to POST /api/v1/fleet/ingest.
 *
 * The map itself is the self-contained D3/three.js viewer vendored at
 * public/fleet-map/ (served at /api/v1/fleet/viewer/index.html); it loads its data from
 * GET /api/v1/fleet/map.js with the admin session cookie. This page is the
 * console frame around it: freshness, counts, refresh, full-screen.
 */

import React, { useState, useEffect, useCallback } from 'react';
import { Box, Button, Chip, Alert, AlertTitle, CircularProgress, Typography, Stack, Tooltip } from '@mui/material';
import { Refresh as RefreshIcon, OpenInNew as OpenInNewIcon } from '@mui/icons-material';
import PageHeader from '../../components/admin/PageHeader';

// Served by the backend under /api/ (session-gated) because the apex path space on the
// multi-site rings belongs to the marketing site; see fleet_map_api.fleet_map_viewer.
const VIEWER_URL = '/api/v1/fleet/viewer/index.html';
const STATUS_URL = '/api/v1/fleet/status';
const POLL_MS = 60000;

function ago(seconds) {
  if (seconds == null) return 'unknown age';
  if (seconds < 60) return `${seconds}s ago`;
  const m = Math.floor(seconds / 60);
  if (m < 60) return `${m} min ago`;
  const h = Math.floor(m / 60);
  if (h < 48) return `${h} h ${m % 60} min ago`;
  return `${Math.floor(h / 24)} d ago`;
}

export default function FleetMap() {
  const [status, setStatus] = useState(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [nonce, setNonce] = useState(0);

  const fetchStatus = useCallback(async () => {
    try {
      const res = await fetch(STATUS_URL, { credentials: 'include' });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body.detail || `Request failed (${res.status})`);
      setStatus(body);
      setError('');
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchStatus();
    const t = setInterval(fetchStatus, POLL_MS);
    return () => clearInterval(t);
  }, [fetchStatus]);

  // Reload the iframe only when the collector has produced a newer snapshot
  // (or on an explicit Refresh) so the operator's zoom/selection isn't reset
  // every poll.
  const generatedAt = status?.generated_at || '';
  const handleRefresh = () => {
    fetchStatus();
    setNonce((n) => n + 1);
  };

  const counts = status?.counts || {};
  const available = !!status?.available;
  const viewerSrc = `${VIEWER_URL}?v=${encodeURIComponent(generatedAt)}&r=${nonce}`;

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', height: 'calc(100vh - 120px)', minHeight: 560 }}>
      <PageHeader
        title="Fleet Map"
        subtitle="Where everything runs — every host, container, route and link, collected live over ssh"
        actions={
          <>
            <Button startIcon={<RefreshIcon />} onClick={handleRefresh} variant="outlined" size="small">
              Refresh
            </Button>
            <Button
              startIcon={<OpenInNewIcon />}
              variant="outlined"
              size="small"
              component="a"
              href={VIEWER_URL}
              target="_blank"
              rel="noopener"
              disabled={!available}
            >
              Full screen
            </Button>
          </>
        }
      />

      {loading ? (
        <Box sx={{ display: 'flex', justifyContent: 'center', mt: 8 }}>
          <CircularProgress />
        </Box>
      ) : error ? (
        <Alert severity="error" sx={{ mb: 2 }}>
          <AlertTitle>Fleet map unavailable</AlertTitle>
          {error}
        </Alert>
      ) : !available ? (
        <Alert severity="info" sx={{ mb: 2 }}>
          <AlertTitle>No topology ingested on this node yet</AlertTitle>
          The bigboy collector (<code>panel-fleet-push.timer</code>, every 5 min) posts <code>data.js</code> to{' '}
          <code>POST {status?.ingest_endpoint}</code> with the <code>FLEET_MAP_INGEST_TOKEN</code> bearer.{' '}
          {status?.ingest_configured
            ? 'The ingest token is configured here; waiting for the first push.'
            : 'The ingest token is NOT configured on this node (FLEET_MAP_INGEST_TOKEN env or backend/data/fleet_map_ingest.token), so pushes are refused with 503.'}
        </Alert>
      ) : (
        <>
          <Stack direction="row" spacing={1} sx={{ mb: 1.5, flexWrap: 'wrap', rowGap: 1 }} alignItems="center">
            <Tooltip title={`generatedAt ${generatedAt}${status.received_at ? ` · received ${status.received_at}` : ''}`}>
              <Chip
                size="small"
                color={status.stale ? 'warning' : 'success'}
                variant="outlined"
                label={`Collected ${ago(status.age_seconds)}${status.stale ? ' · STALE' : ''}`}
              />
            </Tooltip>
            <Chip size="small" variant="outlined" label={`${counts.hosts ?? 0} hosts`} />
            <Chip size="small" variant="outlined" label={`${counts.containers ?? 0} containers`} />
            <Chip size="small" variant="outlined" label={`${counts.routes ?? 0} routes`} />
            <Chip size="small" variant="outlined" label={`${counts.links ?? 0} links`} />
            <Chip size="small" variant="outlined" label={`${counts.sites ?? 0} sites`} />
            {status.source && <Chip size="small" variant="outlined" label={`source: ${status.source}`} />}
            <Typography variant="caption" color="text.secondary" sx={{ ml: 'auto' }}>
              Privacy toggle inside the map hides IPs, ports and client names for screen sharing.
            </Typography>
          </Stack>
          {status.stale && (
            <Alert severity="warning" sx={{ mb: 1.5 }}>
              Snapshot is older than {Math.round((status.stale_after_seconds || 0) / 60)} minutes — check{' '}
              <code>panel-fleet-push.timer</code> on bigboy (<code>journalctl -u panel-fleet-push.service</code>).
            </Alert>
          )}
          <Box
            sx={{
              flex: 1,
              minHeight: 0,
              border: 1,
              borderColor: 'divider',
              borderRadius: 2,
              overflow: 'hidden',
              bgcolor: '#0b1020'
            }}
          >
            <iframe
              key={viewerSrc}
              title="Fleet map"
              src={viewerSrc}
              style={{ border: 0, width: '100%', height: '100%', display: 'block' }}
            />
          </Box>
        </>
      )}
    </Box>
  );
}
