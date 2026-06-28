// ═══ FILE: src/pages/AdminDashboard.tsx ═══
import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useSentinelStore } from '@utils/store';
import { ManagedUser } from '@utils/types';

type Tab = 'analytics' | 'manage' | 'create' | 'settings';

const AdminDashboard: React.FC = () => {
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState<Tab>('analytics');
  
  const { managedUsers, setAdminAuthenticated, addManagedUser, updateManagedUser, deleteManagedUser } = useSentinelStore();

  const handleLogout = () => {
    setAdminAuthenticated(false);
    navigate('/');
  };

  return (
    <div className="sentinel-page">
      <header className="sentinel-page-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h1 className="sentinel-page-title" style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <span style={{ color: '#ff3b3b' }}>🛡️</span> ADMIN DASHBOARD
          </h1>
          <p className="sentinel-page-subtitle">System Management & Analytics</p>
        </div>
        <button className="sentinel-btn sentinel-btn-ghost" onClick={handleLogout}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"></path><polyline points="16 17 21 12 16 7"></polyline><line x1="21" y1="12" x2="9" y2="12"></line></svg>
          LOGOUT
        </button>
      </header>

      <div className="sentinel-tabs">
        <button className={`admin-tab ${activeTab === 'analytics' ? 'active' : ''}`} onClick={() => setActiveTab('analytics')}>📊 ANALYTICS</button>
        <button className={`admin-tab ${activeTab === 'manage' ? 'active' : ''}`} onClick={() => setActiveTab('manage')}>👥 MANAGE USERS</button>
        <button className={`admin-tab ${activeTab === 'create' ? 'active' : ''}`} onClick={() => setActiveTab('create')}>➕ CREATE USER</button>
        <button className={`admin-tab ${activeTab === 'settings' ? 'active' : ''}`} onClick={() => setActiveTab('settings')}>⚙️ SETTINGS</button>
      </div>

      <div className="admin-content" style={{ minHeight: '60vh' }}>
        {activeTab === 'analytics' && <AnalyticsTab users={managedUsers} />}
        {activeTab === 'manage' && <ManageUsersTab users={managedUsers} onUpdate={updateManagedUser} onDelete={deleteManagedUser} />}
        {activeTab === 'create' && <CreateUserTab onAdd={addManagedUser} users={managedUsers} />}
        {activeTab === 'settings' && <SettingsTab />}
      </div>
    </div>
  );
};

// --- TABS ---

const AnalyticsTab: React.FC<{ users: ManagedUser[] }> = ({ users }) => {
  const activeCount = users.filter(u => u.status === 'active').length;
  
  return (
    <div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '20px', marginBottom: '24px' }}>
        <div className="stat-card">
          <div className="stat-card-value">{users.length}</div>
          <div className="stat-card-label">TOTAL USERS</div>
        </div>
        <div className="stat-card">
          <div className="stat-card-value">{activeCount}</div>
          <div className="stat-card-label">ACTIVE TODAY</div>
        </div>
        <div className="stat-card">
          <div className="stat-card-value">{users.reduce((acc, u) => acc + u.loginCount, 0)}</div>
          <div className="stat-card-label">TOTAL LOGINS</div>
        </div>
        <div className="stat-card">
          <div className="stat-card-value">0</div>
          <div className="stat-card-label">ALERTS TODAY</div>
        </div>
      </div>

      <div className="sentinel-card">
        <h3 style={{ marginTop: 0, color: '#00d4ff', fontFamily: 'Orbitron', fontSize: '1rem' }}>RECENT ACTIVITY</h3>
        <div style={{ maxHeight: '300px', overflowY: 'auto', background: '#0a0e1a', padding: '12px', borderRadius: '4px', border: '1px solid #1e2d4a' }}>
          <div className="activity-item admin-action">[10:44:21] ADMIN accessed dashboard</div>
          {users.map(u => (
            <div key={u.id} className="activity-item navigation">[{new Date(u.createdAt).toLocaleTimeString()}] ADMIN created new user: {u.username}</div>
          ))}
          {users.length === 0 && <div style={{ color: '#7a8db0', fontSize: '0.8rem', padding: '8px' }}>No recent user activity.</div>}
        </div>
      </div>
    </div>
  );
};

