// src/pages/AdminPanel.tsx
import React, { useState, useEffect, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { useSentinelStore } from '@utils/store';
import type { User, UserRole, AuditLogEntry, SystemSettings } from '@utils/types';

const API = import.meta.env.VITE_AUTH_ENDPOINT;

type AdminTab = 'users' | 'settings' | 'audit';

// ── User Management Tab ───────────────────────────────────────

const UserManagementTab: React.FC = () => {
  const allUsers = useSentinelStore((s) => s.allUsers);
  const setAllUsers = useSentinelStore((s) => s.setAllUsers);
  const cameras = useSentinelStore((s) => s.cameras);

  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showAddModal, setShowAddModal] = useState(false);
  const [editingUser, setEditingUser] = useState<User | null>(null);
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null);

  // Form state
  const [formFullName, setFormFullName] = useState('');
  const [formUsername, setFormUsername] = useState('');
  const [formEmail, setFormEmail] = useState('');
  const [formPassword, setFormPassword] = useState('');
  const [formRole, setFormRole] = useState<UserRole>('viewer');
  const [formCameraPerms, setFormCameraPerms] = useState<string[]>([]);
  const [formLoading, setFormLoading] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  // Fetch users
  useEffect(() => {
    const controller = new AbortController();
    fetch(`${API}/admin/users`, { credentials: 'include' })
      .then((r) => {
        if (!r.ok) throw new Error('Failed to load users');
        return r.json() as Promise<User[]>;
      })
      .then((users) => {
        if (!controller.signal.aborted) {
          setAllUsers(users);
          setIsLoading(false);
        }
      })
      .catch((err) => {
        if (!controller.signal.aborted) {
          setError(err instanceof Error ? err.message : 'Failed to load users');
          setIsLoading(false);
        }
      });
    return () => controller.abort();
  }, [setAllUsers]);

  const resetForm = useCallback(() => {
    setFormFullName('');
    setFormUsername('');
    setFormEmail('');
    setFormPassword('');
    setFormRole('viewer');
    setFormCameraPerms([]);
    setFormError(null);
  }, []);

  const openAddModal = useCallback(() => {
    resetForm();
    setEditingUser(null);
    setShowAddModal(true);
  }, [resetForm]);

  const openEditModal = useCallback((user: User) => {
    setFormFullName(user.fullName);
    setFormUsername(user.username);
    setFormEmail(user.email);
    setFormPassword('');
    setFormRole(user.role);
    setFormCameraPerms([...user.cameraPermissions]);
    setFormError(null);
    setEditingUser(user);
    setShowAddModal(true);
  }, []);

  const handleSubmit = useCallback(async () => {
    if (formLoading) return;
    setFormError(null);

    if (!formFullName.trim() || !formEmail.trim()) {
      setFormError('Full Name and Email are required.');
      return;
    }

    if (!editingUser && (!formUsername.trim() || !formPassword)) {
      setFormError('Username and Password are required for new users.');
      return;
    }

    setFormLoading(true);

    try {
      if (editingUser) {
        // Update user
        const res = await fetch(`${API}/admin/users/${editingUser.id}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({
            fullName: formFullName.trim(),
            email: formEmail.trim(),
            role: formRole,
            cameraPermissions: formCameraPerms,
          }),
        });
        if (!res.ok) throw new Error('Failed to update user');
        const updated = (await res.json()) as User;
        setAllUsers(allUsers.map((u) => (u.id === updated.id ? updated : u)));
      } else {
        // Create user
        const res = await fetch(`${API}/admin/users`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({
            fullName: formFullName.trim(),
            username: formUsername.trim(),
            email: formEmail.trim(),
            password: formPassword,
            role: formRole,
            cameraPermissions: formCameraPerms,
          }),
        });
        if (!res.ok) throw new Error('Failed to create user');
        const newUser = (await res.json()) as User;
        setAllUsers([...allUsers, newUser]);
      }
      setShowAddModal(false);
      resetForm();
    } catch (err) {
      setFormError(err instanceof Error ? err.message : 'Operation failed');
    } finally {
      setFormLoading(false);
    }
  }, [formFullName, formUsername, formEmail, formPassword, formRole, formCameraPerms, formLoading, editingUser, allUsers, setAllUsers, resetForm]);

  const handleDelete = useCallback(async (userId: string) => {
    try {
      const res = await fetch(`${API}/admin/users/${userId}`, {
        method: 'DELETE',
        credentials: 'include',
      });
      if (!res.ok) throw new Error('Failed to delete user');
      setAllUsers(allUsers.filter((u) => u.id !== userId));
      setDeleteConfirm(null);
    } catch (err) {
      console.error('Delete failed:', err);
    }
  }, [allUsers, setAllUsers]);

  const handleApprove = useCallback(async (userId: string) => {
    try {
      const res = await fetch(`${API}/admin/users/${userId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ status: 'active' }),
      });
      if (!res.ok) throw new Error('Failed to approve user');
      const updated = (await res.json()) as User;
      setAllUsers(allUsers.map((u) => (u.id === updated.id ? updated : u)));
    } catch (err) {
      console.error('Approve failed:', err);
    }
  }, [allUsers, setAllUsers]);

  const toggleCameraPerm = useCallback((cameraId: string) => {
    setFormCameraPerms((prev) =>
      prev.includes(cameraId)
        ? prev.filter((id) => id !== cameraId)
        : [...prev, cameraId],
    );
  }, []);

  const pendingUsers = allUsers.filter((u) => u.status === 'pending');
  const activeUsers = allUsers.filter((u) => u.status !== 'pending');

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <span className="sentinel-spinner text-sentinel-cyan" />
        <span className="ml-3 text-sm text-sentinel-muted">Loading users...</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-4 rounded-lg bg-sentinel-danger/10 border border-sentinel-danger/30 text-sm text-sentinel-danger">
        {error}
      </div>
    );
  }

  return (
    <div>
      {/* Pending Approvals */}
      {pendingUsers.length > 0 && (
        <div className="mb-6">
          <h3 className="text-sm font-semibold text-sentinel-warning mb-3">
            ⏳ Pending Approvals ({pendingUsers.length})
          </h3>
          <div className="flex flex-col gap-2">
            {pendingUsers.map((user) => (
              <div
                key={user.id}
                className="sentinel-card flex items-center justify-between py-3"
              >
                <div>
                  <div className="text-sm font-medium text-sentinel-text">
                    {user.fullName}
                  </div>
                  <div className="text-xs text-sentinel-muted">
                    {user.username} · {user.email}
                  </div>
                </div>
                <div className="flex gap-2">
                  <button
                    className="sentinel-btn sentinel-btn-success text-xs py-1 px-3"
                    onClick={() => handleApprove(user.id)}
                  >
                    ✅ Approve
                  </button>
                  <button
                    className="sentinel-btn sentinel-btn-danger text-xs py-1 px-3"
                    onClick={() => handleDelete(user.id)}
                  >
                    ✕ Reject
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Header with Add button */}
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-semibold text-sentinel-text">
          All Users ({activeUsers.length})
        </h3>
        <button
          className="sentinel-btn sentinel-btn-primary text-xs"
          onClick={openAddModal}
        >
          ➕ Add User
        </button>
      </div>

      {/* Users table */}
      <div className="sentinel-card p-0 overflow-hidden">
        <table className="sentinel-table">
          <thead>
            <tr>
              <th>Full Name</th>
              <th>Username</th>
              <th>Email</th>
              <th>Role</th>
              <th>Status</th>
              <th>Camera Access</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {activeUsers.map((u) => (
              <tr key={u.id}>
                <td className="font-medium">{u.fullName}</td>
                <td className="text-sentinel-muted">{u.username}</td>
                <td className="text-sentinel-muted">{u.email}</td>
                <td>
                  <span className="sentinel-badge sentinel-badge-active">
                    {u.role}
                  </span>
                </td>
                <td>
                  <span
                    className={`sentinel-badge sentinel-badge-${u.status}`}
                  >
                    {u.status}
                  </span>
                </td>
                <td className="text-sentinel-muted text-xs">
                  {u.cameraPermissions.length} cameras
                </td>
                <td>
                  <div className="flex gap-1">
                    <button
                      className="sentinel-btn sentinel-btn-ghost text-xs py-1 px-2"
                      onClick={() => openEditModal(u)}
                    >
                      ✏️
                    </button>
                    <button
                      className="sentinel-btn sentinel-btn-ghost text-xs py-1 px-2 text-sentinel-danger"
                      onClick={() => setDeleteConfirm(u.id)}
                    >
                      🗑️
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Delete confirmation modal */}
      {deleteConfirm && (
        <div className="sentinel-modal-overlay" onClick={() => setDeleteConfirm(null)}>
          <div
            className="sentinel-modal max-w-sm"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="text-base font-semibold text-sentinel-text mb-2">
              Delete User?
            </h3>
            <p className="text-sm text-sentinel-muted mb-4">
              Are you sure you want to delete{' '}
              <strong>
                {allUsers.find((u) => u.id === deleteConfirm)?.username}
              </strong>
              ? This action cannot be undone.
            </p>
            <div className="flex gap-2 justify-end">
              <button
                className="sentinel-btn sentinel-btn-ghost text-xs"
                onClick={() => setDeleteConfirm(null)}
              >
                Cancel
              </button>
              <button
                className="sentinel-btn sentinel-btn-danger text-xs"
                onClick={() => handleDelete(deleteConfirm)}
              >
                Delete User
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Add / Edit User Modal */}
      {showAddModal && (
        <div
          className="sentinel-modal-overlay"
          onClick={() => {
            setShowAddModal(false);
            resetForm();
          }}
        >
          <div
            className="sentinel-modal max-w-lg"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="text-base font-semibold text-sentinel-text mb-4">
              {editingUser ? 'Edit User' : 'Add New User'}
            </h3>

            {formError && (
              <div className="mb-3 p-3 rounded-lg bg-sentinel-danger/10 border border-sentinel-danger/30 text-sm text-sentinel-danger">
                {formError}
              </div>
            )}

            <div className="flex flex-col gap-3">
              <div>
                <label className="sentinel-label">Full Name</label>
                <input
                  className="sentinel-input"
                  value={formFullName}
                  onChange={(e) => setFormFullName(e.target.value)}
                />
              </div>

              {!editingUser && (
                <div>
                  <label className="sentinel-label">Username</label>
                  <input
                    className="sentinel-input"
                    value={formUsername}
                    onChange={(e) => setFormUsername(e.target.value)}
                  />
                </div>
              )}

              <div>
                <label className="sentinel-label">Email</label>
                <input
                  className="sentinel-input"
                  type="email"
                  value={formEmail}
                  onChange={(e) => setFormEmail(e.target.value)}
                />
              </div>

              {!editingUser && (
                <div>
                  <label className="sentinel-label">Password</label>
                  <input
                    className="sentinel-input"
                    type="password"
                    value={formPassword}
                    onChange={(e) => setFormPassword(e.target.value)}
                  />
                </div>
              )}

              <div>
                <label className="sentinel-label">Role</label>
                <select
                  className="sentinel-input sentinel-select"
                  value={formRole}
                  onChange={(e) => setFormRole(e.target.value as UserRole)}
                >
                  <option value="admin">Admin</option>
                  <option value="operator">Operator</option>
                  <option value="viewer">Viewer</option>
                </select>
              </div>

              <div>
                <label className="sentinel-label">Camera Permissions</label>
                <div className="max-h-40 overflow-y-auto border border-sentinel-border rounded-lg p-2 bg-sentinel-bg">
                  {cameras.length === 0 ? (
                    <div className="text-xs text-sentinel-muted/60 py-2 text-center">
                      No cameras available
                    </div>
                  ) : (
                    cameras.map((cam) => (
                      <label
                        key={cam.id}
                        className="flex items-center gap-2 p-1.5 rounded hover:bg-white/5 cursor-pointer"
                      >
                        <input
                          type="checkbox"
                          checked={formCameraPerms.includes(cam.id)}
                          onChange={() => toggleCameraPerm(cam.id)}
                          className="accent-[#00d4ff]"
                        />
                        <span className="text-xs text-sentinel-text">
                          {cam.name}
                        </span>
                      </label>
                    ))
                  )}
                </div>
              </div>
            </div>

            <div className="flex gap-2 justify-end mt-5 pt-4 border-t border-sentinel-border">
              <button
                className="sentinel-btn sentinel-btn-ghost text-xs"
                onClick={() => {
                  setShowAddModal(false);
                  resetForm();
                }}
              >
                Cancel
              </button>
              <button
                className="sentinel-btn sentinel-btn-primary text-xs"
                onClick={handleSubmit}
                disabled={formLoading}
              >
                {formLoading ? (
                  <>
                    <span className="sentinel-spinner" />
                    Saving...
                  </>
                ) : editingUser ? (
                  'Update User'
                ) : (
                  'Create User'
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

// ── System Settings Tab ───────────────────────────────────────

const SystemSettingsTab: React.FC = () => {
  const [settings, setSettings] = useState<SystemSettings>({
    appTitle: 'SENTINEL PRO',
    logoBase64: null,
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    sessionTimeoutMinutes: 30,
    maxFailedLoginAttempts: 5,
  });
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [success, setSuccess] = useState(false);

  useEffect(() => {
    fetch(`${API}/admin/settings`, { credentials: 'include' })
      .then((r) => {
        if (r.ok) return r.json() as Promise<SystemSettings>;
        return null;
      })
      .then((data) => {
        if (data) setSettings(data);
        setIsLoading(false);
      })
      .catch(() => setIsLoading(false));
  }, []);

  const handleSave = async () => {
    setIsSaving(true);
    setSuccess(false);
    try {
      const res = await fetch(`${API}/admin/settings`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(settings),
      });
      if (res.ok) setSuccess(true);
    } finally {
      setIsSaving(false);
    }
  };

  const handleLogoUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      setSettings((s) => ({ ...s, logoBase64: reader.result as string }));
    };
    reader.readAsDataURL(file);
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <span className="sentinel-spinner text-sentinel-cyan" />
      </div>
    );
  }

  return (
    <div className="max-w-lg">
      {success && (
        <div className="mb-4 p-3 rounded-lg bg-sentinel-success/10 border border-sentinel-success/30 text-sm text-sentinel-success">
          Settings saved successfully.
        </div>
      )}

      <div className="flex flex-col gap-4">
        <div>
          <label className="sentinel-label">App Title</label>
          <input
            className="sentinel-input"
            value={settings.appTitle}
            onChange={(e) =>
              setSettings((s) => ({ ...s, appTitle: e.target.value }))
            }
          />
        </div>

        <div>
          <label className="sentinel-label">Logo Upload</label>
          <input
            type="file"
            accept="image/*"
            onChange={handleLogoUpload}
            className="sentinel-input text-xs"
          />
          {settings.logoBase64 && (
            <img
              src={settings.logoBase64}
              alt="Logo preview"
              className="mt-2 h-12 rounded"
            />
          )}
        </div>

        <div>
          <label className="sentinel-label">Timezone</label>
          <input
            className="sentinel-input"
            value={settings.timezone}
            onChange={(e) =>
              setSettings((s) => ({ ...s, timezone: e.target.value }))
            }
          />
        </div>

        <div>
          <label className="sentinel-label">
            Session Timeout (minutes)
          </label>
          <input
            type="number"
            className="sentinel-input"
            value={settings.sessionTimeoutMinutes}
            onChange={(e) =>
              setSettings((s) => ({
                ...s,
                sessionTimeoutMinutes: Number(e.target.value),
              }))
            }
            min={1}
          />
        </div>

        <div>
          <label className="sentinel-label">
            Max Failed Login Attempts
          </label>
          <input
            type="number"
            className="sentinel-input"
            value={settings.maxFailedLoginAttempts}
            onChange={(e) =>
              setSettings((s) => ({
                ...s,
                maxFailedLoginAttempts: Number(e.target.value),
              }))
            }
            min={1}
          />
        </div>

        <button
          className="sentinel-btn sentinel-btn-primary text-xs w-fit"
          onClick={handleSave}
          disabled={isSaving}
        >
          {isSaving ? (
            <>
              <span className="sentinel-spinner" />
              Saving...
            </>
          ) : (
            '💾 Save Settings'
          )}
        </button>
      </div>
    </div>
  );
};

// ── Audit Log Tab ─────────────────────────────────────────────

const AuditLogTab: React.FC = () => {
  const [logs, setLogs] = useState<AuditLogEntry[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    fetch(`${API}/admin/audit-log`, { credentials: 'include' })
      .then((r) => {
        if (r.ok) return r.json() as Promise<AuditLogEntry[]>;
        return [];
      })
      .then((data) => {
        setLogs(data ?? []);
        setIsLoading(false);
      })
      .catch(() => setIsLoading(false));
  }, []);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <span className="sentinel-spinner text-sentinel-cyan" />
      </div>
    );
  }

  return (
    <div className="sentinel-card p-0 overflow-hidden">
      <table className="sentinel-table">
        <thead>
          <tr>
            <th>Timestamp</th>
            <th>User</th>
            <th>Action</th>
            <th>Details</th>
          </tr>
        </thead>
        <tbody>
          {logs.length === 0 ? (
            <tr>
              <td colSpan={4} className="text-center text-sentinel-muted py-6">
                No audit log entries found
              </td>
            </tr>
          ) : (
            logs.map((log) => (
              <tr key={log.id}>
                <td className="text-xs text-sentinel-muted whitespace-nowrap">
                  {new Date(log.timestamp).toLocaleString()}
                </td>
                <td className="text-xs">{log.username}</td>
                <td>
                  <span className="sentinel-badge sentinel-badge-active">
                    {log.action}
                  </span>
                </td>
                <td className="text-xs text-sentinel-muted">
                  {log.details}
                </td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
};

// ── Main Admin Panel ──────────────────────────────────────────

const AdminPanel: React.FC = () => {
  const [activeTab, setActiveTab] = useState<AdminTab>('users');

  return (
    <div className="min-h-screen bg-sentinel-bg">
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
          <Link to="/admin" className="sentinel-nav-link active">
            ⚙️ Admin
          </Link>
          <Link to="/profile" className="sentinel-nav-link">
            👤 Profile
          </Link>
        </div>
      </nav>

      <div className="sentinel-page">
        <div className="sentinel-page-header">
          <h1 className="sentinel-page-title">Admin Panel</h1>
          <p className="sentinel-page-subtitle">
            Manage users, system settings, and audit logs
          </p>
        </div>

        {/* Tabs */}
        <div className="sentinel-tabs">
          <button
            className={`sentinel-tab ${activeTab === 'users' ? 'active' : ''}`}
            onClick={() => setActiveTab('users')}
          >
            👥 User Management
          </button>
          <button
            className={`sentinel-tab ${activeTab === 'settings' ? 'active' : ''}`}
            onClick={() => setActiveTab('settings')}
          >
            ⚙️ System Settings
          </button>
          <button
            className={`sentinel-tab ${activeTab === 'audit' ? 'active' : ''}`}
            onClick={() => setActiveTab('audit')}
          >
            📋 Audit Log
          </button>
        </div>

        {/* Tab content */}
        {activeTab === 'users' && <UserManagementTab />}
        {activeTab === 'settings' && <SystemSettingsTab />}
        {activeTab === 'audit' && <AuditLogTab />}
      </div>
    </div>
  );
};

export default AdminPanel;
