// src/components/CameraSidebar.tsx
import React, { useCallback } from 'react';
import { useSentinelStore } from '@utils/store';

const CameraSidebar: React.FC = () => {
  const cameras = useSentinelStore((s) => s.cameras);
  const activeTrackings = useSentinelStore((s) => s.activeTrackings);
  const manualFullscreenCameraId = useSentinelStore(
    (s) => s.manualFullscreenCameraId,
  );
  const setManualFullscreenCamera = useSentinelStore(
    (s) => s.setManualFullscreenCamera,
  );

  const isTracking = useCallback(
    (cameraId: string): boolean =>
      activeTrackings.some((t) => t.cameraId === cameraId),
    [activeTrackings],
  );

  const handleCameraClick = useCallback(
    (cameraId: string) => {
      if (manualFullscreenCameraId === cameraId) {
        setManualFullscreenCamera(null);
      } else {
        setManualFullscreenCamera(cameraId);
      }
    },
    [manualFullscreenCameraId, setManualFullscreenCamera],
  );

  return (
    <aside
      className="flex-shrink-0 border-r border-sentinel-border bg-sentinel-bg-secondary overflow-y-auto"
      style={{ width: '220px' }}
    >
      {/* Header */}
      <div className="p-3 border-b border-sentinel-border">
        <h3 className="text-xs font-bold uppercase tracking-widest text-sentinel-muted">
          Cameras
        </h3>
        <div className="text-[10px] text-sentinel-muted/60 mt-0.5">
          {cameras.filter((c) => c.status === 'online').length}/
          {cameras.length} online
        </div>
      </div>

      {/* Camera list */}
      <div className="p-2 flex flex-col gap-0.5">
        {cameras.length === 0 ? (
          <div className="text-xs text-sentinel-muted/60 text-center py-6">
            No cameras added yet
          </div>
        ) : (
          cameras.map((camera) => (
            <div
              key={camera.id}
              className={`sidebar-camera-item ${
                manualFullscreenCameraId === camera.id ? 'active' : ''
              }`}
              onClick={() => handleCameraClick(camera.id)}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => {
                if (e.key === 'Enter') handleCameraClick(camera.id);
              }}
            >
              <span
                className={`status-dot status-dot-${camera.status}`}
              />
              <div className="flex-1 min-w-0">
                <div className="text-xs font-medium text-sentinel-text truncate">
                  {camera.name}
                </div>
                <div className="text-[10px] text-sentinel-muted/60 truncate">
                  {camera.location || camera.ipAddress}
                </div>
              </div>
              {isTracking(camera.id) && (
                <span className="sentinel-badge sentinel-badge-tracking text-[8px]">
                  TRACKING
                </span>
              )}
            </div>
          ))
        )}
      </div>

      {/* Close fullscreen button */}
      {manualFullscreenCameraId && (
        <div className="p-2 border-t border-sentinel-border">
          <button
            className="sentinel-btn sentinel-btn-ghost w-full text-xs"
            onClick={() => setManualFullscreenCamera(null)}
          >
            ✕ Close Fullscreen
          </button>
        </div>
      )}
    </aside>
  );
};

export default React.memo(CameraSidebar);
