// src/pages/Monitoring.tsx
import React, { useEffect } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { useSentinelStore } from '@utils/store';
import { fetchAllCameras } from '@utils/cameraDiscovery';
import { logout } from '@utils/auth';
import CameraSidebar from '@components/CameraSidebar';
import CameraGrid from '@components/CameraGrid';
import AlertBanner from '@components/AlertBanner';

const Monitoring: React.FC = () => {
  const navigate = useNavigate();
  const user = useSentinelStore((s) => s.user);
  const setCameras = useSentinelStore((s) => s.setCameras);
  const systemStatus = useSentinelStore((s) => s.systemStatus);

  // Load cameras on mount
  useEffect(() => {
    const controller = new AbortController();

    fetchAllCameras()
      .then((cameras) => {
        if (!controller.signal.aborted) {
          setCameras(cameras);
        }
      })
      .catch((err) => {
        if (!controller.signal.aborted) {
          console.warn('[Monitoring] Failed to load cameras:', err);
        }
      });

    return () => controller.abort();
  }, [setCameras]);

  const handleLogout = async () => {
    await logout();
    navigate('/login', { replace: true });
  };

  return (
    <div className="h-screen flex flex-col bg-sentinel-bg">
      {/* Navbar */}
      <nav className="sentinel-navbar">
        <div className="sentinel-nav-brand">
          <span className="inline-flex items-center justify-center w-8 h-8 rounded-lg bg-gradient-to-br from-sentinel-cyan to-cyan-600 text-xs font-black text-sentinel-bg">
            S
          </span>
          SENTINEL PRO
        </div>

        <div className="sentinel-nav-links">
          <Link to="/monitoring" className="sentinel-nav-link active">
            🖥️ Monitor
          </Link>
          <Link to="/cameras" className="sentinel-nav-link">
            📷 Cameras
          </Link>
          <Link to="/targets" className="sentinel-nav-link">
            🎯 Targets
          </Link>
          {user?.role === 'admin' && (
            <Link to="/admin" className="sentinel-nav-link">
              ⚙️ Admin
            </Link>
          )}
          <Link to="/profile" className="sentinel-nav-link">
            👤 Profile
          </Link>
        </div>

        <div className="flex items-center gap-3">
          {/* System status indicator */}
          {systemStatus && (
            <div className="flex items-center gap-1.5">
              <span
                className={`status-dot status-dot-${
                  systemStatus.alertLevel === 'critical'
                    ? 'error'
                    : systemStatus.alertLevel === 'warning'
                      ? 'connecting'
                      : 'online'
                }`}
              />
              <span className="text-[10px] text-sentinel-muted uppercase tracking-wider">
                {systemStatus.alertLevel}
              </span>
            </div>
          )}

          <span className="text-xs text-sentinel-muted">
            {user?.fullName}
          </span>
          <button
            className="sentinel-btn sentinel-btn-ghost text-xs py-1.5 px-3"
            onClick={handleLogout}
          >
            Logout
          </button>
        </div>
      </nav>

      {/* Main content */}
      <div className="flex-1 flex overflow-hidden">
        {/* Left sidebar */}
        <CameraSidebar />

        {/* Camera viewing area */}
        <main className="flex-1 overflow-hidden relative">
          <CameraGrid />
        </main>
      </div>

      {/* Alert banners (floating) */}
      <AlertBanner />
    </div>
  );
};

export default Monitoring;
