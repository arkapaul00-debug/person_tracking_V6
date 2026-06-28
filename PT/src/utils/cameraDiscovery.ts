// src/utils/cameraDiscovery.ts
import type { Camera, DiscoveredCamera, RTSPTestResult } from './types';

const API = import.meta.env.VITE_AUTH_ENDPOINT;

// ── Manual: Test RTSP before saving ──────────────────────────

export async function testRTSPConnection(
  rtspUrl: string,
): Promise<RTSPTestResult> {
  try {
    const res = await fetch(`${API}/cameras/test-rtsp`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ rtspUrl }),
    });
    if (!res.ok) {
      return {
        success: false,
        latencyMs: null,
        errorMessage: 'Server error',
        resolution: null,
      };
    }
    return (await res.json()) as RTSPTestResult;
  } catch (err) {
    return {
      success: false,
      latencyMs: null,
      errorMessage:
        err instanceof Error ? err.message : 'Connection failed',
      resolution: null,
    };
  }
}

// ── Manual: Save a camera by RTSP link ───────────────────────

export async function addCameraManually(data: {
  name: string;
  rtspUrl: string;
  location: string;
}): Promise<Camera> {
  const res = await fetch(`${API}/cameras/manual`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ ...data, addMethod: 'manual' }),
  });
  if (!res.ok) throw new Error('Failed to add camera');
  return (await res.json()) as Camera;
}

// ── Automatic: Discover all cameras on the local network ─────

export async function discoverNetworkCameras(): Promise<DiscoveredCamera[]> {
  const res = await fetch(`${API}/cameras/discover`, {
    method: 'POST',
    credentials: 'include',
  });
  if (!res.ok) throw new Error('Network discovery failed');
  return (await res.json()) as DiscoveredCamera[];
}

// ── Save all auto-discovered cameras ─────────────────────────

export async function saveDiscoveredCameras(
  discovered: DiscoveredCamera[],
): Promise<Camera[]> {
  const res = await fetch(`${API}/cameras/auto-save`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ cameras: discovered }),
  });
  if (!res.ok) throw new Error('Failed to save discovered cameras');
  return (await res.json()) as Camera[];
}

// ── Load all saved cameras (manual + auto, persistent) ───────

export async function fetchAllCameras(): Promise<Camera[]> {
  const res = await fetch(`${API}/cameras`, {
    credentials: 'include',
  });
  if (!res.ok) throw new Error('Failed to load cameras');
  return (await res.json()) as Camera[];
}

// ── Delete a camera ──────────────────────────────────────────

export async function deleteCamera(cameraId: string): Promise<void> {
  const res = await fetch(`${API}/cameras/${cameraId}`, {
    method: 'DELETE',
    credentials: 'include',
  });
  if (!res.ok) throw new Error('Failed to delete camera');
}
