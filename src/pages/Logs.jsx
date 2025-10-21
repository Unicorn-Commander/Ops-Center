import React, { useState, useEffect, useRef } from 'react';
import { motion } from 'framer-motion';
import {
  DocumentTextIcon,
  ArrowPathIcon,
  FunnelIcon,
  MagnifyingGlassIcon,
  ArrowDownTrayIcon,
  EyeIcon,
  ClockIcon,
  ServerIcon,
  ExclamationTriangleIcon,
  ExclamationCircleIcon,
  InformationCircleIcon,
  CheckCircleIcon,
  XMarkIcon,
  PlayIcon,
  PauseIcon,
  TrashIcon,
  AdjustmentsHorizontalIcon
} from '@heroicons/react/24/outline';

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

const logLevels = {
  ERROR: { color: 'text-red-600 dark:text-red-400', bg: 'bg-red-50 dark:bg-red-900/20', icon: ExclamationCircleIcon },
  WARN: { color: 'text-yellow-600 dark:text-yellow-400', bg: 'bg-yellow-50 dark:bg-yellow-900/20', icon: ExclamationTriangleIcon },
  WARNING: { color: 'text-yellow-600 dark:text-yellow-400', bg: 'bg-yellow-50 dark:bg-yellow-900/20', icon: ExclamationTriangleIcon },
  INFO: { color: 'text-blue-600 dark:text-blue-400', bg: 'bg-blue-50 dark:bg-blue-900/20', icon: InformationCircleIcon },
  DEBUG: { color: 'text-gray-600 dark:text-gray-400', bg: 'bg-gray-50 dark:bg-gray-900/20', icon: CheckCircleIcon },
  SUCCESS: { color: 'text-green-600 dark:text-green-400', bg: 'bg-green-50 dark:bg-green-900/20', icon: CheckCircleIcon }
};

