// src/pages/TargetTracking.tsx
import React, { useState, useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import { useSentinelStore } from '@utils/store';
import type { TargetPerson } from '@utils/types';

const API = import.meta.env.VITE_AUTH_ENDPOINT;

const TargetTracking: React.FC = () => {
  const targets = useSentinelStore((s) => s.targets);
  const setTargets = useSentinelStore((s) => s.setTargets);
  const addTarget = useSentinelStore((s) => s.addTarget);
  const removeTarget = useSentinelStore((s) => s.removeTarget);
  const cameras = useSentinelStore((s) => s.cameras);
  const detectionHistory = useSentinelStore((s) => s.detectionHistory);

  // Add target form
  const [showAddForm, setShowAddForm] = useState(false);
  const [formName, setFormName] = useState('');
  const [formDesc, setFormDesc] = useState('');
  const [photoPreview, setPhotoPreview] = useState<string | null>(null);
  const [photoBase64, setPhotoBase64] = useState<string | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Filters
  const [filterTarget, setFilterTarget] = useState<string>('all');
  const [filterCamera, setFilterCamera] = useState<string>('all');

  // Load targets
  useEffect(() => {
    const controller = new AbortController();
    fetch(`${API}/targets`, { credentials: 'include' })
      .then((r) => {
        if (!r.ok) throw new Error('Failed to load targets');
        return r.json() as Promise<TargetPerson[]>;
      })
      .then((data) => {
        if (!controller.signal.aborted) setTargets(data);
      })
      .catch((err) => {
        if (!controller.signal.aborted) {
          console.warn('[Targets] Failed to load targets:', err);
        }
      });
    return () => controller.abort();
  }, [setTargets]);

  const handlePhotoSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    if (file.size > 5 * 1024 * 1024) {
      setUploadError('File size must be under 5MB');
      return;
    }

    setUploadError(null);
    const reader = new FileReader();
    reader.onload = () => {
      const base64 = reader.result as string;
      setPhotoPreview(base64);
      setPhotoBase64(base64);
    };
    reader.readAsDataURL(file);
  };

  const handleAddSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (isUploading) return;
    setUploadError(null);

    if (!formName.trim()) {
      setUploadError('Target name is required');
      return;
    }
    if (!photoBase64) {
      setUploadError('Target photo is required');
      return;
    }

    setIsUploading(true);
    try {
      const res = await fetch(`${API}/targets`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          name: formName.trim(),
          description: formDesc.trim(),
          photoBase64,
        }),
      });

      if (!res.ok) {
        const err = (await res.json()) as { message?: string };
        throw new Error(err.message ?? 'Failed to add target');
      }

      const newTarget = (await res.json()) as TargetPerson;
      addTarget(newTarget);

      // Reset
      setShowAddForm(false);
      setFormName('');
      setFormDesc('');
      setPhotoPreview(null);
      setPhotoBase64(null);
    } catch (err) {
      setUploadError(
        err instanceof Error ? err.message : 'Upload failed',
      );
    } finally {
      setIsUploading(false);
    }
  };

  const handleDeleteTarget = async (id: string) => {
    if (!window.confirm('Are you sure you want to remove this target?')) return;
    try {
      const res = await fetch(`${API}/targets/${id}`, {
        method: 'DELETE',
        credentials: 'include',
      });
      if (res.ok) removeTarget(id);
    } catch (err) {
      console.error('Failed to delete target', err);
    }
  };

  const filteredHistory = detectionHistory.filter((evt) => {
    if (filterTarget !== 'all' && evt.targetPersonId !== filterTarget) return false;
    if (filterCamera !== 'all' && evt.cameraId !== filterCamera) return false;
    return true;
  });

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
          <Link to="/cameras" className="sentinel-nav-link">📷 Cameras</Link>
          <Link to="/targets" className="sentinel-nav-link active">🎯 Targets</Link>
          <Link to="/profile" className="sentinel-nav-link">👤 Profile</Link>
        </div>
      </nav>

      <div className="sentinel-page">
        <div className="sentinel-page-header flex justify-between items-end">
          <div>
            <h1 className="sentinel-page-title">Target Tracking</h1>
            <p className="sentinel-page-subtitle">
              Manage persons of interest and view detection history
            </p>
          </div>
          <button
            className="sentinel-btn sentinel-btn-primary text-xs"
            onClick={() => setShowAddForm(!showAddForm)}
          >
            {showAddForm ? 'Cancel' : '➕ Add Target Person'}
          </button>
        </div>

        {/* Add Form */}
        {showAddForm && (
          <div className="sentinel-card mb-6 animate-fade-in">
            <h3 className="text-sm font-semibold text-sentinel-text mb-4">
              Add New Target Person
            </h3>

            {uploadError && (
              <div className="mb-4 p-3 rounded-lg bg-sentinel-danger/10 border border-sentinel-danger/30 text-sm text-sentinel-danger">
                {uploadError}
              </div>
            )}

            <form onSubmit={handleAddSubmit} className="flex gap-6">
              {/* Photo Upload Area */}
              <div className="flex-shrink-0">
                <input
                  type="file"
                  accept="image/jpeg, image/png"
                  className="hidden"
                  ref={fileInputRef}
                  onChange={handlePhotoSelect}
                />
                <div
                  className={`w-40 h-40 rounded-xl flex items-center justify-center border-2 border-dashed cursor-pointer overflow-hidden transition-colors ${
                    photoPreview
                      ? 'border-sentinel-cyan'
                      : 'border-sentinel-border hover:border-sentinel-cyan hover:bg-sentinel-cyan/5'
                  }`}
                  onClick={() => fileInputRef.current?.click()}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') fileInputRef.current?.click();
                  }}
                  role="button"
                  tabIndex={0}
                >
                  {photoPreview ? (
                    <img
                      src={photoPreview}
                      alt="Preview"
                      className="w-full h-full object-cover"
                    />
                  ) : (
                    <div className="text-center p-2">
                      <div className="text-2xl mb-1">📸</div>
                      <div className="text-xs text-sentinel-muted">
                        Click to upload photo
                        <br />
                        <span className="text-[10px] opacity-70">
                          (JPG/PNG, Max 5MB)
                        </span>
                      </div>
                    </div>
                  )}
                </div>
              </div>

              {/* Details */}
              <div className="flex-1 flex flex-col gap-3">
                <div>
                  <label className="sentinel-label">Target Name *</label>
                  <input
                    className="sentinel-input"
                    placeholder="E.g., Suspect A"
                    value={formName}
                    onChange={(e) => setFormName(e.target.value)}
                  />
                </div>
                <div>
                  <label className="sentinel-label">Description</label>
                  <textarea
                    className="sentinel-input sentinel-textarea"
                    placeholder="Additional details..."
                    value={formDesc}
                    onChange={(e) => setFormDesc(e.target.value)}
                  />
                </div>
                <div className="mt-auto flex justify-end">
                  <button
                    type="submit"
                    className="sentinel-btn sentinel-btn-success text-xs"
                    disabled={isUploading}
                  >
                    {isUploading ? (
                      <>
                        <span className="sentinel-spinner" />
                        Uploading...
                      </>
                    ) : (
                      '🎯 Save Target'
                    )}
                  </button>
                </div>
              </div>
            </form>
          </div>
        )}

        {/* Active Targets Grid */}
        <h3 className="text-sm font-semibold text-sentinel-text mb-3">
          Active Targets ({targets.length})
        </h3>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
          {targets.map((target) => (
            <div key={target.id} className="sentinel-card flex gap-4 p-4">
              <img
                src={target.photoUrl || target.photoBase64}
                alt={target.name}
                className="w-16 h-16 rounded-lg object-cover border border-sentinel-border"
              />
              <div className="flex-1 min-w-0">
                <div className="flex justify-between items-start">
                  <div className="font-semibold text-sentinel-text truncate">
                    {target.name}
                  </div>
                  <button
                    className="text-sentinel-muted hover:text-sentinel-danger text-xs"
                    onClick={() => handleDeleteTarget(target.id)}
                    aria-label="Delete Target"
                  >
                    🗑️
                  </button>
                </div>
                <div className="text-xs text-sentinel-muted truncate mb-1.5">
                  {target.description || 'No description'}
                </div>
                <span
                  className={`sentinel-badge ${
                    target.isActive
                      ? 'sentinel-badge-tracking'
                      : 'border border-sentinel-border text-sentinel-muted'
                  }`}
                >
                  {target.isActive ? '🟢 TRACKING' : '⚪ MONITORING'}
                </span>
              </div>
            </div>
          ))}
          {targets.length === 0 && (
            <div className="col-span-full text-center text-sm text-sentinel-muted py-8 border border-dashed border-sentinel-border rounded-xl">
              No targets added yet.
            </div>
          )}
        </div>

        {/* Detection History */}
        <div className="flex justify-between items-end mb-3">
          <h3 className="text-sm font-semibold text-sentinel-text">
            Detection History
          </h3>
          <div className="flex gap-2">
            <select
              className="sentinel-input sentinel-select py-1 text-xs"
              value={filterTarget}
              onChange={(e) => setFilterTarget(e.target.value)}
            >
              <option value="all">All Targets</option>
              {targets.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name}
                </option>
              ))}
            </select>
            <select
              className="sentinel-input sentinel-select py-1 text-xs"
              value={filterCamera}
              onChange={(e) => setFilterCamera(e.target.value)}
            >
              <option value="all">All Cameras</option>
              {cameras.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
            <button
              className="sentinel-btn sentinel-btn-ghost text-xs py-1"
              onClick={() => {
                setFilterTarget('all');
                setFilterCamera('all');
              }}
            >
              Clear
            </button>
          </div>
        </div>

        <div className="sentinel-card p-0 overflow-hidden">
          <table className="sentinel-table">
            <thead>
              <tr>
                <th>Target</th>
                <th>Camera</th>
                <th>Timestamp</th>
                <th>Confidence</th>
                <th>Snapshot</th>
              </tr>
            </thead>
            <tbody>
              {filteredHistory.length === 0 ? (
                <tr>
                  <td colSpan={5} className="text-center text-sentinel-muted py-8">
                    No detection events found.
                  </td>
                </tr>
              ) : (
                filteredHistory.map((evt) => {
                  const t = targets.find((x) => x.id === evt.targetPersonId);
                  const c = cameras.find((x) => x.id === evt.cameraId);
                  return (
                    <tr key={evt.id}>
                      <td className="font-medium text-sm">
                        {t?.name || 'Unknown'}
                      </td>
                      <td className="text-sm text-sentinel-muted">
                        {c?.name || 'Unknown Camera'}
                      </td>
                      <td className="text-xs text-sentinel-muted">
                        {new Date(evt.timestamp).toLocaleString()}
                      </td>
                      <td>
                        <span
                          className={`font-semibold ${
                            evt.confidence >= 90
                              ? 'confidence-high'
                              : evt.confidence >= 70
                                ? 'confidence-medium'
                                : 'confidence-low'
                          }`}
                        >
                          {evt.confidence}%
                        </span>
                      </td>
                      <td>
                        {evt.snapshotUrl ? (
                          <a
                            href={evt.snapshotUrl}
                            target="_blank"
                            rel="noreferrer"
                            className="text-xs text-sentinel-cyan hover:underline"
                          >
                            View Image ↗
                          </a>
                        ) : (
                          <span className="text-xs text-sentinel-muted opacity-50">
                            N/A
                          </span>
                        )}
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};

export default TargetTracking;
