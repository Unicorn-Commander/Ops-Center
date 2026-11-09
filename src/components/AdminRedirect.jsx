import React, { useEffect, useState } from 'react';
import { Navigate } from 'react-router-dom';
import LoadingScreen from './LoadingScreen';
import { isPlatformAdminRole } from '../config/routes';

/**
 * AdminRedirect - Smart router for /admin/ landing
 *
 * /dashboard is the home for every signed-in role. /admin is only the
 * deliberate platform Admin Console entry; organization users return home.
 */
export default function AdminRedirect() {
  const [loading, setLoading] = useState(true);
  const [isPlatformAdmin, setIsPlatformAdmin] = useState(false);

  useEffect(() => {
    // Check user role from localStorage or session
    let userInfo = {};
    try {
      userInfo = JSON.parse(localStorage.getItem('userInfo') || '{}');
    } catch (_) {
      userInfo = {};
    }
    const role = userInfo.role || 'viewer';

    setIsPlatformAdmin(isPlatformAdminRole(role));
    setLoading(false);
  }, []);

  if (loading) {
    return <LoadingScreen />;
  }

  // Platform administrators go to the infrastructure console.
  if (isPlatformAdmin) {
    return <Navigate to="/admin/dashboard" replace />;
  }

  return <Navigate to="/dashboard" replace />;
}
