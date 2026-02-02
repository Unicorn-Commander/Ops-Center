import React, { useState, useEffect } from 'react';
import {
  Box,
  Grid,
  Card,
  CardContent,
  CardMedia,
  Typography,
  Button,
  CircularProgress,
  Alert,
  Chip
} from '@mui/material';
import { Launch as LaunchIcon, Public as PublicIcon, Business as BusinessIcon } from '@mui/icons-material';

/**
 * AppsLauncher - Tier-Filtered Apps Dashboard
 *
 * Shows ONLY apps the user's subscription tier includes.
 * Fetches from /api/v1/my-apps/authorized (tier-filtered backend endpoint)
 *
 * Apps can be hosted ANYWHERE:
 * - Same domain (unicorncommander.ai/admin)
 * - Different subdomain (chat.unicorncommander.ai)
 * - Completely different domain (search.centerdeep.online)
 *
 * launch_url is the source of truth for where the app lives.
 */

// Card background colors - vibrant gradients for each app
const CARD_COLORS = [
  { gradient: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)', iconBg: '#ffffff' },  // Purple
  { gradient: 'linear-gradient(135deg, #f093fb 0%, #f5576c 100%)', iconBg: '#ffffff' },  // Pink
  { gradient: 'linear-gradient(135deg, #4facfe 0%, #00f2fe 100%)', iconBg: '#ffffff' },  // Blue
  { gradient: 'linear-gradient(135deg, #43e97b 0%, #38f9d7 100%)', iconBg: '#1a1a2e' },  // Green
  { gradient: 'linear-gradient(135deg, #fa709a 0%, #fee140 100%)', iconBg: '#1a1a2e' },  // Orange/Pink
  { gradient: 'linear-gradient(135deg, #a8edea 0%, #fed6e3 100%)', iconBg: '#1a1a2e' },  // Pastel
  { gradient: 'linear-gradient(135deg, #5ee7df 0%, #b490ca 100%)', iconBg: '#ffffff' },  // Teal/Purple
  { gradient: 'linear-gradient(135deg, #d299c2 0%, #fef9d7 100%)', iconBg: '#1a1a2e' },  // Lavender
  { gradient: 'linear-gradient(135deg, #89f7fe 0%, #66a6ff 100%)', iconBg: '#ffffff' },  // Sky Blue
  { gradient: 'linear-gradient(135deg, #cd9cf2 0%, #f6f3ff 100%)', iconBg: '#1a1a2e' },  // Light Purple
];

