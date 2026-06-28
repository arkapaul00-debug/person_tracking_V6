// src/main.tsx
import React from 'react';
import ReactDOM from 'react-dom/client';
import { RouterProvider } from 'react-router-dom';
import { router } from '@router/router';
import { refreshToken } from '@utils/auth';
import { connectSSE, disconnectSSE } from '@utils/sse';
import { useSentinelStore } from '@utils/store';
import '@styles/globals.css';

async function bootstrap(): Promise<void> {
  // Conditionally load mock backend without touching any other code
  if (import.meta.env.VITE_USE_MOCK_BACKEND === 'true') {
    await import('./mockBackend');
  }

  // Try to restore session
  const sessionValid = await refreshToken();

  if (sessionValid) {
    const { user } = useSentinelStore.getState();
    if (user) {
      connectSSE(user.token);
    }
  }

  // Refresh token every 4 minutes
  setInterval(async () => {
    const ok = await refreshToken();
    if (!ok) {
      useSentinelStore.getState().setUser(null);
      disconnectSSE();
    }
  }, 4 * 60 * 1000);

  const root = document.getElementById('root');
  if (!root) throw new Error('[SENTINEL PRO] Root element #root not found');

  ReactDOM.createRoot(root).render(
    <React.StrictMode>
      <RouterProvider router={router} />
    </React.StrictMode>,
  );
}

bootstrap().catch(console.error);
