// src/components/CameraFeed.tsx
import React, { useRef, useEffect, useState, useCallback } from 'react';
import type { Camera, ActiveTracking } from '@utils/types';
import TrackingOverlay from './TrackingOverlay';

interface CameraFeedProps {
  camera: Camera;
  isTracking: boolean;
  isFullscreen: boolean;
  trackingEvent?: ActiveTracking;
  onClick?: () => void;
}

const CameraFeed: React.FC<CameraFeedProps> = ({
  camera,
  isTracking,
  isFullscreen,
  trackingEvent,
  onClick,
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const [dimensions, setDimensions] = useState({ width: 0, height: 0 });
  const [streamFailed, setStreamFailed] = useState(false);

  // Measure container dimensions for overlay
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        setDimensions({
          width: entry.contentRect.width,
          height: entry.contentRect.height,
        });
      }
    });

    observer.observe(container);
    return () => observer.disconnect();
  }, []);

  // Try to load HLS stream, fallback to MJPEG
  useEffect(() => {
    const video = videoRef.current;
    if (!video || camera.status === 'offline') return;

    // The backend should provide an HLS URL like:
    // http://server:8000/streams/{cameraId}/index.m3u8
    // or MJPEG at: http://server:8000/streams/{cameraId}/mjpeg
    //
    // For now, we set the video source and handle errors gracefully
    const hlsUrl = `${import.meta.env.VITE_AUTH_ENDPOINT}/streams/${camera.id}/index.m3u8`;

    // Try native HLS (Safari) or fallback
    if (video.canPlayType('application/vnd.apple.mpegurl')) {
      video.src = hlsUrl;
      video.play().catch(() => setStreamFailed(true));
    } else {
      // In production, use hls.js here
      // For now, just mark as fallback needed
      setStreamFailed(true);
    }

    return () => {
      video.pause();
      video.src = '';
    };
  }, [camera.id, camera.status]);

  const handleClick = useCallback(() => {
    onClick?.();
  }, [onClick]);

  const isOffline = camera.status === 'offline' || camera.status === 'error';

  return (
    <div
      ref={containerRef}
      className={`camera-feed-container ${isTracking ? 'tracking-border' : ''} ${
        isFullscreen ? 'w-full h-full' : ''
      }`}
      style={isFullscreen ? { aspectRatio: 'auto' } : undefined}
      onClick={handleClick}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === 'Enter') handleClick();
      }}
    >
      {/* Video or placeholder */}
      {isOffline || streamFailed ? (
        <div className="absolute inset-0 flex flex-col items-center justify-center bg-black/90">
          <div className="text-4xl mb-3 opacity-30">📹</div>
          <div className="text-sm font-medium text-sentinel-muted">
            {isOffline ? 'Camera Offline' : 'Stream Loading...'}
          </div>
          <div className="text-xs text-sentinel-muted/60 mt-1">
            {camera.name}
          </div>
        </div>
      ) : (
        <video
          ref={videoRef}
          autoPlay
          muted
          playsInline
          className="w-full h-full object-contain bg-black"
        />
      )}

      {/* Camera name label (bottom-left) */}
      <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/80 to-transparent p-2">
        <div className="flex items-center gap-2">
          <span className={`status-dot status-dot-${camera.status}`} />
          <span className="text-xs font-medium text-white/90 truncate">
            {camera.name}
          </span>
        </div>
      </div>

      {/* Tracking overlay */}
      {isTracking && trackingEvent && (
        <TrackingOverlay
          tracking={trackingEvent}
          containerWidth={dimensions.width}
          containerHeight={dimensions.height}
        />
      )}
    </div>
  );
};

export default React.memo(CameraFeed);
