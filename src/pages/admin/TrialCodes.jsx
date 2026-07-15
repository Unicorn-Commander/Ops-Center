/**
 * Trial Codes Management Page
 * Admin interface for creating and managing shareable trial codes that grant
 * time-limited app/feature access. Codes come in two modes:
 *   - free ($0): redeeming immediately grants the trial.
 *   - paid ($1): redeeming sends the user to a Stripe checkout first.
 *
 * Each code carries one or more feature_keys (e.g. "project_ops_access"),
 * a trial length in days, and a max redemption count. Admins can copy a
 * public redeem link (/redeem/{code}), deactivate a code, and inspect the
 * redemptions for any code.
 *
 * Backend contract (all admin-gated, same-origin, cookie auth):
 *   POST   /api/v1/admin/trial-codes                 -> created code row
 *   GET    /api/v1/admin/trial-codes                 -> array of code rows
 *   POST   /api/v1/admin/trial-codes/{id}/deactivate -> { deactivated: true }
 *   GET    /api/v1/admin/trial-codes/{id}/redemptions-> array of redemptions
 */

import React, { useState, useEffect, useCallback } from 'react';
import {
  Box,
  Paper,
  Typography,
  Button,
  Card,
  CardContent,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  IconButton,
  Chip,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  TextField,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Alert,
  Snackbar,
  CircularProgress,
  LinearProgress,
  Tooltip,
  Stack
} from '@mui/material';
import {
  Add as AddIcon,
  ContentCopy as CopyIcon,
  Link as LinkIcon,
  Block as BlockIcon,
  Refresh as RefreshIcon,
  Group as GroupIcon,
  LocalOffer as OfferIcon
} from '@mui/icons-material';
import PageHeader from '../../components/admin/PageHeader';
import AdminBreadcrumbs from '../../components/admin/AdminBreadcrumbs';

const ADMIN_BASE = '/api/v1/admin';

// Format an ISO timestamp for display
const formatDate = (dateStr) => {
  if (!dateStr) return '—';
  const date = new Date(dateStr);
  if (Number.isNaN(date.getTime())) return '—';
  return date.toLocaleString('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit'
  });
};

const modeLabel = (code) => {
  if (code.mode === 'paid') {
    const dollars = ((code.price_cents ?? 100) / 100).toFixed(2).replace(/\.00$/, '');
    return `Paid ($${dollars})`;
  }
  return 'Free ($0)';
};

