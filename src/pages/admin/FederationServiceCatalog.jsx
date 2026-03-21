/**
 * Federation Service Catalog Page
 * Unified view of all services available across the federation,
 * grouped by service type with node branding and filtering.
 */

import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
  Box,
  Card,
  CardContent,
  Chip,
  Typography,
  Button,
  Alert,
  CircularProgress,
  Grid,
  FormControl,
  InputLabel,
  Select,
  MenuItem
} from '@mui/material';
import {
  Refresh as RefreshIcon
} from '@mui/icons-material';
import PageHeader from '../../components/admin/PageHeader';

const SERVICE_TYPES = [
  { value: 'all', label: 'All Types' },
  { value: 'llm', label: 'LLM' },
  { value: 'tts', label: 'TTS' },
  { value: 'stt', label: 'STT' },
  { value: 'embeddings', label: 'Embeddings' },
  { value: 'image_gen', label: 'Image Generation' },
  { value: 'music_gen', label: 'Music Generation' },
  { value: 'reranker', label: 'Reranker' }
];

const TYPE_COLORS = {
  llm: 'primary',
  tts: 'secondary',
  stt: 'info',
  embeddings: 'success',
  image_gen: 'warning',
  music_gen: 'secondary',
  reranker: 'default'
};

export default function FederationServiceCatalog() {
  const [services, setServices] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [filter, setFilter] = useState('all');

  const fetchServices = useCallback(async () => {
    try {
      const res = await fetch('/api/v1/federation/services', { credentials: 'include' });
      if (!res.ok) throw new Error(`Failed to load services (${res.status})`);
      const data = await res.json();
      setServices(data.services || []);
      setError('');
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchServices();
    const interval = setInterval(fetchServices, 30000);
    return () => clearInterval(interval);
  }, [fetchServices]);

  const filtered = useMemo(() => {
    if (filter === 'all') return services;
    return services.filter((svc) => svc.service_type === filter);
  }, [filter, services]);

  // Group by service type
  const grouped = useMemo(() => {
    const groups = {};
    filtered.forEach((svc) => {
      const type = svc.service_type || 'other';
      if (!groups[type]) groups[type] = [];
      groups[type].push(svc);
    });
    return groups;
  }, [filtered]);

  if (loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', mt: 8 }}>
        <CircularProgress />
      </Box>
    );
  }

  return (
    <Box>
      <PageHeader
        title="Federation Service Catalog"
        subtitle="All services available across the federation mesh"
        actions={
          <Button startIcon={<RefreshIcon />} onClick={fetchServices} variant="outlined" size="small">
            Refresh
          </Button>
        }
      />

      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}

      <Box sx={{ mb: 3 }}>
        <FormControl size="small" sx={{ minWidth: 200 }}>
          <InputLabel id="service-type-filter">Service Type</InputLabel>
          <Select
            labelId="service-type-filter"
            value={filter}
            label="Service Type"
            onChange={(e) => setFilter(e.target.value)}
          >
            {SERVICE_TYPES.map((t) => (
              <MenuItem key={t.value} value={t.value}>
                {t.label}
              </MenuItem>
            ))}
          </Select>
        </FormControl>
      </Box>

      {Object.keys(grouped).length === 0 && !error ? (
        <Alert severity="info">No services found in the federation.</Alert>
      ) : (
        Object.entries(grouped).map(([type, items]) => (
          <Box key={type} sx={{ mb: 4 }}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 2 }}>
              <Chip
                label={type.toUpperCase().replace('_', ' ')}
                color={TYPE_COLORS[type] || 'default'}
                size="small"
              />
              <Typography variant="body2" color="text.secondary">
                {items.length} provider{items.length !== 1 ? 's' : ''}
              </Typography>
            </Box>

            <Grid container spacing={2}>
              {items.map((svc, idx) => (
                <Grid item xs={12} sm={6} md={4} key={`${svc.node_id}-${svc.service_type}-${idx}`}>
                  <Card
                    sx={{
                      height: '100%',
                      borderLeft: `3px solid`,
                      borderColor: svc.status === 'online' ? 'success.main' : svc.status === 'degraded' ? 'warning.main' : 'error.main'
                    }}
                  >
                    <CardContent>
                      {/* Node info with branding */}
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
                        {svc.branding?.logo && (
                          <Box
                            component="img"
                            src={svc.branding.logo}
                            alt=""
                            sx={{ width: 20, height: 20, borderRadius: 0.5 }}
                          />
                        )}
                        <Typography variant="subtitle2" fontWeight={600}>
                          {svc.display_name || svc.node_id}
                        </Typography>
                        <Chip
                          label={svc.status || 'unknown'}
                          size="small"
                          color={svc.status === 'online' ? 'success' : svc.status === 'degraded' ? 'warning' : 'error'}
                          variant="outlined"
                          sx={{ ml: 'auto' }}
                        />
                      </Box>

                      {/* Endpoint */}
                      {svc.endpoint_url && (
                        <Typography variant="caption" color="text.secondary" sx={{ fontFamily: 'monospace', display: 'block', mb: 1 }}>
                          {svc.endpoint_url}{svc.endpoint_path || ''}
                        </Typography>
                      )}

                      {/* Models */}
                      {svc.models?.length > 0 && (
                        <Box sx={{ mb: 1 }}>
                          <Typography variant="caption" color="text.secondary" fontWeight={600}>
                            Models:
                          </Typography>
                          <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap', mt: 0.5 }}>
                            {svc.models.map((model, mIdx) => (
                              <Chip key={mIdx} label={model} size="small" variant="outlined" sx={{ fontSize: '0.7rem' }} />
                            ))}
                          </Box>
                        </Box>
                      )}

                      {/* Metrics */}
                      <Box sx={{ display: 'flex', gap: 2, flexWrap: 'wrap', mt: 1 }}>
                        {svc.avg_latency_ms != null && (
                          <Typography variant="caption" color="text.secondary">
                            Latency: {svc.avg_latency_ms}ms
                          </Typography>
                        )}
                        {svc.cold_start_seconds != null && (
                          <Typography variant="caption" color="text.secondary">
                            Cold start: {svc.cold_start_seconds}s
                          </Typography>
                        )}
                        {svc.cost_usd != null && svc.cost_usd > 0 && (
                          <Typography variant="caption" color="text.secondary">
                            Cost: ${svc.cost_usd}
                          </Typography>
                        )}
                      </Box>
                    </CardContent>
                  </Card>
                </Grid>
              ))}
            </Grid>
          </Box>
        ))
      )}
    </Box>
  );
}
