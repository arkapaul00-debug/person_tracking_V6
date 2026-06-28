// src/utils/store.ts
import { create } from 'zustand';
import type {
  AuthUser, User, Camera, TargetPerson, DetectionEvent,
  ActiveTracking, SystemStatus, MonitoringMode,
} from './types';

interface SentinelStore {
  // Auth
  user: AuthUser | null;
  setUser: (user: AuthUser | null) => void;

  // Users (admin view)
  allUsers: User[];
  setAllUsers: (users: User[]) => void;

  // Cameras
  cameras: Camera[];
  setCameras: (cameras: Camera[]) => void;
  addCamera: (camera: Camera) => void;
  updateCamera: (id: string, patch: Partial<Camera>) => void;
  removeCamera: (id: string) => void;

  // Target Persons
  targets: TargetPerson[];
  setTargets: (targets: TargetPerson[]) => void;
  addTarget: (target: TargetPerson) => void;
  removeTarget: (id: string) => void;

  // Detection History
  detectionHistory: DetectionEvent[];
  addDetectionEvent: (event: DetectionEvent) => void;

  // Live Monitoring
  monitoringMode: MonitoringMode;
  activeTrackings: ActiveTracking[];
  selectedCameraId: string | null;
  manualFullscreenCameraId: string | null;
  setMonitoringMode: (mode: MonitoringMode) => void;
  addActiveTracking: (tracking: ActiveTracking) => void;
  removeActiveTracking: (cameraId: string) => void;
  setSelectedCamera: (id: string | null) => void;
  setManualFullscreenCamera: (id: string | null) => void;

  // System
  systemStatus: SystemStatus | null;
  setSystemStatus: (status: SystemStatus) => void;

  // Alerts (UI)
  alertQueue: DetectionEvent[];
  dismissAlert: (id: string) => void;
}

export const useSentinelStore = create<SentinelStore>((set) => ({
  // ── Auth ──────────────────────────────────────────────────
  user: null,
  setUser: (user) => set({ user }),

  // ── Users ─────────────────────────────────────────────────
  allUsers: [],
  setAllUsers: (allUsers) => set({ allUsers }),

  // ── Cameras ───────────────────────────────────────────────
  cameras: [],
  setCameras: (cameras) => set({ cameras }),
  addCamera: (camera) =>
    set((s) => ({ cameras: [...s.cameras, camera] })),
  updateCamera: (id, patch) =>
    set((s) => ({
      cameras: s.cameras.map((c) => (c.id === id ? { ...c, ...patch } : c)),
    })),
  removeCamera: (id) =>
    set((s) => ({ cameras: s.cameras.filter((c) => c.id !== id) })),

  // ── Targets ───────────────────────────────────────────────
  targets: [],
  setTargets: (targets) => set({ targets }),
  addTarget: (target) =>
    set((s) => ({ targets: [...s.targets, target] })),
  removeTarget: (id) =>
    set((s) => ({ targets: s.targets.filter((t) => t.id !== id) })),

  // ── Detection History ─────────────────────────────────────
  detectionHistory: [],
  addDetectionEvent: (event) =>
    set((s) => ({
      detectionHistory: [event, ...s.detectionHistory].slice(0, 1000),
      alertQueue: [event, ...s.alertQueue],
    })),

  // ── Live Monitoring ───────────────────────────────────────
  monitoringMode: 'normal',
  activeTrackings: [],
  selectedCameraId: null,
  manualFullscreenCameraId: null,

  setMonitoringMode: (monitoringMode) => set({ monitoringMode }),

  addActiveTracking: (tracking) =>
    set((s) => {
      const exists = s.activeTrackings.find(
        (t) => t.cameraId === tracking.cameraId,
      );
      const updated = exists
        ? s.activeTrackings.map((t) =>
            t.cameraId === tracking.cameraId ? tracking : t,
          )
        : [...s.activeTrackings, tracking];
      return {
        activeTrackings: updated,
        monitoringMode: 'tracking' as MonitoringMode,
      };
    }),

  removeActiveTracking: (cameraId) =>
    set((s) => {
      const updated = s.activeTrackings.filter(
        (t) => t.cameraId !== cameraId,
      );
      return {
        activeTrackings: updated,
        monitoringMode:
          updated.length === 0
            ? ('normal' as MonitoringMode)
            : s.monitoringMode,
      };
    }),

  setSelectedCamera: (selectedCameraId) => set({ selectedCameraId }),
  setManualFullscreenCamera: (manualFullscreenCameraId) =>
    set({ manualFullscreenCameraId }),

  // ── System ────────────────────────────────────────────────
  systemStatus: null,
  setSystemStatus: (systemStatus) => set({ systemStatus }),

  // ── Alerts ────────────────────────────────────────────────
  alertQueue: [],
  dismissAlert: (id) =>
    set((s) => ({ alertQueue: s.alertQueue.filter((a) => a.id !== id) })),
}));
