// src/pages/Register.tsx
import React, { useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { register } from '@utils/auth';

const Register: React.FC = () => {
  const navigate = useNavigate();
  const [fullName, setFullName] = useState('');
  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isSuccess, setIsSuccess] = useState(false);

  const validateEmail = (value: string): boolean =>
    /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value);

  const handleSubmit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      if (isLoading) return;

      setError(null);

      // Validate
      if (!fullName.trim() || !username.trim() || !email.trim() || !password || !confirmPassword) {
        setError('All fields are required.');
        return;
      }

      if (!validateEmail(email.trim())) {
        setError('Please enter a valid email address.');
        return;
      }

      if (password.length < 6) {
        setError('Password must be at least 6 characters.');
        return;
      }

      if (password !== confirmPassword) {
        setError('Passwords do not match.');
        return;
      }

      setIsLoading(true);

      try {
        await register({
          fullName: fullName.trim(),
          username: username.trim(),
          email: email.trim(),
          password,
        });
        setIsSuccess(true);
      } catch (err) {
        setError(
          err instanceof Error
            ? err.message
            : 'Registration failed. Please try again.',
        );
      } finally {
        setIsLoading(false);
      }
    },
    [fullName, username, email, password, confirmPassword, isLoading],
  );

  return (
    <div className="min-h-screen flex items-center justify-center px-4 bg-sentinel-bg">
      {/* Background gradient orbs */}
      <div className="fixed inset-0 overflow-hidden pointer-events-none">
        <div
          className="absolute rounded-full blur-[120px] opacity-15"
          style={{
            width: '350px',
            height: '350px',
            background: 'radial-gradient(circle, #00cc88, transparent)',
            top: '-80px',
            left: '-80px',
          }}
        />
        <div
          className="absolute rounded-full blur-[120px] opacity-10"
          style={{
            width: '250px',
            height: '250px',
            background: 'radial-gradient(circle, #00d4ff, transparent)',
            bottom: '-60px',
            right: '-60px',
          }}
        />
      </div>

      <div className="w-full max-w-md relative z-10">
        {/* Logo / Brand */}
        <div className="text-center mb-6">
          <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl bg-gradient-to-br from-sentinel-success to-emerald-600 mb-3">
            <span className="text-xl font-black text-sentinel-bg">S</span>
          </div>
          <h1 className="text-xl font-bold text-sentinel-text tracking-tight">
            Request Access
          </h1>
          <p className="text-xs text-sentinel-muted mt-1">
            Register for a SENTINEL PRO account
          </p>
        </div>

        <div className="sentinel-card">
          {isSuccess ? (
            /* ── Success message ──────────────────────────── */
            <div className="text-center py-4">
              <div className="text-4xl mb-3">✅</div>
              <h3 className="text-lg font-semibold text-sentinel-success mb-2">
                Request Submitted
              </h3>
              <p className="text-sm text-sentinel-muted leading-relaxed mb-6">
                Your request has been submitted. An admin will review and approve
                your account. You will be notified via email.
              </p>
              <button
                className="sentinel-btn sentinel-btn-ghost"
                onClick={() => navigate('/login')}
              >
                Back to Login
              </button>
            </div>
          ) : (
            /* ── Registration form ────────────────────────── */
            <form onSubmit={handleSubmit} className="flex flex-col gap-3.5">
              {error && (
                <div className="p-3 rounded-lg bg-sentinel-danger/10 border border-sentinel-danger/30 text-sm text-sentinel-danger">
                  {error}
                </div>
              )}

              <div>
                <label htmlFor="reg-fullname" className="sentinel-label">
                  Full Name
                </label>
                <input
                  id="reg-fullname"
                  type="text"
                  className="sentinel-input"
                  placeholder="John Doe"
                  value={fullName}
                  onChange={(e) => setFullName(e.target.value)}
                  disabled={isLoading}
                  autoFocus
                />
              </div>

              <div>
                <label htmlFor="reg-username" className="sentinel-label">
                  Username
                </label>
                <input
                  id="reg-username"
                  type="text"
                  className="sentinel-input"
                  placeholder="johndoe"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  disabled={isLoading}
                  autoComplete="username"
                />
              </div>

              <div>
                <label htmlFor="reg-email" className="sentinel-label">
                  Email
                </label>
                <input
                  id="reg-email"
                  type="email"
                  className="sentinel-input"
                  placeholder="john@example.com"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  disabled={isLoading}
                  autoComplete="email"
                />
              </div>

              <div>
                <label htmlFor="reg-password" className="sentinel-label">
                  Password
                </label>
                <input
                  id="reg-password"
                  type="password"
                  className="sentinel-input"
                  placeholder="Min. 6 characters"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  disabled={isLoading}
                  autoComplete="new-password"
                />
              </div>

              <div>
                <label htmlFor="reg-confirm" className="sentinel-label">
                  Confirm Password
                </label>
                <input
                  id="reg-confirm"
                  type="password"
                  className="sentinel-input"
                  placeholder="Repeat password"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  disabled={isLoading}
                  autoComplete="new-password"
                />
              </div>

              <button
                type="submit"
                className="sentinel-btn sentinel-btn-success w-full mt-1"
                disabled={isLoading}
              >
                {isLoading ? (
                  <>
                    <span className="sentinel-spinner" />
                    Submitting...
                  </>
                ) : (
                  '🎯 Request Access'
                )}
              </button>
            </form>
          )}

          {!isSuccess && (
            <div className="mt-5 pt-4 border-t border-sentinel-border text-center">
              <button
                className="text-sm font-medium text-sentinel-cyan hover:underline bg-transparent border-none cursor-pointer"
                onClick={() => navigate('/login')}
              >
                ← Back to Login
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default Register;
