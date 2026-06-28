// src/pages/UserProfile.tsx
import React, { useState, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { useSentinelStore } from '@utils/store';

const API = import.meta.env.VITE_AUTH_ENDPOINT;

const UserProfile: React.FC = () => {
  const user = useSentinelStore((s) => s.user);
  const cameras = useSentinelStore((s) => s.cameras);
  const setUser = useSentinelStore((s) => s.setUser);

  // Edit profile state
  const [isEditing, setIsEditing] = useState(false);
  const [editFullName, setEditFullName] = useState(user?.fullName ?? '');
  const [editEmail, setEditEmail] = useState(user?.email ?? '');
  const [profileError, setProfileError] = useState<string | null>(null);
  const [profileLoading, setProfileLoading] = useState(false);
  const [profileSuccess, setProfileSuccess] = useState(false);

  // Change password state
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmNewPassword, setConfirmNewPassword] = useState('');
  const [passwordError, setPasswordError] = useState<string | null>(null);
  const [passwordLoading, setPasswordLoading] = useState(false);
  const [passwordSuccess, setPasswordSuccess] = useState(false);

  const permittedCameras = cameras.filter((c) =>
    user?.cameraPermissions.includes(c.id),
  );

  const handleProfileSave = useCallback(async () => {
    if (profileLoading) return;
    setProfileError(null);
    setProfileSuccess(false);

    if (!editFullName.trim() || !editEmail.trim()) {
      setProfileError('Full Name and Email are required.');
      return;
    }

    setProfileLoading(true);
    try {
      const res = await fetch(`${API}/users/profile`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          fullName: editFullName.trim(),
          email: editEmail.trim(),
        }),
      });
      if (!res.ok) {
        const err = (await res.json()) as { message?: string };
        throw new Error(err.message ?? 'Failed to update profile');
      }
      if (user) {
        setUser({
          ...user,
          fullName: editFullName.trim(),
          email: editEmail.trim(),
        });
      }
      setProfileSuccess(true);
      setIsEditing(false);
    } catch (err) {
      setProfileError(
        err instanceof Error ? err.message : 'Failed to update profile',
      );
    } finally {
      setProfileLoading(false);
    }
  }, [editFullName, editEmail, profileLoading, user, setUser]);

  const handlePasswordChange = useCallback(async () => {
    if (passwordLoading) return;
    setPasswordError(null);
    setPasswordSuccess(false);

    if (!currentPassword || !newPassword || !confirmNewPassword) {
      setPasswordError('All fields are required.');
      return;
    }
    if (newPassword.length < 6) {
      setPasswordError('New password must be at least 6 characters.');
      return;
    }
    if (newPassword !== confirmNewPassword) {
      setPasswordError('New passwords do not match.');
      return;
    }

    setPasswordLoading(true);
    try {
      const res = await fetch(`${API}/users/change-password`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ currentPassword, newPassword }),
      });
      if (!res.ok) {
        const err = (await res.json()) as { message?: string };
        throw new Error(err.message ?? 'Failed to change password');
      }
      setPasswordSuccess(true);
      setCurrentPassword('');
      setNewPassword('');
      setConfirmNewPassword('');
    } catch (err) {
      setPasswordError(
        err instanceof Error ? err.message : 'Failed to change password',
      );
    } finally {
      setPasswordLoading(false);
    }
  }, [currentPassword, newPassword, confirmNewPassword, passwordLoading]);

  if (!user) return null;

  return (
    <div className="min-h-screen bg-sentinel-bg">
      {/* Simple navbar */}
      <nav className="sentinel-navbar">
        <Link to="/monitoring" className="sentinel-nav-brand">
          <span className="inline-flex items-center justify-center w-8 h-8 rounded-lg bg-gradient-to-br from-sentinel-cyan to-cyan-600 text-xs font-black text-sentinel-bg">
            S
          </span>
          SENTINEL PRO
        </Link>
        <div className="sentinel-nav-links">
          <Link to="/monitoring" className="sentinel-nav-link">
            🖥️ Monitor
          </Link>
          <Link to="/cameras" className="sentinel-nav-link">
            📷 Cameras
          </Link>
          <Link to="/targets" className="sentinel-nav-link">
            🎯 Targets
          </Link>
          <Link to="/profile" className="sentinel-nav-link active">
            👤 Profile
          </Link>
        </div>
      </nav>

      <div className="sentinel-page max-w-3xl">
        <div className="sentinel-page-header">
          <h1 className="sentinel-page-title">My Profile</h1>
          <p className="sentinel-page-subtitle">
            Manage your account settings
          </p>
        </div>

        {/* Profile Information */}
        <div className="sentinel-card mb-4">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-base font-semibold text-sentinel-text">
              Profile Information
            </h2>
            {!isEditing && (
              <button
                className="sentinel-btn sentinel-btn-ghost text-xs"
                onClick={() => {
                  setIsEditing(true);
                  setProfileSuccess(false);
                }}
              >
                ✏️ Edit
              </button>
            )}
          </div>

          {profileError && (
            <div className="mb-3 p-3 rounded-lg bg-sentinel-danger/10 border border-sentinel-danger/30 text-sm text-sentinel-danger">
              {profileError}
            </div>
          )}
          {profileSuccess && (
            <div className="mb-3 p-3 rounded-lg bg-sentinel-success/10 border border-sentinel-success/30 text-sm text-sentinel-success">
              Profile updated successfully.
            </div>
          )}

          <div className="grid grid-cols-2 gap-4">
            <div>
              <span className="sentinel-label">Full Name</span>
              {isEditing ? (
                <input
                  className="sentinel-input"
                  value={editFullName}
                  onChange={(e) => setEditFullName(e.target.value)}
                />
              ) : (
                <div className="text-sm text-sentinel-text">
                  {user.fullName}
                </div>
              )}
            </div>
            <div>
              <span className="sentinel-label">Username</span>
              <div className="text-sm text-sentinel-text">{user.username}</div>
            </div>
            <div>
              <span className="sentinel-label">Email</span>
              {isEditing ? (
                <input
                  className="sentinel-input"
                  type="email"
                  value={editEmail}
                  onChange={(e) => setEditEmail(e.target.value)}
                />
              ) : (
                <div className="text-sm text-sentinel-text">{user.email}</div>
              )}
            </div>
            <div>
              <span className="sentinel-label">Role</span>
              <div>
                <span className="sentinel-badge sentinel-badge-active">
                  {user.role}
                </span>
              </div>
            </div>
          </div>

          {isEditing && (
            <div className="flex gap-2 mt-4 pt-4 border-t border-sentinel-border">
              <button
                className="sentinel-btn sentinel-btn-primary text-xs"
                onClick={handleProfileSave}
                disabled={profileLoading}
              >
                {profileLoading ? (
                  <>
                    <span className="sentinel-spinner" />
                    Saving...
                  </>
                ) : (
                  'Save Changes'
                )}
              </button>
              <button
                className="sentinel-btn sentinel-btn-ghost text-xs"
                onClick={() => {
                  setIsEditing(false);
                  setEditFullName(user.fullName);
                  setEditEmail(user.email);
                  setProfileError(null);
                }}
              >
                Cancel
              </button>
            </div>
          )}
        </div>

        {/* Change Password */}
        <div className="sentinel-card mb-4">
          <h2 className="text-base font-semibold text-sentinel-text mb-4">
            Change Password
          </h2>

          {passwordError && (
            <div className="mb-3 p-3 rounded-lg bg-sentinel-danger/10 border border-sentinel-danger/30 text-sm text-sentinel-danger">
              {passwordError}
            </div>
          )}
          {passwordSuccess && (
            <div className="mb-3 p-3 rounded-lg bg-sentinel-success/10 border border-sentinel-success/30 text-sm text-sentinel-success">
              Password changed successfully.
            </div>
          )}

          <div className="flex flex-col gap-3 max-w-sm">
            <div>
              <label htmlFor="current-pw" className="sentinel-label">
                Current Password
              </label>
              <input
                id="current-pw"
                type="password"
                className="sentinel-input"
                value={currentPassword}
                onChange={(e) => setCurrentPassword(e.target.value)}
                disabled={passwordLoading}
              />
            </div>
            <div>
              <label htmlFor="new-pw" className="sentinel-label">
                New Password
              </label>
              <input
                id="new-pw"
                type="password"
                className="sentinel-input"
                placeholder="Min. 6 characters"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                disabled={passwordLoading}
              />
            </div>
            <div>
              <label htmlFor="confirm-new-pw" className="sentinel-label">
                Confirm New Password
              </label>
              <input
                id="confirm-new-pw"
                type="password"
                className="sentinel-input"
                value={confirmNewPassword}
                onChange={(e) => setConfirmNewPassword(e.target.value)}
                disabled={passwordLoading}
              />
            </div>
            <button
              className="sentinel-btn sentinel-btn-warning text-xs w-fit"
              onClick={handlePasswordChange}
              disabled={passwordLoading}
            >
              {passwordLoading ? (
                <>
                  <span className="sentinel-spinner" />
                  Updating...
                </>
              ) : (
                '🔒 Change Password'
              )}
            </button>
          </div>
        </div>

        {/* Camera Access */}
        <div className="sentinel-card">
          <h2 className="text-base font-semibold text-sentinel-text mb-4">
            My Camera Access
          </h2>
          {permittedCameras.length === 0 ? (
            <div className="text-sm text-sentinel-muted">
              No cameras assigned to your account. Contact an admin.
            </div>
          ) : (
            <div className="grid grid-cols-2 gap-2">
              {permittedCameras.map((cam) => (
                <div
                  key={cam.id}
                  className="flex items-center gap-2 p-2 rounded-lg bg-sentinel-bg border border-sentinel-border"
                >
                  <span className={`status-dot status-dot-${cam.status}`} />
                  <span className="text-xs text-sentinel-text truncate">
                    {cam.name}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default UserProfile;