const TrialCodes = () => {
  const [codes, setCodes] = useState([]);
  const [loading, setLoading] = useState(true);

  // Create dialog
  const [createOpen, setCreateOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({
    mode: 'free',
    featureKeys: ['project_ops_access'],
    featureInput: '',
    trial_days: 14,
    max_uses: 1,
    code: '',
    note: '',
    campaign: ''
  });

  // Redemptions dialog
  const [redemptionsFor, setRedemptionsFor] = useState(null); // the code row
  const [redemptions, setRedemptions] = useState([]);
  const [redemptionsLoading, setRedemptionsLoading] = useState(false);

  // Deactivate confirm
  const [deactivateTarget, setDeactivateTarget] = useState(null);
  const [deactivating, setDeactivating] = useState(false);

  // Toast
  const [toast, setToast] = useState({ open: false, message: '', severity: 'success' });
  const showToast = (message, severity = 'success') => setToast({ open: true, message, severity });

  // --- API helper (matches OrgFeatures convention) ------------------------
  const apiFetch = useCallback(async (url, options = {}) => {
    const response = await fetch(url, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...options.headers
      },
      credentials: 'include'
    });
    if (!response.ok) {
      const err = await response.json().catch(() => ({ detail: `Request failed (${response.status})` }));
      throw new Error(err.detail || `Request failed (${response.status})`);
    }
    const text = await response.text();
    return text ? JSON.parse(text) : null;
  }, []);

  // --- Load codes ---------------------------------------------------------
  const loadCodes = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiFetch(`${ADMIN_BASE}/trial-codes`);
      setCodes(Array.isArray(data) ? data : []);
    } catch (err) {
      console.error('Failed to load trial codes:', err);
      showToast(`Failed to load trial codes: ${err.message}`, 'error');
    } finally {
      setLoading(false);
    }
  }, [apiFetch]);

  useEffect(() => {
    loadCodes();
  }, [loadCodes]);

  // --- Create dialog helpers ---------------------------------------------
  const openCreate = () => {
    setForm({
      mode: 'free',
      featureKeys: ['project_ops_access'],
      featureInput: '',
      trial_days: 14,
      max_uses: 1,
      code: '',
      note: '',
      campaign: ''
    });
    setCreateOpen(true);
  };

  const addFeatureKey = () => {
    const key = form.featureInput.trim();
    if (!key) return;
    if (form.featureKeys.includes(key)) {
      setForm((f) => ({ ...f, featureInput: '' }));
      return;
    }
    setForm((f) => ({ ...f, featureKeys: [...f.featureKeys, key], featureInput: '' }));
  };

  const removeFeatureKey = (key) => {
    setForm((f) => ({ ...f, featureKeys: f.featureKeys.filter((k) => k !== key) }));
  };

  const handleCreate = async () => {
    if (form.featureKeys.length === 0) {
      showToast('Add at least one feature key.', 'warning');
      return;
    }
    setCreating(true);
    try {
      const body = {
        feature_keys: form.featureKeys,
        mode: form.mode,
        trial_days: Number(form.trial_days) || 0,
        max_uses: Number(form.max_uses) || 1
      };
      if (form.mode === 'paid') body.price_cents = 100; // $1 trial
      if (form.code.trim()) body.code = form.code.trim();
      if (form.note.trim()) body.note = form.note.trim();
      if (form.campaign.trim()) body.campaign = form.campaign.trim();

      const created = await apiFetch(`${ADMIN_BASE}/trial-codes`, {
        method: 'POST',
        body: JSON.stringify(body)
      });
      showToast(`Trial code created: ${created?.code || ''}`);
      setCreateOpen(false);
      loadCodes();
    } catch (err) {
      showToast(`Failed to create trial code: ${err.message}`, 'error');
    } finally {
      setCreating(false);
    }
  };

  // --- Copy redeem link ---------------------------------------------------
  const copyRedeemLink = (code) => {
    const link = `${window.location.origin}/redeem/${code}`;
    navigator.clipboard.writeText(link);
    showToast('Redeem link copied to clipboard');
  };

  const copyCode = (code) => {
    navigator.clipboard.writeText(code);
    showToast('Code copied to clipboard');
  };

  // --- Redemptions --------------------------------------------------------
  const openRedemptions = async (code) => {
    setRedemptionsFor(code);
    setRedemptions([]);
    setRedemptionsLoading(true);
    try {
      const data = await apiFetch(`${ADMIN_BASE}/trial-codes/${encodeURIComponent(code.id)}/redemptions`);
      setRedemptions(Array.isArray(data) ? data : []);
    } catch (err) {
      showToast(`Failed to load redemptions: ${err.message}`, 'error');
    } finally {
      setRedemptionsLoading(false);
    }
  };

  // --- Deactivate ---------------------------------------------------------
  const handleDeactivate = async () => {
    if (!deactivateTarget) return;
    setDeactivating(true);
    try {
      await apiFetch(`${ADMIN_BASE}/trial-codes/${encodeURIComponent(deactivateTarget.id)}/deactivate`, {
        method: 'POST'
      });
      showToast(`Code "${deactivateTarget.code}" deactivated`);
      setDeactivateTarget(null);
      loadCodes();
    } catch (err) {
      showToast(`Failed to deactivate code: ${err.message}`, 'error');
    } finally {
      setDeactivating(false);
    }
  };

  return (
    <Box sx={{ p: 3 }}>
      <AdminBreadcrumbs />

      <PageHeader
        title="Trial Codes"
        subtitle="Create and manage shareable trial codes that grant time-limited app access (free $0 or $1 paid)"
        actions={(
          <Stack direction="row" spacing={1}>
            <Button
              variant="outlined"
              startIcon={loading ? <CircularProgress size={16} /> : <RefreshIcon />}
              onClick={loadCodes}
              disabled={loading}
            >
              Refresh
            </Button>
            <Button variant="contained" startIcon={<AddIcon />} onClick={openCreate}>
              Create Code
            </Button>
          </Stack>
        )}
      />

      <Paper sx={{ borderRadius: 2, overflow: 'hidden', boxShadow: 2 }}>
        {loading && <LinearProgress />}
        <TableContainer>
          <Table>
            <TableHead>
              <TableRow sx={{ background: 'linear-gradient(135deg, rgba(102, 126, 234, 0.08) 0%, rgba(118, 75, 162, 0.08) 100%)' }}>
                <TableCell sx={{ fontWeight: 700 }}>Code</TableCell>
                <TableCell sx={{ fontWeight: 700 }}>Mode</TableCell>
                <TableCell sx={{ fontWeight: 700 }}>Feature Keys</TableCell>
                <TableCell align="center" sx={{ fontWeight: 700 }}>Trial Days</TableCell>
                <TableCell align="center" sx={{ fontWeight: 700 }}>Uses</TableCell>
                <TableCell align="center" sx={{ fontWeight: 700 }}>Status</TableCell>
                <TableCell sx={{ fontWeight: 700 }}>Created</TableCell>
                <TableCell align="center" sx={{ fontWeight: 700 }}>Actions</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {!loading && codes.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={8} align="center" sx={{ py: 4 }}>
                    <Typography variant="body2" color="text.secondary">
                      No trial codes yet. Create one to start sharing trial access.
                    </Typography>
                  </TableCell>
                </TableRow>
              ) : (
                codes.map((code) => (
                  <TableRow key={code.id} hover>
                    <TableCell>
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                        <Typography variant="body2" fontFamily="monospace" sx={{ fontWeight: 600 }}>
                          {code.code}
                        </Typography>
                        <Tooltip title="Copy code">
                          <IconButton size="small" onClick={() => copyCode(code.code)}>
                            <CopyIcon fontSize="small" />
                          </IconButton>
                        </Tooltip>
                        <Tooltip title="Copy redeem link">
                          <IconButton size="small" onClick={() => copyRedeemLink(code.code)}>
                            <LinkIcon fontSize="small" />
                          </IconButton>
                        </Tooltip>
                      </Box>
                    </TableCell>
                    <TableCell>
                      <Chip
                        label={modeLabel(code)}
                        size="small"
                        color={code.mode === 'paid' ? 'primary' : 'default'}
                        icon={<OfferIcon />}
                      />
                    </TableCell>
                    <TableCell>
                      <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5, maxWidth: 260 }}>
                        {(code.feature_keys || []).map((k) => (
                          <Chip key={k} label={k} size="small" variant="outlined" sx={{ fontFamily: 'monospace' }} />
                        ))}
                      </Box>
                    </TableCell>
                    <TableCell align="center">{code.trial_days}</TableCell>
                    <TableCell align="center">
                      {code.uses_count ?? 0} / {code.max_uses}
                    </TableCell>
                    <TableCell align="center">
                      <Chip
                        label={code.is_active ? 'Active' : 'Inactive'}
                        size="small"
                        color={code.is_active ? 'success' : 'default'}
                      />
                    </TableCell>
                    <TableCell>
                      <Typography variant="body2">{formatDate(code.created_at)}</Typography>
                    </TableCell>
                    <TableCell align="center">
                      <Tooltip title="View redemptions">
                        <IconButton size="small" onClick={() => openRedemptions(code)}>
                          <GroupIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                      {code.is_active && (
                        <Tooltip title="Deactivate code">
                          <IconButton size="small" color="error" onClick={() => setDeactivateTarget(code)}>
                            <BlockIcon fontSize="small" />
                          </IconButton>
                        </Tooltip>
                      )}
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </TableContainer>
      </Paper>

      {/* Create Code Dialog */}
      <Dialog open={createOpen} onClose={() => setCreateOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Create Trial Code</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <FormControl fullWidth required>
              <InputLabel>Mode</InputLabel>
              <Select
                value={form.mode}
                label="Mode"
                onChange={(e) => setForm((f) => ({ ...f, mode: e.target.value }))}
              >
                <MenuItem value="free">Free ($0)</MenuItem>
                <MenuItem value="paid">Paid ($1)</MenuItem>
              </Select>
            </FormControl>

            <Box>
              <Box sx={{ display: 'flex', gap: 1, alignItems: 'flex-start' }}>
                <TextField
                  label="Feature keys"
                  value={form.featureInput}
                  onChange={(e) => setForm((f) => ({ ...f, featureInput: e.target.value }))}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                      e.preventDefault();
                      addFeatureKey();
                    }
                  }}
                  placeholder="e.g. project_ops_access"
                  helperText="Press Enter or Add to append a feature key"
                  fullWidth
                />
                <Button variant="outlined" onClick={addFeatureKey} sx={{ mt: 1, whiteSpace: 'nowrap' }}>
                  Add
                </Button>
              </Box>
              <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5, mt: 1 }}>
                {form.featureKeys.map((k) => (
                  <Chip
                    key={k}
                    label={k}
                    size="small"
                    onDelete={() => removeFeatureKey(k)}
                    sx={{ fontFamily: 'monospace' }}
                  />
                ))}
              </Box>
            </Box>

            <Stack direction="row" spacing={2}>
              <TextField
                label="Trial days"
                type="number"
                value={form.trial_days}
                onChange={(e) => setForm((f) => ({ ...f, trial_days: e.target.value }))}
                fullWidth
              />
              <TextField
                label="Max uses"
                type="number"
                value={form.max_uses}
                onChange={(e) => setForm((f) => ({ ...f, max_uses: e.target.value }))}
                fullWidth
              />
            </Stack>

            <TextField
              label="Custom code (optional)"
              value={form.code}
              onChange={(e) => setForm((f) => ({ ...f, code: e.target.value }))}
              placeholder="Leave blank to auto-generate"
              helperText="Uppercase / memorable code, e.g. PROJECTOPS14"
              fullWidth
            />

            <TextField
              label="Campaign (optional)"
              value={form.campaign}
              onChange={(e) => setForm((f) => ({ ...f, campaign: e.target.value }))}
              placeholder="e.g. launch-2026"
              fullWidth
            />

            <TextField
              label="Note (optional)"
              value={form.note}
              onChange={(e) => setForm((f) => ({ ...f, note: e.target.value }))}
              multiline
              rows={2}
              placeholder="Admin note, e.g. 'Shared in the Project-Ops launch email'"
              fullWidth
            />
          </Stack>
        </DialogContent>
        <DialogActions sx={{ p: 3, gap: 1 }}>
          <Button onClick={() => setCreateOpen(false)}>Cancel</Button>
          <Button
            variant="contained"
            onClick={handleCreate}
            disabled={creating || form.featureKeys.length === 0}
            startIcon={creating ? <CircularProgress size={16} /> : <AddIcon />}
          >
            Create Code
          </Button>
        </DialogActions>
      </Dialog>

      {/* Redemptions Dialog */}
      <Dialog open={Boolean(redemptionsFor)} onClose={() => setRedemptionsFor(null)} maxWidth="md" fullWidth>
        <DialogTitle>
          Redemptions
          {redemptionsFor && (
            <Typography component="span" variant="body2" color="text.secondary" sx={{ ml: 1, fontFamily: 'monospace' }}>
              {redemptionsFor.code}
            </Typography>
          )}
        </DialogTitle>
        <DialogContent>
          {redemptionsLoading ? (
            <Box sx={{ py: 3 }}>
              <LinearProgress />
            </Box>
          ) : redemptions.length === 0 ? (
            <Alert severity="info" sx={{ mt: 1 }}>
              No redemptions yet for this code.
            </Alert>
          ) : (
            <TableContainer sx={{ mt: 1 }}>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell sx={{ fontWeight: 700 }}>Organization</TableCell>
                    <TableCell sx={{ fontWeight: 700 }}>User</TableCell>
                    <TableCell sx={{ fontWeight: 700 }}>Status</TableCell>
                    <TableCell sx={{ fontWeight: 700 }}>Feature Keys</TableCell>
                    <TableCell sx={{ fontWeight: 700 }}>Expires</TableCell>
                    <TableCell sx={{ fontWeight: 700 }}>Redeemed At</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {redemptions.map((r, idx) => (
                    <TableRow key={`${r.org_id || 'org'}-${idx}`} hover>
                      <TableCell>
                        <Typography variant="body2" sx={{ fontWeight: 500 }}>
                          {r.org_name || '—'}
                        </Typography>
                        {r.org_id && (
                          <Typography variant="caption" color="text.secondary" sx={{ fontFamily: 'monospace' }}>
                            {r.org_id}
                          </Typography>
                        )}
                      </TableCell>
                      <TableCell>{r.user_email || '—'}</TableCell>
                      <TableCell>
                        <Chip
                          label={r.status || '—'}
                          size="small"
                          color={r.status === 'granted' ? 'success' : r.status === 'checkout' ? 'primary' : 'default'}
                        />
                      </TableCell>
                      <TableCell>
                        <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5, maxWidth: 220 }}>
                          {(r.feature_keys || []).map((k) => (
                            <Chip key={k} label={k} size="small" variant="outlined" sx={{ fontFamily: 'monospace' }} />
                          ))}
                        </Box>
                      </TableCell>
                      <TableCell>{formatDate(r.grant_expires_at)}</TableCell>
                      <TableCell>{formatDate(r.redeemed_at)}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          )}
        </DialogContent>
        <DialogActions sx={{ p: 3 }}>
          <Button onClick={() => setRedemptionsFor(null)}>Close</Button>
        </DialogActions>
      </Dialog>

      {/* Deactivate Confirm Dialog */}
      <Dialog open={Boolean(deactivateTarget)} onClose={() => setDeactivateTarget(null)} maxWidth="xs" fullWidth>
        <DialogTitle>Deactivate Code</DialogTitle>
        <DialogContent>
          <Typography variant="body2">
            Deactivate{' '}
            <Box component="span" sx={{ fontFamily: 'monospace', fontWeight: 600 }}>
              {deactivateTarget?.code}
            </Box>
            ?
          </Typography>
          <Alert severity="warning" sx={{ mt: 2 }}>
            The code can no longer be redeemed. Existing trials already granted are not affected.
          </Alert>
        </DialogContent>
        <DialogActions sx={{ p: 3, gap: 1 }}>
          <Button onClick={() => setDeactivateTarget(null)}>Cancel</Button>
          <Button
            variant="contained"
            color="error"
            onClick={handleDeactivate}
            disabled={deactivating}
            startIcon={deactivating ? <CircularProgress size={16} /> : <BlockIcon />}
          >
            Deactivate
          </Button>
        </DialogActions>
      </Dialog>

      {/* Toast */}
      <Snackbar
        open={toast.open}
        autoHideDuration={4000}
        onClose={() => setToast({ ...toast, open: false })}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
      >
        <Alert severity={toast.severity} onClose={() => setToast({ ...toast, open: false })}>
          {toast.message}
        </Alert>
      </Snackbar>
    </Box>
  );
};

export default TrialCodes;
