import React, { useEffect, useState, useCallback, useMemo } from 'react';
import {
  Box, Paper, Typography, Grid, TextField, Button, MenuItem, Chip, Alert,
  CircularProgress, Table, TableBody, TableCell, TableContainer, TableHead, TableRow,
  InputAdornment, Tooltip, Divider, Stack,
} from '@mui/material';
import {
  Save as SaveIcon, Refresh as RefreshIcon, ShieldOutlined as ShieldIcon,
  TrendingUp as MarginIcon, BoltOutlined as LocalIcon,
} from '@mui/icons-material';
import {
  ResponsiveContainer, BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip as RTooltip, Legend, Cell,
} from 'recharts';
import PageHeader from '../../components/admin/PageHeader';

const API = '/api/v1/admin/pricing/rates';
const money = (v) => (v == null ? '—' : `$${Number(v).toLocaleString(undefined, { maximumFractionDigits: v < 1 ? 4 : 2 })}`);
const PROVIDER_COLORS = {
  anthropic: '#d97757', openai: '#10a37f', deepseek: '#7c83ff', google: '#4285f4',
  mistral: '#ff7000', xai: '#9ca3af', together: '#a855f7', fireworks: '#f59e0b', local: '#22d3ee',
};

const PricingRates = () => {
  const [data, setData] = useState(null);
  const [settings, setSettings] = useState({});
  const [overrides, setOverrides] = useState({}); // "provider::model" -> markup %
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState(null);
  const [savedAt, setSavedAt] = useState(null);

  const load = useCallback(async () => {
    try {
      const r = await fetch(API, { credentials: 'include' });
      if (!r.ok) throw new Error(`Couldn't load rates (HTTP ${r.status})`);
      const d = await r.json();
      setData(d); setSettings(d.settings || {}); setOverrides({}); setErr(null);
    } catch (e) { setErr(e.message); } finally { setLoading(false); }
  }, []);
  useEffect(() => { load(); }, [load]);

  const dirty = useMemo(() => {
    if (!data) return false;
    const s0 = JSON.stringify(data.settings || {});
    return s0 !== JSON.stringify(settings) || Object.keys(overrides).length > 0;
  }, [data, settings, overrides]);

  const save = async () => {
    setSaving(true);
    try {
      const providers = {};
      Object.entries(overrides).forEach(([key, val]) => {
        const [p, m] = key.split('::');
        providers[p] = providers[p] || { models: {} };
        providers[p].models[m] = { override_markup_pct: val === '' ? null : Number(val) };
      });
      const body = { ...settings, ...(Object.keys(providers).length ? { providers } : {}) };
      const r = await fetch(API, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, credentials: 'include', body: JSON.stringify(body) });
      if (!r.ok) throw new Error(`Save failed (HTTP ${r.status})`);
      const d = await r.json();
      setData(d); setSettings(d.settings || {}); setOverrides({}); setErr(null); setSavedAt(Date.now());
    } catch (e) { setErr(e.message); } finally { setSaving(false); }
  };

  const setS = (k, v) => setSettings((s) => ({ ...s, [k]: v }));
  const setLocal = (k, v) => setSettings((s) => ({ ...s, local: { ...(s.local || {}), [k]: v } }));

  const rows = data?.rows || [];
  const chartData = useMemo(
    () => rows.filter((r) => r.provider !== 'local' && r.cost_output_per_m > 0).map((r) => ({
      name: r.model.length > 18 ? r.model.slice(0, 17) + '…' : r.model,
      provider: r.provider, cost: r.cost_output_per_m, rate: r.your_output_per_m, margin: r.margin_output_per_m,
    })),
    [rows],
  );

  if (loading) {
    return <Box sx={{ display: 'flex', justifyContent: 'center', py: 10 }}><CircularProgress /></Box>;
  }

  const creditValue = Number(settings.credit_value_usd ?? 0.01);

  return (
    <Box sx={{ p: 3 }}>
      <PageHeader
        title="Pricing & Rates"
        subtitle="Cost-plus rate book — provider cost vs your metered rate, margin, and credits. Metering bills measured cost × markup, so margin is protected even if providers change prices."
        actions={
          <Stack direction="row" spacing={1.5} alignItems="center">
            {savedAt && !dirty && <Chip size="small" color="success" variant="outlined" label="Saved" />}
            <Button variant="outlined" startIcon={<RefreshIcon />} onClick={load} disabled={saving}>Refresh</Button>
            <Button variant="contained" startIcon={saving ? <CircularProgress size={16} /> : <SaveIcon />} onClick={save} disabled={!dirty || saving}>
              Save changes
            </Button>
          </Stack>
        }
      />

      {err && <Alert severity="error" sx={{ mb: 2 }} onClose={() => setErr(null)}>{err}</Alert>}

      {/* Global settings */}
      <Paper sx={{ p: 3, mb: 3, borderRadius: '16px' }}>
        <Typography variant="h6" sx={{ fontWeight: 700, mb: 2 }}>Settings</Typography>
        <Grid container spacing={2.5}>
          <Grid item xs={12} sm={6} md={3}>
            <TextField fullWidth label="Credit value" type="number" value={settings.credit_value_usd ?? ''}
              onChange={(e) => setS('credit_value_usd', e.target.value === '' ? '' : Number(e.target.value))}
              InputProps={{ startAdornment: <InputAdornment position="start">$</InputAdornment> }}
              helperText={`1 credit = ${money(creditValue)}  ·  $1 = ${Math.round(1 / (creditValue || 0.01))} credits`} />
          </Grid>
          <Grid item xs={12} sm={6} md={3}>
            <TextField fullWidth label="Default markup" type="number" value={settings.default_markup_pct ?? ''}
              onChange={(e) => setS('default_markup_pct', e.target.value === '' ? '' : Number(e.target.value))}
              InputProps={{ endAdornment: <InputAdornment position="end">%</InputAdornment>, startAdornment: <MarginIcon sx={{ mr: 1, color: 'text.disabled', fontSize: 18 }} /> }}
              helperText="Margin on top of provider cost" />
          </Grid>
          <Grid item xs={12} sm={6} md={3}>
            <Tooltip title="Extra cushion applied on top of markup, to absorb provider price changes before the cost map catches up — your never-lose-money buffer.">
              <TextField fullWidth label="Safety buffer" type="number" value={settings.buffer_pct ?? ''}
                onChange={(e) => setS('buffer_pct', e.target.value === '' ? '' : Number(e.target.value))}
                InputProps={{ endAdornment: <InputAdornment position="end">%</InputAdornment>, startAdornment: <ShieldIcon sx={{ mr: 1, color: '#34d399', fontSize: 18 }} /> }}
                helperText="Cost-lag cushion" />
            </Tooltip>
          </Grid>
          <Grid item xs={12} sm={6} md={3}>
            <TextField select fullWidth label="Local inference" value={settings.local?.strategy ?? 'bundled'}
              onChange={(e) => setLocal('strategy', e.target.value)}
              InputProps={{ startAdornment: <LocalIcon sx={{ mr: 1, color: '#22d3ee', fontSize: 18 }} /> }}
              helperText="Your self-hosted GPU models">
              <MenuItem value="bundled">Bundled ($0, fair-use throttle)</MenuItem>
              <MenuItem value="metered">Metered (charge a rate)</MenuItem>
            </TextField>
          </Grid>
          {settings.local?.strategy === 'metered' && (
            <Grid item xs={12} sm={6} md={3}>
              <TextField fullWidth label="Local rate / 1M tokens" type="number" value={settings.local?.rate_per_million_usd ?? ''}
                onChange={(e) => setLocal('rate_per_million_usd', e.target.value === '' ? '' : Number(e.target.value))}
                InputProps={{ startAdornment: <InputAdornment position="start">$</InputAdornment> }} />
            </Grid>
          )}
        </Grid>
      </Paper>

      {/* Chart */}
      <Paper sx={{ p: 3, mb: 3, borderRadius: '16px' }}>
        <Typography variant="h6" sx={{ fontWeight: 700, mb: 0.5 }}>Cost vs. your rate — output tokens ($/1M)</Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>The gap between the bars is your margin. Hover for details.</Typography>
        {chartData.length === 0 ? (
          <Alert severity="info">No cloud models priced yet — rates seed in from the provider-research job.</Alert>
        ) : (
          <ResponsiveContainer width="100%" height={Math.max(280, chartData.length * 34)}>
            <BarChart data={chartData} layout="vertical" margin={{ left: 24, right: 24 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(160,170,210,0.12)" horizontal={false} />
              <XAxis type="number" tick={{ fill: '#9aa3c0', fontSize: 11 }} tickFormatter={(v) => `$${v}`} />
              <YAxis type="category" dataKey="name" width={130} tick={{ fill: '#c7cce0', fontSize: 11 }} />
              <RTooltip
                contentStyle={{ background: 'rgba(18,21,33,0.96)', border: '1px solid rgba(160,170,210,0.2)', borderRadius: 10, color: '#e6e8f0' }}
                formatter={(v, n) => [money(v), n === 'cost' ? 'Provider cost' : 'Your rate']} />
              <Legend formatter={(v) => (v === 'cost' ? 'Provider cost' : 'Your rate')} wrapperStyle={{ fontSize: 12 }} />
              <Bar dataKey="cost" fill="rgba(160,170,210,0.45)" radius={[0, 3, 3, 0]} />
              <Bar dataKey="rate" radius={[0, 3, 3, 0]}>
                {chartData.map((d, i) => <Cell key={i} fill={PROVIDER_COLORS[d.provider] || '#7c83ff'} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        )}
      </Paper>

      {/* Detail table */}
      <Paper sx={{ p: 0, borderRadius: '16px', overflow: 'hidden' }}>
        <Box sx={{ p: 3, pb: 1.5, display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 1 }}>
          <Typography variant="h6" sx={{ fontWeight: 700 }}>
            Rate book <Typography component="span" variant="body2" color="text.secondary">· {data?.model_count || 0} models · {data?.provider_count || 0} providers</Typography>
          </Typography>
        </Box>
        <TableContainer>
          <Table size="small" sx={{ '& td, & th': { whiteSpace: 'nowrap' } }}>
            <TableHead>
              <TableRow>
                <TableCell>Provider</TableCell>
                <TableCell>Model</TableCell>
                <TableCell align="right">Cost in/out ($/1M)</TableCell>
                <TableCell align="right">Your rate in/out</TableCell>
                <TableCell align="right">Markup</TableCell>
                <TableCell align="right">Margin (out)</TableCell>
                <TableCell align="right">Credits / 1M (in/out)</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {rows.map((r) => {
                const key = `${r.provider}::${r.model}`;
                const isLocal = r.provider === 'local';
                return (
                  <TableRow key={key} hover>
                    <TableCell>
                      <Chip size="small" label={r.provider_label}
                        sx={{ bgcolor: `${PROVIDER_COLORS[r.provider] || '#7c83ff'}22`, color: PROVIDER_COLORS[r.provider] || '#c7cce0', fontWeight: 600, border: `1px solid ${PROVIDER_COLORS[r.provider] || '#7c83ff'}44` }} />
                    </TableCell>
                    <TableCell sx={{ fontFamily: 'monospace', fontSize: 12 }}>{r.model}</TableCell>
                    <TableCell align="right">{isLocal ? <Chip size="small" label="self-hosted" variant="outlined" /> : `${money(r.cost_input_per_m)} / ${money(r.cost_output_per_m)}`}</TableCell>
                    <TableCell align="right" sx={{ fontWeight: 600 }}>{money(r.your_input_per_m)} / {money(r.your_output_per_m)}</TableCell>
                    <TableCell align="right">
                      {isLocal ? '—' : (
                        <TextField variant="standard" type="number" placeholder={`${data?.settings?.default_markup_pct ?? 20}`}
                          value={overrides[key] ?? (r.markup_pct ?? '')}
                          onChange={(e) => setOverrides((o) => ({ ...o, [key]: e.target.value }))}
                          sx={{ width: 60 }} InputProps={{ endAdornment: <Typography variant="caption" color="text.secondary">%</Typography>, disableUnderline: false }} inputProps={{ style: { textAlign: 'right' } }} />
                      )}
                    </TableCell>
                    <TableCell align="right" sx={{ color: '#34d399' }}>{isLocal ? '100%' : money(r.margin_output_per_m)}</TableCell>
                    <TableCell align="right" sx={{ color: 'text.secondary' }}>{r.credits_per_m_input} / {r.credits_per_m_output}</TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </TableContainer>
      </Paper>

      <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 2 }}>
        Edit a model's markup inline, or set global defaults above, then <strong>Save changes</strong>. Provider costs are kept current by the rate-research job and flagged if a provider raises prices.
      </Typography>
    </Box>
  );
};

export default PricingRates;
