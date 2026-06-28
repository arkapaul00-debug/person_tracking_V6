// ═══ FILE: src/pages/AdminLogin.tsx ═══
import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useSentinelStore } from '@utils/store';

const AdminLogin: React.FC = () => {
  const navigate = useNavigate();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState(false);
  const [loading, setLoading] = useState(false);

  const ADMIN_USERNAME = 'ADMIN';
  const ADMIN_PASSWORD = 'admin123';

  const handleAdminLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(false);
    
    // Simulate network delay
    await new Promise(resolve => setTimeout(resolve, 800));
    
    if (username.trim() === ADMIN_USERNAME && password === ADMIN_PASSWORD) {
      useSentinelStore.getState().setAdminAuthenticated(true);
      navigate('/admin/dashboard');
    } else {
      setError(true);
      setLoading(false);
    }
  };

  return (
    <div style={{ position: 'relative', width: '100vw', height: '100vh', background: '#020810', display: 'flex', alignItems: 'center', justifyContent: 'center', overflow: 'hidden' }}>
      
      {/* Background Animated Grid */}
      <div style={{
        position: 'absolute', top: 0, left: 0, width: '100%', height: '100%',
        backgroundImage: 'linear-gradient(rgba(255, 59, 59, 0.05) 1px, transparent 1px), linear-gradient(90deg, rgba(255, 59, 59, 0.05) 1px, transparent 1px)',
        backgroundSize: '40px 40px',
        transform: 'perspective(500px) rotateX(60deg)',
        transformOrigin: 'bottom',
        zIndex: 0,
        pointerEvents: 'none',
      }}></div>

      <div className={`auth-card auth-card-admin ${error ? 'shake' : ''}`} style={{ position: 'relative', zIndex: 10 }}>
        
        {/* Header */}
        <div style={{ textAlign: 'center', marginBottom: '24px' }}>
          <svg style={{ color: '#ff3b3b', width: '48px', height: '48px', margin: '0 auto 16px' }} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path>
          </svg>
          <h2 style={{ fontFamily: 'Orbitron, monospace', color: '#ff3b3b', fontSize: '1.5rem', margin: 0, letterSpacing: '2px' }}>
            ADMIN ACCESS
          </h2>
          <div style={{ color: '#7a8db0', fontSize: '0.75rem', marginTop: '8px', letterSpacing: '1px' }}>
            RESTRICTED — AUTHORIZED PERSONNEL ONLY
          </div>
        </div>

        <div style={{ height: '1px', background: 'rgba(255, 59, 59, 0.3)', margin: '24px 0' }}></div>

        {/* Warning Banner */}
        <div style={{ background: 'rgba(255, 170, 0, 0.1)', borderLeft: '3px solid #ffaa00', padding: '12px', fontSize: '0.75rem', color: '#ffaa00', marginBottom: '24px' }}>
          ⚠ This portal is monitored and logged. Unauthorized access attempts will be reported.
        </div>

        {/* Form */}
        <form onSubmit={handleAdminLogin}>
          
          <div style={{ marginBottom: '20px' }}>
            <label style={{ display: 'block', color: '#7a8db0', fontSize: '0.7rem', textTransform: 'uppercase', marginBottom: '8px', letterSpacing: '1px' }}>
              ADMIN USERNAME
            </label>
            <div style={{ position: 'relative' }}>
              <div style={{ position: 'absolute', left: '12px', top: '12px', color: '#7a8db0' }}>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path><circle cx="12" cy="7" r="4"></circle></svg>
              </div>
              <input 
                type="text" 
                className="sentinel-input admin-input"
                style={{ paddingLeft: '36px' }}
                placeholder="Enter admin username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoComplete="off"
              />
            </div>
          </div>

          <div style={{ marginBottom: '24px' }}>
            <label style={{ display: 'block', color: '#7a8db0', fontSize: '0.7rem', textTransform: 'uppercase', marginBottom: '8px', letterSpacing: '1px' }}>
              ADMIN PASSWORD
            </label>
            <div style={{ position: 'relative' }}>
              <div style={{ position: 'absolute', left: '12px', top: '12px', color: '#7a8db0' }}>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect><path d="M7 11V7a5 5 0 0 1 10 0v4"></path></svg>
              </div>
              <input 
                type={showPassword ? "text" : "password"} 
                className="sentinel-input admin-input"
                style={{ paddingLeft: '36px', paddingRight: '36px' }}
                placeholder="••••••••"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
              <button type="button" onClick={() => setShowPassword(!showPassword)} style={{ position: 'absolute', right: '12px', top: '12px', background: 'none', border: 'none', color: '#7a8db0', cursor: 'pointer', padding: 0 }}>
                {showPassword ? (
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"></path><line x1="1" y1="1" x2="23" y2="23"></line></svg>
                ) : (
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path><circle cx="12" cy="12" r="3"></circle></svg>
                )}
              </button>
            </div>
          </div>

          <button type="submit" disabled={loading} style={{
            width: '100%',
            background: loading ? '#660000' : '#cc0000',
            color: 'white',
            border: 'none',
            padding: '16px',
            fontFamily: 'Orbitron, monospace',
            fontSize: '1rem',
            letterSpacing: '1px',
            cursor: loading ? 'wait' : 'pointer',
            borderRadius: '4px',
            transition: 'all 0.2s'
          }}
          onMouseOver={(e) => !loading && (e.currentTarget.style.background = '#ff1a1a', e.currentTarget.style.boxShadow = '0 0 15px rgba(255, 59, 59, 0.4)')}
          onMouseOut={(e) => !loading && (e.currentTarget.style.background = '#cc0000', e.currentTarget.style.boxShadow = 'none')}
          >
            {loading ? <div className="sentinel-spinner" style={{ margin: '0 auto' }}></div> : 'ACCESS SYSTEM'}
          </button>
        </form>

        {/* Error State */}
        {error && (
          <div style={{ marginTop: '16px', background: 'rgba(255, 59, 59, 0.1)', border: '1px solid #ff3b3b', color: '#ff3b3b', padding: '12px', fontSize: '0.8rem', textAlign: 'center', borderRadius: '4px' }}>
            ⛔ ACCESS DENIED — Invalid credentials
          </div>
        )}

        <div style={{ marginTop: '32px', textAlign: 'center' }}>
          <button onClick={() => navigate('/')} style={{ background: 'none', border: 'none', color: '#00d4ff', fontSize: '0.8rem', cursor: 'pointer', fontFamily: 'monospace', textDecoration: 'none' }}>
            ← Return to Main Terminal
          </button>
        </div>

      </div>
    </div>
  );
};

export default AdminLogin;
