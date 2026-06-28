// src/pages/Login.tsx
import React, { useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { login } from '@utils/auth';
import { connectSSE } from '@utils/sse';
import '@styles/sentinel.css';

const Login: React.FC = () => {
  const navigate = useNavigate();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  const handleSubmit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      if (isLoading) return;

      setError(null);

      if (!username.trim() || !password.trim()) {
        setError('Please fill in all fields.');
        return;
      }

      setIsLoading(true);

      try {
        const user = await login({ username: username.trim(), password });
        connectSSE(user.token);
        navigate('/monitoring', { replace: true });
      } catch (err) {
        setError(
          err instanceof Error ? err.message : 'Login failed. Please try again.',
        );
      } finally {
        setIsLoading(false);
      }
    },
    [username, password, isLoading, navigate],
  );

  return (
    <div className="min-h-screen flex items-center justify-center px-4 bg-sentinel-bg">
      {/* Background gradient orbs */}
      <div className="fixed inset-0 overflow-hidden pointer-events-none">
        <div
          className="absolute rounded-full blur-[120px] opacity-20"
          style={{
            width: '400px',
            height: '400px',
            background: 'radial-gradient(circle, #00d4ff, transparent)',
            top: '-100px',
            right: '-100px',
          }}
        />
        <div
          className="absolute rounded-full blur-[120px] opacity-10"
          style={{
            width: '300px',
            height: '300px',
            background: 'radial-gradient(circle, #ff0040, transparent)',
            bottom: '-50px',
            left: '-50px',
          }}
        />
      </div>

      <div className="w-full max-w-md relative z-10">
        {/* Logo / Brand */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-gradient-to-br from-sentinel-cyan to-cyan-600 mb-4">
            <span className="text-2xl font-black text-sentinel-bg">S</span>
          </div>
          <h1 className="text-2xl font-bold text-sentinel-text tracking-tight">
            SENTINEL PRO
          </h1>
          <p className="text-sm text-sentinel-muted mt-1">
            Enterprise Surveillance Platform
          </p>
        </div>

        {/* Login Card */}
        <div className="sentinel-card sentinel-card-glow">
          <h2 className="text-lg font-semibold text-sentinel-text mb-1">
            Sign In
          </h2>
          <p className="text-xs text-sentinel-muted mb-6">
            Enter your credentials to access the system
          </p>

          <form onSubmit={handleSubmit} className="flex flex-col gap-4">
            {/* Error message */}
            {error && (
              <div className="p-3 rounded-lg bg-sentinel-danger/10 border border-sentinel-danger/30 text-sm text-sentinel-danger">
                {error}
              </div>
            )}

            {/* Username */}
            <div>
              <label htmlFor="login-username" className="sentinel-label">
                Username
              </label>
              <input
                id="login-username"
                type="text"
                className="sentinel-input"
                placeholder="Enter your username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                disabled={isLoading}
                autoComplete="username"
                autoFocus
              />
            </div>

            {/* Password */}
            <div>
              <label htmlFor="login-password" className="sentinel-label">
                Password
              </label>
              <input
                id="login-password"
                type="password"
                className="sentinel-input"
                placeholder="Enter your password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                disabled={isLoading}
                autoComplete="current-password"
              />
            </div>

            {/* Submit */}
            <button
              type="submit"
              className="sentinel-btn sentinel-btn-primary w-full mt-2"
              disabled={isLoading}
            >
              {isLoading ? (
                <>
                  <span className="sentinel-spinner" />
                  Signing In...
                </>
              ) : (
                'Sign In'
              )}
            </button>
          </form>

          {/* Register link */}
          <div className="mt-6 pt-4 border-t border-sentinel-border text-center">
            <span className="text-sm text-sentinel-muted">
              Don&apos;t have an account?{' '}
            </span>
            <button
              className="text-sm font-medium text-sentinel-cyan hover:underline bg-transparent border-none cursor-pointer"
              onClick={() => navigate('/register')}
            >
              Request Access
            </button>
          </div>
        </div>

        {/* Footer */}
        <p className="text-center text-[11px] text-sentinel-muted/40 mt-6">
          SENTINEL PRO v2.0 — Enterprise Surveillance Platform
        </p>
      </div>
    </div>
  );
};

export default Login;
