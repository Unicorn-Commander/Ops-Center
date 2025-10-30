/**
 * Subscription Management Page
 * Admin interface for managing subscription tiers, features, and user migrations
 * Epic 4.4: Subscription Management GUI
 */

import React, { useState, useEffect } from 'react';
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
  TablePagination,
  IconButton,
  Chip,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  TextField,
  Switch,
  FormControlLabel,
  Tabs,
  Tab,
  Grid,
  Card,
  CardContent,
  Alert,
  Tooltip,
  Checkbox,
  Select,
  MenuItem,
  FormControl,
  InputLabel,
  Accordion,
  AccordionSummary,
  AccordionDetails,
  CircularProgress,
  Divider
} from '@mui/material';
import {
  Add as AddIcon,
  Edit as EditIcon,
  Delete as DeleteIcon,
  History as HistoryIcon,
  Check as CheckIcon,
  Close as CloseIcon,
  AttachMoney as MoneyIcon,
  People as PeopleIcon,
  TrendingUp as TrendingUpIcon,
  Sync as SyncIcon,
  ExpandMore as ExpandMoreIcon
} from '@mui/icons-material';

const SubscriptionManagement = () => {
  // State management
  const [tiers, setTiers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);

  // Pagination
  const [page, setPage] = useState(0);
  const [rowsPerPage, setRowsPerPage] = useState(10);

  // Dialog states
  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [editDialogOpen, setEditDialogOpen] = useState(false);
  const [featuresDialogOpen, setFeaturesDialogOpen] = useState(false);
  const [migrationDialogOpen, setMigrationDialogOpen] = useState(false);
  const [auditLogDialogOpen, setAuditLogDialogOpen] = useState(false);

  // Selected tier for editing
  const [selectedTier, setSelectedTier] = useState(null);

  // Form data
  const [formData, setFormData] = useState({
    tier_code: '',
    tier_name: '',
    description: '',
    price_monthly: 0,
    price_yearly: 0,
    is_active: true,
    is_invite_only: false,
    sort_order: 0,
    api_calls_limit: 1000,
    team_seats: 1,
    byok_enabled: false,
    priority_support: false,
    lago_plan_code: '',
    stripe_price_monthly: '',
    stripe_price_yearly: ''
  });

  // Features data
  const [features, setFeatures] = useState([]);
  const [featureDefinitions, setFeatureDefinitions] = useState([
    { key: 'chat_access', name: 'Open-WebUI Access', category: 'services' },
    { key: 'search_enabled', name: 'Center-Deep Search', category: 'services' },
    { key: 'tts_enabled', name: 'Text-to-Speech', category: 'services' },
    { key: 'stt_enabled', name: 'Speech-to-Text', category: 'services' },
    { key: 'billing_dashboard', name: 'Billing Dashboard', category: 'services' },
    { key: 'litellm_access', name: 'LiteLLM Gateway', category: 'services' },
    { key: 'brigade_access', name: 'Brigade Agents', category: 'services' },
    { key: 'bolt_access', name: 'Bolt.DIY', category: 'services' },
    { key: 'priority_support', name: 'Priority Support', category: 'support' },
    { key: 'dedicated_support', name: 'Dedicated Support', category: 'support' },
    { key: 'sso_enabled', name: 'SSO Integration', category: 'enterprise' },
    { key: 'audit_logs', name: 'Audit Logs', category: 'enterprise' },
    { key: 'custom_integrations', name: 'Custom Integrations', category: 'enterprise' },
    { key: 'white_label', name: 'White Label', category: 'enterprise' }
  ]);

  // Migration data
  const [migrationData, setMigrationData] = useState({
    user_id: '',
    new_tier_code: '',
    reason: '',
    send_notification: true
  });

  // Audit log data
  const [auditLog, setAuditLog] = useState([]);
  const [auditPage, setAuditPage] = useState(0);
  const [auditRowsPerPage, setAuditRowsPerPage] = useState(10);

  // Tab state
  const [tabValue, setTabValue] = useState(0);

  // ============================================
  // API Functions
  // ============================================

  const fetchTiers = async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch('/api/v1/admin/tiers');
      if (!response.ok) throw new Error('Failed to fetch tiers');
      const data = await response.json();
      setTiers(data);
    } catch (err) {
      setError(err.message);
      console.error('Error fetching tiers:', err);
    } finally {
      setLoading(false);
    }
  };

  const fetchTierFeatures = async (tierId) => {
    try {
      const response = await fetch(`/api/v1/admin/tiers/${tierId}/features`);
      if (!response.ok) throw new Error('Failed to fetch features');
      const data = await response.json();
      setFeatures(data);
    } catch (err) {
      setError(err.message);
      console.error('Error fetching features:', err);
    }
  };

  const fetchAuditLog = async () => {
    try {
      const response = await fetch('/api/v1/admin/tiers/migrations');
      if (!response.ok) throw new Error('Failed to fetch audit log');
      const data = await response.json();
      setAuditLog(data);
    } catch (err) {
      setError(err.message);
      console.error('Error fetching audit log:', err);
    }
  };

  const createTier = async () => {
    try {
      const response = await fetch('/api/v1/admin/tiers/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(formData)
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || 'Failed to create tier');
      }

      setSuccess('Tier created successfully');
      setCreateDialogOpen(false);
      fetchTiers();
      resetForm();
    } catch (err) {
      setError(err.message);
      console.error('Error creating tier:', err);
    }
  };

  const updateTier = async () => {
    if (!selectedTier) return;

    try {
      const response = await fetch(`/api/v1/admin/tiers/${selectedTier.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(formData)
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || 'Failed to update tier');
      }

      setSuccess('Tier updated successfully');
      setEditDialogOpen(false);
      fetchTiers();
      resetForm();
    } catch (err) {
      setError(err.message);
      console.error('Error updating tier:', err);
    }
  };

  const deleteTier = async (tierId, tierCode) => {
    if (!confirm(`Are you sure you want to deactivate tier '${tierCode}'? This will mark it as inactive.`)) {
      return;
    }

    try {
      const response = await fetch(`/api/v1/admin/tiers/${tierId}`, {
        method: 'DELETE'
      });

      if (!response.ok) throw new Error('Failed to delete tier');

      setSuccess('Tier deactivated successfully');
      fetchTiers();
    } catch (err) {
      setError(err.message);
      console.error('Error deleting tier:', err);
    }
  };

  const updateTierFeatures = async () => {
    if (!selectedTier) return;

    try {
      const response = await fetch(`/api/v1/admin/tiers/${selectedTier.id}/features`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ features })
      });

      if (!response.ok) throw new Error('Failed to update features');

      setSuccess('Features updated successfully');
      setFeaturesDialogOpen(false);
      fetchTiers();
    } catch (err) {
      setError(err.message);
      console.error('Error updating features:', err);
    }
  };

  const migrateUser = async () => {
    try {
      const response = await fetch(`/api/v1/admin/tiers/users/${migrationData.user_id}/migrate-tier`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(migrationData)
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || 'Failed to migrate user');
      }

      const result = await response.json();
      setSuccess(`User migrated successfully: ${result.message}`);
      setMigrationDialogOpen(false);
      resetMigrationForm();
    } catch (err) {
      setError(err.message);
      console.error('Error migrating user:', err);
    }
  };

  // ============================================
  // Form Handlers
  // ============================================

  const resetForm = () => {
    setFormData({
      tier_code: '',
      tier_name: '',
      description: '',
      price_monthly: 0,
      price_yearly: 0,
      is_active: true,
      is_invite_only: false,
      sort_order: 0,
      api_calls_limit: 1000,
      team_seats: 1,
      byok_enabled: false,
      priority_support: false,
      lago_plan_code: '',
      stripe_price_monthly: '',
      stripe_price_yearly: ''
    });
  };

  const resetMigrationForm = () => {
    setMigrationData({
      user_id: '',
      new_tier_code: '',
      reason: '',
      send_notification: true
    });
  };

  const handleEditTier = (tier) => {
    setSelectedTier(tier);
    setFormData({
      tier_code: tier.tier_code,
      tier_name: tier.tier_name,
      description: tier.description || '',
      price_monthly: tier.price_monthly,
      price_yearly: tier.price_yearly || 0,
      is_active: tier.is_active,
      is_invite_only: tier.is_invite_only,
      sort_order: tier.sort_order,
      api_calls_limit: tier.api_calls_limit,
      team_seats: tier.team_seats,
      byok_enabled: tier.byok_enabled,
      priority_support: tier.priority_support,
      lago_plan_code: tier.lago_plan_code || '',
      stripe_price_monthly: tier.stripe_price_monthly || '',
      stripe_price_yearly: tier.stripe_price_yearly || ''
    });
    setEditDialogOpen(true);
  };

  const handleManageFeatures = async (tier) => {
    setSelectedTier(tier);
    await fetchTierFeatures(tier.id);

    // Initialize features with all definitions
    const initialFeatures = featureDefinitions.map(def => {
      const existing = features.find(f => f.feature_key === def.key);
      return existing || { feature_key: def.key, feature_value: 'true', enabled: false };
    });
    setFeatures(initialFeatures);
    setFeaturesDialogOpen(true);
  };

  const toggleFeature = (featureKey) => {
    setFeatures(prev => prev.map(f =>
      f.feature_key === featureKey ? { ...f, enabled: !f.enabled } : f
    ));
  };

  // ============================================
  // Effects
  // ============================================

  useEffect(() => {
    fetchTiers();
  }, []);

  // ============================================
  // Render Helpers
  // ============================================

  const formatPrice = (price) => {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD'
    }).format(price);
  };

  const formatApiLimit = (limit) => {
    if (limit === -1) return 'Unlimited';
    return limit.toLocaleString();
  };

  // ============================================
  // Main Render
  // ============================================

  if (loading && tiers.length === 0) {
    return (
      <Box display="flex" justifyContent="center" alignItems="center" minHeight="400px">
        <CircularProgress />
      </Box>
    );
  }

  return (
    <Box sx={{ p: 3 }}>
      {/* Header */}
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
        <Typography variant="h4" component="h1">
          Subscription Management
        </Typography>
        <Box>
          <Button
            variant="outlined"
            startIcon={<HistoryIcon />}
            onClick={() => {
              fetchAuditLog();
              setAuditLogDialogOpen(true);
            }}
            sx={{ mr: 2 }}
          >
            Audit Log
          </Button>
          <Button
            variant="outlined"
            startIcon={<PeopleIcon />}
            onClick={() => setMigrationDialogOpen(true)}
            sx={{ mr: 2 }}
          >
            Migrate User
          </Button>
          <Button
            variant="contained"
            startIcon={<AddIcon />}
            onClick={() => {
              resetForm();
              setCreateDialogOpen(true);
            }}
          >
            Create Tier
          </Button>
        </Box>
      </Box>

      {/* Alerts */}
      {error && (
        <Alert severity="error" onClose={() => setError(null)} sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}
      {success && (
        <Alert severity="success" onClose={() => setSuccess(null)} sx={{ mb: 2 }}>
          {success}
        </Alert>
      )}

      {/* Analytics Cards */}
      <Grid container spacing={3} sx={{ mb: 3 }}>
        <Grid item xs={12} md={3}>
          <Card>
            <CardContent>
              <Typography color="text.secondary" gutterBottom>
                Total Tiers
              </Typography>
              <Typography variant="h4">{tiers.length}</Typography>
            </CardContent>
          </Card>
        </Grid>
        <Grid item xs={12} md={3}>
          <Card>
            <CardContent>
              <Typography color="text.secondary" gutterBottom>
                Active Tiers
              </Typography>
              <Typography variant="h4">
                {tiers.filter(t => t.is_active).length}
              </Typography>
            </CardContent>
          </Card>
        </Grid>
        <Grid item xs={12} md={3}>
          <Card>
            <CardContent>
              <Typography color="text.secondary" gutterBottom>
                Total Users
              </Typography>
              <Typography variant="h4">
                {tiers.reduce((sum, t) => sum + t.active_user_count, 0)}
              </Typography>
            </CardContent>
          </Card>
        </Grid>
        <Grid item xs={12} md={3}>
          <Card>
            <CardContent>
              <Typography color="text.secondary" gutterBottom>
                Monthly Revenue
              </Typography>
              <Typography variant="h4">
                {formatPrice(tiers.reduce((sum, t) => sum + t.monthly_revenue, 0))}
              </Typography>
            </CardContent>
          </Card>
        </Grid>
      </Grid>

      {/* Tier Table */}
      <Paper>
        <TableContainer>
          <Table>
            <TableHead>
              <TableRow>
                <TableCell>Name</TableCell>
                <TableCell>Code</TableCell>
                <TableCell align="right">Price (Monthly)</TableCell>
                <TableCell align="right">Price (Yearly)</TableCell>
                <TableCell align="center">Status</TableCell>
                <TableCell align="center">Invite Only</TableCell>
                <TableCell align="right">API Limit</TableCell>
                <TableCell align="right">Seats</TableCell>
                <TableCell align="right">Users</TableCell>
                <TableCell align="right">Revenue</TableCell>
                <TableCell align="center">Features</TableCell>
                <TableCell align="center">Actions</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {tiers
                .slice(page * rowsPerPage, page * rowsPerPage + rowsPerPage)
                .map((tier) => (
                  <TableRow key={tier.id} hover>
                    <TableCell>
                      <Typography variant="body1" fontWeight="bold">
                        {tier.tier_name}
                      </Typography>
                    </TableCell>
                    <TableCell>
                      <Chip label={tier.tier_code} size="small" />
                    </TableCell>
                    <TableCell align="right">
                      <Typography variant="body2" fontWeight="bold">
                        {formatPrice(tier.price_monthly)}
                      </Typography>
                    </TableCell>
                    <TableCell align="right">
                      {tier.price_yearly ? formatPrice(tier.price_yearly) : '-'}
                    </TableCell>
                    <TableCell align="center">
                      <Chip
                        label={tier.is_active ? 'Active' : 'Inactive'}
                        color={tier.is_active ? 'success' : 'default'}
                        size="small"
                      />
                    </TableCell>
                    <TableCell align="center">
                      {tier.is_invite_only ? (
                        <CheckIcon color="primary" />
                      ) : (
                        <CloseIcon color="disabled" />
                      )}
                    </TableCell>
                    <TableCell align="right">
                      {formatApiLimit(tier.api_calls_limit)}
                    </TableCell>
                    <TableCell align="right">{tier.team_seats}</TableCell>
                    <TableCell align="right">{tier.active_user_count}</TableCell>
                    <TableCell align="right">
                      {formatPrice(tier.monthly_revenue)}
                    </TableCell>
                    <TableCell align="center">
                      <Chip
                        label={`${tier.feature_count} features`}
                        size="small"
                        color="primary"
                        variant="outlined"
                      />
                    </TableCell>
                    <TableCell align="center">
                      <Tooltip title="Manage Features">
                        <IconButton
                          size="small"
                          onClick={() => handleManageFeatures(tier)}
                        >
                          <SyncIcon />
                        </IconButton>
                      </Tooltip>
                      <Tooltip title="Edit">
                        <IconButton
                          size="small"
                          onClick={() => handleEditTier(tier)}
                        >
                          <EditIcon />
                        </IconButton>
                      </Tooltip>
                      <Tooltip title="Deactivate">
                        <IconButton
                          size="small"
                          onClick={() => deleteTier(tier.id, tier.tier_code)}
                          disabled={!tier.is_active}
                        >
                          <DeleteIcon />
                        </IconButton>
                      </Tooltip>
                    </TableCell>
                  </TableRow>
                ))}
            </TableBody>
          </Table>
        </TableContainer>
        <TablePagination
          rowsPerPageOptions={[5, 10, 25]}
          component="div"
          count={tiers.length}
          rowsPerPage={rowsPerPage}
          page={page}
          onPageChange={(e, newPage) => setPage(newPage)}
          onRowsPerPageChange={(e) => {
            setRowsPerPage(parseInt(e.target.value, 10));
            setPage(0);
          }}
        />
      </Paper>

      {/* Create Tier Dialog */}
      <Dialog
        open={createDialogOpen}
        onClose={() => setCreateDialogOpen(false)}
        maxWidth="md"
        fullWidth
      >
        <DialogTitle>Create New Subscription Tier</DialogTitle>
        <DialogContent>
          <Grid container spacing={2} sx={{ mt: 1 }}>
            <Grid item xs={12} md={6}>
              <TextField
                fullWidth
                label="Tier Code"
                value={formData.tier_code}
                onChange={(e) => setFormData({ ...formData, tier_code: e.target.value.toLowerCase() })}
                helperText="Lowercase, no spaces (e.g., 'vip_founder')"
                required
              />
            </Grid>
            <Grid item xs={12} md={6}>
              <TextField
                fullWidth
                label="Tier Name"
                value={formData.tier_name}
                onChange={(e) => setFormData({ ...formData, tier_name: e.target.value })}
                required
              />
            </Grid>
            <Grid item xs={12}>
              <TextField
                fullWidth
                label="Description"
                value={formData.description}
                onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                multiline
                rows={2}
              />
            </Grid>
            <Grid item xs={12} md={6}>
              <TextField
                fullWidth
                label="Monthly Price ($)"
                type="number"
                value={formData.price_monthly}
                onChange={(e) => setFormData({ ...formData, price_monthly: parseFloat(e.target.value) })}
                required
              />
            </Grid>
            <Grid item xs={12} md={6}>
              <TextField
                fullWidth
                label="Yearly Price ($)"
                type="number"
                value={formData.price_yearly}
                onChange={(e) => setFormData({ ...formData, price_yearly: parseFloat(e.target.value) })}
              />
            </Grid>
            <Grid item xs={12} md={4}>
              <TextField
                fullWidth
                label="API Calls Limit"
                type="number"
                value={formData.api_calls_limit}
                onChange={(e) => setFormData({ ...formData, api_calls_limit: parseInt(e.target.value) })}
                helperText="-1 for unlimited"
                required
              />
            </Grid>
            <Grid item xs={12} md={4}>
              <TextField
                fullWidth
                label="Team Seats"
                type="number"
                value={formData.team_seats}
                onChange={(e) => setFormData({ ...formData, team_seats: parseInt(e.target.value) })}
                required
              />
            </Grid>
            <Grid item xs={12} md={4}>
              <TextField
                fullWidth
                label="Sort Order"
                type="number"
                value={formData.sort_order}
                onChange={(e) => setFormData({ ...formData, sort_order: parseInt(e.target.value) })}
              />
            </Grid>
            <Grid item xs={12} md={6}>
              <TextField
                fullWidth
                label="Lago Plan Code"
                value={formData.lago_plan_code}
                onChange={(e) => setFormData({ ...formData, lago_plan_code: e.target.value })}
                helperText="For Lago integration"
              />
            </Grid>
            <Grid item xs={12} md={6}>
              <TextField
                fullWidth
                label="Stripe Price ID (Monthly)"
                value={formData.stripe_price_monthly}
                onChange={(e) => setFormData({ ...formData, stripe_price_monthly: e.target.value })}
              />
            </Grid>
            <Grid item xs={12}>
              <Divider sx={{ my: 2 }} />
            </Grid>
            <Grid item xs={12} md={3}>
              <FormControlLabel
                control={
                  <Switch
                    checked={formData.is_active}
                    onChange={(e) => setFormData({ ...formData, is_active: e.target.checked })}
                  />
                }
                label="Active"
              />
            </Grid>
            <Grid item xs={12} md={3}>
              <FormControlLabel
                control={
                  <Switch
                    checked={formData.is_invite_only}
                    onChange={(e) => setFormData({ ...formData, is_invite_only: e.target.checked })}
                  />
                }
                label="Invite Only"
              />
            </Grid>
            <Grid item xs={12} md={3}>
              <FormControlLabel
                control={
                  <Switch
                    checked={formData.byok_enabled}
                    onChange={(e) => setFormData({ ...formData, byok_enabled: e.target.checked })}
                  />
                }
                label="BYOK"
              />
            </Grid>
            <Grid item xs={12} md={3}>
              <FormControlLabel
                control={
                  <Switch
                    checked={formData.priority_support}
                    onChange={(e) => setFormData({ ...formData, priority_support: e.target.checked })}
                  />
                }
                label="Priority Support"
              />
            </Grid>
          </Grid>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setCreateDialogOpen(false)}>Cancel</Button>
          <Button onClick={createTier} variant="contained">
            Create Tier
          </Button>
        </DialogActions>
      </Dialog>

      {/* Edit Tier Dialog (similar to Create) */}
      <Dialog
        open={editDialogOpen}
        onClose={() => setEditDialogOpen(false)}
        maxWidth="md"
        fullWidth
      >
        <DialogTitle>Edit Subscription Tier</DialogTitle>
        <DialogContent>
          <Grid container spacing={2} sx={{ mt: 1 }}>
            <Grid item xs={12} md={6}>
              <TextField
                fullWidth
                label="Tier Code"
                value={formData.tier_code}
                disabled
                helperText="Cannot change tier code"
              />
            </Grid>
            <Grid item xs={12} md={6}>
              <TextField
                fullWidth
                label="Tier Name"
                value={formData.tier_name}
                onChange={(e) => setFormData({ ...formData, tier_name: e.target.value })}
                required
              />
            </Grid>
            <Grid item xs={12}>
              <TextField
                fullWidth
                label="Description"
                value={formData.description}
                onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                multiline
                rows={2}
              />
            </Grid>
            <Grid item xs={12} md={6}>
              <TextField
                fullWidth
                label="Monthly Price ($)"
                type="number"
                value={formData.price_monthly}
                onChange={(e) => setFormData({ ...formData, price_monthly: parseFloat(e.target.value) })}
                required
              />
            </Grid>
            <Grid item xs={12} md={6}>
              <TextField
                fullWidth
                label="Yearly Price ($)"
                type="number"
                value={formData.price_yearly}
                onChange={(e) => setFormData({ ...formData, price_yearly: parseFloat(e.target.value) })}
              />
            </Grid>
            <Grid item xs={12} md={4}>
              <TextField
                fullWidth
                label="API Calls Limit"
                type="number"
                value={formData.api_calls_limit}
                onChange={(e) => setFormData({ ...formData, api_calls_limit: parseInt(e.target.value) })}
                helperText="-1 for unlimited"
                required
              />
            </Grid>
            <Grid item xs={12} md={4}>
              <TextField
                fullWidth
                label="Team Seats"
                type="number"
                value={formData.team_seats}
                onChange={(e) => setFormData({ ...formData, team_seats: parseInt(e.target.value) })}
                required
              />
            </Grid>
            <Grid item xs={12} md={4}>
              <TextField
                fullWidth
                label="Sort Order"
                type="number"
                value={formData.sort_order}
                onChange={(e) => setFormData({ ...formData, sort_order: parseInt(e.target.value) })}
              />
            </Grid>
            <Grid item xs={12}>
              <Divider sx={{ my: 2 }} />
            </Grid>
            <Grid item xs={12} md={3}>
              <FormControlLabel
                control={
                  <Switch
                    checked={formData.is_active}
                    onChange={(e) => setFormData({ ...formData, is_active: e.target.checked })}
                  />
                }
                label="Active"
              />
            </Grid>
            <Grid item xs={12} md={3}>
              <FormControlLabel
                control={
                  <Switch
                    checked={formData.is_invite_only}
                    onChange={(e) => setFormData({ ...formData, is_invite_only: e.target.checked })}
                  />
                }
                label="Invite Only"
              />
            </Grid>
            <Grid item xs={12} md={3}>
              <FormControlLabel
                control={
                  <Switch
                    checked={formData.byok_enabled}
                    onChange={(e) => setFormData({ ...formData, byok_enabled: e.target.checked })}
                  />
                }
                label="BYOK"
              />
            </Grid>
            <Grid item xs={12} md={3}>
              <FormControlLabel
                control={
                  <Switch
                    checked={formData.priority_support}
                    onChange={(e) => setFormData({ ...formData, priority_support: e.target.checked })}
                  />
                }
                label="Priority Support"
              />
            </Grid>
          </Grid>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setEditDialogOpen(false)}>Cancel</Button>
          <Button onClick={updateTier} variant="contained">
            Save Changes
          </Button>
        </DialogActions>
      </Dialog>

      {/* Features Dialog */}
      <Dialog
        open={featuresDialogOpen}
        onClose={() => setFeaturesDialogOpen(false)}
        maxWidth="md"
        fullWidth
      >
        <DialogTitle>
          Manage Features: {selectedTier?.tier_name}
        </DialogTitle>
        <DialogContent>
          <Box sx={{ mt: 2 }}>
            {['services', 'support', 'enterprise'].map(category => (
              <Accordion key={category} defaultExpanded={category === 'services'}>
                <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                  <Typography variant="h6" textTransform="capitalize">
                    {category}
                  </Typography>
                </AccordionSummary>
                <AccordionDetails>
                  <Grid container spacing={2}>
                    {featureDefinitions
                      .filter(def => def.category === category)
                      .map(def => {
                        const feature = features.find(f => f.feature_key === def.key);
                        return (
                          <Grid item xs={12} md={6} key={def.key}>
                            <FormControlLabel
                              control={
                                <Checkbox
                                  checked={feature?.enabled || false}
                                  onChange={() => toggleFeature(def.key)}
                                />
                              }
                              label={def.name}
                            />
                          </Grid>
                        );
                      })}
                  </Grid>
                </AccordionDetails>
              </Accordion>
            ))}
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setFeaturesDialogOpen(false)}>Cancel</Button>
          <Button onClick={updateTierFeatures} variant="contained">
            Save Features
          </Button>
        </DialogActions>
      </Dialog>

      {/* User Migration Dialog */}
      <Dialog
        open={migrationDialogOpen}
        onClose={() => setMigrationDialogOpen(false)}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle>Migrate User Tier</DialogTitle>
        <DialogContent>
          <Grid container spacing={2} sx={{ mt: 1 }}>
            <Grid item xs={12}>
              <TextField
                fullWidth
                label="User ID or Email"
                value={migrationData.user_id}
                onChange={(e) => setMigrationData({ ...migrationData, user_id: e.target.value })}
                helperText="Keycloak user ID or email address"
                required
              />
            </Grid>
            <Grid item xs={12}>
              <FormControl fullWidth required>
                <InputLabel>New Tier</InputLabel>
                <Select
                  value={migrationData.new_tier_code}
                  onChange={(e) => setMigrationData({ ...migrationData, new_tier_code: e.target.value })}
                  label="New Tier"
                >
                  {tiers
                    .filter(t => t.is_active)
                    .map(tier => (
                      <MenuItem key={tier.tier_code} value={tier.tier_code}>
                        {tier.tier_name} - {formatPrice(tier.price_monthly)}/mo
                      </MenuItem>
                    ))}
                </Select>
              </FormControl>
            </Grid>
            <Grid item xs={12}>
              <TextField
                fullWidth
                label="Reason for Change"
                value={migrationData.reason}
                onChange={(e) => setMigrationData({ ...migrationData, reason: e.target.value })}
                multiline
                rows={3}
                helperText="Minimum 10 characters required"
                required
              />
            </Grid>
            <Grid item xs={12}>
              <FormControlLabel
                control={
                  <Checkbox
                    checked={migrationData.send_notification}
                    onChange={(e) => setMigrationData({ ...migrationData, send_notification: e.target.checked })}
                  />
                }
                label="Send email notification to user"
              />
            </Grid>
          </Grid>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setMigrationDialogOpen(false)}>Cancel</Button>
          <Button
            onClick={migrateUser}
            variant="contained"
            disabled={!migrationData.user_id || !migrationData.new_tier_code || migrationData.reason.length < 10}
          >
            Migrate User
          </Button>
        </DialogActions>
      </Dialog>

      {/* Audit Log Dialog */}
      <Dialog
        open={auditLogDialogOpen}
        onClose={() => setAuditLogDialogOpen(false)}
        maxWidth="lg"
        fullWidth
      >
        <DialogTitle>Tier Migration Audit Log</DialogTitle>
        <DialogContent>
          <TableContainer>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Timestamp</TableCell>
                  <TableCell>User Email</TableCell>
                  <TableCell>Old Tier</TableCell>
                  <TableCell>New Tier</TableCell>
                  <TableCell>Reason</TableCell>
                  <TableCell>Changed By</TableCell>
                  <TableCell align="right">API Limit Change</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {auditLog
                  .slice(auditPage * auditRowsPerPage, auditPage * auditRowsPerPage + auditRowsPerPage)
                  .map((entry) => (
                    <TableRow key={entry.id}>
                      <TableCell>
                        {new Date(entry.change_timestamp).toLocaleString()}
                      </TableCell>
                      <TableCell>{entry.user_email || '-'}</TableCell>
                      <TableCell>
                        <Chip label={entry.old_tier_code || 'none'} size="small" />
                      </TableCell>
                      <TableCell>
                        <Chip label={entry.new_tier_code} size="small" color="primary" />
                      </TableCell>
                      <TableCell>
                        <Tooltip title={entry.change_reason}>
                          <Typography variant="body2" noWrap sx={{ maxWidth: 200 }}>
                            {entry.change_reason}
                          </Typography>
                        </Tooltip>
                      </TableCell>
                      <TableCell>{entry.changed_by}</TableCell>
                      <TableCell align="right">
                        {entry.old_api_limit !== null && entry.new_api_limit !== null ? (
                          <Chip
                            label={`${formatApiLimit(entry.old_api_limit)} → ${formatApiLimit(entry.new_api_limit)}`}
                            size="small"
                            color={entry.new_api_limit > entry.old_api_limit ? 'success' : 'warning'}
                          />
                        ) : '-'}
                      </TableCell>
                    </TableRow>
                  ))}
              </TableBody>
            </Table>
          </TableContainer>
          <TablePagination
            rowsPerPageOptions={[5, 10, 25]}
            component="div"
            count={auditLog.length}
            rowsPerPage={auditRowsPerPage}
            page={auditPage}
            onPageChange={(e, newPage) => setAuditPage(newPage)}
            onRowsPerPageChange={(e) => {
              setAuditRowsPerPage(parseInt(e.target.value, 10));
              setAuditPage(0);
            }}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setAuditLogDialogOpen(false)}>Close</Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
};

export default SubscriptionManagement;
