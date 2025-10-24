/**
 * AccountAPIKeys Component
 *
 * BYOK (Bring Your Own Key) API keys management
 * - List of API keys (OpenAI, Anthropic, HuggingFace, etc.)
 * - Add/edit/delete key forms
 * - Masked display of keys for security
 * - Test key validation
 *
 * API Endpoints:
 * - GET /api/v1/auth/byok/keys - List all API keys
 * - POST /api/v1/auth/byok/keys - Add new API key
 * - PUT /api/v1/auth/byok/keys/{key_id} - Update API key
 * - DELETE /api/v1/auth/byok/keys/{key_id} - Delete API key
 * - POST /api/v1/auth/byok/keys/{key_id}/test - Test API key validity
 */

import React, { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import {
  KeyIcon,
  PlusIcon,
  TrashIcon,
  EyeIcon,
  EyeSlashIcon,
  CheckCircleIcon,
  ExclamationCircleIcon,
  PencilIcon,
  ShieldCheckIcon,
  ServerIcon,
  SparklesIcon
} from '@heroicons/react/24/outline';
import { useTheme } from '../../contexts/ThemeContext';
import BYOKWizard from '../../components/BYOKWizard';

export default function AccountAPIKeys() {
  const { theme, currentTheme } = useTheme();
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState(null);
  const [apiKeys, setApiKeys] = useState([]);
  const [showAddModal, setShowAddModal] = useState(false);
  const [editingKey, setEditingKey] = useState(null);
  const [visibleKeys, setVisibleKeys] = useState({});
  const [testingKey, setTestingKey] = useState(null);
  const [llmProviderKeys, setLLMProviderKeys] = useState([]);
  const [showBYOKWizard, setShowBYOKWizard] = useState(false);

  const [keyForm, setKeyForm] = useState({
    provider: 'openai',
    name: '',
    apiKey: '',
    description: ''
  });

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
    input: currentTheme === 'unicorn'
      ? 'bg-purple-900/50 border-white/20 text-purple-100'
      : currentTheme === 'light'
      ? 'bg-gray-50 border-gray-300 text-gray-900'
      : 'bg-slate-900 border-slate-600 text-slate-100',
    button: currentTheme === 'unicorn'
      ? 'bg-purple-600 hover:bg-purple-700 text-white'
      : currentTheme === 'light'
      ? 'bg-blue-600 hover:bg-blue-700 text-white'
      : 'bg-blue-600 hover:bg-blue-700 text-white',
    modal: currentTheme === 'unicorn'
      ? 'bg-purple-900/95 backdrop-blur-xl border-white/20'
      : currentTheme === 'light'
      ? 'bg-white border-gray-200'
      : 'bg-slate-800 border-slate-700'
  };

  const providers = [
    { value: 'openai', label: 'OpenAI', placeholder: 'sk-...' },
    { value: 'anthropic', label: 'Anthropic', placeholder: 'sk-ant-...' },
    { value: 'huggingface', label: 'HuggingFace', placeholder: 'hf_...' },
    { value: 'cohere', label: 'Cohere', placeholder: 'co-...' },
    { value: 'replicate', label: 'Replicate', placeholder: 'r8_...' },
    { value: 'custom', label: 'Custom Endpoint', placeholder: 'API Key' }
  ];

  useEffect(() => {
    loadAPIKeys();
    loadLLMProviderKeys();
  }, []);

  const loadAPIKeys = async () => {
    try {
      const response = await fetch('/api/v1/auth/byok/keys');
      if (response.ok) {
        const data = await response.json();
        setApiKeys(data.keys || []);
      }
    } catch (error) {
      console.error('Failed to load API keys:', error);
      // Mock data for demonstration
      setApiKeys([
        {
          id: '1',
          provider: 'openai',
          name: 'OpenAI Production',
          apiKey: 'REMOVED',
          description: 'Primary OpenAI key for production',
          createdAt: '2024-10-01',
          lastUsed: '2 hours ago',
          status: 'active'
        },
        {
          id: '2',
          provider: 'anthropic',
          name: 'Claude API',
          apiKey: 'sk-ant-xyz789abc123def456',
          description: 'Anthropic Claude access',
          createdAt: '2024-10-05',
          lastUsed: '1 day ago',
          status: 'active'
        }
      ]);
    } finally {
      setLoading(false);
    }
  };

  const loadLLMProviderKeys = async () => {
    try {
      const response = await fetch('/api/v1/llm/providers/keys', {
        credentials: 'include'
      });
      if (response.ok) {
        const data = await response.json();
        setLLMProviderKeys(data.keys || []);
      }
    } catch (error) {
      console.error('Failed to load LLM provider keys:', error);
      // Mock data for demonstration
      setLLMProviderKeys([
        {
          id: '1',
          provider_name: 'OpenAI (BYOK)',
          provider: 'openai',
          api_key: 'REMOVEDjkl012',
          description: 'Personal OpenAI key for testing',
          status: 'active',
          last_tested: '5 minutes ago',
          created_at: '2025-10-15'
        },
        {
          id: '2',
          provider_name: 'Anthropic (BYOK)',
          provider: 'anthropic',
          api_key: 'sk-ant-api03-xyz789abc123def456',
          description: 'Claude API access for production',
          status: 'active',
          last_tested: '1 hour ago',
          created_at: '2025-10-20'
        }
      ]);
    }
  };

  const maskKey = (key) => {
    if (key.length <= 8) return '••••••••';
    return key.substring(0, 4) + '••••••••' + key.substring(key.length - 4);
  };

  const toggleKeyVisibility = (keyId) => {
    setVisibleKeys({ ...visibleKeys, [keyId]: !visibleKeys[keyId] });
  };

  const handleAddKey = async (e) => {
    e.preventDefault();

    try {
      const response = await fetch('/api/v1/auth/byok/keys', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(keyForm)
      });

      if (response.ok) {
        const newKey = await response.json();
        setApiKeys([...apiKeys, newKey]);
        setMessage({ type: 'success', text: 'API key added successfully' });
        setShowAddModal(false);
        setKeyForm({ provider: 'openai', name: '', apiKey: '', description: '' });
        setTimeout(() => setMessage(null), 3000);
      } else {
        const error = await response.json();
        setMessage({ type: 'error', text: error.detail || 'Failed to add API key' });
      }
    } catch (error) {
      console.error('Failed to add API key:', error);
      setMessage({ type: 'error', text: 'An error occurred while adding API key' });
    }
  };

  const handleDeleteKey = async (keyId) => {
    if (!confirm('Are you sure you want to delete this API key?')) {
      return;
    }

    try {
      const response = await fetch(`/api/v1/auth/byok/keys/${keyId}`, {
        method: 'DELETE'
      });

      if (response.ok) {
        setApiKeys(apiKeys.filter(k => k.id !== keyId));
        setMessage({ type: 'success', text: 'API key deleted successfully' });
        setTimeout(() => setMessage(null), 2000);
      } else {
        setMessage({ type: 'error', text: 'Failed to delete API key' });
      }
    } catch (error) {
      console.error('Failed to delete API key:', error);
      setMessage({ type: 'error', text: 'An error occurred while deleting API key' });
    }
  };

  const handleTestKey = async (keyId) => {
    setTestingKey(keyId);

    try {
      const response = await fetch(`/api/v1/auth/byok/keys/${keyId}/test`, {
        method: 'POST'
      });

      if (response.ok) {
        setMessage({ type: 'success', text: 'API key is valid and working' });
        setTimeout(() => setMessage(null), 2000);
      } else {
        setMessage({ type: 'error', text: 'API key validation failed' });
      }
    } catch (error) {
      console.error('Failed to test API key:', error);
      setMessage({ type: 'error', text: 'An error occurred while testing API key' });
    } finally {
      setTestingKey(null);
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
      <div className="flex items-center justify-between">
        <div>
          <h1 className={`text-3xl font-bold ${themeClasses.text}`}>API Keys</h1>
          <p className={`mt-2 ${themeClasses.subtext}`}>
            Manage your BYOK (Bring Your Own Key) API credentials
          </p>
        </div>
        <button
          onClick={() => setShowAddModal(true)}
          className={`flex items-center gap-2 px-4 py-2 rounded-lg ${themeClasses.button}`}
        >
          <PlusIcon className="h-5 w-5" />
          Add API Key
        </button>
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

      {/* Security Notice */}
      <div className={`rounded-lg p-4 border ${
        currentTheme === 'light'
          ? 'bg-blue-50 border-blue-200'
          : 'bg-blue-500/10 border-blue-500/30'
      }`}>
        <div className="flex gap-3">
          <ShieldCheckIcon className="h-5 w-5 text-blue-500 flex-shrink-0 mt-0.5" />
          <div>
            <p className={`text-sm font-medium ${themeClasses.text}`}>
              Your API keys are encrypted and secure
            </p>
            <p className={`text-sm ${themeClasses.subtext} mt-1`}>
              Keys are encrypted at rest and never logged. Only you can view or use your keys.
            </p>
          </div>
        </div>
      </div>

      {/* LLM Provider Keys Section (BYOK) */}
      <div className="mb-12">
        <div className="flex items-center gap-3 mb-4">
          <div className="w-10 h-10 bg-gradient-to-br from-purple-500 to-violet-600 rounded-lg flex items-center justify-center">
            <SparklesIcon className="h-6 w-6 text-white" />
          </div>
          <div>
            <h2 className={`text-2xl font-bold ${themeClasses.text}`}>
              LLM Provider Keys (BYOK)
            </h2>
            <p className={`${themeClasses.subtext}`}>
              Bring Your Own Key for AI model providers. Use your own API keys for LLM routing.
            </p>
          </div>
        </div>

        <div className="space-y-4">
          {llmProviderKeys.length === 0 ? (
            <div className={`rounded-xl border-2 border-dashed p-12 text-center ${themeClasses.card}`}>
              <ServerIcon className={`h-12 w-12 ${themeClasses.subtext} mx-auto mb-4`} />
              <p className={`text-lg font-medium ${themeClasses.text}`}>
                No LLM provider keys configured
              </p>
              <p className={`${themeClasses.subtext} mt-2 mb-6`}>
                Add your first provider key to start using BYOK for LLM routing
              </p>
              <button
                onClick={() => setShowBYOKWizard(true)}
                className={`px-6 py-3 rounded-lg ${themeClasses.button} font-medium`}
              >
                Add Your First Provider
              </button>
            </div>
          ) : (
            <>
              {llmProviderKeys.map((key) => (
                <motion.div
                  key={key.id}
                  whileHover={{ scale: 1.01 }}
                  className={`rounded-xl border p-6 ${themeClasses.card}`}
                >
                  <div className="flex items-start justify-between">
                    <div className="flex-1">
                      <div className="flex items-center gap-3 mb-3">
                        <div className="w-10 h-10 bg-gradient-to-br from-purple-500 to-pink-600 rounded-lg flex items-center justify-center">
                          <ServerIcon className="h-5 w-5 text-white" />
                        </div>
                        <div>
                          <h3 className={`font-semibold ${themeClasses.text}`}>
                            {key.provider_name}
                          </h3>
                          <p className={`text-sm ${themeClasses.subtext}`}>
                            {key.description || 'No description'}
                          </p>
                        </div>
                      </div>

                      <div className="flex items-center gap-4 text-sm mt-3">
                        <div className={`flex items-center gap-2 px-3 py-1 rounded ${
                          currentTheme === 'light' ? 'bg-gray-100' : 'bg-gray-700/30'
                        }`}>
                          <code className={themeClasses.text}>
                            {visibleKeys[key.id] ? key.api_key : maskKey(key.api_key)}
                          </code>
                          <button
                            onClick={() => toggleKeyVisibility(key.id)}
                            className={themeClasses.subtext}
                          >
                            {visibleKeys[key.id] ? (
                              <EyeSlashIcon className="h-4 w-4" />
                            ) : (
                              <EyeIcon className="h-4 w-4" />
                            )}
                          </button>
                        </div>

                        <span className={`px-2 py-1 rounded text-xs ${
                          key.status === 'active'
                            ? 'bg-green-500/20 text-green-400 border border-green-500/30'
                            : 'bg-red-500/20 text-red-400 border border-red-500/30'
                        }`}>
                          {key.status}
                        </span>

                        <span className={`text-xs ${themeClasses.subtext}`}>
                          Last tested: {key.last_tested}
                        </span>
                      </div>
                    </div>

                    <div className="flex items-center gap-2 ml-4">
                      <button
                        onClick={() => handleTestKey(key.id)}
                        disabled={testingKey === key.id}
                        className={`p-2 rounded-lg ${themeClasses.button} disabled:opacity-50`}
                        title="Test API key"
                      >
                        {testingKey === key.id ? (
                          <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-white"></div>
                        ) : (
                          <CheckCircleIcon className="h-5 w-5" />
                        )}
                      </button>
                      <button
                        onClick={() => handleDeleteKey(key.id)}
                        className="p-2 rounded-lg text-red-400 hover:bg-red-500/10"
                        title="Delete API key"
                      >
                        <TrashIcon className="h-5 w-5" />
                      </button>
                    </div>
                  </div>
                </motion.div>
              ))}

              <button
                onClick={() => setShowBYOKWizard(true)}
                className={`w-full px-4 py-3 rounded-lg border-2 border-dashed ${
                  currentTheme === 'light'
                    ? 'border-gray-300 hover:border-gray-400 hover:bg-gray-50'
                    : 'border-slate-600 hover:border-slate-500 hover:bg-slate-700/50'
                } flex items-center justify-center gap-2 ${themeClasses.text}`}
              >
                <PlusIcon className="h-5 w-5" />
                Add Another LLM Provider
              </button>
            </>
          )}
        </div>
      </div>

      {/* Platform API Keys Section */}
      <div className="mb-4">
        <h2 className={`text-2xl font-bold ${themeClasses.text} mb-4`}>
          Platform API Keys
        </h2>
        <p className={`${themeClasses.subtext} mb-4`}>
          API keys for accessing the Unicorn Commander platform
        </p>
      </div>

      {/* API Keys List */}
      <div className="space-y-4">
        {apiKeys.length === 0 ? (
          <div className={`rounded-xl border p-12 text-center ${themeClasses.card}`}>
            <KeyIcon className={`h-12 w-12 ${themeClasses.subtext} mx-auto mb-4`} />
            <p className={`text-lg font-medium ${themeClasses.text}`}>
              No API keys configured
            </p>
            <p className={`${themeClasses.subtext} mt-2`}>
              Add your first API key to get started with BYOK
            </p>
          </div>
        ) : (
          apiKeys.map((key) => (
            <motion.div
              key={key.id}
              whileHover={{ scale: 1.01 }}
              className={`rounded-xl border p-6 ${themeClasses.card}`}
            >
              <div className="flex items-start justify-between">
                <div className="flex-1">
                  <div className="flex items-center gap-3 mb-3">
                    <div className="w-10 h-10 bg-gradient-to-br from-blue-500 to-purple-600 rounded-lg flex items-center justify-center">
                      <KeyIcon className="h-5 w-5 text-white" />
                    </div>
                    <div>
                      <h3 className={`font-semibold ${themeClasses.text}`}>
                        {key.name}
                      </h3>
                      <p className={`text-sm ${themeClasses.subtext}`}>
                        {providers.find(p => p.value === key.provider)?.label || key.provider}
                      </p>
                    </div>
                  </div>

                  {key.description && (
                    <p className={`text-sm ${themeClasses.subtext} mb-3`}>
                      {key.description}
                    </p>
                  )}

                  <div className="flex items-center gap-4 text-sm">
                    <div className={`flex items-center gap-2 px-3 py-1 rounded ${
                      currentTheme === 'light' ? 'bg-gray-100' : 'bg-gray-700/30'
                    }`}>
                      <code className={themeClasses.text}>
                        {visibleKeys[key.id] ? key.apiKey : maskKey(key.apiKey)}
                      </code>
                      <button
                        onClick={() => toggleKeyVisibility(key.id)}
                        className={themeClasses.subtext}
                      >
                        {visibleKeys[key.id] ? (
                          <EyeSlashIcon className="h-4 w-4" />
                        ) : (
                          <EyeIcon className="h-4 w-4" />
                        )}
                      </button>
                    </div>

                    <div className={`flex items-center gap-1 ${themeClasses.subtext}`}>
                      <span>Last used: {key.lastUsed}</span>
                    </div>
                  </div>
                </div>

                <div className="flex items-center gap-2 ml-4">
                  <button
                    onClick={() => handleTestKey(key.id)}
                    disabled={testingKey === key.id}
                    className={`p-2 rounded-lg ${themeClasses.button} disabled:opacity-50`}
                    title="Test API key"
                  >
                    {testingKey === key.id ? (
                      <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-white"></div>
                    ) : (
                      <CheckCircleIcon className="h-5 w-5" />
                    )}
                  </button>
                  <button
                    onClick={() => handleDeleteKey(key.id)}
                    className="p-2 rounded-lg text-red-400 hover:bg-red-500/10"
                    title="Delete API key"
                  >
                    <TrashIcon className="h-5 w-5" />
                  </button>
                </div>
              </div>
            </motion.div>
          ))
        )}
      </div>

      {/* BYOK Wizard */}
      {showBYOKWizard && (
        <BYOKWizard
          onClose={() => setShowBYOKWizard(false)}
          onComplete={() => {
            setShowBYOKWizard(false);
            loadLLMProviderKeys();
            showToast('LLM provider added successfully');
          }}
        />
      )}

      {/* Add Key Modal */}
      {showAddModal && (
        <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50">
          <motion.div
            initial={{ scale: 0.9, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            className={`rounded-xl border p-6 max-w-md w-full m-4 ${themeClasses.modal}`}
          >
            <h3 className={`text-xl font-bold ${themeClasses.text} mb-4`}>
              Add API Key
            </h3>

            <form onSubmit={handleAddKey} className="space-y-4">
              <div>
                <label className={`block text-sm font-medium mb-2 ${themeClasses.text}`}>
                  Provider
                </label>
                <select
                  value={keyForm.provider}
                  onChange={(e) => setKeyForm({ ...keyForm, provider: e.target.value })}
                  className={`w-full px-4 py-2 rounded-lg border ${themeClasses.input}`}
                >
                  {providers.map(provider => (
                    <option key={provider.value} value={provider.value}>
                      {provider.label}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className={`block text-sm font-medium mb-2 ${themeClasses.text}`}>
                  Name
                </label>
                <input
                  type="text"
                  value={keyForm.name}
                  onChange={(e) => setKeyForm({ ...keyForm, name: e.target.value })}
                  className={`w-full px-4 py-2 rounded-lg border ${themeClasses.input}`}
                  placeholder="My Production Key"
                  required
                />
              </div>

              <div>
                <label className={`block text-sm font-medium mb-2 ${themeClasses.text}`}>
                  API Key
                </label>
                <input
                  type="password"
                  value={keyForm.apiKey}
                  onChange={(e) => setKeyForm({ ...keyForm, apiKey: e.target.value })}
                  className={`w-full px-4 py-2 rounded-lg border ${themeClasses.input}`}
                  placeholder={providers.find(p => p.value === keyForm.provider)?.placeholder}
                  required
                />
              </div>

              <div>
                <label className={`block text-sm font-medium mb-2 ${themeClasses.text}`}>
                  Description (Optional)
                </label>
                <textarea
                  value={keyForm.description}
                  onChange={(e) => setKeyForm({ ...keyForm, description: e.target.value })}
                  className={`w-full px-4 py-2 rounded-lg border ${themeClasses.input}`}
                  rows="2"
                  placeholder="Additional notes about this key"
                />
              </div>

              <div className="flex gap-3 pt-4">
                <button
                  type="button"
                  onClick={() => setShowAddModal(false)}
                  className={`flex-1 px-4 py-2 rounded-lg border ${
                    currentTheme === 'light'
                      ? 'border-gray-300 text-gray-700 hover:bg-gray-50'
                      : 'border-slate-600 text-slate-300 hover:bg-slate-700'
                  }`}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className={`flex-1 px-4 py-2 rounded-lg ${themeClasses.button}`}
                >
                  Add Key
                </button>
              </div>
            </form>
          </motion.div>
        </div>
      )}
    </div>
  );
}
