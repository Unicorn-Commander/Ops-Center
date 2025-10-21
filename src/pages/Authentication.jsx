import React, { useState, useEffect } from 'react';
import { Shield, Users, Key, Settings, Server, Globe, CheckCircle, XCircle, AlertCircle } from 'lucide-react';

const Authentication = () => {
  const [authConfig, setAuthConfig] = useState({
    enabled: false,
    status: 'disabled',
    providers: []
  });
  const [loading, setLoading] = useState(true);
  const [services, setServices] = useState([]);

  useEffect(() => {
    fetchAuthStatus();
    fetchServices();
  }, []);

  const fetchAuthStatus = async () => {
    try {
      // Check if Authentik is running
      const response = await fetch('/api/v1/services');
      const services = await response.json();
      const authentikService = services.find(s => s.name.includes('authentik'));
      
      setAuthConfig({
        enabled: !!authentikService && authentikService.status === 'running',
        status: authentikService ? authentikService.status : 'disabled',
        providers: [] // TODO: Fetch configured providers
      });
    } catch (error) {
      console.error('Failed to fetch auth status:', error);
    } finally {
      setLoading(false);
    }
  };

  const fetchServices = async () => {
    try {
      const response = await fetch('/api/v1/services');
      const data = await response.json();
      setServices(data);
    } catch (error) {
      console.error('Failed to fetch services:', error);
    }
  };

  const handleEnableSSO = async () => {
    try {
      // This would call the backend to enable SSO
      const response = await fetch('/api/v1/auth/enable', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
      });
      
      if (response.ok) {
        fetchAuthStatus();
      }
    } catch (error) {
      console.error('Failed to enable SSO:', error);
    }
  };

  const handleConfigureProvider = (provider) => {
    // This would open configuration modal for the provider
    console.log(`Configure ${provider}`);
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-32 w-32 border-b-2 border-blue-500"></div>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-gray-900 dark:text-white flex items-center gap-3">
            <Shield className="w-8 h-8 text-blue-500" />
            Authentication & SSO
          </h1>
          <p className="text-gray-600 dark:text-gray-400 mt-1">
            Manage enterprise authentication and single sign-on across UC-1 Pro services
          </p>
        </div>
      </div>

      {/* Status Card */}
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-xl font-semibold text-gray-900 dark:text-white">
            SSO Status
          </h2>
          <div className={`flex items-center gap-2 px-3 py-1 rounded-full text-sm font-medium ${
            authConfig.enabled 
              ? 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200'
              : 'bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-200'
          }`}>
            {authConfig.enabled ? (
              <>
                <CheckCircle className="w-4 h-4" />
                Enabled
              </>
            ) : (
              <>
                <XCircle className="w-4 h-4" />
                Disabled
              </>
            )}
          </div>
        </div>

        {!authConfig.enabled ? (
          <div className="text-center py-8">
            <Shield className="w-16 h-16 text-gray-400 mx-auto mb-4" />
            <h3 className="text-lg font-medium text-gray-900 dark:text-white mb-2">
              Enterprise SSO Available
            </h3>
            <p className="text-gray-600 dark:text-gray-400 mb-6 max-w-md mx-auto">
              Enable Authentik SSO to provide secure, centralized authentication 
              across all UC-1 Pro services with support for Microsoft 365, Google Workspace, and more.
            </p>
            <button
              onClick={handleEnableSSO}
              className="px-6 py-2 bg-blue-500 hover:bg-blue-600 text-white rounded-lg font-medium transition-colors"
            >
              Enable SSO
            </button>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="text-center p-4">
              <Users className="w-8 h-8 text-blue-500 mx-auto mb-2" />
              <div className="text-2xl font-bold text-gray-900 dark:text-white">12</div>
              <div className="text-sm text-gray-600 dark:text-gray-400">Active Users</div>
            </div>
            <div className="text-center p-4">
              <Key className="w-8 h-8 text-green-500 mx-auto mb-2" />
              <div className="text-2xl font-bold text-gray-900 dark:text-white">2</div>
              <div className="text-sm text-gray-600 dark:text-gray-400">Auth Providers</div>
            </div>
            <div className="text-center p-4">
              <Server className="w-8 h-8 text-purple-500 mx-auto mb-2" />
              <div className="text-2xl font-bold text-gray-900 dark:text-white">8</div>
              <div className="text-sm text-gray-600 dark:text-gray-400">Protected Services</div>
            </div>
          </div>
        )}
      </div>

      {/* OAuth Providers */}
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-6">
        <h2 className="text-xl font-semibold text-gray-900 dark:text-white mb-4">
          OAuth Providers
        </h2>
        
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {/* Microsoft 365 */}
          <div className="border border-gray-200 dark:border-gray-600 rounded-lg p-4">
            <div className="flex items-center gap-3 mb-3">
              <div className="w-10 h-10 bg-blue-500 rounded-lg flex items-center justify-center">
                <Globe className="w-6 h-6 text-white" />
              </div>
              <div>
                <h3 className="font-medium text-gray-900 dark:text-white">Microsoft 365</h3>
                <p className="text-sm text-gray-600 dark:text-gray-400">Azure AD / Entra ID</p>
              </div>
            </div>
            <button
              onClick={() => handleConfigureProvider('microsoft365')}
              className="w-full px-4 py-2 text-sm border border-gray-300 dark:border-gray-600 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
              disabled={!authConfig.enabled}
            >
              Configure
            </button>
          </div>

          {/* Google Workspace */}
          <div className="border border-gray-200 dark:border-gray-600 rounded-lg p-4">
            <div className="flex items-center gap-3 mb-3">
              <div className="w-10 h-10 bg-red-500 rounded-lg flex items-center justify-center">
                <Globe className="w-6 h-6 text-white" />
              </div>
              <div>
                <h3 className="font-medium text-gray-900 dark:text-white">Google Workspace</h3>
                <p className="text-sm text-gray-600 dark:text-gray-400">Google OAuth2</p>
              </div>
            </div>
            <button
              onClick={() => handleConfigureProvider('google')}
              className="w-full px-4 py-2 text-sm border border-gray-300 dark:border-gray-600 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
              disabled={!authConfig.enabled}
            >
              Configure
            </button>
          </div>

          {/* Generic OIDC */}
          <div className="border border-gray-200 dark:border-gray-600 rounded-lg p-4">
            <div className="flex items-center gap-3 mb-3">
              <div className="w-10 h-10 bg-green-500 rounded-lg flex items-center justify-center">
                <Key className="w-6 h-6 text-white" />
              </div>
              <div>
                <h3 className="font-medium text-gray-900 dark:text-white">Generic OIDC</h3>
                <p className="text-sm text-gray-600 dark:text-gray-400">OpenID Connect</p>
              </div>
            </div>
            <button
              onClick={() => handleConfigureProvider('oidc')}
              className="w-full px-4 py-2 text-sm border border-gray-300 dark:border-gray-600 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
              disabled={!authConfig.enabled}
            >
              Configure
            </button>
          </div>
        </div>
      </div>

      {/* Service Integration Status */}
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-6">
        <h2 className="text-xl font-semibold text-gray-900 dark:text-white mb-4">
          Service Integration
        </h2>
        
        <div className="space-y-3">
          {['Open-WebUI', 'Ops Center', 'Center-Deep', 'Grafana', 'Traefik Dashboard'].map((service) => {
            const serviceData = services.find(s => s.display_name?.includes(service.split(' ')[0]));
            const isRunning = serviceData?.status === 'running';
            
            return (
              <div key={service} className="flex items-center justify-between py-2">
                <div className="flex items-center gap-3">
                  <div className={`w-3 h-3 rounded-full ${
                    isRunning ? 'bg-green-500' : 'bg-gray-400'
                  }`} />
                  <span className="font-medium text-gray-900 dark:text-white">{service}</span>
                </div>
                <div className="flex items-center gap-2">
                  {authConfig.enabled && isRunning ? (
                    <>
                      <CheckCircle className="w-4 h-4 text-green-500" />
                      <span className="text-sm text-green-600 dark:text-green-400">Protected</span>
                    </>
                  ) : (
                    <>
                      <AlertCircle className="w-4 h-4 text-gray-400" />
                      <span className="text-sm text-gray-600 dark:text-gray-400">
                        {authConfig.enabled ? 'Not Running' : 'Unprotected'}
                      </span>
                    </>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Quick Actions */}
      {authConfig.enabled && (
        <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-6">
          <h2 className="text-xl font-semibold text-gray-900 dark:text-white mb-4">
            Quick Actions
          </h2>
          
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
            <button className="flex items-center justify-center gap-2 p-4 border border-gray-200 dark:border-gray-600 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors">
              <Settings className="w-5 h-5" />
              <span>Authentik Admin</span>
            </button>
            <button className="flex items-center justify-center gap-2 p-4 border border-gray-200 dark:border-gray-600 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors">
              <Users className="w-5 h-5" />
              <span>Manage Users</span>
            </button>
            <button className="flex items-center justify-center gap-2 p-4 border border-gray-200 dark:border-gray-600 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors">
              <Key className="w-5 h-5" />
              <span>API Tokens</span>
            </button>
            <button className="flex items-center justify-center gap-2 p-4 border border-gray-200 dark:border-gray-600 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors">
              <Server className="w-5 h-5" />
              <span>Service Config</span>
            </button>
          </div>
        </div>
      )}
    </div>
  );
};

export default Authentication;