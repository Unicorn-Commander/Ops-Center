import React, { useState, useEffect } from 'react';
import {
  Box,
  Container,
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
  Chip,
  IconButton,
  Menu,
  MenuItem,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  TextField,
  Alert,
  Skeleton,
  Tooltip
} from '@mui/material';
import {
  PlusIcon,
  EllipsisVerticalIcon,
  PencilIcon,
  TrashIcon,
  CheckCircleIcon,
  XCircleIcon,
  ArrowPathIcon
} from '@heroicons/react/24/outline';
import { useSearchParams } from 'react-router-dom';

const TraefikServices = () => {
  const [searchParams] = useSearchParams();
  const [services, setServices] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);

  // Table state
  const [page, setPage] = useState(0);
  const [rowsPerPage, setRowsPerPage] = useState(25);

  // Menu state
  const [menuAnchor, setMenuAnchor] = useState(null);
  const [selectedService, setSelectedService] = useState(null);

  // Dialog state
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingService, setEditingService] = useState(null);
  const [formData, setFormData] = useState({
    name: '',
    url: '',
    healthCheck: '/health'
  });

  useEffect(() => {
    loadServices();

    // Auto-discover on load if requested
    if (searchParams.get('action') === 'discover') {
      handleDiscover();
    }
  }, [searchParams]);

  const loadServices = async () => {
    try {
      const response = await fetch('/api/v1/traefik/services', {
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('authToken')}`
        }
      });

      if (!response.ok) throw new Error('Failed to load services');

      const data = await response.json();
      setServices(data.services || []);
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleDiscover = async () => {
    setLoading(true);
    try {
      const response = await fetch('/api/v1/traefik/services/discover', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('authToken')}`
        }
      });

      if (!response.ok) throw new Error('Service discovery failed');

      const data = await response.json();
      setSuccess(`Discovered ${data.count} services`);
      loadServices();
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleSave = async () => {
    try {
      const url = editingService
        ? `/api/v1/traefik/services/${editingService.id}`
        : '/api/v1/traefik/services';

      const method = editingService ? 'PUT' : 'POST';

      const response = await fetch(url, {
        method,
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('authToken')}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(formData)
      });

      if (!response.ok) throw new Error('Failed to save service');

      setSuccess(`Service ${editingService ? 'updated' : 'created'} successfully`);
      setDialogOpen(false);
      setEditingService(null);
      setFormData({ name: '', url: '', healthCheck: '/health' });
      loadServices();
    } catch (err) {
      setError(err.message);
    }
  };

  const handleDelete = async (serviceId) => {
    if (!confirm('Are you sure you want to delete this service?')) return;

    try {
      const response = await fetch(`/api/v1/traefik/services/${serviceId}`, {
        method: 'DELETE',
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('authToken')}`
        }
      });

      if (!response.ok) throw new Error('Failed to delete service');

      setSuccess('Service deleted successfully');
      loadServices();
    } catch (err) {
      setError(err.message);
    }
  };

  const handleEdit = (service) => {
    setEditingService(service);
    setFormData({
      name: service.name,
      url: service.url,
      healthCheck: service.healthCheck || '/health'
    });
    setDialogOpen(true);
    handleMenuClose();
  };

  const handleMenuOpen = (event, service) => {
    setMenuAnchor(event.currentTarget);
    setSelectedService(service);
  };

  const handleMenuClose = () => {
    setMenuAnchor(null);
    setSelectedService(null);
  };

  const paginatedServices = services.slice(
    page * rowsPerPage,
    page * rowsPerPage + rowsPerPage
  );

  return (
    <Container maxWidth="xl" sx={{ py: 4 }}>
      {/* Header */}
      <Box display="flex" justifyContent="space-between" alignItems="center" mb={4}>
        <Box>
          <Typography variant="h4" component="h1" gutterBottom>
            Services
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Manage backend services
          </Typography>
        </Box>
        <Box display="flex" gap={2}>
          <Button
            variant="outlined"
            startIcon={<ArrowPathIcon style={{ width: 20, height: 20 }} />}
            onClick={handleDiscover}
            disabled={loading}
          >
            Discover Services
          </Button>
          <Button
            variant="contained"
            startIcon={<PlusIcon style={{ width: 20, height: 20 }} />}
            onClick={() => {
              setEditingService(null);
              setFormData({ name: '', url: '', healthCheck: '/health' });
              setDialogOpen(true);
            }}
          >
            Add Service
          </Button>
        </Box>
      </Box>

      {error && (
        <Alert severity="error" sx={{ mb: 3 }} onClose={() => setError(null)}>
          {error}
        </Alert>
      )}

      {success && (
        <Alert severity="success" sx={{ mb: 3 }} onClose={() => setSuccess(null)}>
          {success}
        </Alert>
      )}

      {/* Services Table */}
      <Paper>
        <TableContainer>
          <Table>
            <TableHead>
              <TableRow>
                <TableCell>Service Name</TableCell>
                <TableCell>Backend URL</TableCell>
                <TableCell>Health Check</TableCell>
                <TableCell>Status</TableCell>
                <TableCell>Request Count</TableCell>
                <TableCell align="right">Actions</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {loading ? (
                [...Array(5)].map((_, i) => (
                  <TableRow key={i}>
                    {[...Array(6)].map((_, j) => (
                      <TableCell key={j}>
                        <Skeleton />
                      </TableCell>
                    ))}
                  </TableRow>
                ))
              ) : paginatedServices.length > 0 ? (
                paginatedServices.map((service) => (
                  <TableRow key={service.id} hover>
                    <TableCell>
                      <Typography variant="body2" fontWeight={500}>
                        {service.name}
                      </Typography>
                    </TableCell>
                    <TableCell>
                      <Typography variant="body2" sx={{ fontFamily: 'monospace' }}>
                        {service.url}
                      </Typography>
                    </TableCell>
                    <TableCell>
                      <Typography variant="body2" color="text.secondary">
                        {service.healthCheck || 'None'}
                      </Typography>
                    </TableCell>
                    <TableCell>
                      <Chip
                        label={service.healthy ? 'Healthy' : 'Unhealthy'}
                        size="small"
                        color={service.healthy ? 'success' : 'error'}
                        icon={
                          service.healthy ? (
                            <CheckCircleIcon style={{ width: 16, height: 16 }} />
                          ) : (
                            <XCircleIcon style={{ width: 16, height: 16 }} />
                          )
                        }
                      />
                    </TableCell>
                    <TableCell>
                      <Typography variant="body2">
                        {service.requestCount?.toLocaleString() || 0}
                      </Typography>
                    </TableCell>
                    <TableCell align="right">
                      <IconButton
                        size="small"
                        onClick={(e) => handleMenuOpen(e, service)}
                      >
                        <EllipsisVerticalIcon style={{ width: 20, height: 20 }} />
                      </IconButton>
                    </TableCell>
                  </TableRow>
                ))
              ) : (
                <TableRow>
                  <TableCell colSpan={6} align="center" sx={{ py: 8 }}>
                    <Typography variant="body2" color="text.secondary">
                      No services found. Click "Discover Services" to auto-detect Docker containers.
                    </Typography>
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </TableContainer>

        <TablePagination
          component="div"
          count={services.length}
          page={page}
          onPageChange={(e, newPage) => setPage(newPage)}
          rowsPerPage={rowsPerPage}
          onRowsPerPageChange={(e) => {
            setRowsPerPage(parseInt(e.target.value, 10));
            setPage(0);
          }}
          rowsPerPageOptions={[10, 25, 50]}
        />
      </Paper>

      {/* Action Menu */}
      <Menu
        anchorEl={menuAnchor}
        open={Boolean(menuAnchor)}
        onClose={handleMenuClose}
      >
        <MenuItem onClick={() => handleEdit(selectedService)}>
          <PencilIcon style={{ width: 16, height: 16, marginRight: 8 }} />
          Edit
        </MenuItem>
        <MenuItem
          onClick={() => {
            handleDelete(selectedService?.id);
            handleMenuClose();
          }}
          sx={{ color: 'error.main' }}
        >
          <TrashIcon style={{ width: 16, height: 16, marginRight: 8 }} />
          Delete
        </MenuItem>
      </Menu>

      {/* Service Editor Dialog */}
      <Dialog open={dialogOpen} onClose={() => setDialogOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>
          {editingService ? 'Edit Service' : 'Add Service'}
        </DialogTitle>
        <DialogContent>
          <Box display="flex" flexDirection="column" gap={2} mt={2}>
            <TextField
              label="Service Name"
              value={formData.name}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              fullWidth
              required
            />
            <TextField
              label="Backend URL"
              value={formData.url}
              onChange={(e) => setFormData({ ...formData, url: e.target.value })}
              fullWidth
              required
              placeholder="http://container-name:8080"
            />
            <TextField
              label="Health Check Path"
              value={formData.healthCheck}
              onChange={(e) => setFormData({ ...formData, healthCheck: e.target.value })}
              fullWidth
              placeholder="/health"
            />
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDialogOpen(false)}>Cancel</Button>
          <Button variant="contained" onClick={handleSave}>
            {editingService ? 'Update' : 'Create'}
          </Button>
        </DialogActions>
      </Dialog>
    </Container>
  );
};

export default TraefikServices;
