import React, { useEffect, useState } from 'react';
import {
  Box,
  Paper,
  Typography,
  Button,
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
  Select,
  MenuItem,
  FormControl,
  InputLabel,
  Alert,
  Snackbar,
  Tooltip,
  Grid,
  Card,
  CardContent,
  Tabs,
  Tab,
  Divider
} from '@mui/material';
import {
  Add as AddIcon,
  Edit as EditIcon,
  Delete as DeleteIcon,
  ContentCopy as CopyIcon,
  Campaign as CampaignIcon,
  LocalOffer as OfferIcon,
  Group as GroupIcon,
  CheckCircle as CheckCircleIcon,
  PauseCircle as PauseCircleIcon,
  PendingActions as PendingIcon,
  Cancel as CancelIcon
} from '@mui/icons-material';
import PageHeader from '../../components/admin/PageHeader';

const emptyCampaignForm = {
  slug: '',
  name: '',
  description: '',
  app_feature_keys: [],
  comp_tier_code: '',
  starts_at: '',
  ends_at: '',
  status: 'draft',
  notes: ''
};

const emptyCodeForm = {
  tier_code: '',
  max_uses: null,
  expires_in_days: null,
  notes: ''
};

const emptyGrantForm = {
  org_id: '',
  user_email: '',
  expires_at: ''
};

