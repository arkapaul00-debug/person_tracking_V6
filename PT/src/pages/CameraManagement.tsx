// src/pages/CameraManagement.tsx
import React, { useState, useEffect, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { useSentinelStore } from '@utils/store';
import type { Camera, DiscoveredCamera, RTSPTestResult } from '@utils/types';
import {
  fetchAllCameras,
  testRTSPConnection,
  addCameraManually,
  discoverNetworkCameras,
  saveDiscoveredCameras,
  deleteCamera,
} from '@utils/cameraDiscovery';

const API = import.meta.env.VITE_AUTH_ENDPOINT;

const CameraManagement: React.FC = () => {
  const cameras = useSentinelStore((s) => s.cameras);
  const setCameras = useSentinelStore((s) => s.setCameras);
  const addCameraToStore = useSentinelStore((s) => s.addCamera);
  const removeCamera = useSentinelStore((s) => s.removeCamera);
  const updateCamera = useSentinelStore((s) => s.updateCamera);

  const [isLoading, setIsLoading] = useState(true);

  // Manual add state
  const [showManualPanel, setShowManualPanel] = useState(false);
  const [manualName, setManualName] = useState('');
  const [manualRtsp, setManualRtsp] = useState('');
  const [manualLocation, setManualLocation] = useState('');
  const [testResult, setTestResult] = useState<RTSPTestResult | null>(null);
  const [isTesting, setIsTesting] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [manualError, setManualError] = useState<string | null>(null);

  // Auto-discover state
  const [showDiscoverPanel, setShowDiscoverPanel] = useState(false);
  const [isDiscovering, setIsDiscovering] = useState(false);
  const [discovered, setDiscovered] = useState<DiscoveredCamera[]>([]);
  const [discoverError, setDiscoverError] = useState<string | null>(null);
  const [isSavingDiscovered, setIsSavingDiscovered] = useState(false);

  // Edit state
  const [editingCamera, setEditingCamera] = useState<Camera | null>(null);
  const [editName, setEditName] = useState('');
  const [editLocation, setEditLocation] = useState('');

  // Delete confirmation
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null);

  // Load cameras on mount
  useEffect(() => {
    const controller = new AbortController();
    fetchAllCameras()
      .then((cams) => {
        if (!controller.signal.aborted) {
          setCameras(cams);
          setIsLoading(false);
        }
      })
      .catch(() => {
        if (!controller.signal.aborted) setIsLoading(false);
      });
    return () => controller.abort();
  }, [setCameras]);

  // ── Manual Add Handlers ─────────────────────────────────

  const handleTestRTSP = useCallback(async () => {
    if (isTesting || !manualRtsp.trim()) return;
    setIsTesting(true);
    setTestResult(null);
    setManualError(null);

    const result = await testRTSPConnection(manualRtsp.trim());
    setTestResult(result);
    setIsTesting(false);
  }, [manualRtsp, isTesting]);

  const handleManualSave = useCallback(async () => {
    if (isSaving || !manualName.trim() || !manualRtsp.trim()) return;
    setIsSaving(true);
    setManualError(null);

    try {
      const camera = await addCameraManually({
        name: manualName.trim(),
        rtspUrl: manualRtsp.trim(),
        location: manualLocation.trim(),
      });
      addCameraToStore(camera);
      setShowManualPanel(false);
      setManualName('');
      setManualRtsp('');
      setManualLocation('');
      setTestResult(null);
    } catch (err) {
      setManualError(
        err instanceof Error ? err.message : 'Failed to save camera',
      );
    } finally {
      setIsSaving(false);
    }
  }, [manualName, manualRtsp, manualLocation, isSaving, addCameraToStore]);

  // ── Auto-Discover Handlers ──────────────────────────────

  const handleDiscover = useCallback(async () => {
    if (isDiscovering) return;
    setIsDiscovering(true);
    setDiscoverError(null);
    setDiscovered([]);

    try {
      const result = await discoverNetworkCameras();
      setDiscovered(result);
    } catch (err) {
      setDiscoverError(
        err instanceof Error ? err.message : 'Discovery failed',
      );
    } finally {
      setIsDiscovering(false);
    }
  }, [isDiscovering]);

  const handleSaveAllDiscovered = useCallback(async () => {
    if (isSavingDiscovered || discovered.length === 0) return;
    setIsSavingDiscovered(true);

    try {
      const saved = await saveDiscoveredCameras(discovered);
      saved.forEach((cam) => addCameraToStore(cam));
      setDiscovered([]);
      setShowDiscoverPanel(false);
    } catch (err) {
      setDiscoverError(
        err instanceof Error ? err.message : 'Failed to save cameras',
      );
    } finally {
      setIsSavingDiscovered(false);
    }
  }, [discovered, isSavingDiscovered, addCameraToStore]);

  const handleSaveSingleDiscovered = useCallback(
    async (disc: DiscoveredCamera) => {
      try {
        const saved = await saveDiscoveredCameras([disc]);
        saved.forEach((cam) => addCameraToStore(cam));
        setDiscovered((prev) =>
          prev.filter((d) => d.ipAddress !== disc.ipAddress),
        );
      } catch (err) {
        console.error('Failed to save camera:', err);
      }
    },
    [addCameraToStore],
  );

  // ── Test existing camera ────────────────────────────────

  const handleTestExisting = useCallback(
    async (camera: Camera) => {
      updateCamera(camera.id, { status: 'connecting' });
      const result = await testRTSPConnection(camera.rtspUrl);
      updateCamera(camera.id, {
        status: result.success ? 'online' : 'error',
        lastSeenAt: result.success ? Date.now() : camera.lastSeenAt,
      });
    },
    [updateCamera],
  );

  // ── Delete camera ───────────────────────────────────────

  const handleDelete = useCallback(
    async (cameraId: string) => {
      try {
        await deleteCamera(cameraId);
        removeCamera(cameraId);
        setDeleteConfirm(null);
      } catch (err) {
        console.error('Failed to delete camera:', err);
      }
    },
    [removeCamera],
  );

  // ── Edit camera ─────────────────────────────────────────

  const handleEditSave = useCallback(async () => {
    if (!editingCamera) return;
    try {
      const res = await fetch(`${API}/cameras/${editingCamera.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          name: editName.trim(),
          location: editLocation.trim(),
        }),
      });
      if (!res.ok) throw new Error('Failed to update camera');
      updateCamera(editingCamera.id, {
        name: editName.trim(),
        location: editLocation.trim(),
      });
      setEditingCamera(null);
    } catch (err) {
      console.error('Edit failed:', err);
    }
  }, [editingCamera, editName, editLocation, updateCamera]);

  const statusIcon = (status: string) => {
    switch (status) {
      case 'online': return '🟢';
      case 'offline': return '🔴';
      case 'connecting': return '🟡';
      default: return '⚠️';
    }
  };

  return (
    <div className="min-h-screen bg-sentinel-bg">
      {/* Navbar */}
      <nav className="sentinel-navbar">
        <Link to="/monitoring" className="sentinel-nav-brand">
          <span className="inline-flex items-center justify-center w-8 h-8 rounded-lg bg-gradient-to-br from-sentinel-cyan to-cyan-600 text-xs font-black text-sentinel-bg">
            S
          </span>
          SENTINEL PRO
        </Link>
        <div className="sentinel-nav-links">
          <Link to="/monitoring" className="sentinel-nav-link">🖥️ Monitor</Link>
          <Link to="/cameras" className="sentinel-nav-link active">📷 Cameras</Link>
          <Link to="/targets" className="sentinel-nav-link">🎯 Targets</Link>
          <Link to="/admin" className="sentinel-nav-link">⚙️ Admin</Link>
          <Link to="/profile" className="sentinel-nav-link">👤 Profile</Link>
        </div>
      </nav>

      <div className="sentinel-page">
        <div className="sentinel-page-header">
          <h1 className="sentinel-page-title">Camera Management</h1>
          <p className="sentinel-page-subtitle">
            Add, discover, and manage all surveillance cameras
          </p>
        </div>

        {/* Action Buttons */}
        <div className="flex gap-3 mb-6">
          <button
            className="sentinel-btn sentinel-btn-primary"
            onClick={() => {
              setShowManualPanel(!showManualPanel);
              setShowDiscoverPanel(false);
            }}
          >
            ➕ Add Camera Manually
          </button>
          <button
            className="sentinel-btn sentinel-btn-success"
            onClick={() => {
              setShowDiscoverPanel(!showDiscoverPanel);
              setShowManualPanel(false);
              if (!showDiscoverPanel) handleDiscover();
            }}
          >
            📡 Auto-Discover Network Cameras
          </button>
        </div>

        {/* Manual Add Panel */}
        {showManualPanel && (
          <div className="sentinel-card mb-6 animate-fade-in">
            <h3 className="text-sm font-semibold text-sentinel-text mb-4">
              Add Camera Manually
            </h3>

            {manualError && (
              <div className="mb-3 p-3 rounded-lg bg-sentinel-danger/10 border border-sentinel-danger/30 text-sm text-sentinel-danger">
                {manualError}
              </div>
            )}

            <div className="grid grid-cols-3 gap-3 mb-4">
              <div>
                <label className="sentinel-label">Camera Name *</label>
                <input
                  className="sentinel-input"
                  placeholder="Front Entrance"
                  value={manualName}
                  onChange={(e) => setManualName(e.target.value)}
                />
              </div>
              <div>
                <label className="sentinel-label">RTSP URL *</label>
                <input
                  className="sentinel-input"
                  placeholder="rtsp://192.168.1.x:554/stream"
                  value={manualRtsp}
                  onChange={(e) => setManualRtsp(e.target.value)}
                />
              </div>
              <div>
                <label className="sentinel-label">Location</label>
                <input
                  className="sentinel-input"
                  placeholder="Building A, Floor 1"
                  value={manualLocation}
                  onChange={(e) => setManualLocation(e.target.value)}
                />
              </div>
            </div>

            {/* Test Result */}
            {testResult && (
              <div
                className={`mb-4 p-3 rounded-lg text-sm ${
                  testResult.success
                    ? 'bg-sentinel-success/10 border border-sentinel-success/30 text-sentinel-success'
                    : 'bg-sentinel-danger/10 border border-sentinel-danger/30 text-sentinel-danger'
                }`}
              >
                {testResult.success
                  ? `✅ Connection successful! Latency: ${testResult.latencyMs}ms${
                      testResult.resolution
                        ? ` | Resolution: ${testResult.resolution.width}×${testResult.resolution.height}`
                        : ''
                    }`
                  : `❌ Connection failed: ${testResult.errorMessage}`}
              </div>
            )}

            <div className="flex gap-2">
              <button
                className="sentinel-btn sentinel-btn-warning text-xs"
                onClick={handleTestRTSP}
                disabled={isTesting || !manualRtsp.trim()}
              >
                {isTesting ? (
                  <>
                    <span className="sentinel-spinner" />
                    Testing...
                  </>
                ) : (
                  '🔌 Test RTSP Connection'
                )}
              </button>
              <button
                className="sentinel-btn sentinel-btn-primary text-xs"
                onClick={handleManualSave}
                disabled={
                  isSaving ||
                  !testResult?.success ||
                  !manualName.trim()
                }
              >
                {isSaving ? (
                  <>
                    <span className="sentinel-spinner" />
                    Saving...
                  </>
                ) : (
                  '💾 Save Camera'
                )}
              </button>
            </div>
          </div>
        )}

        {/* Auto-Discover Panel */}
        {showDiscoverPanel && (
          <div className="sentinel-card mb-6 animate-fade-in">
            <h3 className="text-sm font-semibold text-sentinel-text mb-4">
              Network Camera Discovery
            </h3>

            {isDiscovering && (
              <div className="p-4 rounded-lg bg-sentinel-cyan/5 border border-sentinel-cyan/20 mb-4 flex items-center gap-3">
                <span className="sentinel-spinner text-sentinel-cyan" />
                <span className="text-sm text-sentinel-cyan">
                  🔍 Scanning your network for RTSP/ONVIF cameras...
                </span>
              </div>
            )}

            {discoverError && (
              <div className="mb-4 p-3 rounded-lg bg-sentinel-danger/10 border border-sentinel-danger/30 text-sm text-sentinel-danger">
                {discoverError}
              </div>
            )}

            {discovered.length > 0 && (
              <>
                <div className="sentinel-card p-0 overflow-hidden mb-4">
                  <table className="sentinel-table">
                    <thead>
                      <tr>
                        <th>Camera Name</th>
                        <th>IP Address</th>
                        <th>Manufacturer</th>
                        <th>RTSP URL</th>
                        <th>Action</th>
                      </tr>
                    </thead>
                    <tbody>
                      {discovered.map((disc) => (
                        <tr key={`${disc.ipAddress}:${disc.port}`}>
                          <td>{disc.name}</td>
                          <td className="text-sentinel-muted">
                            {disc.ipAddress}:{disc.port}
                          </td>
                          <td className="text-sentinel-muted">
                            {disc.manufacturer}
                          </td>
                          <td className="text-xs text-sentinel-muted font-mono">
                            {disc.rtspUrl}
                          </td>
                          <td>
                            <button
                              className="sentinel-btn sentinel-btn-success text-xs py-1 px-2"
                              onClick={() => handleSaveSingleDiscovered(disc)}
                            >
                              ✅ Add
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                <button
                  className="sentinel-btn sentinel-btn-primary text-xs"
                  onClick={handleSaveAllDiscovered}
                  disabled={isSavingDiscovered}
                >
                  {isSavingDiscovered ? (
                    <>
                      <span className="sentinel-spinner" />
                      Saving All...
                    </>
                  ) : (
                    `💾 Save All Discovered Cameras (${discovered.length})`
                  )}
                </button>
              </>
            )}

            {!isDiscovering && discovered.length === 0 && !discoverError && (
              <div className="text-sm text-sentinel-muted text-center py-6">
                No cameras discovered on the network. Try scanning again.
              </div>
            )}
          </div>
        )}

        {/* Camera Table */}
        {isLoading ? (
          <div className="flex items-center justify-center py-12">
            <span className="sentinel-spinner text-sentinel-cyan" />
            <span className="ml-3 text-sm text-sentinel-muted">
              Loading cameras...
            </span>
          </div>
        ) : (
          <div className="sentinel-card p-0 overflow-hidden">
            <table className="sentinel-table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>IP</th>
                  <th>RTSP URL</th>
                  <th>Method</th>
                  <th>Status</th>
                  <th>Added</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {cameras.length === 0 ? (
                  <tr>
                    <td
                      colSpan={7}
                      className="text-center text-sentinel-muted py-8"
                    >
                      No cameras added yet. Use the buttons above to add
                      cameras.
                    </td>
                  </tr>
                ) : (
                  cameras.map((cam) => (
                    <tr key={cam.id}>
                      <td className="font-medium">{cam.name}</td>
                      <td className="text-sentinel-muted text-xs">
                        {cam.ipAddress}
                      </td>
                      <td className="text-sentinel-muted text-xs font-mono max-w-[200px] truncate">
                        {cam.rtspUrl}
                      </td>
                      <td>
                        <span
                          className={`sentinel-badge ${
                            cam.addMethod === 'manual'
                              ? 'sentinel-badge-active'
                              : 'sentinel-badge-connecting'
                          }`}
                        >
                          {cam.addMethod}
                        </span>
                      </td>
                      <td>
                        {statusIcon(cam.status)}{' '}
                        <span className="text-xs">{cam.status}</span>
                      </td>
                      <td className="text-xs text-sentinel-muted">
                        {new Date(cam.addedAt).toLocaleDateString()}
                      </td>
                      <td>
                        <div className="flex gap-1">
                          <button
                            className="sentinel-btn sentinel-btn-ghost text-xs py-1 px-2"
                            onClick={() => handleTestExisting(cam)}
                            title="Test Connection"
                          >
                            🔌
                          </button>
                          <button
                            className="sentinel-btn sentinel-btn-ghost text-xs py-1 px-2"
                            onClick={() => {
                              setEditingCamera(cam);
                              setEditName(cam.name);
                              setEditLocation(cam.location);
                            }}
                            title="Edit"
                          >
                            ✏️
                          </button>
                          <button
                            className="sentinel-btn sentinel-btn-ghost text-xs py-1 px-2 text-sentinel-danger"
                            onClick={() => setDeleteConfirm(cam.id)}
                            title="Delete"
                          >
                            🗑️
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Edit Modal */}
      {editingCamera && (
        <div
          className="sentinel-modal-overlay"
          onClick={() => setEditingCamera(null)}
        >
          <div
            className="sentinel-modal max-w-md"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="text-base font-semibold text-sentinel-text mb-4">
              Edit Camera
            </h3>
            <div className="flex flex-col gap-3">
              <div>
                <label className="sentinel-label">Camera Name</label>
                <input
                  className="sentinel-input"
                  value={editName}
                  onChange={(e) => setEditName(e.target.value)}
                />
              </div>
              <div>
                <label className="sentinel-label">Location</label>
                <input
                  className="sentinel-input"
                  value={editLocation}
                  onChange={(e) => setEditLocation(e.target.value)}
                />
              </div>
            </div>
            <div className="flex gap-2 justify-end mt-4 pt-4 border-t border-sentinel-border">
              <button
                className="sentinel-btn sentinel-btn-ghost text-xs"
                onClick={() => setEditingCamera(null)}
              >
                Cancel
              </button>
              <button
                className="sentinel-btn sentinel-btn-primary text-xs"
                onClick={handleEditSave}
              >
                Save Changes
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Delete Modal */}
      {deleteConfirm && (
        <div
          className="sentinel-modal-overlay"
          onClick={() => setDeleteConfirm(null)}
        >
          <div
            className="sentinel-modal max-w-sm"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="text-base font-semibold text-sentinel-text mb-2">
              Delete Camera?
            </h3>
            <p className="text-sm text-sentinel-muted mb-4">
              This will permanently remove the camera from the system.
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
                Delete Camera
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default CameraManagement;
