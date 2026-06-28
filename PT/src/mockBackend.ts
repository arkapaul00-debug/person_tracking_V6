// src/mockBackend.ts
import type { User, AuthUser, SystemSettings, AuditLogEntry } from './utils/types';

// Initial Mock Database
const INITIAL_USERS: User[] = [
  {
    id: 'admin-1',
    username: 'admin',
    fullName: 'System Administrator',
    email: 'admin@sentinelpro.com',
    role: 'admin',
    status: 'active',
    cameraPermissions: [],
    createdAt: Date.now(),
    lastLoginAt: Date.now(),
  },
];

const INITIAL_SETTINGS: SystemSettings = {
  appTitle: 'SENTINEL PRO',
  logoBase64: null,
  timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
  sessionTimeoutMinutes: 30,
  maxFailedLoginAttempts: 5,
};

// Initialize localStorage if empty
if (!localStorage.getItem('mock_users')) {
  localStorage.setItem('mock_users', JSON.stringify(INITIAL_USERS));
}
if (!localStorage.getItem('mock_settings')) {
  localStorage.setItem('mock_settings', JSON.stringify(INITIAL_SETTINGS));
}
if (!localStorage.getItem('mock_audit_log')) {
  localStorage.setItem('mock_audit_log', JSON.stringify([]));
}

// Helpers
const getUsers = (): User[] => JSON.parse(localStorage.getItem('mock_users') || '[]');
const saveUsers = (users: User[]) => localStorage.setItem('mock_users', JSON.stringify(users));

const getSettings = (): SystemSettings => JSON.parse(localStorage.getItem('mock_settings') || '{}');
const saveSettings = (s: SystemSettings) => localStorage.setItem('mock_settings', JSON.stringify(s));

const getLogs = (): AuditLogEntry[] => JSON.parse(localStorage.getItem('mock_audit_log') || '[]');
const addLog = (log: Omit<AuditLogEntry, 'id' | 'timestamp'>) => {
  const logs = getLogs();
  logs.unshift({
    ...log,
    id: `log-${Date.now()}`,
    timestamp: Date.now(),
  });
  localStorage.setItem('mock_audit_log', JSON.stringify(logs));
};

// Intercept global fetch
const originalFetch = window.fetch;

window.fetch = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
  const url = typeof input === 'string' ? input : (input instanceof Request ? input.url : input.toString());
  const method = init?.method || (input instanceof Request ? input.method : 'GET');
  const body = init?.body ? JSON.parse(init.body as string) : null;

  // Only intercept our backend API endpoints
  if (url.includes(import.meta.env.VITE_AUTH_ENDPOINT)) {
    console.log(`[Mock Backend] Intercepted: ${method} ${url}`, body || '');

    // Sleep to simulate network delay
    await new Promise((resolve) => setTimeout(resolve, 300));

    // MOCK RESPONSE BUILDER
    const jsonResponse = (data: unknown, status = 200) => {
      return new Response(JSON.stringify(data), {
        status,
        headers: { 'Content-Type': 'application/json' },
      });
    };

    try {
      // 1. AUTH ROUTES
      if (url.endsWith('/auth/login') && method === 'POST') {
        const { username, password } = body;
        const users = getUsers();
        
        // Find user by username
        const user = users.find((u) => u.username === username);
        
        // For mock, any password works for valid users, EXCEPT we simulate admin123 for admin
        if (!user || (username === 'admin' && password !== 'admin123')) {
          return jsonResponse({ message: 'Invalid username or password' }, 401);
        }

        if (user.status !== 'active') {
          return jsonResponse({ message: 'Account is pending approval or inactive' }, 403);
        }

        const authUser: AuthUser = {
          ...user,
          token: `mock-token-${user.id}-${Date.now()}`,
          expiresAt: Date.now() + 1000 * 60 * 60 * 24, // 24 hours
        };
        
        // Store mock cookie in localStorage
        localStorage.setItem('mock_auth_token', JSON.stringify(authUser));
        addLog({ userId: user.id, username: user.username, action: 'LOGIN', details: 'User logged in successfully' });

        return jsonResponse(authUser);
      }

      if (url.endsWith('/auth/refresh') && method === 'POST') {
        const tokenData = localStorage.getItem('mock_auth_token');
        if (tokenData) {
          return jsonResponse(JSON.parse(tokenData));
        }
        return jsonResponse({ message: 'Unauthorized' }, 401);
      }

      // 2. ADMIN USER MANAGEMENT ROUTES
      if (url.includes('/admin/users')) {
        const users = getUsers();
        
        if (method === 'GET') {
          return jsonResponse(users);
        }

        if (method === 'POST') {
          const newUser: User = {
            id: `user-${Date.now()}`,
            username: body.username,
            fullName: body.fullName,
            email: body.email,
            role: body.role,
            status: 'active', // auto-approve mock creations
            cameraPermissions: body.cameraPermissions || [],
            createdAt: Date.now(),
            lastLoginAt: Date.now(),
          };
          saveUsers([...users, newUser]);
          return jsonResponse(newUser, 201);
        }

        // Handle /admin/users/:id (PATCH / DELETE)
        const parts = url.split('/');
        const id = parts[parts.length - 1];

        if (method === 'PATCH') {
          const index = users.findIndex((u) => u.id === id);
          if (index !== -1) {
            users[index] = { ...users[index], ...body };
            saveUsers(users);
            return jsonResponse(users[index]);
          }
          return jsonResponse({ message: 'User not found' }, 404);
        }

        if (method === 'DELETE') {
          const filtered = users.filter((u) => u.id !== id);
          saveUsers(filtered);
          return jsonResponse({ success: true });
        }
      }

      // 3. SETTINGS & AUDIT LOG
      if (url.endsWith('/admin/settings')) {
        if (method === 'GET') return jsonResponse(getSettings());
        if (method === 'PUT') {
          const s = { ...getSettings(), ...body };
          saveSettings(s);
          return jsonResponse(s);
        }
      }

      if (url.endsWith('/admin/audit-log') && method === 'GET') {
        return jsonResponse(getLogs());
      }

      // 4. CAMERAS / TARGETS (Empty defaults for now, so pages load)
      if (url.endsWith('/cameras') && method === 'GET') {
        return jsonResponse([]);
      }
      if (url.endsWith('/targets') && method === 'GET') {
        return jsonResponse([]);
      }

      // Fallback 404 for unmatched mock routes
      return jsonResponse({ message: 'Mock endpoint not implemented' }, 404);
    } catch (err) {
      console.error('[Mock Backend] Error processing request:', err);
      return jsonResponse({ message: 'Internal mock server error' }, 500);
    }
  }

  // If it's not our API, let the normal fetch handle it
  return originalFetch(input, init);
};

console.log('[Mock Backend] Interceptor installed successfully.');