const ManageUsersTab: React.FC<{ users: ManagedUser[], onUpdate: (id: string, patch: Partial<ManagedUser>) => void, onDelete: (id: string) => void }> = ({ users, onUpdate, onDelete }) => {
  const [editingId, setEditingId] = useState<string | null>(null);
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null);
  const [deleteCanClick, setDeleteCanClick] = useState(false);

  // Edit form state
  const [editName, setEditName] = useState('');
  const [editDesig, setEditDesig] = useState('');
  const [editPhone, setEditPhone] = useState('');
  const [editEmail, setEditEmail] = useState('');
  const [editStatus, setEditStatus] = useState<'active'|'suspended'>('active');

  const startEdit = (u: ManagedUser) => {
    setEditingId(u.id);
    setEditName(u.name);
    setEditDesig(u.designation);
    setEditPhone(u.phone);
    setEditEmail(u.email);
    setEditStatus(u.status);
  };

  const saveEdit = () => {
    if (editingId) {
      onUpdate(editingId, { name: editName, designation: editDesig, phone: editPhone, email: editEmail, status: editStatus });
      setEditingId(null);
    }
  };

  const triggerDeleteConfirm = (id: string) => {
    setDeleteConfirmId(id);
    setDeleteCanClick(false);
    setTimeout(() => setDeleteCanClick(true), 1000);
  };

  const confirmDelete = () => {
    if (deleteConfirmId && deleteCanClick) {
      onDelete(deleteConfirmId);
      setDeleteConfirmId(null);
    }
  };

  return (
    <div className="sentinel-card">
      <table className="admin-table">
        <thead>
          <tr>
            <th>NAME</th>
            <th>DESIGNATION</th>
            <th>USERNAME</th>
            <th>STATUS</th>
            <th>ACTIONS</th>
          </tr>
        </thead>
        <tbody>
          {users.map(u => (
            <React.Fragment key={u.id}>
              <tr className={u.status === 'suspended' ? 'suspended' : ''}>
                <td>{u.name}</td>
                <td>{u.designation}</td>
                <td>{u.username}</td>
                <td>
                  <span className={`sentinel-badge ${u.status === 'active' ? 'sentinel-badge-active' : 'sentinel-badge-suspended'}`}>
                    {u.status}
                  </span>
                </td>
                <td>
                  <button className="sentinel-btn sentinel-btn-ghost" style={{ padding: '4px 8px', fontSize: '0.7rem' }} onClick={() => startEdit(u)}>✏️ EDIT</button>
                  <button className="sentinel-btn sentinel-btn-ghost" style={{ padding: '4px 8px', fontSize: '0.7rem', color: '#ff3b3b', marginLeft: '8px' }} onClick={() => triggerDeleteConfirm(u.id)}>🗑️</button>
                  <button className="sentinel-btn sentinel-btn-ghost" style={{ padding: '4px 8px', fontSize: '0.7rem', marginLeft: '8px' }} onClick={() => onUpdate(u.id, { status: u.status === 'active' ? 'suspended' : 'active' })}>
                    {u.status === 'active' ? '🔒 SUSPEND' : '🔓 UNSUSPEND'}
                  </button>
                </td>
              </tr>
              {editingId === u.id && (
                <tr>
                  <td colSpan={5} style={{ background: 'rgba(0,212,255,0.05)', padding: '16px' }}>
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px', marginBottom: '16px' }}>
                      <div>
                        <label className="sentinel-label">NAME</label>
                        <input className="sentinel-input" value={editName} onChange={e => setEditName(e.target.value)} />
                      </div>
                      <div>
                        <label className="sentinel-label">DESIGNATION</label>
                        <input className="sentinel-input" value={editDesig} onChange={e => setEditDesig(e.target.value)} />
                      </div>
                      <div>
                        <label className="sentinel-label">PHONE</label>
                        <input className="sentinel-input" value={editPhone} onChange={e => setEditPhone(e.target.value)} />
                      </div>
                      <div>
                        <label className="sentinel-label">EMAIL</label>
                        <input className="sentinel-input" value={editEmail} onChange={e => setEditEmail(e.target.value)} />
                      </div>
                      <div>
                        <label className="sentinel-label">USERNAME (READ-ONLY)</label>
                        <input className="sentinel-input" value={u.username} disabled />
                      </div>
                      <div>
                        <label className="sentinel-label">STATUS</label>
                        <select className="sentinel-input sentinel-select" value={editStatus} onChange={e => setEditStatus(e.target.value as 'active'|'suspended')}>
                          <option value="active">Active</option>
                          <option value="suspended">Suspended</option>
                        </select>
                      </div>
                    </div>
                    <div>
                      <button className="sentinel-btn sentinel-btn-primary" onClick={saveEdit}>💾 SAVE CHANGES</button>
                      <button className="sentinel-btn sentinel-btn-ghost" style={{ marginLeft: '12px' }} onClick={() => setEditingId(null)}>CANCEL</button>
                    </div>
                  </td>
                </tr>
              )}
            </React.Fragment>
          ))}
          {users.length === 0 && <tr><td colSpan={5} style={{ textAlign: 'center', color: '#7a8db0' }}>No users found.</td></tr>}
        </tbody>
      </table>

      {deleteConfirmId && (
        <div className="sentinel-modal-overlay">
          <div className="sentinel-modal" style={{ border: '1px solid #ff3b3b' }}>
            <h3 style={{ color: '#ff3b3b', marginTop: 0 }}>⚠️ CONFIRM USER DELETION</h3>
            <p>You are about to permanently delete the user.</p>
            <p>This action CANNOT be undone. The user will immediately lose system access.</p>
            <div style={{ display: 'flex', gap: '12px', marginTop: '24px' }}>
              <button className="sentinel-btn sentinel-btn-ghost" onClick={() => setDeleteConfirmId(null)}>CANCEL</button>
              <button 
                className="sentinel-btn sentinel-btn-danger" 
                onClick={confirmDelete}
                disabled={!deleteCanClick}
              >
                {deleteCanClick ? '⛔ DELETE USER' : 'WAIT...'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

const CreateUserTab: React.FC<{ onAdd: (user: ManagedUser) => void, users: ManagedUser[] }> = ({ onAdd, users }) => {
  const [name, setName] = useState('');
  const [desig, setDesig] = useState('');
  const [phone, setPhone] = useState('');
  const [email, setEmail] = useState('');
  const [username, setUsername] = useState('');
  const [sameAsEmail, setSameAsEmail] = useState(false);
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [showToast, setShowToast] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});

  const getStrength = (pass: string) => {
    if (pass.length === 0) return 0;
    if (pass.length < 6) return 1; // weak
    let strength = 2; // fair
    if (pass.length >= 8 && (/[A-Z]/.test(pass) || /[0-9]/.test(pass))) strength = 3; // good
    if (pass.length >= 8 && /[A-Z]/.test(pass) && /[a-z]/.test(pass) && /[0-9]/.test(pass) && /[^A-Za-z0-9]/.test(pass)) strength = 4; // strong
    return strength;
  };

  const strength = getStrength(password);

  const handleSameAsEmailToggle = () => {
    setSameAsEmail(!sameAsEmail);
    if (!sameAsEmail) setUsername(email);
  };

  const handleEmailChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = e.target.value;
    setEmail(val);
    if (sameAsEmail) setUsername(val);
  };

  const validate = () => {
    const newErrs: Record<string, string> = {};
    if (name.length < 2) newErrs.name = "Name must be at least 2 characters";
    if (!desig) newErrs.desig = "Designation is required";
    if (!phone) newErrs.phone = "Phone is required";
    if (!email.includes('@')) newErrs.email = "Valid email is required";
    if (users.some(u => u.email === email)) newErrs.email = "Email already exists";
    if (username.length < 3 || username.includes(' ')) newErrs.username = "Username must be 3+ characters with no spaces";
    if (users.some(u => u.username === username)) newErrs.username = "Username already exists";
    if (password.length < 6) newErrs.password = "Password must be at least 6 characters";
    if (password !== confirmPassword) newErrs.confirmPassword = "Passwords do not match";
    
    setErrors(newErrs);
    return Object.keys(newErrs).length === 0;
  };

  const handleSubmit = () => {
    if (validate()) {
      const newUser: ManagedUser = {
        id: Math.random().toString(36).substring(7),
        name,
        designation: desig,
        phone,
        email,
        username,
        passwordHash: password, // In a real app, hash this!
        status: 'active',
        createdAt: Date.now(),
        lastLoginAt: null,
        loginCount: 0,
        lastActiveRoute: null
      };
      onAdd(newUser);
      
      // Reset
      setName(''); setDesig(''); setPhone(''); setEmail(''); setUsername(''); setPassword(''); setConfirmPassword(''); setSameAsEmail(false);
      
      // Toast
      setShowToast(true);
      setTimeout(() => setShowToast(false), 3000);
    }
  };

  return (
    <div className="sentinel-card" style={{ maxWidth: '800px', margin: '0 auto' }}>
      <h2 style={{ color: '#00d4ff', fontFamily: 'Orbitron', marginTop: 0, borderBottom: '1px solid #1e2d4a', paddingBottom: '12px' }}>CREATE NEW USER</h2>
      
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '24px', marginTop: '24px' }}>
        <div>
          <label className="sentinel-label">FULL NAME *</label>
          <input className="sentinel-input" value={name} onChange={e => setName(e.target.value)} placeholder="e.g. John Smith" />
          {errors.name && <div style={{ color: '#ff3b3b', fontSize: '0.75rem', marginTop: '4px' }}>{errors.name}</div>}
        </div>
        <div>
          <label className="sentinel-label">DESIGNATION *</label>
          <input className="sentinel-input" value={desig} onChange={e => setDesig(e.target.value)} placeholder="e.g. Security Opr." />
          {errors.desig && <div style={{ color: '#ff3b3b', fontSize: '0.75rem', marginTop: '4px' }}>{errors.desig}</div>}
        </div>
        
        <div>
          <label className="sentinel-label">PHONE NUMBER *</label>
          <input className="sentinel-input" value={phone} onChange={e => setPhone(e.target.value)} placeholder="+91 9XXXXXXXXX" />
          {errors.phone && <div style={{ color: '#ff3b3b', fontSize: '0.75rem', marginTop: '4px' }}>{errors.phone}</div>}
        </div>
        <div>
          <label className="sentinel-label">EMAIL ADDRESS *</label>
          <input className="sentinel-input" value={email} onChange={handleEmailChange} placeholder="john@company.com" />
          {errors.email && <div style={{ color: '#ff3b3b', fontSize: '0.75rem', marginTop: '4px' }}>{errors.email}</div>}
        </div>

        <div style={{ gridColumn: '1 / -1' }}>
          <label className="sentinel-label">USERNAME *</label>
          <input className="sentinel-input" value={username} onChange={e => setUsername(e.target.value)} disabled={sameAsEmail} style={{ background: sameAsEmail ? '#060a14' : '', opacity: sameAsEmail ? 0.6 : 1 }} />
          <label className="username-same-as-email">
            <input type="checkbox" checked={sameAsEmail} onChange={handleSameAsEmailToggle} />
            Same as email address
          </label>
          {errors.username && <div style={{ color: '#ff3b3b', fontSize: '0.75rem', marginTop: '4px' }}>{errors.username}</div>}
        </div>

        <div>
          <label className="sentinel-label">PASSWORD *</label>
          <input type="password" className="sentinel-input" value={password} onChange={e => setPassword(e.target.value)} placeholder="••••••••" />
          {errors.password && <div style={{ color: '#ff3b3b', fontSize: '0.75rem', marginTop: '4px' }}>{errors.password}</div>}
          
          <div style={{ marginTop: '12px' }}>
            <div style={{ fontSize: '0.7rem', color: '#7a8db0', marginBottom: '4px' }}>
              PASSWORD STRENGTH: {strength === 1 ? 'WEAK' : strength === 2 ? 'FAIR' : strength === 3 ? 'GOOD' : strength === 4 ? 'STRONG' : ''}
            </div>
            <div className="strength-bar">
              <div className={`strength-segment ${strength >= 1 ? (strength===1?'weak':strength===2?'fair':strength===3?'good':'strong') : ''}`}></div>
              <div className={`strength-segment ${strength >= 2 ? (strength===2?'fair':strength===3?'good':'strong') : ''}`}></div>
              <div className={`strength-segment ${strength >= 3 ? (strength===3?'good':'strong') : ''}`}></div>
              <div className={`strength-segment ${strength >= 4 ? 'strong' : ''}`}></div>
            </div>
          </div>
        </div>
        
        <div>
          <label className="sentinel-label">CONFIRM PASSWORD *</label>
          <div style={{ position: 'relative' }}>
            <input type="password" className="sentinel-input" value={confirmPassword} onChange={e => setConfirmPassword(e.target.value)} placeholder="••••••••" />
            {confirmPassword && (
              <span style={{ position: 'absolute', right: '12px', top: '10px' }}>
                {password === confirmPassword ? '✅' : '❌'}
              </span>
            )}
          </div>
          {errors.confirmPassword && <div style={{ color: '#ff3b3b', fontSize: '0.75rem', marginTop: '4px' }}>{errors.confirmPassword}</div>}
        </div>
      </div>

      <div style={{ marginTop: '32px', display: 'flex', gap: '16px' }}>
        <button className="sentinel-btn sentinel-btn-ghost" onClick={() => {
          setName(''); setDesig(''); setPhone(''); setEmail(''); setUsername(''); setPassword(''); setConfirmPassword(''); setErrors({});
        }}>CLEAR FORM</button>
        <button className="sentinel-btn sentinel-btn-primary" onClick={handleSubmit}>✅ CREATE USER</button>
      </div>

      {showToast && (
        <div className="toast-success">
          ✅ User {username} created successfully
        </div>
      )}
    </div>
  );
};

