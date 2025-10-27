import React, { useState, useEffect } from 'react';
import {
  Box,
  Paper,
  Typography,
  TextField,
  Button,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TablePagination,
  Chip,
  IconButton,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Grid,
  Card,
  CardContent,
  CircularProgress,
  Alert,
  Tooltip,
  Checkbox,
  FormControlLabel,
  Badge,
  Collapse,
  InputAdornment,
  Divider,
} from '@mui/material';
import {
  Search as SearchIcon,
  Refresh as RefreshIcon,
  FilterList as FilterListIcon,
  Close as CloseIcon,
  ExpandMore as ExpandMoreIcon,
  ExpandLess as ExpandLessIcon,
  ContentCopy as CopyIcon,
  CheckCircle as CheckCircleIcon,
  Cancel as CancelIcon,
  Info as InfoIcon,
} from '@mui/icons-material';

/**
 * Model Catalog Tab
 *
 * Displays comprehensive model catalog with filtering, search, and sorting.
 * Shows all models from LLM providers (OpenRouter, OpenAI, Anthropic, etc.)
 */
export default function ModelCatalog() {
  // State for models data
  const [models, setModels] = useState([]);
  const [filteredModels, setFilteredModels] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Filter state
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedProviders, setSelectedProviders] = useState([]);
  const [statusFilter, setStatusFilter] = useState('all'); // all, enabled, disabled
  const [sortBy, setSortBy] = useState('name'); // name, price, context_length
  const [showFilters, setShowFilters] = useState(false);

  // Pagination state
  const [page, setPage] = useState(0);
  const [rowsPerPage, setRowsPerPage] = useState(25);

  // Modal state
  const [selectedModel, setSelectedModel] = useState(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [copiedText, setCopiedText] = useState('');

  // Fetch models from API
  const fetchModels = async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      params.append('limit', '500'); // Get all models

      if (searchQuery) {
        params.append('search', searchQuery);
      }
      if (statusFilter !== 'all') {
        params.append('enabled', statusFilter === 'enabled');
      }
      if (sortBy) {
        params.append('sort', sortBy);
      }

      const response = await fetch(`/api/v1/llm/models?${params}`);
      if (!response.ok) {
        throw new Error(`Failed to fetch models: ${response.statusText}`);
      }

      const data = await response.json();
      setModels(data);
      applyClientFilters(data);
    } catch (err) {
      console.error('Failed to load models:', err);
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  // Apply client-side filters (provider selection)
  const applyClientFilters = (allModels) => {
    let filtered = allModels;

    // Provider filter
    if (selectedProviders.length > 0) {
      filtered = filtered.filter(m => selectedProviders.includes(m.provider_name));
    }

    setFilteredModels(filtered);
  };

  // Initial load
  useEffect(() => {
    fetchModels();
  }, [searchQuery, statusFilter, sortBy]);

  // Apply client filters when providers change
  useEffect(() => {
    applyClientFilters(models);
  }, [selectedProviders, models]);

  // Get unique providers
  const uniqueProviders = [...new Set(models.map(m => m.provider_name))].sort();

  // Calculate statistics
  const stats = {
    total: filteredModels.length,
    enabled: filteredModels.filter(m => m.enabled).length,
    providers: uniqueProviders.length,
    free: filteredModels.filter(m => m.cost_per_1m_input === 0 && m.cost_per_1m_output === 0).length,
  };

  // Handle search with debouncing
  const handleSearchChange = (event) => {
    const value = event.target.value;
    setSearchQuery(value);
    setPage(0);
  };

  // Handle provider toggle
  const handleProviderToggle = (provider) => {
    setSelectedProviders(prev => {
      if (prev.includes(provider)) {
        return prev.filter(p => p !== provider);
      } else {
        return [...prev, provider];
      }
    });
    setPage(0);
  };

  // Clear all filters
  const handleClearFilters = () => {
    setSearchQuery('');
    setSelectedProviders([]);
    setStatusFilter('all');
    setSortBy('name');
    setPage(0);
  };

  // Format cost
  const formatCost = (inputCost, outputCost) => {
    if (inputCost === 0 && outputCost === 0) {
      return 'Free';
    }
    return `$${inputCost.toFixed(2)} / $${outputCost.toFixed(2)} per 1M`;
  };

  // Format context length
  const formatContextLength = (length) => {
    if (length >= 1000000) {
      return `${(length / 1000000).toFixed(1)}M tokens`;
    }
    if (length >= 1000) {
      return `${(length / 1000).toFixed(0)}K tokens`;
    }
    return `${length} tokens`;
  };

  // Get provider badge color
  const getProviderColor = (provider) => {
    const colors = {
      'OpenRouter': 'primary',
      'OpenAI': 'success',
      'Anthropic': 'warning',
      'Google': 'error',
      'Cohere': 'info',
      'Meta': 'secondary',
    };
    return colors[provider] || 'default';
  };

  // Handle row click
  const handleRowClick = (model) => {
    setSelectedModel(model);
    setModalOpen(true);
  };

  // Copy to clipboard
  const handleCopy = (text, label) => {
    navigator.clipboard.writeText(text);
    setCopiedText(label);
    setTimeout(() => setCopiedText(''), 2000);
  };

  // Pagination handlers
  const handleChangePage = (event, newPage) => {
    setPage(newPage);
  };

  const handleChangeRowsPerPage = (event) => {
    setRowsPerPage(parseInt(event.target.value, 10));
    setPage(0);
  };

  // Get paginated models
  const paginatedModels = filteredModels.slice(
    page * rowsPerPage,
    page * rowsPerPage + rowsPerPage
  );

  // Count active filters
  const activeFilterCount = [
    searchQuery !== '',
    selectedProviders.length > 0,
    statusFilter !== 'all',
    sortBy !== 'name',
  ].filter(Boolean).length;

  if (loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '400px' }}>
        <CircularProgress />
      </Box>
    );
  }

  if (error) {
    return (
      <Box sx={{ p: 3 }}>
        <Alert severity="error">
          Failed to load models: {error}
        </Alert>
      </Box>
    );
  }

  return (
    <Box sx={{ p: 3 }}>
      {/* Statistics Cards */}
      <Grid container spacing={3} sx={{ mb: 3 }}>
        <Grid item xs={12} sm={6} md={3}>
          <Card sx={{ bgcolor: 'primary.main', color: 'white' }}>
            <CardContent>
              <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <Box>
                  <Typography variant="h4" fontWeight="bold">
                    {stats.total}
                  </Typography>
                  <Typography variant="body2" sx={{ opacity: 0.9 }}>
                    Total Models
                  </Typography>
                </Box>
                <InfoIcon sx={{ fontSize: 48, opacity: 0.8 }} />
              </Box>
            </CardContent>
          </Card>
        </Grid>

        <Grid item xs={12} sm={6} md={3}>
          <Card sx={{ bgcolor: 'success.main', color: 'white' }}>
            <CardContent>
              <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <Box>
                  <Typography variant="h4" fontWeight="bold">
                    {stats.enabled}
                  </Typography>
                  <Typography variant="body2" sx={{ opacity: 0.9 }}>
                    Enabled Models
                  </Typography>
                </Box>
                <CheckCircleIcon sx={{ fontSize: 48, opacity: 0.8 }} />
              </Box>
            </CardContent>
          </Card>
        </Grid>

        <Grid item xs={12} sm={6} md={3}>
          <Card sx={{ bgcolor: 'info.main', color: 'white' }}>
            <CardContent>
              <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <Box>
                  <Typography variant="h4" fontWeight="bold">
                    {stats.providers}
                  </Typography>
                  <Typography variant="body2" sx={{ opacity: 0.9 }}>
                    Providers
                  </Typography>
                </Box>
                <FilterListIcon sx={{ fontSize: 48, opacity: 0.8 }} />
              </Box>
            </CardContent>
          </Card>
        </Grid>

        <Grid item xs={12} sm={6} md={3}>
          <Card sx={{ bgcolor: 'warning.main', color: 'white' }}>
            <CardContent>
              <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <Box>
                  <Typography variant="h4" fontWeight="bold">
                    {stats.free}
                  </Typography>
                  <Typography variant="body2" sx={{ opacity: 0.9 }}>
                    Free Models
                  </Typography>
                </Box>
                <CheckCircleIcon sx={{ fontSize: 48, opacity: 0.8 }} />
              </Box>
            </CardContent>
          </Card>
        </Grid>
      </Grid>

      {/* Main Content */}
      <Paper sx={{ p: 3 }}>
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
          <Typography variant="h5" fontWeight="bold">
            Model Catalog
          </Typography>
          <Button
            variant="outlined"
            startIcon={<RefreshIcon />}
            onClick={fetchModels}
          >
            Refresh
          </Button>
        </Box>

        {/* Search and Filter Controls */}
        <Grid container spacing={2} sx={{ mb: 3 }}>
          <Grid item xs={12} md={6}>
            <TextField
              fullWidth
              placeholder="Search by model name..."
              value={searchQuery}
              onChange={handleSearchChange}
              InputProps={{
                startAdornment: (
                  <InputAdornment position="start">
                    <SearchIcon sx={{ color: 'text.secondary' }} />
                  </InputAdornment>
                ),
              }}
            />
          </Grid>

          <Grid item xs={6} md={2}>
            <FormControl fullWidth>
              <InputLabel>Status</InputLabel>
              <Select
                value={statusFilter}
                label="Status"
                onChange={(e) => {
                  setStatusFilter(e.target.value);
                  setPage(0);
                }}
              >
                <MenuItem value="all">All</MenuItem>
                <MenuItem value="enabled">Enabled</MenuItem>
                <MenuItem value="disabled">Disabled</MenuItem>
              </Select>
            </FormControl>
          </Grid>

          <Grid item xs={6} md={2}>
            <FormControl fullWidth>
              <InputLabel>Sort By</InputLabel>
              <Select
                value={sortBy}
                label="Sort By"
                onChange={(e) => {
                  setSortBy(e.target.value);
                  setPage(0);
                }}
              >
                <MenuItem value="name">Name (A-Z)</MenuItem>
                <MenuItem value="price">Price (Low to High)</MenuItem>
                <MenuItem value="context_length">Context (High to Low)</MenuItem>
              </Select>
            </FormControl>
          </Grid>

          <Grid item xs={12} md={2}>
            <Button
              fullWidth
              variant="outlined"
              startIcon={
                <Badge badgeContent={activeFilterCount} color="error">
                  <FilterListIcon />
                </Badge>
              }
              endIcon={showFilters ? <ExpandLessIcon /> : <ExpandMoreIcon />}
              onClick={() => setShowFilters(!showFilters)}
              sx={{ height: '56px' }}
            >
              Filters
            </Button>
          </Grid>
        </Grid>

        {/* Advanced Filters Panel */}
        <Collapse in={showFilters}>
          <Paper sx={{ p: 3, mb: 3, bgcolor: 'background.default' }}>
            <Typography variant="h6" gutterBottom>
              Filter by Provider
            </Typography>
            <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', mb: 2 }}>
              {uniqueProviders.map((provider) => (
                <FormControlLabel
                  key={provider}
                  control={
                    <Checkbox
                      checked={selectedProviders.includes(provider)}
                      onChange={() => handleProviderToggle(provider)}
                    />
                  }
                  label={provider}
                />
              ))}
            </Box>

            {activeFilterCount > 0 && (
              <>
                <Divider sx={{ my: 2 }} />
                <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <Typography variant="body2" color="text.secondary">
                    {activeFilterCount} filter{activeFilterCount !== 1 ? 's' : ''} active
                  </Typography>
                  <Button
                    variant="outlined"
                    color="error"
                    startIcon={<CloseIcon />}
                    onClick={handleClearFilters}
                    size="small"
                  >
                    Clear All Filters
                  </Button>
                </Box>
              </>
            )}
          </Paper>
        </Collapse>

        {/* Active Filters Display */}
        {activeFilterCount > 0 && (
          <Box sx={{ mb: 2, display: 'flex', gap: 1, flexWrap: 'wrap' }}>
            {searchQuery && (
              <Chip
                label={`Search: "${searchQuery}"`}
                onDelete={() => setSearchQuery('')}
                color="primary"
                size="small"
              />
            )}
            {statusFilter !== 'all' && (
              <Chip
                label={`Status: ${statusFilter}`}
                onDelete={() => setStatusFilter('all')}
                color="secondary"
                size="small"
              />
            )}
            {sortBy !== 'name' && (
              <Chip
                label={`Sort: ${sortBy}`}
                onDelete={() => setSortBy('name')}
                color="info"
                size="small"
              />
            )}
            {selectedProviders.map((provider) => (
              <Chip
                key={provider}
                label={`Provider: ${provider}`}
                onDelete={() => handleProviderToggle(provider)}
                color="default"
                size="small"
              />
            ))}
          </Box>
        )}

        {/* Results Count */}
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          Showing {paginatedModels.length} of {filteredModels.length} models
          {activeFilterCount > 0 && ` (${activeFilterCount} filter${activeFilterCount !== 1 ? 's' : ''} applied)`}
        </Typography>

        {/* Model Table */}
        {filteredModels.length === 0 ? (
          <Box sx={{ py: 8, textAlign: 'center' }}>
            <Typography variant="h6" color="text.secondary" gutterBottom>
              No models found
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
              Try adjusting your filters or search query
            </Typography>
            <Button
              variant="outlined"
              startIcon={<CloseIcon />}
              onClick={handleClearFilters}
            >
              Clear All Filters
            </Button>
          </Box>
        ) : (
          <>
            <TableContainer>
              <Table>
                <TableHead>
                  <TableRow>
                    <TableCell>Model Name</TableCell>
                    <TableCell>Provider</TableCell>
                    <TableCell align="right">Cost (per 1M tokens)</TableCell>
                    <TableCell align="right">Context Length</TableCell>
                    <TableCell align="center">Status</TableCell>
                    <TableCell align="right">Latency</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {paginatedModels.map((model) => (
                    <TableRow
                      key={model.id}
                      hover
                      onClick={() => handleRowClick(model)}
                      sx={{ cursor: 'pointer' }}
                    >
                      <TableCell>
                        <Typography variant="body2" fontWeight="medium">
                          {model.display_name}
                        </Typography>
                        <Typography variant="caption" color="text.secondary">
                          {model.name}
                        </Typography>
                      </TableCell>
                      <TableCell>
                        <Chip
                          label={model.provider_name}
                          color={getProviderColor(model.provider_name)}
                          size="small"
                        />
                      </TableCell>
                      <TableCell align="right">
                        <Typography variant="body2">
                          {formatCost(model.cost_per_1m_input, model.cost_per_1m_output)}
                        </Typography>
                      </TableCell>
                      <TableCell align="right">
                        <Typography variant="body2">
                          {formatContextLength(model.context_length)}
                        </Typography>
                      </TableCell>
                      <TableCell align="center">
                        {model.enabled ? (
                          <Chip
                            icon={<CheckCircleIcon />}
                            label="Enabled"
                            color="success"
                            size="small"
                          />
                        ) : (
                          <Chip
                            icon={<CancelIcon />}
                            label="Disabled"
                            color="error"
                            size="small"
                          />
                        )}
                      </TableCell>
                      <TableCell align="right">
                        <Typography variant="body2" color="text.secondary">
                          {model.avg_latency_ms ? `${model.avg_latency_ms}ms` : '-'}
                        </Typography>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>

            <TablePagination
              component="div"
              count={filteredModels.length}
              page={page}
              onPageChange={handleChangePage}
              rowsPerPage={rowsPerPage}
              onRowsPerPageChange={handleChangeRowsPerPage}
              rowsPerPageOptions={[10, 25, 50, 100]}
            />
          </>
        )}
      </Paper>

      {/* Model Details Modal */}
      <Dialog
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        maxWidth="md"
        fullWidth
      >
        <DialogTitle>
          Model Details
          {selectedModel && (
            <Typography variant="body2" color="text.secondary">
              {selectedModel.display_name}
            </Typography>
          )}
        </DialogTitle>
        <DialogContent>
          {selectedModel && (
            <Box sx={{ pt: 2 }}>
              <Grid container spacing={3}>
                {/* Provider */}
                <Grid item xs={12} sm={6}>
                  <Typography variant="subtitle2" color="text.secondary" gutterBottom>
                    Provider
                  </Typography>
                  <Chip
                    label={selectedModel.provider_name}
                    color={getProviderColor(selectedModel.provider_name)}
                  />
                </Grid>

                {/* Status */}
                <Grid item xs={12} sm={6}>
                  <Typography variant="subtitle2" color="text.secondary" gutterBottom>
                    Status
                  </Typography>
                  {selectedModel.enabled ? (
                    <Chip icon={<CheckCircleIcon />} label="Enabled" color="success" />
                  ) : (
                    <Chip icon={<CancelIcon />} label="Disabled" color="error" />
                  )}
                </Grid>

                {/* Model ID */}
                <Grid item xs={12}>
                  <Typography variant="subtitle2" color="text.secondary" gutterBottom>
                    Model ID
                  </Typography>
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                    <Typography variant="body2" sx={{ fontFamily: 'monospace' }}>
                      {selectedModel.name}
                    </Typography>
                    <Tooltip title={copiedText === 'id' ? 'Copied!' : 'Copy to clipboard'}>
                      <IconButton
                        size="small"
                        onClick={() => handleCopy(selectedModel.name, 'id')}
                      >
                        <CopyIcon fontSize="small" />
                      </IconButton>
                    </Tooltip>
                  </Box>
                </Grid>

                {/* Cost */}
                <Grid item xs={12} sm={6}>
                  <Typography variant="subtitle2" color="text.secondary" gutterBottom>
                    Input Cost (per 1M tokens)
                  </Typography>
                  <Typography variant="body1">
                    ${selectedModel.cost_per_1m_input.toFixed(4)}
                  </Typography>
                </Grid>

                <Grid item xs={12} sm={6}>
                  <Typography variant="subtitle2" color="text.secondary" gutterBottom>
                    Output Cost (per 1M tokens)
                  </Typography>
                  <Typography variant="body1">
                    ${selectedModel.cost_per_1m_output.toFixed(4)}
                  </Typography>
                </Grid>

                {/* Context Length */}
                <Grid item xs={12} sm={6}>
                  <Typography variant="subtitle2" color="text.secondary" gutterBottom>
                    Context Length
                  </Typography>
                  <Typography variant="body1">
                    {formatContextLength(selectedModel.context_length)}
                  </Typography>
                </Grid>

                {/* Average Latency */}
                <Grid item xs={12} sm={6}>
                  <Typography variant="subtitle2" color="text.secondary" gutterBottom>
                    Average Latency
                  </Typography>
                  <Typography variant="body1">
                    {selectedModel.avg_latency_ms ? `${selectedModel.avg_latency_ms}ms` : 'Not available'}
                  </Typography>
                </Grid>

                {/* Internal IDs */}
                <Grid item xs={12}>
                  <Divider sx={{ my: 2 }} />
                  <Typography variant="subtitle2" color="text.secondary" gutterBottom>
                    Internal IDs (for reference)
                  </Typography>
                  <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                      <Typography variant="caption" color="text.secondary" sx={{ minWidth: 80 }}>
                        Model ID:
                      </Typography>
                      <Typography variant="caption" sx={{ fontFamily: 'monospace' }}>
                        {selectedModel.id}
                      </Typography>
                      <Tooltip title={copiedText === 'model_id' ? 'Copied!' : 'Copy'}>
                        <IconButton
                          size="small"
                          onClick={() => handleCopy(selectedModel.id, 'model_id')}
                        >
                          <CopyIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                    </Box>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                      <Typography variant="caption" color="text.secondary" sx={{ minWidth: 80 }}>
                        Provider ID:
                      </Typography>
                      <Typography variant="caption" sx={{ fontFamily: 'monospace' }}>
                        {selectedModel.provider_id}
                      </Typography>
                      <Tooltip title={copiedText === 'provider_id' ? 'Copied!' : 'Copy'}>
                        <IconButton
                          size="small"
                          onClick={() => handleCopy(selectedModel.provider_id, 'provider_id')}
                        >
                          <CopyIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                    </Box>
                  </Box>
                </Grid>
              </Grid>
            </Box>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setModalOpen(false)}>
            Close
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
