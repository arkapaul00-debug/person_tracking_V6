// src/router/router.ts
import { createBrowserRouter } from 'react-router-dom';
import { requireAuth, requireAdmin } from '@utils/auth';

export const router = createBrowserRouter([
  {
    path: '/login',
    lazy: () =>
      import('@pages/Login').then((m) => ({ Component: m.default })),
  },
  {
    path: '/register',
    lazy: () =>
      import('@pages/Register').then((m) => ({ Component: m.default })),
  },
  {
    path: '/',
    loader: requireAuth,
    children: [
      {
        index: true,
        lazy: () =>
          import('@pages/Monitoring').then((m) => ({
            Component: m.default,
          })),
      },
      {
        path: 'monitoring',
        lazy: () =>
          import('@pages/Monitoring').then((m) => ({
            Component: m.default,
          })),
      },
      {
        path: 'cameras',
        lazy: () =>
          import('@pages/CameraManagement').then((m) => ({
            Component: m.default,
          })),
      },
      {
        path: 'targets',
        lazy: () =>
          import('@pages/TargetTracking').then((m) => ({
            Component: m.default,
          })),
      },
      {
        path: 'profile',
        lazy: () =>
          import('@pages/UserProfile').then((m) => ({
            Component: m.default,
          })),
      },
      {
        path: 'admin',
        loader: requireAdmin,
        lazy: () =>
          import('@pages/AdminPanel').then((m) => ({
            Component: m.default,
          })),
      },
    ],
  },
]);