const CampaignsManagement = () => {
  const [campaigns, setCampaigns] = useState([]);
  const [apps, setApps] = useState([]);
  const [tiers, setTiers] = useState([]);
  const [selectedCampaign, setSelectedCampaign] = useState(null);
  const [campaignGrants, setCampaignGrants] = useState([]);
  const [campaignCodes, setCampaignCodes] = useState([]);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [campaignMode, setCampaignMode] = useState('create');
  const [campaignForm, setCampaignForm] = useState(emptyCampaignForm);
  const [codeDialogOpen, setCodeDialogOpen] = useState(false);
  const [codeForm, setCodeForm] = useState(emptyCodeForm);
  const [grantDialogOpen, setGrantDialogOpen] = useState(false);
  const [grantMode, setGrantMode] = useState('grant');
  const [grantForm, setGrantForm] = useState(emptyGrantForm);
  const [confirmDialog, setConfirmDialog] = useState({ open: false, title: '', body: '', onConfirm: null, confirmText: 'Confirm' });
  const [tab, setTab] = useState(0);
  const [snackbar, setSnackbar] = useState({ open: false, message: '', severity: 'success' });

  useEffect(() => {
    loadBootstrap();
  }, []);

  useEffect(() => {
    if (selectedCampaign) {
      loadCampaignDetail(selectedCampaign.id);
    }
  }, [selectedCampaign]);

  const showSnackbar = (message, severity = 'success') => {
    setSnackbar({ open: true, message, severity });
  };

  const loadBootstrap = async () => {
    try {
      setLoading(true);
      await Promise.all([loadCampaigns(), loadApps(), loadTiers()]);
    } finally {
      setLoading(false);
    }
  };

  const loadCampaigns = async () => {
    const response = await fetch('/api/v1/admin/campaigns', { credentials: 'include' });
    if (!response.ok) throw new Error('Failed to load campaigns');
    const data = await response.json();
    setCampaigns(data);
    if (!selectedCampaign && data.length > 0) {
      setSelectedCampaign(data[0]);
    } else if (selectedCampaign) {
      const refreshed = data.find((item) => item.id === selectedCampaign.id);
      if (refreshed) setSelectedCampaign(refreshed);
    }
  };

  const loadApps = async () => {
    const response = await fetch('/api/v1/admin/features/available', { credentials: 'include' });
    if (!response.ok) throw new Error('Failed to load app catalog');
    const data = await response.json();
    setApps(data);
  };

  const loadTiers = async () => {
    const response = await fetch('/api/v1/admin/tiers/', { credentials: 'include' });
    if (!response.ok) throw new Error('Failed to load tiers');
    const data = await response.json();
    setTiers(data);
  };

  const loadCampaignDetail = async (campaignId) => {
    try {
      setDetailLoading(true);
      const [grantsRes, codesRes, campaignRes] = await Promise.all([
        fetch(`/api/v1/admin/campaigns/${campaignId}/grants`, { credentials: 'include' }),
        fetch(`/api/v1/admin/invite-codes/?campaign_id=${campaignId}`, { credentials: 'include' }),
        fetch(`/api/v1/admin/campaigns/${campaignId}`, { credentials: 'include' })
      ]);

      if (grantsRes.ok) setCampaignGrants(await grantsRes.json());
      if (codesRes.ok) setCampaignCodes(await codesRes.json());
      if (campaignRes.ok) {
        const data = await campaignRes.json();
        setSelectedCampaign(data);
      }
    } catch (error) {
      console.error('Error loading campaign detail:', error);
      showSnackbar('Failed to load campaign detail', 'error');
    } finally {
      setDetailLoading(false);
    }
  };

  const openCreateCampaign = () => {
    setCampaignMode('create');
    setCampaignForm(emptyCampaignForm);
    setDialogOpen(true);
  };

  const openEditCampaign = (campaign) => {
    setCampaignMode('edit');
    setCampaignForm({
      slug: campaign.slug || '',
      name: campaign.name || '',
      description: campaign.description || '',
      app_feature_keys: campaign.app_feature_keys || [],
      comp_tier_code: campaign.comp_tier_code || '',
      starts_at: campaign.starts_at ? new Date(campaign.starts_at).toISOString().slice(0, 16) : '',
      ends_at: campaign.ends_at ? new Date(campaign.ends_at).toISOString().slice(0, 16) : '',
      status: campaign.status || 'draft',
      notes: campaign.notes || ''
    });
    setSelectedCampaign(campaign);
    setDialogOpen(true);
  };

  const submitCampaign = async () => {
    const payload = {
      ...campaignForm,
      slug: campaignForm.slug || undefined,
      comp_tier_code: campaignForm.comp_tier_code || undefined,
      starts_at: campaignForm.starts_at || undefined,
      ends_at: campaignForm.ends_at || undefined,
      app_feature_keys: campaignForm.app_feature_keys || []
    };

    const response = await fetch(
      campaignMode === 'create' ? '/api/v1/admin/campaigns' : `/api/v1/admin/campaigns/${selectedCampaign.id}`,
      {
        method: campaignMode === 'create' ? 'POST' : 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(payload)
      }
    );

    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.detail || 'Failed to save campaign');
    }

    const saved = await response.json();
    showSnackbar(campaignMode === 'create' ? 'Campaign created' : 'Campaign updated', 'success');
    setDialogOpen(false);
    setSelectedCampaign(saved);
    await loadCampaigns();
    await loadCampaignDetail(saved.id);
  };

  const handleDeleteCampaign = (campaign) => {
    setConfirmDialog({
      open: true,
      title: `End ${campaign.name}?`,
      body: 'This marks the campaign ended without removing historical grant records.',
      confirmText: 'End Campaign',
      onConfirm: async () => {
        const response = await fetch(`/api/v1/admin/campaigns/${campaign.id}`, {
          method: 'DELETE',
          credentials: 'include'
        });
        if (!response.ok) {
          throw new Error('Failed to end campaign');
        }
        showSnackbar('Campaign ended', 'success');
        setConfirmDialog({ open: false, title: '', body: '', onConfirm: null, confirmText: 'Confirm' });
        await loadCampaigns();
      }
    });
  };

  const handleMintCode = async () => {
    if (!selectedCampaign) return;
    const payload = {
      ...codeForm,
      campaign_id: selectedCampaign.id,
      max_uses: codeForm.max_uses === '' ? null : codeForm.max_uses,
      expires_in_days: codeForm.expires_in_days === '' ? null : codeForm.expires_in_days
    };

    const response = await fetch('/api/v1/admin/invite-codes/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(payload)
    });

    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.detail || 'Failed to mint invite code');
    }

    const data = await response.json();
    showSnackbar(`Minted code ${data.code}`, 'success');
    setCodeDialogOpen(false);
    setCodeForm(emptyCodeForm);
    await loadCampaignDetail(selectedCampaign.id);
    await loadCampaigns();
  };

  const openGrantDialog = (mode) => {
    setGrantMode(mode);
    setGrantForm(emptyGrantForm);
    setGrantDialogOpen(true);
  };

  const submitGrant = async () => {
    if (!selectedCampaign) return;
    const response = await fetch(`/api/v1/admin/campaigns/${selectedCampaign.id}/${grantMode}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({
        org_id: grantForm.org_id || undefined,
        user_email: grantForm.user_email || undefined,
        expires_at: grantForm.expires_at || undefined
      })
    });

    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.detail || `Failed to ${grantMode} campaign`);
    }

    showSnackbar(grantMode === 'grant' ? 'Campaign granted' : 'Campaign revoked', 'success');
    setGrantDialogOpen(false);
    await loadCampaignDetail(selectedCampaign.id);
    await loadCampaigns();
  };

  const handleRevokeGrant = (grant) => {
    setConfirmDialog({
      open: true,
      title: 'Revoke campaign access?',
      body: `This removes the campaign feature keys from ${grant.org_display_name || grant.org_name || grant.org_id}.`,
      confirmText: 'Revoke',
      onConfirm: async () => {
        const response = await fetch(`/api/v1/admin/campaigns/${selectedCampaign.id}/revoke`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({
            org_id: grant.org_id,
            user_email: grant.user_email || undefined
          })
        });
        if (!response.ok) {
          throw new Error('Failed to revoke campaign');
        }
        showSnackbar('Campaign revoked', 'success');
        setConfirmDialog({ open: false, title: '', body: '', onConfirm: null, confirmText: 'Confirm' });
        await loadCampaignDetail(selectedCampaign.id);
        await loadCampaigns();
      }
    });
  };

  const getStatusChip = (status) => {
    if (status === 'active') return <Chip label="Active" color="success" size="small" icon={<CheckCircleIcon />} />;
    if (status === 'paused') return <Chip label="Paused" color="warning" size="small" icon={<PauseCircleIcon />} />;
    if (status === 'ended') return <Chip label="Ended" color="default" size="small" icon={<CancelIcon />} />;
    return <Chip label="Draft" color="info" size="small" icon={<PendingIcon />} />;
  };

  const formatDate = (value) => {
    if (!value) return 'Never';
    return new Date(value).toLocaleString();
  };

  const selectedApps = apps.filter((app) => (campaignForm.app_feature_keys || []).includes(app.feature_key));

  const summary = {
    total: campaigns.length,
    active: campaigns.filter((c) => c.status === 'active').length,
    paused: campaigns.filter((c) => c.status === 'paused').length,
    ended: campaigns.filter((c) => c.status === 'ended').length,
    minted: campaigns.reduce((sum, c) => sum + (c.minted_codes || 0), 0),
    redeemed: campaigns.reduce((sum, c) => sum + (c.redeemed_codes || 0), 0)
  };

  return (
    <Box sx={{ p: 3 }}>
      <PageHeader
        title="Campaigns"
        subtitle="Define promos, scope them to apps, mint codes, and review the granted cohort."
        actions={(
          <Button variant="contained" startIcon={<AddIcon />} onClick={openCreateCampaign}>
            New Campaign
          </Button>
        )}
      />

      <Grid container spacing={2} sx={{ mb: 3 }}>
        <Grid item xs={12} sm={6} md={2}>
          <Card><CardContent><Typography color="text.secondary">Campaigns</Typography><Typography variant="h4">{summary.total}</Typography></CardContent></Card>
        </Grid>
        <Grid item xs={12} sm={6} md={2}>
          <Card><CardContent><Typography color="text.secondary">Active</Typography><Typography variant="h4" color="success.main">{summary.active}</Typography></CardContent></Card>
        </Grid>
        <Grid item xs={12} sm={6} md={2}>
          <Card><CardContent><Typography color="text.secondary">Paused</Typography><Typography variant="h4" color="warning.main">{summary.paused}</Typography></CardContent></Card>
        </Grid>
        <Grid item xs={12} sm={6} md={2}>
          <Card><CardContent><Typography color="text.secondary">Ended</Typography><Typography variant="h4" color="text.secondary">{summary.ended}</Typography></CardContent></Card>
        </Grid>
        <Grid item xs={12} sm={6} md={2}>
          <Card><CardContent><Typography color="text.secondary">Codes</Typography><Typography variant="h4">{summary.minted}</Typography></CardContent></Card>
        </Grid>
        <Grid item xs={12} sm={6} md={2}>
          <Card><CardContent><Typography color="text.secondary">Redemptions</Typography><Typography variant="h4">{summary.redeemed}</Typography></CardContent></Card>
        </Grid>
      </Grid>

      <TableContainer component={Paper} sx={{ mb: 3 }}>
        <Table>
          <TableHead>
            <TableRow>
              <TableCell>Campaign</TableCell>
              <TableCell>Status</TableCell>
              <TableCell>Scope</TableCell>
              <TableCell>Window</TableCell>
              <TableCell>Codes</TableCell>
              <TableCell>Grants</TableCell>
              <TableCell align="right">Actions</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {loading ? (
              <TableRow><TableCell colSpan={7} align="center">Loading...</TableCell></TableRow>
            ) : campaigns.length === 0 ? (
              <TableRow><TableCell colSpan={7} align="center">No campaigns yet</TableCell></TableRow>
            ) : campaigns.map((campaign) => (
              <TableRow key={campaign.id} selected={selectedCampaign?.id === campaign.id}>
                <TableCell>
                  <Box>
                    <Typography fontWeight={700}>{campaign.name}</Typography>
                    <Typography variant="body2" color="text.secondary">{campaign.slug}</Typography>
                  </Box>
                </TableCell>
                <TableCell>{getStatusChip(campaign.status)}</TableCell>
                <TableCell>
                  <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap' }}>
                    {(campaign.app_names || []).slice(0, 3).map((name) => (
                      <Chip key={name} label={name} size="small" variant="outlined" />
                    ))}
                    {(campaign.app_names || []).length > 3 && (
                      <Chip label={`+${campaign.app_names.length - 3}`} size="small" />
                    )}
                  </Box>
                </TableCell>
                <TableCell>
                  <Typography variant="body2">{formatDate(campaign.starts_at)}</Typography>
                  <Typography variant="body2" color="text.secondary">{campaign.ends_at ? formatDate(campaign.ends_at) : 'Open-ended'}</Typography>
                </TableCell>
                <TableCell>
                  <Chip label={`${campaign.minted_codes || 0} / ${campaign.redeemed_codes || 0}`} size="small" icon={<OfferIcon />} />
                </TableCell>
                <TableCell>
                  <Chip label={`${campaign.active_grants || 0} active`} size="small" icon={<GroupIcon />} color="primary" />
                </TableCell>
                <TableCell align="right">
                  <Tooltip title="View">
                    <IconButton size="small" onClick={() => setSelectedCampaign(campaign)}>
                      <CampaignIcon fontSize="small" />
                    </IconButton>
                  </Tooltip>
                  <Tooltip title="Edit">
                    <IconButton size="small" onClick={() => openEditCampaign(campaign)}>
                      <EditIcon fontSize="small" />
                    </IconButton>
                  </Tooltip>
                  <Tooltip title="End">
                    <IconButton size="small" onClick={() => handleDeleteCampaign(campaign)}>
                      <DeleteIcon fontSize="small" />
                    </IconButton>
                  </Tooltip>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>

      <Paper sx={{ p: 3 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 2, mb: 2 }}>
          <Box>
            <Typography variant="h5" fontWeight={700}>
              {selectedCampaign ? selectedCampaign.name : 'Select a campaign'}
            </Typography>
            <Typography variant="body2" color="text.secondary">
              {selectedCampaign ? selectedCampaign.description || 'No description' : 'Choose a campaign to inspect the cohort and mint codes.'}
            </Typography>
          </Box>
          {selectedCampaign && (
            <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
              <Button variant="outlined" onClick={() => openGrantDialog('grant')}>Grant Comp</Button>
              <Button variant="outlined" onClick={() => setCodeDialogOpen(true)}>Mint Code</Button>
              <Button variant="outlined" onClick={() => loadCampaignDetail(selectedCampaign.id)}>Refresh</Button>
            </Box>
          )}
        </Box>

        {selectedCampaign ? (
          <>
            <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', mb: 2 }}>
              {getStatusChip(selectedCampaign.status)}
              {selectedCampaign.comp_tier_code && <Chip label={`Comp Tier: ${selectedCampaign.comp_tier_code}`} size="small" color="secondary" />}
              <Chip label={`${selectedCampaign.active_grants || 0} active grants`} size="small" />
              <Chip label={`${selectedCampaign.redeemed_codes || 0} redemptions`} size="small" />
            </Box>

            <Grid container spacing={2} sx={{ mb: 2 }}>
              <Grid item xs={12} md={5}>
                <Card>
                  <CardContent>
                    <Typography variant="overline" color="text.secondary">Scope</Typography>
                    <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', mt: 1 }}>
                      {selectedCampaign.app_names?.length ? selectedCampaign.app_names.map((name) => (
                        <Chip key={name} label={name} size="small" />
                      )) : <Typography variant="body2" color="text.secondary">No scoped apps</Typography>}
                    </Box>
                  </CardContent>
                </Card>
              </Grid>
              <Grid item xs={12} md={3}>
                <Card>
                  <CardContent>
                    <Typography variant="overline" color="text.secondary">Window</Typography>
                    <Typography variant="body2" sx={{ mt: 1 }}>{formatDate(selectedCampaign.starts_at)}</Typography>
                    <Typography variant="body2" color="text.secondary">{selectedCampaign.ends_at ? formatDate(selectedCampaign.ends_at) : 'No end date'}</Typography>
                  </CardContent>
                </Card>
              </Grid>
              <Grid item xs={12} md={4}>
                <Card>
                  <CardContent>
                    <Typography variant="overline" color="text.secondary">Attribution</Typography>
                    <Typography variant="body2" sx={{ mt: 1 }}>Codes: {selectedCampaign.minted_codes || 0}</Typography>
                    <Typography variant="body2">Redemptions: {selectedCampaign.redeemed_codes || 0}</Typography>
                    <Typography variant="body2">Active grants: {selectedCampaign.active_grants || 0}</Typography>
                  </CardContent>
                </Card>
              </Grid>
            </Grid>

            <Tabs value={tab} onChange={(_, value) => setTab(value)} sx={{ mb: 2 }}>
              <Tab label="Cohort" />
              <Tab label="Invite Codes" />
            </Tabs>

            {tab === 0 && (
              <TableContainer component={Paper} variant="outlined">
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell>Org / User</TableCell>
                      <TableCell>Source</TableCell>
                      <TableCell>Status</TableCell>
                      <TableCell>Features</TableCell>
                      <TableCell>Created</TableCell>
                      <TableCell align="right">Actions</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {detailLoading ? (
                      <TableRow><TableCell colSpan={6} align="center">Loading...</TableCell></TableRow>
                    ) : campaignGrants.length === 0 ? (
                      <TableRow><TableCell colSpan={6} align="center">No grants yet</TableCell></TableRow>
                    ) : campaignGrants.map((grant) => (
                      <TableRow key={grant.id}>
                        <TableCell>
                          <Typography fontWeight={600}>{grant.org_display_name || grant.org_name || grant.org_id}</Typography>
                          <Typography variant="body2" color="text.secondary">{grant.user_email || grant.user_id || 'Org-level grant'}</Typography>
                        </TableCell>
                        <TableCell><Chip label={grant.source} size="small" /></TableCell>
                        <TableCell>{grant.status === 'active' ? <Chip label="Active" color="success" size="small" /> : <Chip label={grant.status} size="small" />}</TableCell>
                        <TableCell>
                          <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap' }}>
                            {(grant.granted_feature_keys || []).map((key) => (
                              <Chip key={key} label={key} size="small" variant="outlined" />
                            ))}
                          </Box>
                        </TableCell>
                        <TableCell>{formatDate(grant.created_at)}</TableCell>
                        <TableCell align="right">
                          {grant.status === 'active' && (
                            <Button size="small" color="error" onClick={() => handleRevokeGrant(grant)}>
                              Revoke
                            </Button>
                          )}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </TableContainer>
            )}

            {tab === 1 && (
              <TableContainer component={Paper} variant="outlined">
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell>Code</TableCell>
                      <TableCell>Tier</TableCell>
                      <TableCell>Status</TableCell>
                      <TableCell>Uses</TableCell>
                      <TableCell>Expires</TableCell>
                      <TableCell>Notes</TableCell>
                      <TableCell align="right">Actions</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {detailLoading ? (
                      <TableRow><TableCell colSpan={7} align="center">Loading...</TableCell></TableRow>
                    ) : campaignCodes.length === 0 ? (
                      <TableRow><TableCell colSpan={7} align="center">No codes minted for this campaign</TableCell></TableRow>
                    ) : campaignCodes.map((code) => (
                      <TableRow key={code.id}>
                        <TableCell>
                          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                            <Typography variant="body2" fontFamily="monospace">{code.code}</Typography>
                            <IconButton size="small" onClick={() => navigator.clipboard.writeText(code.code)}>
                              <CopyIcon fontSize="small" />
                            </IconButton>
                          </Box>
                        </TableCell>
                        <TableCell>{code.tier_name || code.tier_code}</TableCell>
                        <TableCell>{code.is_active ? (code.is_expired ? <Chip label="Expired" size="small" color="error" /> : <Chip label="Active" size="small" color="success" />) : <Chip label="Inactive" size="small" />}</TableCell>
                        <TableCell>{code.max_uses === null ? 'Unlimited' : `${code.current_uses}/${code.max_uses}`}</TableCell>
                        <TableCell>{formatDate(code.expires_at)}</TableCell>
                        <TableCell>{code.notes || '-'}</TableCell>
                        <TableCell align="right">
                          <Button size="small" onClick={() => navigator.clipboard.writeText(code.code)}>Copy</Button>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </TableContainer>
            )}
          </>
        ) : (
          <Alert severity="info">Create or select a campaign to view the cohort and mint campaign-scoped codes.</Alert>
        )}
      </Paper>

      <Dialog open={dialogOpen} onClose={() => setDialogOpen(false)} maxWidth="md" fullWidth>
        <DialogTitle>{campaignMode === 'create' ? 'Create Campaign' : 'Edit Campaign'}</DialogTitle>
        <DialogContent>
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2, mt: 2 }}>
            <TextField label="Name" value={campaignForm.name} onChange={(e) => setCampaignForm({ ...campaignForm, name: e.target.value })} fullWidth />
            <TextField label="Slug" value={campaignForm.slug} onChange={(e) => setCampaignForm({ ...campaignForm, slug: e.target.value })} helperText="Optional. Auto-generated from name if blank." fullWidth />
            <TextField label="Description" value={campaignForm.description} onChange={(e) => setCampaignForm({ ...campaignForm, description: e.target.value })} multiline rows={3} fullWidth />
            <FormControl fullWidth>
              <InputLabel>App Scope</InputLabel>
              <Select
                multiple
                value={campaignForm.app_feature_keys}
                label="App Scope"
                onChange={(e) => setCampaignForm({ ...campaignForm, app_feature_keys: e.target.value })}
                renderValue={(selected) => selected.map((key) => apps.find((app) => app.feature_key === key)?.app_name || key).join(', ')}
              >
                {apps.map((app) => (
                  <MenuItem key={app.feature_key} value={app.feature_key}>
                    {app.app_name} ({app.feature_key})
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            <FormControl fullWidth>
              <InputLabel>Comp Tier</InputLabel>
              <Select
                value={campaignForm.comp_tier_code}
                label="Comp Tier"
                onChange={(e) => setCampaignForm({ ...campaignForm, comp_tier_code: e.target.value })}
              >
                <MenuItem value=""><em>None</em></MenuItem>
                {tiers.map((tier) => (
                  <MenuItem key={tier.tier_code} value={tier.tier_code}>{tier.tier_name} ({tier.tier_code})</MenuItem>
                ))}
              </Select>
            </FormControl>
            <TextField label="Starts At" type="datetime-local" value={campaignForm.starts_at} onChange={(e) => setCampaignForm({ ...campaignForm, starts_at: e.target.value })} InputLabelProps={{ shrink: true }} fullWidth />
            <TextField label="Ends At" type="datetime-local" value={campaignForm.ends_at} onChange={(e) => setCampaignForm({ ...campaignForm, ends_at: e.target.value })} InputLabelProps={{ shrink: true }} fullWidth />
            <FormControl fullWidth>
              <InputLabel>Status</InputLabel>
              <Select value={campaignForm.status} label="Status" onChange={(e) => setCampaignForm({ ...campaignForm, status: e.target.value })}>
                <MenuItem value="draft">Draft</MenuItem>
                <MenuItem value="active">Active</MenuItem>
                <MenuItem value="paused">Paused</MenuItem>
                <MenuItem value="ended">Ended</MenuItem>
              </Select>
            </FormControl>
            <TextField label="Notes" value={campaignForm.notes} onChange={(e) => setCampaignForm({ ...campaignForm, notes: e.target.value })} multiline rows={2} fullWidth />
            <Divider />
            <Box>
              <Typography variant="subtitle2" gutterBottom>Selected scope</Typography>
              <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
                {selectedApps.length ? selectedApps.map((app) => <Chip key={app.feature_key} label={app.app_name} size="small" />) : <Typography variant="body2" color="text.secondary">No apps selected</Typography>}
              </Box>
            </Box>
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDialogOpen(false)}>Cancel</Button>
          <Button onClick={submitCampaign} variant="contained">{campaignMode === 'create' ? 'Create' : 'Save'}</Button>
        </DialogActions>
      </Dialog>

      <Dialog open={codeDialogOpen} onClose={() => setCodeDialogOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Mint Campaign Code</DialogTitle>
        <DialogContent>
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2, mt: 2 }}>
            <Alert severity="info">The new code will carry the current campaign scope and campaign attribution.</Alert>
            <FormControl fullWidth>
              <InputLabel>Subscription Tier</InputLabel>
              <Select value={codeForm.tier_code} label="Subscription Tier" onChange={(e) => setCodeForm({ ...codeForm, tier_code: e.target.value })}>
                {tiers.map((tier) => (
                  <MenuItem key={tier.tier_code} value={tier.tier_code}>{tier.tier_name} ({tier.tier_code})</MenuItem>
                ))}
              </Select>
            </FormControl>
            <TextField label="Max Uses" type="number" value={codeForm.max_uses ?? ''} onChange={(e) => setCodeForm({ ...codeForm, max_uses: e.target.value === '' ? null : parseInt(e.target.value, 10) })} fullWidth />
            <TextField label="Expires in Days" type="number" value={codeForm.expires_in_days ?? ''} onChange={(e) => setCodeForm({ ...codeForm, expires_in_days: e.target.value === '' ? null : parseInt(e.target.value, 10) })} fullWidth />
            <TextField label="Notes" value={codeForm.notes} onChange={(e) => setCodeForm({ ...codeForm, notes: e.target.value })} multiline rows={3} fullWidth />
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setCodeDialogOpen(false)}>Cancel</Button>
          <Button onClick={handleMintCode} variant="contained">Mint Code</Button>
        </DialogActions>
      </Dialog>

      <Dialog open={grantDialogOpen} onClose={() => setGrantDialogOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>{grantMode === 'grant' ? 'Grant Campaign Comp' : 'Revoke Campaign Comp'}</DialogTitle>
        <DialogContent>
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2, mt: 2 }}>
            <Alert severity="warning">
              {grantMode === 'grant'
                ? 'This will write the campaign feature keys into org_features and record attribution.'
                : 'This will revoke only the feature keys associated with the selected campaign grant.'}
            </Alert>
            <TextField label="Org ID" value={grantForm.org_id} onChange={(e) => setGrantForm({ ...grantForm, org_id: e.target.value })} fullWidth helperText="Use org_id or user_email" />
            <TextField label="User Email" value={grantForm.user_email} onChange={(e) => setGrantForm({ ...grantForm, user_email: e.target.value })} fullWidth />
            {grantMode === 'grant' && (
              <TextField label="Expires At" type="datetime-local" value={grantForm.expires_at} onChange={(e) => setGrantForm({ ...grantForm, expires_at: e.target.value })} InputLabelProps={{ shrink: true }} fullWidth />
            )}
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setGrantDialogOpen(false)}>Cancel</Button>
          <Button
            onClick={async () => {
              try {
                await submitGrant();
              } catch (error) {
                console.error(error);
                showSnackbar(error.message, 'error');
              }
            }}
            variant="contained"
          >
            {grantMode === 'grant' ? 'Grant' : 'Revoke'}
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={confirmDialog.open} onClose={() => setConfirmDialog({ open: false, title: '', body: '', onConfirm: null, confirmText: 'Confirm' })} maxWidth="sm" fullWidth>
        <DialogTitle>{confirmDialog.title}</DialogTitle>
        <DialogContent>
          <Typography sx={{ mt: 1 }}>{confirmDialog.body}</Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setConfirmDialog({ open: false, title: '', body: '', onConfirm: null, confirmText: 'Confirm' })}>Cancel</Button>
          <Button
            color="error"
            variant="contained"
            onClick={async () => {
              try {
                if (confirmDialog.onConfirm) {
                  await confirmDialog.onConfirm();
                }
              } catch (error) {
                console.error(error);
                showSnackbar(error.message, 'error');
              }
            }}
          >
            {confirmDialog.confirmText}
          </Button>
        </DialogActions>
      </Dialog>

      <Snackbar
        open={snackbar.open}
        autoHideDuration={5000}
        onClose={() => setSnackbar({ ...snackbar, open: false })}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
      >
        <Alert severity={snackbar.severity} variant="filled" onClose={() => setSnackbar({ ...snackbar, open: false })}>
          {snackbar.message}
        </Alert>
      </Snackbar>
    </Box>
  );
};

export default CampaignsManagement;
