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
  Alert,
  Skeleton,
  Tooltip,
  LinearProgress
} from '@mui/material';
import {
  LockClosedIcon,
  EllipsisVerticalIcon,
  ArrowPathIcon,
  DocumentTextIcon,
  ExclamationTriangleIcon,
  CheckCircleIcon,
  ClockIcon
} from '@heroicons/react/24/outline';
import { useSearchParams } from 'react-router-dom';

const TraefikSSL = () => {
  const [searchParams] = useSearchParams();
  const [certificates, setCertificates] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);

  // Table state
  const [page, setPage] = useState(0);
  const [rowsPerPage, setRowsPerPage] = useState(25);

  // Menu state
  const [menuAnchor, setMenuAnchor] = useState(null);
  const [selectedCert, setSelectedCert] = useState(null);

  // Detail dialog state
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [certDetails, setCertDetails] = useState(null);

  // Renewal state
  const [renewing, setRenewing] = useState(false);

  useEffect(() => {
    loadCertificates();

    // Auto-renew if requested
    if (searchParams.get('action') === 'renew') {
      handleRenewAll();
    }
  }, [searchParams]);

  const loadCertificates = async () => {
    try {
      const response = await fetch('/api/v1/traefik/certificates', {
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('authToken')}`
        }
      });

      if (!response.ok) throw new Error('Failed to load certificates');

      const data = await response.json();
      setCertificates(data.certificates || []);
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleRenew = async (certId) => {
    setRenewing(true);
    try {
      const response = await fetch(`/api/v1/traefik/certificates/${certId}/renew`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('authToken')}`
        }
      });

      if (!response.ok) throw new Error('Certificate renewal failed');

      setSuccess('Certificate renewed successfully');
      loadCertificates();
    } catch (err) {
      setError(err.message);
    } finally {
      setRenewing(false);
      handleMenuClose();
    }
  };

  const handleRenewAll = async () => {
    setRenewing(true);
    try {
      const response = await fetch('/api/v1/traefik/certificates/renew', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('authToken')}`
        }
      });

      if (!response.ok) throw new Error('Bulk renewal failed');

      const data = await response.json();
      setSuccess(`Renewed ${data.count} certificates successfully`);
      loadCertificates();
    } catch (err) {
      setError(err.message);
    } finally {
      setRenewing(false);
    }
  };

  const handleViewDetails = async (cert) => {
    setCertDetails(cert);
    setDetailsOpen(true);
    handleMenuClose();
  };

  const handleMenuOpen = (event, cert) => {
    setMenuAnchor(event.currentTarget);
    setSelectedCert(cert);
  };

  const handleMenuClose = () => {
    setMenuAnchor(null);
    setSelectedCert(null);
  };

  const getDaysUntilExpiry = (expiryDate) => {
    const now = new Date();
    const expiry = new Date(expiryDate);
    const diff = expiry - now;
    return Math.floor(diff / (1000 * 60 * 60 * 24));
  };

  const getStatusChip = (cert) => {
    const daysLeft = getDaysUntilExpiry(cert.expiresAt);

    if (daysLeft < 0) {
      return (
        <Chip
          label="Expired"
          size="small"
          color="error"
          icon={<XCircleIcon style={{ width: 16, height: 16 }} />}
        />
      );
    } else if (daysLeft < 30) {
      return (
        <Chip
          label="Expiring Soon"
          size="small"
          color="warning"
          icon={<ExclamationTriangleIcon style={{ width: 16, height: 16 }} />}
        />
      );
    } else {
      return (
        <Chip
          label="Valid"
          size="small"
          color="success"
          icon={<CheckCircleIcon style={{ width: 16, height: 16 }} />}
        />
      );
    }
  };

  const paginatedCertificates = certificates.slice(
    page * rowsPerPage,
    page * rowsPerPage + rowsPerPage
  );

  return (
    <Container maxWidth="xl" sx={{ py: 4 }}>
      {/* Header */}
      <Box display="flex" justifyContent="space-between" alignItems="center" mb={4}>
        <Box>
          <Typography variant="h4" component="h1" gutterBottom>
            SSL Certificates
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Manage SSL/TLS certificates
          </Typography>
        </Box>
        <Box display="flex" gap={2}>
          <Button
            variant="outlined"
            startIcon={<ArrowPathIcon style={{ width: 20, height: 20 }} />}
            onClick={loadCertificates}
            disabled={loading || renewing}
          >
            Refresh
          </Button>
          <Button
            variant="contained"
            startIcon={<LockClosedIcon style={{ width: 20, height: 20 }} />}
            onClick={handleRenewAll}
            disabled={renewing}
          >
            Renew All
          </Button>
        </Box>
      </Box>

      {renewing && <LinearProgress sx={{ mb: 3 }} />}

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

      {/* Certificates Table */}
      <Paper>
        <TableContainer>
          <Table>
            <TableHead>
              <TableRow>
                <TableCell>Domain</TableCell>
                <TableCell>Issuer</TableCell>
                <TableCell>Valid From</TableCell>
                <TableCell>Valid Until</TableCell>
                <TableCell>Days Until Expiry</TableCell>
                <TableCell>Status</TableCell>
                <TableCell align="right">Actions</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {loading ? (
                [...Array(5)].map((_, i) => (
                  <TableRow key={i}>
                    {[...Array(7)].map((_, j) => (
                      <TableCell key={j}>
                        <Skeleton />
                      </TableCell>
                    ))}
                  </TableRow>
                ))
              ) : paginatedCertificates.length > 0 ? (
                paginatedCertificates.map((cert) => {
                  const daysLeft = getDaysUntilExpiry(cert.expiresAt);
                  return (
                    <TableRow key={cert.id} hover>
                      <TableCell>
                        <Box display="flex" alignItems="center" gap={1}>
                          <LockClosedIcon style={{ width: 16, height: 16 }} />
                          <Typography variant="body2" fontWeight={500}>
                            {cert.domain}
                          </Typography>
                        </Box>
                      </TableCell>
                      <TableCell>
                        <Typography variant="body2" color="text.secondary">
                          {cert.issuer || 'Let\'s Encrypt'}
                        </Typography>
                      </TableCell>
                      <TableCell>
                        <Typography variant="body2">
                          {new Date(cert.validFrom).toLocaleDateString()}
                        </Typography>
                      </TableCell>
                      <TableCell>
                        <Typography variant="body2">
                          {new Date(cert.expiresAt).toLocaleDateString()}
                        </Typography>
                      </TableCell>
                      <TableCell>
                        <Box display="flex" alignItems="center" gap={1}>
                          <Typography
                            variant="body2"
                            color={daysLeft < 30 ? 'error.main' : 'text.primary'}
                          >
                            {daysLeft < 0 ? 'Expired' : `${daysLeft} days`}
                          </Typography>
                          {daysLeft >= 0 && daysLeft < 30 && (
                            <ClockIcon
                              style={{ width: 16, height: 16, color: 'orange' }}
                            />
                          )}
                        </Box>
                      </TableCell>
                      <TableCell>{getStatusChip(cert)}</TableCell>
                      <TableCell align="right">
                        <IconButton
                          size="small"
                          onClick={(e) => handleMenuOpen(e, cert)}
                        >
                          <EllipsisVerticalIcon style={{ width: 20, height: 20 }} />
                        </IconButton>
                      </TableCell>
                    </TableRow>
                  );
                })
              ) : (
                <TableRow>
                  <TableCell colSpan={7} align="center" sx={{ py: 8 }}>
                    <Typography variant="body2" color="text.secondary">
                      No SSL certificates found
                    </Typography>
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </TableContainer>

        <TablePagination
          component="div"
          count={certificates.length}
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
        <MenuItem onClick={() => handleViewDetails(selectedCert)}>
          <DocumentTextIcon style={{ width: 16, height: 16, marginRight: 8 }} />
          View Details
        </MenuItem>
        <MenuItem onClick={() => handleRenew(selectedCert?.id)}>
          <ArrowPathIcon style={{ width: 16, height: 16, marginRight: 8 }} />
          Renew Certificate
        </MenuItem>
      </Menu>

      {/* Certificate Details Dialog */}
      <Dialog open={detailsOpen} onClose={() => setDetailsOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Certificate Details</DialogTitle>
        <DialogContent>
          {certDetails && (
            <Box display="flex" flexDirection="column" gap={2} mt={2}>
              <Box>
                <Typography variant="caption" color="text.secondary">
                  Domain
                </Typography>
                <Typography variant="body1">{certDetails.domain}</Typography>
              </Box>
              <Box>
                <Typography variant="caption" color="text.secondary">
                  Issuer
                </Typography>
                <Typography variant="body1">{certDetails.issuer || 'Let\'s Encrypt'}</Typography>
              </Box>
              <Box>
                <Typography variant="caption" color="text.secondary">
                  Valid From
                </Typography>
                <Typography variant="body1">
                  {new Date(certDetails.validFrom).toLocaleString()}
                </Typography>
              </Box>
              <Box>
                <Typography variant="caption" color="text.secondary">
                  Expires At
                </Typography>
                <Typography variant="body1">
                  {new Date(certDetails.expiresAt).toLocaleString()}
                </Typography>
              </Box>
              <Box>
                <Typography variant="caption" color="text.secondary">
                  Serial Number
                </Typography>
                <Typography variant="body2" sx={{ fontFamily: 'monospace' }}>
                  {certDetails.serialNumber || 'N/A'}
                </Typography>
              </Box>
              <Box>
                <Typography variant="caption" color="text.secondary">
                  Status
                </Typography>
                <Box mt={1}>{getStatusChip(certDetails)}</Box>
              </Box>
            </Box>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDetailsOpen(false)}>Close</Button>
          <Button
            variant="contained"
            onClick={() => {
              handleRenew(certDetails?.id);
              setDetailsOpen(false);
            }}
          >
            Renew Now
          </Button>
        </DialogActions>
      </Dialog>
    </Container>
  );
};

export default TraefikSSL;
