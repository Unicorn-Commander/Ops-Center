/**
 * AccountSecurity Component
 *
 * Security settings and session management
 * - Keycloak password management link
 * - Active sessions list
 * - 2FA setup (placeholder for now)
 * - Recent security activity
 *
 * API Endpoints:
 * - GET /api/v1/auth/sessions - List active sessions
 */

import React, { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import {
  ShieldCheckIcon,
  KeyIcon,
  DevicePhoneMobileIcon,
  ComputerDesktopIcon,
  CheckCircleIcon,
  ExclamationCircleIcon,
  ClockIcon,
  MapPinIcon
} from '@heroicons/react/24/outline';
import { useTheme } from '../../contexts/ThemeContext';
import { getKeycloakAccountSignInUrl } from '../../utils/keycloak';

// Derive a readable device label from the backend's user_agent string.
// GET /api/v1/auth/sessions returns snake_case SessionInfo objects:
// { id, ip_address, user_agent, last_active, created_at, is_current }
const describeDevice = (userAgent) => {
  if (!userAgent) return null;
  const browser = /Edg(e|A|iOS)?\//.test(userAgent) ? 'Edge'
    : /OPR\//.test(userAgent) ? 'Opera'
    : /Firefox\//.test(userAgent) ? 'Firefox'
    : /Chrome\//.test(userAgent) ? 'Chrome'
    : /Safari\//.test(userAgent) ? 'Safari'
    : null;
  const os = /Windows/.test(userAgent) ? 'Windows'
    : /Android/.test(userAgent) ? 'Android'
    : /iPhone|iPad|iOS/.test(userAgent) ? 'iOS'
    : /Mac OS X|Macintosh/.test(userAgent) ? 'macOS'
    : /Linux/.test(userAgent) ? 'Linux'
    : null;
  if (browser && os) return `${browser} on ${os}`;
  return browser || os || userAgent;
};

const formatSessionTime = (isoString) => {
  if (!isoString) return null;
  const date = new Date(isoString);
  return Number.isNaN(date.getTime()) ? null : date.toLocaleString();
};

export default function AccountSecurity() {
  const { theme, currentTheme } = useTheme();
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState(null);
  const [sessions, setSessions] = useState([]);

  // Theme classes matching UserSettings pattern
  const themeClasses = {
    card: currentTheme === 'unicorn'
      ? 'bg-purple-900/50 backdrop-blur-xl border-white/20'
      : currentTheme === 'light'
      ? 'bg-white border-gray-200'
      : 'bg-slate-800 border-slate-700',
    text: currentTheme === 'unicorn'
      ? 'text-purple-100'
      : currentTheme === 'light'
      ? 'text-gray-900'
      : 'text-slate-100',
    subtext: currentTheme === 'unicorn'
      ? 'text-purple-300'
      : currentTheme === 'light'
      ? 'text-gray-600'
      : 'text-slate-400',
    button: currentTheme === 'unicorn'
      ? 'bg-purple-600 hover:bg-purple-700 text-white'
      : currentTheme === 'light'
      ? 'bg-blue-600 hover:bg-blue-700 text-white'
      : 'bg-blue-600 hover:bg-blue-700 text-white'
  };

  useEffect(() => {
    loadSessions();
  }, []);

  const loadSessions = async () => {
    try {
      const response = await fetch('/api/v1/auth/sessions', { credentials: 'include' });
      if (response.ok) {
        const data = await response.json();
        setSessions(data.sessions || []);
      }
    } catch (error) {
      console.error('Failed to load sessions:', error);
      setSessions([]);
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <div className={`flex items-center justify-center py-12 ${themeClasses.text}`}>
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-current"></div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className={`text-3xl font-bold ${themeClasses.text}`}>Security Settings</h1>
        <p className={`mt-2 ${themeClasses.subtext}`}>
          Manage your account security and active sessions
        </p>
      </div>

      {/* Status Message */}
      {message && (
        <motion.div
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          className={`rounded-lg p-4 ${
            message.type === 'success'
              ? 'bg-green-500/20 border border-green-500/50'
              : 'bg-red-500/20 border border-red-500/50'
          }`}
        >
          <div className="flex items-center gap-2">
            {message.type === 'success' ? (
              <>
                <CheckCircleIcon className="h-5 w-5 text-green-400" />
                <span className="text-green-400">{message.text}</span>
              </>
            ) : (
              <>
                <ExclamationCircleIcon className="h-5 w-5 text-red-400" />
                <span className="text-red-400">{message.text}</span>
              </>
            )}
          </div>
        </motion.div>
      )}

      {/* Change Password */}
      <div>
        <div className={`rounded-xl border p-6 ${themeClasses.card}`}>
          <div className="flex items-center gap-3 mb-6">
            <KeyIcon className={`h-6 w-6 ${themeClasses.text}`} />
            <h2 className={`text-xl font-semibold ${themeClasses.text}`}>
              Change Password
            </h2>
          </div>

          <div className="space-y-4">
            <p className={themeClasses.subtext}>
              Passwords are managed by Keycloak SSO. Use the account console to update your password and sign-in settings.
            </p>
            <a
              href={getKeycloakAccountSignInUrl()}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex px-4 py-2 rounded-lg font-medium bg-blue-600 hover:bg-blue-700 text-white"
            >
              Open Keycloak sign-in settings
            </a>
          </div>
        </div>
      </div>

      {/* Two-Factor Authentication */}
      <div className={`rounded-xl border p-6 ${themeClasses.card}`}>
        <div className="flex items-center gap-3 mb-6">
          <ShieldCheckIcon className={`h-6 w-6 ${themeClasses.text}`} />
          <h2 className={`text-xl font-semibold ${themeClasses.text}`}>
            Two-Factor Authentication
          </h2>
        </div>

        <div className="flex items-center justify-between">
          <div>
            <p className={`font-medium ${themeClasses.text}`}>
              Authenticator App
            </p>
            <p className={`text-sm ${themeClasses.subtext} mt-1`}>
              Use an authenticator app for additional security
            </p>
          </div>
          <button
            onClick={() => window.open(getKeycloakAccountSignInUrl(), '_blank', 'noopener,noreferrer')}
            className={`px-4 py-2 rounded-lg ${themeClasses.button}`}
          >
            Configure 2FA
          </button>
        </div>
      </div>

      {/* Active Sessions */}
      <div className={`rounded-xl border p-6 ${themeClasses.card}`}>
        <div className="flex items-center gap-3 mb-6">
          <DevicePhoneMobileIcon className={`h-6 w-6 ${themeClasses.text}`} />
          <h2 className={`text-xl font-semibold ${themeClasses.text}`}>
            Active Sessions
          </h2>
        </div>

        <div className="space-y-3">
          {sessions.length === 0 && (
            <p className={`text-sm ${themeClasses.subtext}`}>
              No active sessions reported.
            </p>
          )}
          {sessions.map((session) => (
            <motion.div
              key={session.id}
              whileHover={{ scale: 1.01 }}
              className={`p-4 rounded-lg border ${
                session.is_current
                  ? 'border-green-500/30 bg-green-500/5'
                  : currentTheme === 'light'
                  ? 'border-gray-200 bg-gray-50'
                  : 'border-gray-700 bg-gray-700/20'
              }`}
            >
              <div className="flex items-start justify-between">
                <div className="flex gap-3">
                  <ComputerDesktopIcon className={`h-5 w-5 ${themeClasses.text} mt-1`} />
                  <div>
                    <p className={`font-medium ${themeClasses.text} flex items-center gap-2`}>
                      {describeDevice(session.user_agent) || '—'}
                      {session.is_current && (
                        <span className="px-2 py-0.5 text-xs bg-green-500/20 text-green-400 rounded-full">
                          Current
                        </span>
                      )}
                    </p>
                    <div className={`text-sm ${themeClasses.subtext} mt-1 space-y-1`}>
                      <div className="flex items-center gap-2">
                        <MapPinIcon className="h-4 w-4" />
                        {/* Backend does not provide a location — only the IP address */}
                        {session.ip_address || '—'}
                      </div>
                      <div className="flex items-center gap-2">
                        <ClockIcon className="h-4 w-4" />
                        {formatSessionTime(session.last_active)
                          ? `Last active ${formatSessionTime(session.last_active)}`
                          : '—'}
                      </div>
                    </div>
                  </div>
                </div>

              </div>
            </motion.div>
          ))}
        </div>
      </div>
    </div>
  );
}
