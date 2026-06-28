// src/components/AlertBanner.tsx
import React, { useEffect, useCallback } from 'react';
import { useSentinelStore } from '@utils/store';
import type { DetectionEvent } from '@utils/types';

const MAX_ALERTS = Number(import.meta.env.VITE_MAX_ALERT_DISPLAY) || 5;
const DISMISS_MS = Number(import.meta.env.VITE_ALERT_AUTO_DISMISS_MS) || 8000;

const AlertBanner: React.FC = () => {
  const alertQueue = useSentinelStore((s) => s.alertQueue);
  const dismissAlert = useSentinelStore((s) => s.dismissAlert);
  const targets = useSentinelStore((s) => s.targets);
  const cameras = useSentinelStore((s) => s.cameras);
  const setManualFullscreenCamera = useSentinelStore(
    (s) => s.setManualFullscreenCamera,
  );

  const visibleAlerts = alertQueue.slice(0, MAX_ALERTS);

  // Auto-dismiss oldest alerts when exceeding max
  useEffect(() => {
    if (alertQueue.length > MAX_ALERTS) {
      const excess = alertQueue.slice(MAX_ALERTS);
      excess.forEach((a) => dismissAlert(a.id));
    }
  }, [alertQueue, dismissAlert]);

  // Auto-dismiss each alert after timeout
  useEffect(() => {
    const timers: ReturnType<typeof setTimeout>[] = [];
    visibleAlerts.forEach((alert) => {
      const timer = setTimeout(() => {
        dismissAlert(alert.id);
      }, DISMISS_MS);
      timers.push(timer);
    });
    return () => timers.forEach(clearTimeout);
  }, [visibleAlerts, dismissAlert]);

  const getTargetName = useCallback(
    (event: DetectionEvent): string => {
      const target = targets.find((t) => t.id === event.targetPersonId);
      return target?.name ?? 'Unknown Target';
    },
    [targets],
  );

  const getCameraName = useCallback(
    (event: DetectionEvent): string => {
      const camera = cameras.find((c) => c.id === event.cameraId);
      return camera?.name ?? 'Unknown Camera';
    },
    [cameras],
  );

  const handleAlertClick = useCallback(
    (cameraId: string) => {
      setManualFullscreenCamera(cameraId);
    },
    [setManualFullscreenCamera],
  );

  if (visibleAlerts.length === 0) return null;

  return (
    <div className="fixed top-16 right-4 z-40 flex flex-col gap-2 w-96 max-w-[calc(100vw-2rem)]">
      {visibleAlerts.map((alert) => (
        <div
          key={alert.id}
          className="alert-banner"
          onClick={() => handleAlertClick(alert.cameraId)}
          role="button"
          tabIndex={0}
          onKeyDown={(e) => {
            if (e.key === 'Enter') handleAlertClick(alert.cameraId);
          }}
        >
          <span className="text-lg flex-shrink-0">🚨</span>
          <div className="flex-1 min-w-0">
            <div className="text-sm font-semibold text-sentinel-text truncate">
              {getTargetName(alert)} detected on {getCameraName(alert)}
            </div>
            <div className="text-xs text-sentinel-muted mt-0.5">
              {new Date(alert.timestamp).toLocaleTimeString()} — Confidence:{' '}
              <span
                className={
                  alert.confidence >= 90
                    ? 'confidence-high'
                    : alert.confidence >= 70
                      ? 'confidence-medium'
                      : 'confidence-low'
                }
              >
                {alert.confidence}%
              </span>
            </div>
          </div>
          <button
            className="text-sentinel-muted hover:text-sentinel-text transition-colors text-lg leading-none flex-shrink-0"
            onClick={(e) => {
              e.stopPropagation();
              dismissAlert(alert.id);
            }}
            aria-label="Dismiss alert"
          >
            ✕
          </button>
        </div>
      ))}
    </div>
  );
};

export default React.memo(AlertBanner);
