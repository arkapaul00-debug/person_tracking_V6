// src/utils/auth.ts
import type { AuthUser, LoginCredentials, RegisterRequest } from './types';
import { useSentinelStore } from './store';

const AUTH_ENDPOINT = import.meta.env.VITE_AUTH_ENDPOINT;

export async function login(
  credentials: LoginCredentials,
): Promise<AuthUser> {
  const res = await fetch(`${AUTH_ENDPOINT}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify(credentials),
  });
  if (!res.ok) {
    const err = (await res.json()) as { message?: string };
    throw new Error(err.message ?? 'Login failed');
  }
  const user: AuthUser = (await res.json()) as AuthUser;
  useSentinelStore.getState().setUser(user);
  return user;
}

export async function register(data: RegisterRequest): Promise<void> {
  const res = await fetch(`${AUTH_ENDPOINT}/auth/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    const err = (await res.json()) as { message?: string };
    throw new Error(err.message ?? 'Registration failed');
  }
}

export async function logout(): Promise<void> {
  try {
    await fetch(`${AUTH_ENDPOINT}/auth/logout`, {
      method: 'POST',
      credentials: 'include',
    });
  } finally {
    useSentinelStore.getState().setUser(null);
  }
}

export async function refreshToken(): Promise<boolean> {
  try {
    const res = await fetch(`${AUTH_ENDPOINT}/auth/refresh`, {
      method: 'POST',
      credentials: 'include',
    });
    if (!res.ok) return false;
    const user: AuthUser = (await res.json()) as AuthUser;
    useSentinelStore.getState().setUser(user);
    return true;
  } catch {
    return false;
  }
}

export function requireAuth(): Response | null {
  const { user } = useSentinelStore.getState();
  if (!user || Date.now() > user.expiresAt) {
    return new Response(null, {
      status: 302,
      headers: { Location: '/login' },
    });
  }
  return null;
}

export function requireAdmin(): Response | null {
  const { user } = useSentinelStore.getState();
  if (!user || user.role !== 'admin') {
    return new Response(null, {
      status: 302,
      headers: { Location: '/monitoring' },
    });
  }
  return null;
}