export default function Logs() {
  const [activeTab, setActiveTab] = useState('live');
  const [selectedService, setSelectedService] = useState('all');
  const [logLevel, setLogLevel] = useState('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  const [logs, setLogs] = useState([]);
  const [filteredLogs, setFilteredLogs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showFilters, setShowFilters] = useState(false);
  const [autoScroll, setAutoScroll] = useState(true);
  const [maxLines, setMaxLines] = useState(1000);
  const [logSources, setLogSources] = useState([]);
  const [selectedSource, setSelectedSource] = useState(null);
  const wsRef = useRef(null);
  const logsEndRef = useRef(null);
  const logsContainerRef = useRef(null);

  // Load log sources on mount
  useEffect(() => {
    loadLogSources();
    return () => {
      // Cleanup WebSocket on unmount
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, []);

  useEffect(() => {
    if (selectedSource) {
      if (isStreaming) {
        startStreaming();
      } else {
        loadLogs();
      }
    }
  }, [selectedSource, isStreaming]);

  useEffect(() => {
    filterLogs();
  }, [logs, searchQuery, logLevel]);

  useEffect(() => {
    if (autoScroll && logsEndRef.current) {
      logsEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [filteredLogs, autoScroll]);

  const loadLogSources = async () => {
    try {
      const response = await fetch('/api/v1/logs/sources');
      const data = await response.json();
      setLogSources(data.sources || []);
      
      // Auto-select first source if available
      if (data.sources && data.sources.length > 0) {
        setSelectedSource(data.sources[0].id);
      }
    } catch (error) {
      console.error('Failed to load log sources:', error);
    }
  };

  const loadLogs = async () => {
    if (!selectedSource) return;
    
    setLoading(true);
    try {
      const filters = {
        sources: [selectedSource],
        limit: maxLines
      };
      
      if (logLevel !== 'all') {
        filters.levels = [logLevel.toUpperCase()];
      }
      
      if (searchQuery) {
        filters.search = searchQuery;
      }
      
      const response = await fetch('/api/v1/logs/search', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(filters)
      });
      
      const data = await response.json();
      setLogs(data.logs || []);
    } catch (error) {
      console.error('Failed to load logs:', error);
    } finally {
      setLoading(false);
    }
  };

  const startStreaming = () => {
    if (!selectedSource || wsRef.current) return;
    
    // Construct WebSocket URL with filters
    const wsUrl = new URL(`ws://localhost:8084/ws/logs/${encodeURIComponent(selectedSource)}`, window.location.href);
    if (logLevel !== 'all') {
      wsUrl.searchParams.append('levels', logLevel.toUpperCase());
    }
    if (searchQuery) {
      wsUrl.searchParams.append('search', searchQuery);
    }
    
    wsRef.current = new WebSocket(wsUrl.href);
    
    wsRef.current.onopen = () => {
      console.log('Log streaming connected');
      setIsStreaming(true);
    };
    
    wsRef.current.onmessage = (event) => {
      try {
        const logEntry = JSON.parse(event.data);
        setLogs(prev => [...prev.slice(-maxLines + 1), logEntry]);
      } catch (error) {
        console.error('Failed to parse log entry:', error);
      }
    };
    
    wsRef.current.onclose = () => {
      console.log('Log streaming disconnected');
      setIsStreaming(false);
      wsRef.current = null;
    };
    
    wsRef.current.onerror = (error) => {
      console.error('WebSocket error:', error);
      setIsStreaming(false);
    };
  };
  
  const stopStreaming = () => {
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    setIsStreaming(false);
  };
  
  const refreshLogs = () => {
    if (isStreaming) {
      stopStreaming();
      setLogs([]);
      startStreaming();
    } else {
      loadLogs();
    }
  };

  const filterLogs = () => {
    // If streaming, filtering is done server-side
    if (isStreaming) {
      setFilteredLogs(logs);
      return;
    }
    
    let filtered = logs;
    
    // Client-side filtering for non-streaming mode
    if (searchQuery && !isStreaming) {
      filtered = filtered.filter(log => 
        log.message.toLowerCase().includes(searchQuery.toLowerCase()) ||
        log.source.toLowerCase().includes(searchQuery.toLowerCase())
      );
    }
    
    setFilteredLogs(filtered);
  };

  const clearLogs = () => {
    setLogs([]);
    setFilteredLogs([]);
  };

  const exportLogs = async () => {
    try {
      const filters = {
        limit: maxLines,
        format: 'json'
      };
      
      if (selectedSource) {
        filters.sources = [selectedSource];
      }
      
      if (logLevel !== 'all') {
        filters.levels = [logLevel.toUpperCase()];
      }
      
      if (searchQuery) {
        filters.search = searchQuery;
      }
      
      const response = await fetch('/api/v1/logs/export', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filters, format: 'json' })
      });
      
      const result = await response.json();
      
      if (result.success) {
        // Create download link
        const dataStr = JSON.stringify(result, null, 2);
        const dataUri = 'data:application/json;charset=utf-8,'+ encodeURIComponent(dataStr);
        const linkElement = document.createElement('a');
        linkElement.setAttribute('href', dataUri);
        linkElement.setAttribute('download', result.filename);
        linkElement.click();
      } else {
        alert(`Export failed: ${result.error}`);
      }
    } catch (error) {
      console.error('Failed to export logs:', error);
      alert('Failed to export logs');
    }
  };

  const getLevelIcon = (level) => {
    const config = logLevels[level] || logLevels.INFO;
    const Icon = config.icon;
    return <Icon className={`h-4 w-4 ${config.color}`} />;
  };
  
  const getSourceName = (sourceId) => {
    const source = logSources.find(s => s.id === sourceId);
    return source ? source.name : sourceId;
  };

  return (
    <motion.div
      initial="hidden"
      animate="visible"
      variants={containerVariants}
      className="space-y-6"
    >
      {/* Header */}
      <motion.div variants={itemVariants} className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white flex items-center gap-3">
            <DocumentTextIcon className="h-8 w-8 text-blue-600" />
            Logs & Diagnostics
          </h1>
          <p className="mt-1 text-sm text-gray-600 dark:text-gray-400">
            Monitor and analyze system logs in real-time
          </p>
        </div>
        
        <div className="flex items-center gap-3">
          <button
            onClick={refreshLogs}
            className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 flex items-center gap-2"
          >
            <ArrowPathIcon className="h-5 w-5" />
            Refresh
          </button>
        </div>
      </motion.div>

      {/* Tab Navigation */}
      <motion.div variants={itemVariants} className="border-b dark:border-gray-700">
        <nav className="-mb-px flex space-x-8">
          <button
            onClick={() => setActiveTab('live')}
            className={`py-2 px-1 border-b-2 font-medium text-sm ${
              activeTab === 'live'
                ? 'border-blue-500 text-blue-600 dark:text-blue-400'
                : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
            }`}
          >
            <div className="flex items-center gap-2">
              <EyeIcon className="h-5 w-5" />
              Live Logs
            </div>
          </button>
          <button
            onClick={() => setActiveTab('history')}
            className={`py-2 px-1 border-b-2 font-medium text-sm ${
              activeTab === 'history'
                ? 'border-blue-500 text-blue-600 dark:text-blue-400'
                : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
            }`}
          >
            <div className="flex items-center gap-2">
              <ClockIcon className="h-5 w-5" />
              Log History
            </div>
          </button>
        </nav>
      </motion.div>

      {/* Tab Content */}
      {activeTab === 'live' && (
        <motion.div variants={itemVariants} className="space-y-4">
          {/* Controls */}
          <div className="bg-white dark:bg-gray-800 rounded-lg p-4 shadow-sm">
            {/* Filter Bar */}
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-4 flex-1">
                <select
                  value={selectedSource || ''}
                  onChange={(e) => setSelectedSource(e.target.value)}
                  className="px-3 py-2 bg-white dark:bg-gray-700 border border-gray-300 dark:border-gray-600 rounded-lg text-sm focus:ring-2 focus:ring-blue-500"
                >
                  <option value="">Select Log Source</option>
                  {logSources.map(source => (
                    <option key={source.id} value={source.id}>
                      {source.name} ({source.type})
                    </option>
                  ))}
                </select>

                <select
                  value={logLevel}
                  onChange={(e) => setLogLevel(e.target.value)}
                  className="px-3 py-2 bg-white dark:bg-gray-700 border border-gray-300 dark:border-gray-600 rounded-lg text-sm focus:ring-2 focus:ring-blue-500"
                >
                  <option value="all">All Levels</option>
                  <option value="error">Error</option>
                  <option value="warn">Warning</option>
                  <option value="info">Info</option>
                  <option value="debug">Debug</option>
                </select>

                <div className="flex-1 relative">
                  <MagnifyingGlassIcon className="absolute left-3 top-1/2 transform -translate-y-1/2 h-5 w-5 text-gray-400" />
                  <input
                    type="text"
                    placeholder="Search logs..."
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    className="w-full pl-10 pr-4 py-2 bg-white dark:bg-gray-700 border border-gray-300 dark:border-gray-600 rounded-lg text-sm focus:ring-2 focus:ring-blue-500"
                  />
                </div>
              </div>

              <div className="flex items-center gap-2">
                <button
                  onClick={() => {
                    if (isStreaming) {
                      stopStreaming();
                    } else {
                      startStreaming();
                    }
                  }}
                  disabled={!selectedSource}
                  className={`flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
                    isStreaming
                      ? 'bg-red-600 text-white hover:bg-red-700'
                      : 'bg-green-600 text-white hover:bg-green-700 disabled:bg-gray-400 disabled:cursor-not-allowed'
                  }`}
                >
                  {isStreaming ? (
                    <><PauseIcon className="h-4 w-4" /> Stop Streaming</>
                  ) : (
                    <><PlayIcon className="h-4 w-4" /> Start Streaming</>
                  )}
                </button>

                <button
                  onClick={() => setShowFilters(!showFilters)}
                  className="px-3 py-2 bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-600"
                >
                  <FunnelIcon className="h-5 w-5" />
                </button>
              </div>
            </div>

            {/* Advanced Filters (collapsible) */}
            {showFilters && (
              <div className="border-t dark:border-gray-700 pt-4">
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                  <div>
                    <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                      Max Lines
                    </label>
                    <input
                      type="number"
                      value={maxLines}
                      onChange={(e) => setMaxLines(parseInt(e.target.value) || 1000)}
                      className="w-full px-3 py-2 bg-white dark:bg-gray-700 border border-gray-300 dark:border-gray-600 rounded-lg text-sm"
                    />
                  </div>
                  
                  <div>
                    <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                      Auto Scroll
                    </label>
                    <label className="flex items-center gap-2">
                      <input
                        type="checkbox"
                        checked={autoScroll}
                        onChange={(e) => setAutoScroll(e.target.checked)}
                        className="rounded text-blue-600 focus:ring-blue-500"
                      />
                      <span className="text-sm text-gray-700 dark:text-gray-300">
                        Automatically scroll to new logs
                      </span>
                    </label>
                  </div>
                  
                  <div className="flex items-end gap-2">
                    <button
                      onClick={clearLogs}
                      className="px-3 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 flex items-center gap-2"
                    >
                      <TrashIcon className="h-4 w-4" />
                      Clear
                    </button>
                    
                    <button
                      onClick={exportLogs}
                      className="px-3 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 flex items-center gap-2"
                    >
                      <ArrowDownTrayIcon className="h-4 w-4" />
                      Export
                    </button>
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* Log Viewer */}
          <div className="bg-gray-900 rounded-lg shadow-sm overflow-hidden">
            <div 
              ref={logsContainerRef}
              className="h-[600px] overflow-y-auto p-4 font-mono text-sm"
            >
              {loading ? (
                <div className="flex items-center justify-center h-full">
                  <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500"></div>
                </div>
              ) : filteredLogs.length === 0 ? (
                <div className="text-center text-gray-500 py-8">
                  {selectedSource ? 'No logs found' : 'Select a log source to view logs'}
                </div>
              ) : (
                <div className="space-y-1">
                  {filteredLogs.map((log, index) => (
                    <div
                      key={index}
                      className={`flex items-start gap-3 p-2 rounded ${logLevels[log.level]?.bg || ''}`}
                    >
                      <div className="flex items-center gap-2 min-w-[200px]">
                        <div className="text-xs text-gray-500 dark:text-gray-400">
                          {new Date(log.timestamp).toLocaleTimeString()}
                        </div>
                        <div className="flex items-center gap-2">
                          {getLevelIcon(log.level)}
                          <span className={`text-xs font-medium ${logLevels[log.level]?.color || 'text-gray-600'}`}>
                            {log.level}
                          </span>
                        </div>
                        <div className="text-xs text-gray-600 dark:text-gray-400">
                          [{getSourceName(log.source)}]
                        </div>
                      </div>
                      <div className="text-sm text-gray-800 dark:text-gray-200 font-mono">
                        {log.message}
                      </div>
                    </div>
                  ))}
                  <div ref={logsEndRef} />
                </div>
              )}
            </div>
          </div>

          {/* Status Bar */}
          <div className="bg-white dark:bg-gray-800 rounded-lg p-3 shadow-sm">
            <div className="flex items-center justify-between text-sm text-gray-600 dark:text-gray-400">
              <div className="flex items-center gap-4">
                <span>Total Logs: {filteredLogs.length}</span>
                <span>•</span>
                <span>Status: {isStreaming ? 'Streaming' : 'Paused'}</span>
              </div>
              <div className="flex items-center gap-4">
                <span>Last Update: {new Date().toLocaleTimeString()}</span>
              </div>
            </div>
          </div>
        </motion.div>
      )}

      {activeTab === 'history' && (
        <motion.div variants={itemVariants} className="bg-white dark:bg-gray-800 rounded-lg p-6">
          <div className="text-center py-12">
            <ClockIcon className="h-12 w-12 text-gray-400 mx-auto mb-4" />
            <h3 className="text-lg font-medium text-gray-900 dark:text-white mb-2">
              Log History
            </h3>
            <p className="text-gray-600 dark:text-gray-400">
              Browse and search through historical logs
            </p>
          </div>
        </motion.div>
      )}

    </motion.div>
  );
}