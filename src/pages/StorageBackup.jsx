import React, { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { useTheme } from '../contexts/ThemeContext';
import {
  ChartPieIcon,
  ArrowPathIcon,
  CloudArrowDownIcon,
  CloudArrowUpIcon,
  FolderIcon,
  ServerIcon,
  ClockIcon,
  Cog6ToothIcon,
  TrashIcon,
  DocumentDuplicateIcon,
  ExclamationTriangleIcon,
  CheckCircleIcon,
  InformationCircleIcon,
  CalendarIcon,
  ArchiveBoxIcon
} from '@heroicons/react/24/outline';
import { getTooltip } from '../data/tooltipContent';
import HelpTooltip from '../components/HelpTooltip';

const containerVariants = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: {
      staggerChildren: 0.1
    }
  }
};

const itemVariants = {
  hidden: { y: 20, opacity: 0 },
  visible: {
    y: 0,
    opacity: 1,
    transition: {
      duration: 0.5
    }
  }
};

export default function StorageBackup() {
  const { theme, currentTheme } = useTheme();
  const [activeTab, setActiveTab] = useState('storage');
  const [storageData, setStorageData] = useState(null);
  const [backupData, setBackupData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [showBackupModal, setShowBackupModal] = useState(false);
  const [showScheduleModal, setShowScheduleModal] = useState(false);
  const [backupConfig, setBackupConfig] = useState({
    schedule: '0 2 * * *',
    retention_days: 7,
    backup_location: '/home/ucadmin/UC-1-Pro/backups',
    backup_enabled: true
  });

  // Mock data - will be replaced with API calls
  const [mockStorageData] = useState({
    total_space: 1000 * 1024 * 1024 * 1024, // 1TB
    used_space: 350 * 1024 * 1024 * 1024,   // 350GB
    free_space: 650 * 1024 * 1024 * 1024,   // 650GB
    volumes: [
      {
        name: 'vllm_models',
        path: '/home/ucadmin/UC-1-Pro/volumes/vllm_models',
        size: 38.7 * 1024 * 1024 * 1024, // 38.7GB
        type: 'AI Models',
        health: 'healthy',
        last_accessed: '2025-01-28T10:30:00Z'
      },
      {
        name: 'embedding_models',
        path: '/home/ucadmin/UC-1-Pro/volumes/embedding_models',
        size: 2.1 * 1024 * 1024 * 1024, // 2.1GB
        type: 'AI Models',
        health: 'healthy',
        last_accessed: '2025-01-28T09:15:00Z'
      },
      {
        name: 'whisperx_models',
        path: '/home/ucadmin/UC-1-Pro/volumes/whisperx_models',
        size: 5.2 * 1024 * 1024 * 1024, // 5.2GB
        type: 'AI Models',
        health: 'healthy',
        last_accessed: '2025-01-28T08:45:00Z'
      },
      {
        name: 'kokoro_models',
        path: '/home/ucadmin/UC-1-Pro/volumes/kokoro_models',
        size: 180 * 1024 * 1024, // 180MB
        type: 'AI Models',
        health: 'healthy',
        last_accessed: '2025-01-28T07:20:00Z'
      },
      {
        name: 'postgres_data',
        path: '/var/lib/postgresql/data',
        size: 1.5 * 1024 * 1024 * 1024, // 1.5GB
        type: 'Database',
        health: 'healthy',
        last_accessed: '2025-01-28T10:35:00Z'
      },
      {
        name: 'redis_data',
        path: '/var/lib/redis',
        size: 200 * 1024 * 1024, // 200MB
        type: 'Cache',
        health: 'healthy',
        last_accessed: '2025-01-28T10:35:00Z',
        can_delete: false,
        reason: 'Required by running service'
      },
      {
        name: 'qdrant_data',
        path: '/var/lib/qdrant',
        size: 850 * 1024 * 1024, // 850MB
        type: 'Vector Database',
        health: 'healthy',
        last_accessed: '2025-01-28T10:30:00Z',
        can_delete: false,
        reason: 'Contains vector embeddings'
      },
      {
        name: 'backup_temp',
        path: '/home/ucadmin/UC-1-Pro/temp/backup',
        size: 2.3 * 1024 * 1024 * 1024, // 2.3GB
        type: 'Temporary',
        health: 'healthy',
        last_accessed: '2025-01-27T14:20:00Z',
        can_delete: true,
        reason: 'Safe to delete - temporary backup files'
      }
    ]
  });

  const [mockBackupData] = useState({
    backup_enabled: true,
    schedule: '0 2 * * *', // 2 AM daily
    last_backup: '2025-01-28T02:00:00Z',
    next_backup: '2025-01-29T02:00:00Z',
    backup_location: '/home/ucadmin/UC-1-Pro/backups',
    retention_days: 7,
    backups: [
      {
        id: 'backup-20250128-020000',
        timestamp: '2025-01-28T02:00:00Z',
        size: 45.8 * 1024 * 1024 * 1024, // 45.8GB
        type: 'Full',
        status: 'completed',
        duration: '23m 45s',
        files_count: 15420
      },
      {
        id: 'backup-20250127-020000',
        timestamp: '2025-01-27T02:00:00Z',
        size: 44.2 * 1024 * 1024 * 1024, // 44.2GB
        type: 'Full',
        status: 'completed',
        duration: '22m 18s',
        files_count: 15018
      },
      {
        id: 'backup-20250126-020000',
        timestamp: '2025-01-26T02:00:00Z',
        size: 43.9 * 1024 * 1024 * 1024, // 43.9GB
        type: 'Full',
        status: 'completed',
        duration: '21m 52s',
        files_count: 14895
      }
    ]
  });

  useEffect(() => {
    loadStorageData();
    loadBackupData();
  }, []);

  const loadStorageData = async () => {
    setLoading(true);
    try {
      const response = await fetch('/api/v1/storage');
      const data = await response.json();
      setStorageData(data);
    } catch (error) {
      console.error('Failed to load storage data:', error);
      // Fallback to mock data if API fails
      setStorageData(mockStorageData);
    } finally {
      setLoading(false);
    }
  };

  const loadBackupData = async () => {
    try {
      const response = await fetch('/api/v1/backup/status');
      const data = await response.json();
      setBackupData(data);
      
      // Update backup config form state with actual data
      setBackupConfig({
        schedule: data.schedule || '0 2 * * *',
        retention_days: data.retention_days || 7,
        backup_location: data.backup_location || '/home/ucadmin/UC-1-Pro/backups',
        backup_enabled: data.backup_enabled !== undefined ? data.backup_enabled : true
      });
    } catch (error) {
      console.error('Failed to load backup data:', error);
      // Fallback to mock data if API fails
      setBackupData(mockBackupData);
    }
  };

  const refreshData = async () => {
    setRefreshing(true);
    await Promise.all([loadStorageData(), loadBackupData()]);
    setRefreshing(false);
  };

  const handleCreateBackup = async () => {
    try {
      const response = await fetch('/api/v1/backup/create', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ backup_type: 'manual' }),
      });
      
      if (response.ok) {
        const result = await response.json();
        console.log('Backup created:', result.backup_id);
        // Refresh backup data after creation
        await loadBackupData();
      } else {
        console.error('Failed to create backup');
      }
    } catch (error) {
      console.error('Error creating backup:', error);
    } finally {
      setShowBackupModal(false);
    }
  };

  const handleRestoreBackup = async (backupId) => {
    try {
      const response = await fetch(`/api/v1/backup/${backupId}/restore`, {
        method: 'POST',
      });
      
      if (response.ok) {
        const result = await response.json();
        console.log('Backup restored:', result);
        alert(`Backup ${backupId} restored successfully to ${result.restore_path}`);
      } else {
        console.error('Failed to restore backup');
        alert('Failed to restore backup');
      }
    } catch (error) {
      console.error('Error restoring backup:', error);
      alert('Error restoring backup');
    }
  };

  const handleDeleteBackup = async (backupId) => {
    if (!confirm(`Are you sure you want to delete backup ${backupId}?`)) {
      return;
    }

    try {
      const response = await fetch(`/api/v1/backup/${backupId}`, {
        method: 'DELETE',
      });
      
      if (response.ok) {
        console.log('Backup deleted:', backupId);
        // Refresh backup data after deletion
        await loadBackupData();
      } else {
        console.error('Failed to delete backup');
        alert('Failed to delete backup');
      }
    } catch (error) {
      console.error('Error deleting backup:', error);
      alert('Error deleting backup');
    }
  };

  const handleSaveBackupConfig = async () => {
    try {
      const response = await fetch('/api/v1/backup/config', {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(backupConfig),
      });
      
      if (response.ok) {
        const result = await response.json();
        console.log('Backup configuration saved:', result);
        // Refresh backup data to show updated config
        await loadBackupData();
      } else {
        console.error('Failed to save backup configuration');
        alert('Failed to save backup configuration');
      }
    } catch (error) {
      console.error('Error saving backup configuration:', error);
      alert('Error saving backup configuration');
    } finally {
      setShowScheduleModal(false);
    }
  };

  const formatBytes = (bytes) => {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return `${parseFloat((bytes / Math.pow(k, i)).toFixed(2))} ${sizes[i]}`;
  };

  const formatDate = (dateString) => {
    return new Date(dateString).toLocaleString();
  };

  const getHealthColor = (health) => {
    switch (health) {
      case 'healthy': return 'text-green-600 dark:text-green-400';
      case 'warning': return 'text-yellow-600 dark:text-yellow-400';
      case 'error': return 'text-red-600 dark:text-red-400';
      default: return 'text-gray-600 dark:text-gray-400';
    }
  };

  const getHealthIcon = (health) => {
    switch (health) {
      case 'healthy': return CheckCircleIcon;
      case 'warning': return ExclamationTriangleIcon;
      case 'error': return ExclamationTriangleIcon;
      default: return InformationCircleIcon;
    }
  };

  if (loading || !storageData || !backupData) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="animate-spin rounded-full h-32 w-32 border-b-2 border-blue-600"></div>
      </div>
    );
  }

  return (
    <motion.div 
      className="space-y-6"
      variants={containerVariants}
      initial="hidden"
      animate="visible"
    >
      {/* Header */}
      <motion.div variants={itemVariants} className="flex justify-between items-start">
        <div>
          <h1 className="text-3xl font-bold text-gray-900 dark:text-white">
            Storage & Backup Management
          </h1>
          <p className="mt-2 text-gray-600 dark:text-gray-400">
            Monitor storage usage, manage volumes, and configure backups
          </p>
        </div>
        
        <button
          onClick={refreshData}
          disabled={refreshing}
          className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
        >
          <ArrowPathIcon className={`h-5 w-5 ${refreshing ? 'animate-spin' : ''}`} />
          {refreshing ? 'Refreshing...' : 'Refresh'}
        </button>
      </motion.div>

      {/* Tab Navigation */}
      <motion.div variants={itemVariants} className="border-b dark:border-gray-700">
        <nav className="-mb-px flex space-x-8">
          <button
            onClick={() => setActiveTab('storage')}
            className={`py-2 px-1 border-b-2 font-medium text-sm ${
              activeTab === 'storage'
                ? 'border-blue-500 text-blue-600 dark:text-blue-400'
                : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
            }`}
          >
            <div className="flex items-center gap-2">
              <ServerIcon className="h-5 w-5" />
              Storage Overview
            </div>
          </button>
          <button
            onClick={() => setActiveTab('volumes')}
            className={`py-2 px-1 border-b-2 font-medium text-sm ${
              activeTab === 'volumes'
                ? 'border-blue-500 text-blue-600 dark:text-blue-400'
                : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
            }`}
          >
            <div className="flex items-center gap-2">
              <FolderIcon className="h-5 w-5" />
              Volume Management
            </div>
          </button>
          <button
            onClick={() => setActiveTab('backup')}
            className={`py-2 px-1 border-b-2 font-medium text-sm ${
              activeTab === 'backup'
                ? 'border-blue-500 text-blue-600 dark:text-blue-400'
                : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
            }`}
          >
            <div className="flex items-center gap-2">
              <ArchiveBoxIcon className="h-5 w-5" />
              Backup & Recovery
            </div>
          </button>
        </nav>
      </motion.div>

      {/* Storage Overview Tab */}
      {activeTab === 'storage' && (
        <>
          {/* Storage Summary Cards */}
          <motion.div variants={itemVariants} className="grid grid-cols-1 md:grid-cols-3 gap-6">
            <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-gray-600 dark:text-gray-400">Total Storage</p>
                  <p className="text-2xl font-bold text-gray-900 dark:text-white">
                    {formatBytes(storageData.total_space)}
                  </p>
                </div>
                <ServerIcon className="h-8 w-8 text-blue-500" />
              </div>
            </div>

            <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-gray-600 dark:text-gray-400">Used Storage</p>
                  <p className="text-2xl font-bold text-gray-900 dark:text-white">
                    {formatBytes(storageData.used_space)}
                  </p>
                  <p className="text-sm text-gray-500">
                    {((storageData.used_space / storageData.total_space) * 100).toFixed(1)}% used
                  </p>
                </div>
                <ChartPieIcon className="h-8 w-8 text-yellow-500" />
              </div>
            </div>

            <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-gray-600 dark:text-gray-400">Available Storage</p>
                  <p className="text-2xl font-bold text-gray-900 dark:text-white">
                    {formatBytes(storageData.free_space)}
                  </p>
                  <p className="text-sm text-gray-500">
                    {((storageData.free_space / storageData.total_space) * 100).toFixed(1)}% free
                  </p>
                </div>
                <CloudArrowDownIcon className="h-8 w-8 text-green-500" />
              </div>
            </div>
          </motion.div>

          {/* Storage Usage Chart */}
          <motion.div variants={itemVariants} className="bg-white dark:bg-gray-800 rounded-lg shadow p-6">
            <h2 className="text-lg font-semibold mb-4 text-gray-900 dark:text-white">Storage Usage</h2>
            
            {/* Progress bar */}
            <div className="mb-4">
              <div className="flex justify-between text-sm text-gray-600 dark:text-gray-400 mb-2">
                <span>Used: {formatBytes(storageData.used_space)}</span>
                <span>Free: {formatBytes(storageData.free_space)}</span>
              </div>
              <div className="w-full bg-gray-200 dark:bg-gray-700 rounded-full h-4">
                <div 
                  className="bg-blue-600 h-4 rounded-full" 
                  style={{ 
                    width: `${(storageData.used_space / storageData.total_space) * 100}%` 
                  }}
                ></div>
              </div>
            </div>

            {/* Storage breakdown by type */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-6">
              {Object.entries(
                storageData.volumes.reduce((acc, volume) => {
                  acc[volume.type] = (acc[volume.type] || 0) + volume.size;
                  return acc;
                }, {})
              ).map(([type, size]) => (
                <div key={type} className="text-center">
                  <p className="text-2xl font-bold text-gray-900 dark:text-white">
                    {formatBytes(size)}
                  </p>
                  <p className="text-sm text-gray-600 dark:text-gray-400">{type}</p>
                </div>
              ))}
            </div>
          </motion.div>
        </>
      )}

      {/* Volume Management Tab */}
      {activeTab === 'volumes' && (
        <motion.div variants={itemVariants} className="bg-white dark:bg-gray-800 rounded-lg shadow">
          <div className="p-6 border-b dark:border-gray-700">
            <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Volume Management</h2>
            <p className="text-sm text-gray-600 dark:text-gray-400 mt-1">
              Monitor and manage storage volumes
            </p>
          </div>

          <div className="p-6 space-y-4">
            {storageData.volumes.map((volume) => {
              const HealthIcon = getHealthIcon(volume.health);
              return (
                <div
                  key={volume.name}
                  className="border dark:border-gray-700 rounded-lg p-4 hover:bg-gray-50 dark:hover:bg-gray-700/50"
                >
                  <div className="flex justify-between items-start">
                    <div className="flex-1">
                      <div className="flex items-center gap-3 mb-2">
                        <FolderIcon className="h-6 w-6 text-blue-500" />
                        <div>
                          <h3 className="font-medium text-gray-900 dark:text-white">{volume.name}</h3>
                          <p className="text-sm text-gray-600 dark:text-gray-400">{volume.path}</p>
                        </div>
                      </div>
                      
                      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
                        <div>
                          <span className="text-gray-600 dark:text-gray-400">Size:</span>
                          <span className="ml-2 font-medium text-gray-900 dark:text-white">
                            {formatBytes(volume.size)}
                          </span>
                        </div>
                        <div>
                          <span className="text-gray-600 dark:text-gray-400">Type:</span>
                          <span className="ml-2 font-medium text-gray-900 dark:text-white">
                            {volume.type}
                          </span>
                        </div>
                        <div className="flex items-center">
                          <span className="text-gray-600 dark:text-gray-400">Health:</span>
                          <HealthIcon className={`ml-2 h-4 w-4 ${getHealthColor(volume.health)}`} />
                          <span className={`ml-1 font-medium capitalize ${getHealthColor(volume.health)}`}>
                            {volume.health}
                          </span>
                        </div>
                        <div className="flex items-center gap-1">
                          <span className="text-gray-600 dark:text-gray-400">Last Access:</span>
                          <span className="ml-2 font-medium text-gray-900 dark:text-white">
                            {formatDate(volume.last_accessed)}
                          </span>
                        </div>
                      </div>
                      
                      <div className="mt-3 flex items-center gap-2">
                        <span className="text-gray-600 dark:text-gray-400 text-sm">Mount Point:</span>
                        <code className="text-xs bg-gray-100 dark:bg-gray-700 px-2 py-1 rounded font-mono">
                          {volume.path}
                        </code>
                        <HelpTooltip 
                          title={getTooltip('storage', 'mountPoint').title}
                          content={getTooltip('storage', 'mountPoint').content}
                          position="top"
                        />
                      </div>
                      
                      {/* Volume Actions/Status */}
                      <div className="mt-3 pt-3 border-t dark:border-gray-600">
                        {!volume.can_delete ? (
                          <div className="flex items-center gap-2 text-sm">
                            <ExclamationTriangleIcon className="h-4 w-4 text-yellow-500" />
                            <span className="text-yellow-700 dark:text-yellow-300">
                              Cannot delete: {volume.reason}
                            </span>
                            <HelpTooltip 
                              title={getTooltip('storage', 'volumeInUse').title}
                              content={getTooltip('storage', 'volumeInUse').content}
                              position="top"
                            />
                          </div>
                        ) : (
                          <div className="flex items-center justify-between">
                            <div className="flex items-center gap-2 text-sm">
                              <CheckCircleIcon className="h-4 w-4 text-green-500" />
                              <span className="text-green-700 dark:text-green-300">
                                Safe to manage: {volume.reason}
                              </span>
                            </div>
                            <div className="flex gap-2">
                              <button className="px-3 py-1 text-xs bg-blue-100 text-blue-700 hover:bg-blue-200 dark:bg-blue-900 dark:text-blue-300 dark:hover:bg-blue-800 rounded">
                                Backup
                              </button>
                              <button className="px-3 py-1 text-xs bg-red-100 text-red-700 hover:bg-red-200 dark:bg-red-900 dark:text-red-300 dark:hover:bg-red-800 rounded">
                                Delete
                              </button>
                            </div>
                          </div>
                        )}
                      </div>
                    </div>
                    
                    <div className="flex gap-2">
                      <button className="px-3 py-1 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 flex items-center gap-1">
                        <InformationCircleIcon className="h-4 w-4" />
                        Details
                      </button>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </motion.div>
      )}

      {/* Backup & Recovery Tab */}
      {activeTab === 'backup' && (
        <>
          {/* Backup Status Cards */}
          <motion.div variants={itemVariants} className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
            <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-gray-600 dark:text-gray-400">Backup Status</p>
                  <p className={`text-lg font-bold ${backupData.backup_enabled ? 'text-green-600' : 'text-red-600'}`}>
                    {backupData.backup_enabled ? 'Enabled' : 'Disabled'}
                  </p>
                </div>
                <ArchiveBoxIcon className={`h-8 w-8 ${backupData.backup_enabled ? 'text-green-500' : 'text-red-500'}`} />
              </div>
            </div>

            <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-gray-600 dark:text-gray-400">Last Backup</p>
                  <p className="text-lg font-bold text-gray-900 dark:text-white">
                    {formatDate(backupData.last_backup)}
                  </p>
                </div>
                <ClockIcon className="h-8 w-8 text-blue-500" />
              </div>
            </div>

            <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-gray-600 dark:text-gray-400">Next Backup</p>
                  <p className="text-lg font-bold text-gray-900 dark:text-white">
                    {formatDate(backupData.next_backup)}
                  </p>
                </div>
                <CalendarIcon className="h-8 w-8 text-yellow-500" />
              </div>
            </div>

            <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-gray-600 dark:text-gray-400">Retention</p>
                  <p className="text-lg font-bold text-gray-900 dark:text-white">
                    {backupData.retention_days} days
                  </p>
                </div>
                <TrashIcon className="h-8 w-8 text-purple-500" />
              </div>
            </div>
          </motion.div>

          {/* Backup Actions */}
          <motion.div variants={itemVariants} className="flex gap-4">
            <button
              onClick={handleCreateBackup}
              className="px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 flex items-center gap-2"
            >
              <CloudArrowUpIcon className="h-5 w-5" />
              Start Backup Now
            </button>
            <button
              onClick={() => setShowScheduleModal(true)}
              className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 flex items-center gap-2"
            >
              <Cog6ToothIcon className="h-5 w-5" />
              Configure Schedule
            </button>
          </motion.div>

          {/* Backup Configuration Modal */}
          {showScheduleModal && (
            <motion.div 
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50"
            >
              <motion.div
                initial={{ scale: 0.95, opacity: 0 }}
                animate={{ scale: 1, opacity: 1 }}
                className="bg-white dark:bg-gray-800 rounded-lg shadow-xl max-w-2xl w-full mx-4 max-h-[90vh] overflow-y-auto"
              >
                <div className="p-6">
                  <div className="flex justify-between items-center mb-6">
                    <h2 className="text-xl font-semibold text-gray-900 dark:text-white">
                      Backup Configuration
                    </h2>
                    <button
                      onClick={() => setShowScheduleModal(false)}
                      className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
                    >
                      <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                      </svg>
                    </button>
                  </div>

                  <div className="space-y-6">
                    {/* Backup Schedule */}
                    <div>
                      <div className="flex items-center gap-2 mb-2">
                        <label className="text-sm font-medium text-gray-700 dark:text-gray-300">
                          Backup Schedule (Cron Format)
                        </label>
                        <HelpTooltip 
                          title={getTooltip('settings', 'backupSchedule').title}
                          content={getTooltip('settings', 'backupSchedule').content}
                          position="right"
                        />
                      </div>
                      <input
                        type="text"
                        value={backupConfig.schedule}
                        onChange={(e) => setBackupConfig({...backupConfig, schedule: e.target.value})}
                        className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md shadow-sm focus:ring-blue-500 focus:border-blue-500 dark:bg-gray-700 dark:text-white"
                        placeholder="0 2 * * * (Daily at 2 AM)"
                      />
                      <p className="mt-1 text-sm text-gray-500">
                        Examples: "0 2 * * *" (Daily at 2 AM), "0 2 * * 0" (Weekly on Sunday at 2 AM)
                        <br />Format: minute hour day month weekday
                      </p>
                    </div>

                    {/* Retention Days */}
                    <div>
                      <div className="flex items-center gap-2 mb-2">
                        <label className="text-sm font-medium text-gray-700 dark:text-gray-300">
                          Retention Days
                        </label>
                        <HelpTooltip 
                          title="Backup Retention"
                          content="Number of days to keep backup files before automatic deletion. Longer retention provides more recovery options but uses more storage."
                          position="right"
                        />
                      </div>
                      <input
                        type="number"
                        value={backupConfig.retention_days}
                        onChange={(e) => setBackupConfig({...backupConfig, retention_days: parseInt(e.target.value)})}
                        min="1"
                        max="365"
                        className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md shadow-sm focus:ring-blue-500 focus:border-blue-500 dark:bg-gray-700 dark:text-white"
                      />
                      <p className="mt-1 text-sm text-gray-500">
                        Number of days to keep backups before automatic deletion
                      </p>
                    </div>

                    {/* Backup Location */}
                    <div>
                      <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                        Backup Location
                      </label>
                      <input
                        type="text"
                        value={backupConfig.backup_location}
                        onChange={(e) => setBackupConfig({...backupConfig, backup_location: e.target.value})}
                        className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md shadow-sm focus:ring-blue-500 focus:border-blue-500 dark:bg-gray-700 dark:text-white"
                      />
                    </div>

                    {/* Enable/Disable Backups */}
                    <div className="flex items-center">
                      <input
                        type="checkbox"
                        id="backup-enabled"
                        checked={backupConfig.backup_enabled}
                        onChange={(e) => setBackupConfig({...backupConfig, backup_enabled: e.target.checked})}
                        className="h-4 w-4 text-blue-600 focus:ring-blue-500 border-gray-300 rounded"
                      />
                      <label htmlFor="backup-enabled" className="ml-2 block text-sm text-gray-900 dark:text-white">
                        Enable automatic backups
                      </label>
                    </div>
                  </div>

                  <div className="flex justify-end gap-3 mt-8">
                    <button
                      onClick={() => setShowScheduleModal(false)}
                      className="px-4 py-2 text-sm font-medium text-gray-700 bg-gray-100 hover:bg-gray-200 dark:bg-gray-600 dark:text-gray-300 dark:hover:bg-gray-500 rounded-md"
                    >
                      Cancel
                    </button>
                    <button
                      onClick={handleSaveBackupConfig}
                      className="px-4 py-2 text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 rounded-md"
                    >
                      Save Configuration
                    </button>
                  </div>
                </div>
              </motion.div>
            </motion.div>
          )}

          {/* Backup History */}
          <motion.div variants={itemVariants} className="bg-white dark:bg-gray-800 rounded-lg shadow">
            <div className="p-6 border-b dark:border-gray-700">
              <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Backup History</h2>
              <p className="text-sm text-gray-600 dark:text-gray-400 mt-1">
                Recent backup operations and their status
              </p>
            </div>

            <div className="p-6 space-y-4">
              {backupData.backups.map((backup) => (
                <div
                  key={backup.id}
                  className="border dark:border-gray-700 rounded-lg p-4 hover:bg-gray-50 dark:hover:bg-gray-700/50"
                >
                  <div className="flex justify-between items-start">
                    <div className="flex-1">
                      <div className="flex items-center gap-3 mb-2">
                        <ArchiveBoxIcon className="h-6 w-6 text-green-500" />
                        <div>
                          <h3 className="font-medium text-gray-900 dark:text-white">{backup.id}</h3>
                          <p className="text-sm text-gray-600 dark:text-gray-400">
                            {formatDate(backup.timestamp)}
                          </p>
                        </div>
                      </div>
                      
                      <div className="grid grid-cols-2 md:grid-cols-5 gap-4 text-sm">
                        <div>
                          <span className="text-gray-600 dark:text-gray-400">Size:</span>
                          <span className="ml-2 font-medium text-gray-900 dark:text-white">
                            {formatBytes(backup.size)}
                          </span>
                        </div>
                        <div>
                          <span className="text-gray-600 dark:text-gray-400">Type:</span>
                          <span className="ml-2 font-medium text-gray-900 dark:text-white">
                            {backup.type}
                          </span>
                        </div>
                        <div>
                          <span className="text-gray-600 dark:text-gray-400">Duration:</span>
                          <span className="ml-2 font-medium text-gray-900 dark:text-white">
                            {backup.duration}
                          </span>
                        </div>
                        <div>
                          <span className="text-gray-600 dark:text-gray-400">Files:</span>
                          <span className="ml-2 font-medium text-gray-900 dark:text-white">
                            {backup.files_count.toLocaleString()}
                          </span>
                        </div>
                        <div className="flex items-center">
                          <CheckCircleIcon className="h-4 w-4 text-green-500 mr-1" />
                          <span className="font-medium text-green-600 dark:text-green-400 capitalize">
                            {backup.status}
                          </span>
                        </div>
                      </div>
                    </div>
                    
                    <div className="flex gap-2">
                      <button 
                        onClick={() => handleRestoreBackup(backup.id)}
                        className="px-3 py-1 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 flex items-center gap-1"
                      >
                        <CloudArrowDownIcon className="h-4 w-4" />
                        Restore
                      </button>
                      <button 
                        onClick={() => handleDeleteBackup(backup.id)}
                        className="px-3 py-1 text-sm bg-red-600 text-white rounded hover:bg-red-700 flex items-center gap-1"
                      >
                        <TrashIcon className="h-4 w-4" />
                        Delete
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </motion.div>
        </>
      )}
    </motion.div>
  );
}