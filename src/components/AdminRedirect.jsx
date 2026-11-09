import React, { useEffect, useState } from 'react';
import { Navigate } from 'react-router-dom';
import LoadingScreen from './LoadingScreen';
import { isPlatformAdminRole } from '../config/routes';

/**
 * AdminRedirect - Smart router for /admin/ landing
 *
 * /dashboard is the home for every signed-in role, platform administrators
 * included. A bare /admin (a bookmark, or the return URL after sign-in) goes
 * home. The Admin console is entered on purpose, by its own links, which
 * point at /admin/dashboard.
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

  return <Navigate to="/dashboard" replace />;
}
