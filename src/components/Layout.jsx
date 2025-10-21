/**
 * Layout Component - Ops Center Main Layout with Hierarchical Navigation
 *
 * UPDATED: October 13, 2025
 * CHANGES: Integrated hierarchical navigation structure with collapsible sections
 *
 * Navigation Structure:
 * - Personal Section: Dashboard, My Account, My Subscription (always visible)
 * - Organization Section: Team management, settings (org admins/owners only)
 * - System Section: Infrastructure administration (platform admins only)
 *
 * Components Used:
 * - NavigationSection: Collapsible navigation sections with expand/collapse
 * - NavigationItem: Individual navigation items with active state and theming
 *
 * Role-Based Access:
 * - role: admin → Full system administration access
 * - org_role: admin/owner → Organization management access
 * - All authenticated users → Personal sections
 */

import React, { useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import {
  HomeIcon,
  CubeIcon,
  CogIcon,
  ServerIcon,
  ChartBarIcon,
  WifiIcon,
  SunIcon,
  MoonIcon,
  QuestionMarkCircleIcon,
  ArchiveBoxIcon,
  PuzzlePieceIcon,
  DocumentTextIcon,
  ShieldCheckIcon,
  KeyIcon,
  ArrowRightOnRectangleIcon,
  UserCircleIcon,
  PaintBrushIcon,
  CreditCardIcon,
  BuildingOfficeIcon,
  UsersIcon,
  ComputerDesktopIcon,
  WrenchIcon,
  CurrencyDollarIcon,
  ChartPieIcon,
  DocumentDuplicateIcon,
  RectangleStackIcon,
  MagnifyingGlassIcon,
  SparklesIcon,
  EnvelopeIcon
} from '@heroicons/react/24/outline';
import { useTheme } from '../contexts/ThemeContext';
import { ColonelLogo, MagicUnicornLogo, CenterDeepLogo } from './Logos';
import NavigationSection from './NavigationSection';
import NavigationItem from './NavigationItem';
import { routes } from '../config/routes';
import NotificationBell from './NotificationBell';
import OrganizationSelector from './OrganizationSelectorSimple';

// Icon mapping for dynamic icon resolution from route configuration
const iconMap = {
  HomeIcon,
  UserCircleIcon,
  CreditCardIcon,
  CubeIcon,
  ServerIcon,
  ChartBarIcon,
  WifiIcon,
  ArchiveBoxIcon,
  DocumentTextIcon,
  ShieldCheckIcon,
  KeyIcon,
  PuzzlePieceIcon,
  PaintBrushIcon,
  CogIcon,
  BuildingOfficeIcon,
  UsersIcon,
  ComputerDesktopIcon,
  WrenchIcon,
  CurrencyDollarIcon,
  ChartPieIcon,
  DocumentDuplicateIcon,
  RectangleStackIcon,
  MagnifyingGlassIcon,
  SparklesIcon,
  EnvelopeIcon
};

export default function Layout({ children }) {
  const location = useLocation();
  const navigate = useNavigate();
  const { theme, currentTheme, switchTheme, availableThemes, isDarkMode, toggleDarkMode } = useTheme();

  // Theme configurations for display names
  const themes = {
    dark: { name: 'Dark', icon: '🌙' },
    light: { name: 'Light', icon: '☀️' },
    unicorn: { name: 'Unicorn', icon: '🦄' }
  };

  const userInfo = JSON.parse(localStorage.getItem('userInfo') || '{}');
  const userRole = userInfo.role || 'viewer';
  const userOrgRole = userInfo.org_role || null;

  // Debug logging
  console.log('DEBUG Layout: userInfo from localStorage:', userInfo);
  console.log('DEBUG Layout: userRole:', userRole);
  console.log('DEBUG Layout: userOrgRole:', userOrgRole);

  // Collapsible section state management - Load from localStorage
  const loadSectionState = () => {
    const saved = localStorage.getItem('navSectionState');
    if (saved) {
      try {
        return JSON.parse(saved);
      } catch (e) {
        console.error('Failed to parse saved section state:', e);
      }
    }
    // Default state
    return {
      infrastructure: true,
      usersOrgs: true,
      billingUsage: true,
      platform: true
    };
  };

  const [sectionState, setSectionState] = useState(loadSectionState);

  // Save section state to localStorage whenever it changes
  const toggleSection = (sectionName) => {
    setSectionState(prev => {
      const newState = {
        ...prev,
        [sectionName]: !prev[sectionName]
      };
      localStorage.setItem('navSectionState', JSON.stringify(newState));
      return newState;
    });
  };

  const handleLogout = async () => {
    try {
      // Call backend logout endpoint
      await fetch('/api/v1/auth/logout', {
        method: 'POST',
        credentials: 'include'
      });
    } catch (error) {
      console.error('Logout API call failed:', error);
    }

    // Clear local storage
    localStorage.removeItem('authToken');
    localStorage.removeItem('userInfo');
    localStorage.removeItem('user');
    localStorage.removeItem('token');

    // Redirect to home page (will trigger OAuth login)
    window.location.href = '/';
  };

  const themeClasses = {
    background: `min-h-screen ${theme.background}`,
    sidebar: theme.sidebar,
    nav: currentTheme === 'unicorn' 
      ? 'hover:bg-white/10'
      : currentTheme === 'light'
      ? 'hover:bg-gray-100'
      : 'hover:bg-slate-700/50',
    logo: theme.text.logo,
    brandText: theme.text.secondary,
    themeLabel: theme.text.secondary
  };

  return (
    <div className={themeClasses.background}>
      <div className="flex h-screen">
        {/* Sidebar */}
        <div className="hidden md:flex md:w-64 md:flex-col">
          <div className={`flex flex-col flex-grow pt-5 pb-4 overflow-y-auto ${themeClasses.sidebar}`}>
            {/* Brand Header */}
            <div className="flex flex-col items-center flex-shrink-0 px-4 mb-8">
              {/* Main Logo Area - Clickable to navigate to landing page */}
              <Link
                to="/"
                className={`flex items-center gap-3 mb-3 cursor-pointer transition-all duration-200 rounded-lg p-2 ${
                  currentTheme === 'unicorn'
                    ? 'hover:bg-white/10'
                    : currentTheme === 'light'
                    ? 'hover:bg-gray-100'
                    : 'hover:bg-slate-700/50'
                }`}
              >
                {/* The Colonel Logo */}
                <ColonelLogo className="w-14 h-14 drop-shadow-xl" />
                <div className="text-center">
                  <h1 className={`text-2xl font-bold ${themeClasses.logo} leading-tight`}>
                    Ops Center
                  </h1>
                  <div className={`text-lg ${currentTheme === 'unicorn' ? 'text-purple-200/80' : currentTheme === 'light' ? 'text-gray-600' : 'text-gray-400'} font-medium`}>
                    UC-1 Pro Control
                  </div>
                </div>
              </Link>

              {/* System Management - subtitle */}
              <div className={`text-sm ${currentTheme === 'unicorn' ? 'text-purple-200/70' : currentTheme === 'light' ? 'text-gray-500' : 'text-gray-400'} mb-2 font-medium`}>
                System Management Console
              </div>

              {/* Version */}
              <div className={`text-xs ${currentTheme === 'unicorn' ? 'text-purple-300/60' : currentTheme === 'light' ? 'text-gray-500' : 'text-gray-500'} font-mono`}>
                v1.0.0
              </div>
            </div>
            <div className="mt-8 flex flex-col flex-1">
              <nav className="flex-1 px-2 space-y-1">
                {/* ============================ */}
                {/* DASHBOARD - Top Level */}
                {/* ============================ */}
                <NavigationItem
                  name="Dashboard"
                  href="/admin/"
                  icon={iconMap.HomeIcon}
                />

                {/* ============================ */}
                {/* INFRASTRUCTURE SECTION */}
                {/* ============================ */}
                {userRole === 'admin' && (
                  <>
                    {/* Section Header */}
                    <div className={`mt-4 mb-2 px-3 flex items-center gap-2 ${
                      currentTheme === 'unicorn'
                        ? 'text-purple-300/70'
                        : currentTheme === 'light'
                        ? 'text-gray-500'
                        : 'text-gray-400'
                    }`}>
                      <div className="flex-1 h-px bg-current opacity-20"></div>
                      <span className="text-xs font-bold uppercase tracking-wider">Infrastructure</span>
                      <div className="flex-1 h-px bg-current opacity-20"></div>
                    </div>

                    <NavigationSection
                      title="Infrastructure"
                      icon={iconMap.ComputerDesktopIcon}
                      defaultOpen={sectionState.infrastructure}
                      onToggle={() => toggleSection('infrastructure')}
                    >
                      <NavigationItem
                        name="Services"
                        href="/admin/services"
                        icon={iconMap.ServerIcon}
                        indent={true}
                      />
                      <NavigationItem
                        name="Hardware Management"
                        href="/admin/infrastructure/hardware"
                        icon={iconMap.WrenchIcon}
                        indent={true}
                      />
                      <NavigationItem
                        name="Monitoring"
                        href="/admin/system"
                        icon={iconMap.ChartBarIcon}
                        indent={true}
                      />
                      <NavigationItem
                        name="LLM Management"
                        href="/admin/llm-management"
                        icon={iconMap.CubeIcon}
                        indent={true}
                      />
                    </NavigationSection>
                  </>
                )}

                {/* ============================ */}
                {/* USERS & ORGANIZATIONS SECTION */}
                {/* ============================ */}
                {userRole === 'admin' && (
                  <>
                    {/* Section Header */}
                    <div className={`mt-4 mb-2 px-3 flex items-center gap-2 ${
                      currentTheme === 'unicorn'
                        ? 'text-purple-300/70'
                        : currentTheme === 'light'
                        ? 'text-gray-500'
                        : 'text-gray-400'
                    }`}>
                      <div className="flex-1 h-px bg-current opacity-20"></div>
                      <span className="text-xs font-bold uppercase tracking-wider">Users & Organizations</span>
                      <div className="flex-1 h-px bg-current opacity-20"></div>
                    </div>

                    <NavigationSection
                      title="Users & Organizations"
                      icon={iconMap.UsersIcon}
                      defaultOpen={sectionState.usersOrgs}
                      onToggle={() => toggleSection('usersOrgs')}
                    >
                      <NavigationItem
                        name="User Management"
                        href="/admin/system/users"
                        icon={iconMap.UsersIcon}
                        indent={true}
                      />
                      <NavigationItem
                        name="Organizations"
                        href="/admin/org/settings"
                        icon={iconMap.BuildingOfficeIcon}
                        indent={true}
                      />
                      <NavigationItem
                        name="Roles & Permissions"
                        href="/admin/system/permissions"
                        icon={iconMap.ShieldCheckIcon}
                        indent={true}
                      />
                      <NavigationItem
                        name="API Keys"
                        href="/admin/authentication"
                        icon={iconMap.KeyIcon}
                        indent={true}
                      />
                    </NavigationSection>
                  </>
                )}

                {/* ============================ */}
                {/* BILLING & USAGE SECTION */}
                {/* ============================ */}
                {userRole === 'admin' && (
                  <>
                    {/* Section Header */}
                    <div className={`mt-4 mb-2 px-3 flex items-center gap-2 ${
                      currentTheme === 'unicorn'
                        ? 'text-purple-300/70'
                        : currentTheme === 'light'
                        ? 'text-gray-500'
                        : 'text-gray-400'
                    }`}>
                      <div className="flex-1 h-px bg-current opacity-20"></div>
                      <span className="text-xs font-bold uppercase tracking-wider">Billing & Usage</span>
                      <div className="flex-1 h-px bg-current opacity-20"></div>
                    </div>

                    <NavigationSection
                      title="Billing & Usage"
                      icon={iconMap.CurrencyDollarIcon}
                      defaultOpen={sectionState.billingUsage}
                      onToggle={() => toggleSection('billingUsage')}
                    >
                      <NavigationItem
                        name="Billing Dashboard"
                        href="/admin/system/billing"
                        icon={iconMap.CurrencyDollarIcon}
                        indent={true}
                      />
                      <NavigationItem
                        name="Advanced Analytics"
                        href="/admin/system/analytics"
                        icon={iconMap.ChartBarIcon}
                        indent={true}
                      />
                      <NavigationItem
                        name="Usage Metrics"
                        href="/admin/system/usage-metrics"
                        icon={iconMap.ChartPieIcon}
                        indent={true}
                      />
                      <NavigationItem
                        name="Subscriptions"
                        href="/admin/billing"
                        icon={iconMap.RectangleStackIcon}
                        indent={true}
                      />
                      <NavigationItem
                        name="Invoices"
                        href="/admin/system/billing#invoices"
                        icon={iconMap.DocumentDuplicateIcon}
                        indent={true}
                      />
                    </NavigationSection>
                  </>
                )}

                {/* ============================ */}
                {/* PLATFORM SECTION */}
                {/* ============================ */}
                {userRole === 'admin' && (
                  <>
                    {/* Section Header */}
                    <div className={`mt-4 mb-2 px-3 flex items-center gap-2 ${
                      currentTheme === 'unicorn'
                        ? 'text-purple-300/70'
                        : currentTheme === 'light'
                        ? 'text-gray-500'
                        : 'text-gray-400'
                    }`}>
                      <div className="flex-1 h-px bg-current opacity-20"></div>
                      <span className="text-xs font-bold uppercase tracking-wider">Platform</span>
                      <div className="flex-1 h-px bg-current opacity-20"></div>
                    </div>

                    <NavigationSection
                      title="Platform"
                      icon={iconMap.SparklesIcon}
                      defaultOpen={sectionState.platform}
                      onToggle={() => toggleSection('platform')}
                    >
                      <NavigationItem
                        name="Unicorn Brigade"
                        href="/admin/brigade"
                        icon={iconMap.SparklesIcon}
                        indent={true}
                      />
                      <NavigationItem
                        name="Center-Deep Search"
                        href="https://search.unicorncommander.ai"
                        icon={iconMap.MagnifyingGlassIcon}
                        indent={true}
                        external={true}
                      />
                      <NavigationItem
                        name="Email Settings"
                        href="/admin/platform/email-settings"
                        icon={iconMap.EnvelopeIcon}
                        indent={true}
                      />
                    </NavigationSection>
                  </>
                )}
              </nav>
              
              {/* Help Button */}
              <div className="px-2 mb-4">
                <button
                  onClick={() => {
                    const currentHost = window.location.hostname;
                    window.open(`http://${currentHost}:8086`, '_blank');
                  }}
                  className={`w-full flex items-center gap-2 px-3 py-2 text-sm font-medium rounded-lg transition-all duration-200 ${
                    currentTheme === 'unicorn'
                      ? 'text-purple-200 hover:bg-white/10 hover:text-white'
                      : currentTheme === 'light'
                      ? 'text-gray-600 hover:bg-gray-100 hover:text-gray-900'
                      : 'text-gray-300 hover:bg-gray-700 hover:text-white'
                  }`}
                >
                  <QuestionMarkCircleIcon className="h-5 w-5" />
                  Help & Documentation
                </button>
              </div>
              
              {/* User Info and Logout */}
              <div className="px-2 mb-4">
                <div className="border-t border-white/10 pt-4">
                  {userInfo.username && (
                    <div className={`flex items-center gap-2 px-2 mb-3 text-sm ${
                      currentTheme === 'unicorn' ? 'text-purple-200' : currentTheme === 'light' ? 'text-gray-600' : 'text-gray-400'
                    }`}>
                      <UserCircleIcon className="h-5 w-5" />
                      <span>{userInfo.username}</span>
                    </div>
                  )}
                  <button
                    onClick={handleLogout}
                    className={`w-full flex items-center gap-2 px-3 py-2 text-sm font-medium rounded-lg transition-all duration-200 ${
                      currentTheme === 'unicorn'
                        ? 'text-red-300 hover:bg-red-900/20 hover:text-red-200'
                        : currentTheme === 'light'
                        ? 'text-red-600 hover:bg-red-50 hover:text-red-700'
                        : 'text-red-400 hover:bg-red-900/20 hover:text-red-300'
                    }`}
                  >
                    <ArrowRightOnRectangleIcon className="h-5 w-5" />
                    Logout
                  </button>
                </div>
              </div>
              
              {/* Theme Switcher */}
              <div className="px-2 pb-4">
                <div className="border-t border-white/10 pt-4">
                  <div className={`text-xs ${themeClasses.themeLabel} mb-2 px-2`}>Theme</div>
                  <div className="flex gap-1">
                    {availableThemes.map((themeName) => (
                      <button
                        key={themeName}
                        onClick={() => switchTheme(themeName)}
                        className={`
                          px-2 py-1 text-xs rounded transition-all
                          ${currentTheme === themeName
                            ? 'bg-white/20 text-white'
                            : currentTheme === 'unicorn' ? 'text-purple-300/70 hover:bg-white/10 hover:text-white' : currentTheme === 'light' ? 'text-gray-600 hover:bg-gray-100' : 'text-gray-400 hover:bg-gray-700'
                          }
                        `}
                        title={`Switch to ${themeName} theme`}
                      >
                        {themes[themeName]?.icon} {themes[themeName]?.name || themeName}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Main content */}
        <div className="flex flex-col flex-1 overflow-hidden">
          {/* Top Header Bar */}
          <header className={`${
            currentTheme === 'unicorn'
              ? 'bg-gradient-to-r from-purple-900/50 to-pink-900/50 backdrop-blur-md border-b border-purple-500/20'
              : currentTheme === 'light'
              ? 'bg-white border-b border-gray-200'
              : 'bg-slate-800 border-b border-slate-700'
          } shadow-sm`}>
            <div className="flex items-center justify-between px-4 py-3">
              {/* Left: Page Title or Breadcrumbs */}
              <div className="flex-1">
                <h2 className={`text-lg font-semibold ${
                  currentTheme === 'unicorn'
                    ? 'text-white'
                    : currentTheme === 'light'
                    ? 'text-gray-900'
                    : 'text-white'
                }`}>
                  {/* Page title can be dynamically set here */}
                </h2>
              </div>

              {/* Right: Organization Selector, Notification Bell and User Info */}
              <div className="flex items-center gap-4">
                {/* Organization Selector */}
                <OrganizationSelector />

                {/* Notification Bell (Admin only) */}
                {userInfo.role === 'admin' && (
                  <div className={`${
                    currentTheme === 'unicorn'
                      ? 'text-purple-200'
                      : currentTheme === 'light'
                      ? 'text-gray-600'
                      : 'text-gray-300'
                  }`}>
                    <NotificationBell />
                  </div>
                )}

                {/* User Avatar/Name */}
                <div className="flex items-center gap-2">
                  <div className={`flex items-center justify-center w-8 h-8 rounded-full ${
                    currentTheme === 'unicorn'
                      ? 'bg-purple-500 text-white'
                      : currentTheme === 'light'
                      ? 'bg-gray-200 text-gray-700'
                      : 'bg-slate-600 text-white'
                  }`}>
                    {userInfo.username?.charAt(0).toUpperCase() || 'U'}
                  </div>
                  <span className={`text-sm font-medium ${
                    currentTheme === 'unicorn'
                      ? 'text-white'
                      : currentTheme === 'light'
                      ? 'text-gray-700'
                      : 'text-gray-200'
                  }`}>
                    {userInfo.username || 'User'}
                  </span>
                </div>
              </div>
            </div>
          </header>

          <main className="flex-1 relative overflow-y-auto focus:outline-none">
            <div className="py-6">
              <div className="max-w-7xl mx-auto px-4 sm:px-6 md:px-8">
                {children}
              </div>
            </div>
          </main>
        </div>
      </div>
    </div>
  );
}