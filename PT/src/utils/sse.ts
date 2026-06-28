// src/utils/sse.ts
import type {
  SSEMessage, DetectionEvent, SystemStatus,
  ActiveTracking, CameraStatus,
} from './types';
import { useSentinelStore } from './store';

const SSE_ENDPOINT = import.meta.env.VITE_SSE_ENDPOINT;

let eventSource: EventSource | null = null;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

export function connectSSE(token: string): void {
  if (eventSource) {
    eventSource.close();
  }
  if (reconnectTimer) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }

  eventSource = new EventSource(
    `${SSE_ENDPOINT}/events?token=${encodeURIComponent(token)}`,
    { withCredentials: true },
  );

  // AI target detection alert
  eventSource.addEventListener('detection_alert', (e: MessageEvent) => {
    const msg = JSON.parse(e.data as string) as SSEMessage<DetectionEvent>;
    useSentinelStore.getState().addDetectionEvent(msg.payload);
  });

  // Tracking started on a camera
  eventSource.addEventListener('tracking_start', (e: MessageEvent) => {
    const msg = JSON.parse(e.data as string) as SSEMessage<ActiveTracking>;
    useSentinelStore.getState().addActiveTracking(msg.payload);
  });

  // Tracking ended on a camera
  eventSource.addEventListener('tracking_end', (e: MessageEvent) => {
    const msg = JSON.parse(
      e.data as string,
    ) as SSEMessage<{ cameraId: string }>;
    useSentinelStore.getState().removeActiveTracking(msg.payload.cameraId);
  });

  // System health updates
  eventSource.addEventListener('system_status', (e: MessageEvent) => {
    const msg = JSON.parse(e.data as string) as SSEMessage<SystemStatus>;
    useSentinelStore.getState().setSystemStatus(msg.payload);
  });

  // Camera status changes (online/offline)
  eventSource.addEventListener('camera_status', (e: MessageEvent) => {
    const msg = JSON.parse(
      e.data as string,
    ) as SSEMessage<{ cameraId: string; status: string }>;
    useSentinelStore.getState().updateCamera(msg.payload.cameraId, {
      status: msg.payload.status as CameraStatus,
      lastSeenAt: Date.now(),
    });
  });

  eventSource.addEventListener('error', () => {
    console.warn('[SSE] Connection lost. Reconnecting in 5 seconds...');
    eventSource?.close();
    eventSource = null;
    reconnectTimer = setTimeout(() => connectSSE(token), 5000);
  });
}

export function disconnectSSE(): void {
  if (reconnectTimer) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
  eventSource?.close();
  eventSource = null;
}
