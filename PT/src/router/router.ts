// src/router/router.ts
import { createBrowserRouter } from 'react-router-dom';
import { requireAuth, requireAdmin } from '@utils/auth';

export const router = createBrowserRouter([

  // ── Landing Page ─────────────────────────────────────────
  {
    path: '/',
    lazy: () => import('@pages/Landing').then((m) => ({ Component: m.default })),
  },

  // ── Admin Routes ─────────────────────────────────────────
  {
    path: '/admin/login',
    lazy: () => import('@pages/AdminLogin').then((m) => ({ Component: m.default })),
  },
  {
    path: '/admin',
    loader: requireAdmin,
    children: [
      {
        path: 'dashboard',
        lazy: () => import('@pages/AdminDashboard').then((m) => ({ Component: m.default })),
      },
    ],
  },

  // ── User Routes ───────────────────────────────────────────
  {
    path: '/login',
    lazy: () => import('@pages/Login').then((m) => ({ Component: m.default })),
  },
  {
    path: '/',
    loader: requireAuth,
    children: [
      {
        path: 'monitoring',
        lazy: () => import('@pages/Monitoring').then((m) => ({ Component: m.default })),
      },
      {
        path: 'cameras',
        lazy: () => import('@pages/CameraManagement').then((m) => ({ Component: m.default })),
      },
      {
        path: 'targets',
        lazy: () => import('@pages/TargetTracking').then((m) => ({ Component: m.default })),
      },
      {
        path: 'profile',
        lazy: () => import('@pages/UserProfile').then((m) => ({ Component: m.default })),
      },
    ],
  },
]);
