// src/components/TrackingOverlay.tsx
import React, { useRef, useEffect } from 'react';
import type { ActiveTracking } from '@utils/types';
import { useSentinelStore } from '@utils/store';

interface TrackingOverlayProps {
  tracking: ActiveTracking;
  containerWidth: number;
  containerHeight: number;
}

const TrackingOverlay: React.FC<TrackingOverlayProps> = ({
  tracking,
  containerWidth,
  containerHeight,
}) => {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const targets = useSentinelStore((s) => s.targets);
  const cameras = useSentinelStore((s) => s.cameras);

  const targetName =
    targets.find((t) => t.id === tracking.targetPersonId)?.name ??
    'Unknown Target';
  const cameraName =
    cameras.find((c) => c.id === tracking.cameraId)?.name ??
    'Unknown Camera';

  // Draw bounding box on canvas
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    canvas.width = containerWidth;
    canvas.height = containerHeight;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    ctx.clearRect(0, 0, canvas.width, canvas.height);

    const { boundingBox } = tracking.detectionEvent;
    const x = boundingBox.x * containerWidth;
    const y = boundingBox.y * containerHeight;
    const w = boundingBox.width * containerWidth;
    const h = boundingBox.height * containerHeight;

    // Fill
    ctx.fillStyle = 'rgba(255, 0, 64, 0.1)';
    ctx.fillRect(x, y, w, h);

    // Border
    ctx.strokeStyle = '#ff0040';
    ctx.lineWidth = 2;
    ctx.strokeRect(x, y, w, h);

    // Corner accents
    const cornerLen = Math.min(w, h) * 0.2;
    ctx.strokeStyle = '#ff0040';
    ctx.lineWidth = 3;

    // Top-left
    ctx.beginPath();
    ctx.moveTo(x, y + cornerLen);
    ctx.lineTo(x, y);
    ctx.lineTo(x + cornerLen, y);
    ctx.stroke();

    // Top-right
    ctx.beginPath();
    ctx.moveTo(x + w - cornerLen, y);
    ctx.lineTo(x + w, y);
    ctx.lineTo(x + w, y + cornerLen);
    ctx.stroke();

    // Bottom-left
    ctx.beginPath();
    ctx.moveTo(x, y + h - cornerLen);
    ctx.lineTo(x, y + h);
    ctx.lineTo(x + cornerLen, y + h);
    ctx.stroke();

    // Bottom-right
    ctx.beginPath();
    ctx.moveTo(x + w - cornerLen, y + h);
    ctx.lineTo(x + w, y + h);
    ctx.lineTo(x + w, y + h - cornerLen);
    ctx.stroke();

    // Label
    const label = `${targetName} (${tracking.detectionEvent.confidence}%)`;
    ctx.font = 'bold 12px Inter, sans-serif';
    const textMetrics = ctx.measureText(label);
    const labelPad = 6;

    ctx.fillStyle = 'rgba(255, 0, 64, 0.9)';
    ctx.fillRect(
      x,
      y - 22,
      textMetrics.width + labelPad * 2,
      20,
    );

    ctx.fillStyle = '#fff';
    ctx.fillText(label, x + labelPad, y - 7);
  }, [
    tracking,
    containerWidth,
    containerHeight,
    targetName,
  ]);

  return (
    <>
      {/* Top tracking banner */}
      <div className="tracking-banner">
        <span>🎯</span>
        <span>
          TRACKING ACTIVE — {targetName} — {cameraName}
        </span>
        <span className="ml-auto text-xs opacity-80">
          {new Date(tracking.startedAt).toLocaleTimeString()}
        </span>
      </div>

      {/* Confidence badge */}
      <div className="absolute top-9 right-2 z-10">
        <span
          className={`sentinel-badge ${
            tracking.detectionEvent.confidence >= 90
              ? 'sentinel-badge-online'
              : tracking.detectionEvent.confidence >= 70
                ? 'sentinel-badge-connecting'
                : 'sentinel-badge-offline'
          }`}
        >
          {tracking.detectionEvent.confidence}%
        </span>
      </div>

      {/* Canvas overlay for bounding box */}
      <canvas
        ref={canvasRef}
        className="absolute inset-0 z-[5] pointer-events-none"
        style={{ width: '100%', height: '100%' }}
      />
    </>
  );
};

export default React.memo(TrackingOverlay);
