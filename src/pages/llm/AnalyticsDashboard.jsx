/**
 * Analytics Dashboard Tab
 *
 * Displays LLM-specific usage analytics with cost tracking and performance metrics.
 * This component provides comprehensive insights into LLM API usage across all models and providers.
 */

import React from 'react';
import { useTheme } from '../../contexts/ThemeContext';
import UsageAnalytics from '../UsageAnalytics';

export default function AnalyticsDashboard() {
  const { theme, currentTheme } = useTheme();

  return (
    <div>
      {/* Header Section */}
      <div className="mb-6">
        <h2 className={`text-2xl font-bold ${
          currentTheme === 'unicorn'
            ? 'text-white'
            : currentTheme === 'light'
            ? 'text-gray-900'
            : 'text-white'
        }`}>
          LLM Usage Analytics
        </h2>
        <p className={`mt-2 ${
          currentTheme === 'unicorn'
            ? 'text-purple-200'
            : currentTheme === 'light'
            ? 'text-gray-600'
            : 'text-gray-400'
        }`}>
          Track API usage, costs, and performance across all LLM models and providers.
          Monitor token consumption, response times, and identify optimization opportunities.
        </p>
      </div>

      {/* Analytics Component */}
      <div className={`rounded-lg ${
        currentTheme === 'unicorn'
          ? 'bg-purple-900/20 border border-purple-500/20'
          : currentTheme === 'light'
          ? 'bg-white border border-gray-200'
          : 'bg-gray-800 border border-gray-700'
      } p-6`}>
        <UsageAnalytics />
      </div>
    </div>
  );
}