const AppsLauncher = () => {
  const [apps, setApps] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetchApps();
  }, []);

  const fetchApps = async () => {
    try {
      // NEW API: tier-filtered apps the user has access to
      const response = await fetch('/api/v1/my-apps/authorized');
      if (!response.ok) throw new Error('Failed to fetch apps');

      const data = await response.json();
      setApps(data);
      setLoading(false);
    } catch (err) {
      console.error('Error fetching apps:', err);
      setError(err.message);
      setLoading(false);
    }
  };

  const handleLaunch = (app) => {
    // Open app in new tab - launch_url can be ANYWHERE
    window.open(app.launch_url, '_blank', 'noopener,noreferrer');
  };

  const getHostBadge = (launch_url) => {
    try {
      const url = new URL(launch_url);
      const host = url.hostname;

      // Determine if hosted by UC or federated
      if (host.includes('unicorncommander.ai') || host.includes('magicunicorn.dev')) {
        return { label: 'UC Hosted', icon: <BusinessIcon />, color: 'primary' };
      } else {
        return { label: 'Federated', icon: <PublicIcon />, color: 'secondary' };
      }
    } catch (e) {
      return { label: 'External', icon: <PublicIcon />, color: 'default' };
    }
  };

  const getCardColor = (index) => {
    return CARD_COLORS[index % CARD_COLORS.length];
  };

  if (loading) {
    return (
      <Box display="flex" justifyContent="center" alignItems="center" minHeight="60vh">
        <CircularProgress />
      </Box>
    );
  }

  if (error) {
    return (
      <Box p={3}>
        <Alert severity="error">Error loading apps: {error}</Alert>
      </Box>
    );
  }

  return (
    <Box p={3}>
      <Box mb={4}>
        <Typography variant="h4" gutterBottom sx={{ fontWeight: 600 }}>
          My Apps
        </Typography>
        <Typography variant="body1" color="text.secondary">
          Apps included in your subscription tier
        </Typography>
      </Box>

      <Grid container spacing={3}>
        {apps.map((app, index) => {
          const hostBadge = getHostBadge(app.launch_url);
          const cardColor = getCardColor(index);

          return (
            <Grid item xs={12} sm={6} md={4} lg={3} key={app.id}>
              <Card
                sx={{
                  height: 320,  // Fixed height for all cards
                  display: 'flex',
                  flexDirection: 'column',
                  cursor: 'pointer',
                  transition: 'all 0.3s ease',
                  position: 'relative',
                  background: cardColor.gradient,
                  borderRadius: 3,
                  overflow: 'hidden',
                  '&:hover': {
                    transform: 'translateY(-8px) scale(1.02)',
                    boxShadow: '0 20px 40px rgba(0,0,0,0.3)',
                  }
                }}
                onClick={() => handleLaunch(app)}
              >
                {/* Host Badge */}
                <Box sx={{ position: 'absolute', top: 12, right: 12, zIndex: 1 }}>
                  <Chip
                    icon={hostBadge.icon}
                    label={hostBadge.label}
                    size="small"
                    sx={{
                      fontSize: '0.7rem',
                      bgcolor: 'rgba(255,255,255,0.9)',
                      color: '#333',
                      fontWeight: 600,
                      '& .MuiChip-icon': {
                        color: '#333'
                      }
                    }}
                  />
                </Box>

                {/* App Icon with background */}
                <Box
                  sx={{
                    p: 3,
                    pt: 5,
                    display: 'flex',
                    justifyContent: 'center',
                    alignItems: 'center',
                    flexGrow: 0,
                    minHeight: 140
                  }}
                >
                  <Box
                    sx={{
                      width: 90,
                      height: 90,
                      borderRadius: 3,
                      bgcolor: cardColor.iconBg,
                      display: 'flex',
                      justifyContent: 'center',
                      alignItems: 'center',
                      boxShadow: '0 4px 20px rgba(0,0,0,0.2)',
                      p: 1.5
                    }}
                  >
                    {app.icon_url ? (
                      <CardMedia
                        component="img"
                        image={app.icon_url}
                        alt={app.name}
                        sx={{
                          width: '100%',
                          height: '100%',
                          objectFit: 'contain'
                        }}
                      />
                    ) : (
                      <LaunchIcon sx={{ fontSize: 50, color: cardColor.iconBg === '#ffffff' ? '#667eea' : '#ffffff' }} />
                    )}
                  </Box>
                </Box>

                {/* App Info */}
                <CardContent
                  sx={{
                    flexGrow: 1,
                    display: 'flex',
                    flexDirection: 'column',
                    bgcolor: 'rgba(255,255,255,0.95)',
                    borderTopLeftRadius: 24,
                    borderTopRightRadius: 24,
                    mt: 'auto'
                  }}
                >
                  <Typography
                    variant="h6"
                    gutterBottom
                    textAlign="center"
                    sx={{
                      fontWeight: 700,
                      color: '#1a1a2e'
                    }}
                  >
                    {app.name}
                  </Typography>

                  {app.description && (
                    <Typography
                      variant="body2"
                      sx={{
                        mb: 2,
                        flexGrow: 1,
                        textAlign: 'center',
                        color: '#666',
                        fontSize: '0.85rem',
                        lineHeight: 1.4
                      }}
                    >
                      {app.description.length > 60
                        ? app.description.substring(0, 60) + '...'
                        : app.description
                      }
                    </Typography>
                  )}

                  <Button
                    variant="contained"
                    startIcon={<LaunchIcon />}
                    fullWidth
                    onClick={(e) => {
                      e.stopPropagation();
                      handleLaunch(app);
                    }}
                    sx={{
                      mt: 'auto',
                      background: cardColor.gradient,
                      fontWeight: 600,
                      borderRadius: 2,
                      textTransform: 'none',
                      py: 1,
                      '&:hover': {
                        opacity: 0.9
                      }
                    }}
                  >
                    Launch
                  </Button>
                </CardContent>
              </Card>
            </Grid>
          );
        })}
      </Grid>

      {apps.length === 0 && (
        <Box textAlign="center" py={8}>
          <Typography variant="h6" color="text.secondary" gutterBottom>
            No apps in your tier
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Upgrade your subscription to access more apps
          </Typography>
          <Button
            variant="contained"
            color="primary"
            sx={{ mt: 3 }}
            onClick={() => window.location.href = '/admin/apps/marketplace'}
          >
            Browse Marketplace
          </Button>
        </Box>
      )}
    </Box>
  );
};

export default AppsLauncher;
