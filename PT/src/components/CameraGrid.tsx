// src/components/CameraGrid.tsx
import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useSentinelStore } from '@utils/store';
import CameraFeed from './CameraFeed';

const FEED_ASPECT_RATIO = 8 / 5;

const CameraGrid: React.FC = () => {
  const cameras = useSentinelStore((s) => s.cameras);
  const activeTrackings = useSentinelStore((s) => s.activeTrackings);
  const monitoringMode = useSentinelStore((s) => s.monitoringMode);
  const manualFullscreenCameraId = useSentinelStore(
    (s) => s.manualFullscreenCameraId,
  );
  const setManualFullscreenCamera = useSentinelStore(
    (s) => s.setManualFullscreenCamera,
  );

  const gridRef = useRef<HTMLDivElement>(null);
  const [feedsPerPage, setFeedsPerPage] = useState(6);
  const [currentPage, setCurrentPage] = useState(0);

  // Calculate how many feeds fit on screen
  useEffect(() => {
    const grid = gridRef.current;
    if (!grid) return;

    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const { width, height } = entry.contentRect;
        // Each column is ~26.67% of width
        const cols = Math.max(1, Math.floor(width / (width * 0.2667)));
        // Each feed height = colWidth / aspectRatio
        const colWidth = width / cols;
        const feedHeight = colWidth / FEED_ASPECT_RATIO;
        const rows = Math.max(1, Math.floor(height / feedHeight));
        setFeedsPerPage(cols * rows);
      }
    });

    observer.observe(grid);
    return () => observer.disconnect();
  }, []);

  // Reset page when cameras change
  useEffect(() => {
    setCurrentPage(0);
  }, [cameras.length]);

  const handleCameraClick = useCallback(
    (cameraId: string) => {
      setManualFullscreenCamera(cameraId);
    },
    [setManualFullscreenCamera],
  );

  // ── Manual Fullscreen Mode ──────────────────────────────
  if (manualFullscreenCameraId) {
    const fullscreenCamera = cameras.find(
      (c) => c.id === manualFullscreenCameraId,
    );
    if (!fullscreenCamera) return null;

    const trackingEvent = activeTrackings.find(
      (t) => t.cameraId === fullscreenCamera.id,
    );

    return (
      <div className="w-full h-full flex items-center justify-center bg-black relative">
        <button
          className="absolute top-3 right-3 z-20 sentinel-btn sentinel-btn-ghost text-sm"
          onClick={() => setManualFullscreenCamera(null)}
        >
          ✕ Exit Fullscreen
        </button>
        <div className="absolute top-3 left-3 z-20 flex items-center gap-2">
          <span
            className={`status-dot status-dot-${fullscreenCamera.status}`}
          />
          <span className="text-sm font-semibold text-white">
            {fullscreenCamera.name}
          </span>
        </div>
        <CameraFeed
          camera={fullscreenCamera}
          isTracking={!!trackingEvent}
          isFullscreen
          trackingEvent={trackingEvent}
        />
      </div>
    );
  }

  // ── Tracking Mode ───────────────────────────────────────
  if (monitoringMode === 'tracking' && activeTrackings.length > 0) {
    const trackingCameras = cameras.filter((c) =>
      activeTrackings.some((t) => t.cameraId === c.id),
    );
    const cols = trackingCameras.length;

    return (
      <div
        className="w-full h-full"
        style={{
          display: 'grid',
          gridTemplateColumns: `repeat(${cols}, 1fr)`,
          gap: '4px',
        }}
      >
        {trackingCameras.map((camera) => {
          const trackingEvent = activeTrackings.find(
            (t) => t.cameraId === camera.id,
          );
          return (
            <CameraFeed
              key={camera.id}
              camera={camera}
              isTracking
              isFullscreen={cols === 1}
              trackingEvent={trackingEvent}
              onClick={() => handleCameraClick(camera.id)}
            />
          );
        })}
      </div>
    );
  }

  // ── Normal Grid Mode ────────────────────────────────────
  const totalPages = Math.max(1, Math.ceil(cameras.length / feedsPerPage));
  const safeCurrentPage = Math.min(currentPage, totalPages - 1);
  const pageStart = safeCurrentPage * feedsPerPage;
  const pageCameras = cameras.slice(pageStart, pageStart + feedsPerPage);

  return (
    <div className="w-full h-full flex flex-col">
      {/* Grid */}
      <div
        ref={gridRef}
        className="flex-1 overflow-hidden"
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(26.67%, 1fr))',
          gap: '4px',
          alignContent: 'start',
        }}
      >
        {pageCameras.length === 0 ? (
          <div className="col-span-full flex flex-col items-center justify-center h-full text-center py-20">
            <div className="text-5xl mb-4 opacity-20">📹</div>
            <div className="text-lg font-medium text-sentinel-muted">
              No cameras configured
            </div>
            <div className="text-sm text-sentinel-muted/60 mt-1">
              Go to Camera Management to add cameras
            </div>
          </div>
        ) : (
          pageCameras.map((camera) => {
            const trackingEvent = activeTrackings.find(
              (t) => t.cameraId === camera.id,
            );
            return (
              <CameraFeed
                key={camera.id}
                camera={camera}
                isTracking={!!trackingEvent}
                isFullscreen={false}
                trackingEvent={trackingEvent}
                onClick={() => handleCameraClick(camera.id)}
              />
            );
          })
        )}
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-3 py-2 border-t border-sentinel-border bg-sentinel-bg-secondary">
          <button
            className="sentinel-btn sentinel-btn-ghost text-xs py-1 px-3"
            disabled={safeCurrentPage === 0}
            onClick={() => setCurrentPage((p) => Math.max(0, p - 1))}
          >
            ◀ Previous
          </button>
          <span className="text-xs text-sentinel-muted">
            Page {safeCurrentPage + 1} of {totalPages}
          </span>
          <button
            className="sentinel-btn sentinel-btn-ghost text-xs py-1 px-3"
            disabled={safeCurrentPage >= totalPages - 1}
            onClick={() =>
              setCurrentPage((p) => Math.min(totalPages - 1, p + 1))
            }
          >
            Next ▶
          </button>
        </div>
      )}
    </div>
  );
};

export default React.memo(CameraGrid);