const SettingsTab: React.FC = () => {
  return (
    <div className="sentinel-card" style={{ maxWidth: '600px', margin: '0 auto' }}>
      <h3 style={{ color: '#00d4ff', fontFamily: 'Orbitron', marginTop: 0 }}>SYSTEM SETTINGS</h3>
      <div style={{ marginTop: '24px' }}>
        <label className="sentinel-label">SESSION TIMEOUT (MINUTES)</label>
        <input type="number" className="sentinel-input" defaultValue={60} />
      </div>
      <div style={{ marginTop: '16px' }}>
        <label className="sentinel-label">SYSTEM NAME</label>
        <input type="text" className="sentinel-input" defaultValue="SENTINEL PRO" />
      </div>
      <div style={{ marginTop: '24px', padding: '16px', background: 'rgba(255, 170, 0, 0.1)', border: '1px solid #ffaa00', borderRadius: '4px' }}>
        <label style={{ display: 'flex', alignItems: 'center', gap: '12px', color: '#ffaa00', fontWeight: 'bold' }}>
          <input type="checkbox" style={{ width: '18px', height: '18px' }} />
          ENABLE MAINTENANCE MODE
        </label>
        <p style={{ margin: '8px 0 0 30px', fontSize: '0.8rem', color: '#7a8db0' }}>Regular users cannot log in while maintenance mode is active.</p>
      </div>
      <button className="sentinel-btn sentinel-btn-primary" style={{ marginTop: '24px' }}>SAVE SETTINGS</button>
    </div>
  );
};

export default AdminDashboard;
