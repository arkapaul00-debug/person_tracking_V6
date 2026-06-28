// src/utils/types.ts

// ── Auth & Users ──────────────────────────────────────────────

export type UserRole = 'admin' | 'operator' | 'viewer';
export type UserStatus = 'active' | 'pending' | 'suspended';

export interface User {
  id: string;
  username: string;
  fullName: string;
  email: string;
  role: UserRole;
  status: UserStatus;
  cameraPermissions: string[];
  createdAt: number;
  lastLoginAt: number | null;
}

export interface AuthUser extends User {
  token: string;
  expiresAt: number;
}

export interface LoginCredentials {
  username: string;
  password: string;
}

export interface RegisterRequest {
  username: string;
  fullName: string;
  email: string;
  password: string;
}

// ── Cameras ───────────────────────────────────────────────────

export type CameraStatus = 'online' | 'offline' | 'error' | 'connecting';
export type CameraAddMethod = 'manual' | 'automatic';

export interface Camera {
  id: string;
  name: string;
  rtspUrl: string;
  location: string;
  status: CameraStatus;
  addMethod: CameraAddMethod;
  ipAddress: string;
  port: number;
  resolution: { width: number; height: number };
  fps: number;
  addedAt: number;
  lastSeenAt: number | null;
}

export interface RTSPTestResult {
  success: boolean;
  latencyMs: number | null;
  errorMessage: string | null;
  resolution: { width: number; height: number } | null;
}

export interface DiscoveredCamera {
  ipAddress: string;
  port: number;
  name: string;
  manufacturer: string;
  rtspUrl: string;
}

// ── Target Persons ────────────────────────────────────────────

export interface TargetPerson {
  id: string;
  name: string;
  description: string;
  photoUrl: string;
  photoBase64: string;
  addedAt: number;
  isActive: boolean;
}

export interface DetectionEvent {
  id: string;
  targetPersonId: string;
  cameraId: string;
  timestamp: number;
  confidence: number;
  boundingBox: { x: number; y: number; width: number; height: number };
  snapshotUrl: string | null;
}

export interface DetectionHistory {
  targetPersonId: string;
  events: DetectionEvent[];
  totalCount: number;
}

// ── Live Monitoring ───────────────────────────────────────────

export type MonitoringMode = 'normal' | 'tracking';

export interface ActiveTracking {
  cameraId: string;
  targetPersonId: string;
  startedAt: number;
  detectionEvent: DetectionEvent;
}

// ── System ────────────────────────────────────────────────────

export interface SystemStatus {
  serverId: string;
  uptime: number;
  cpuUsage: number;
  memoryUsage: number;
  activeStreams: number;
  alertLevel: 'normal' | 'warning' | 'critical';
}

export interface SSEMessage<T = unknown> {
  type: 'detection_alert' | 'system_status' | 'camera_status' | 'tracking_start' | 'tracking_end';
  payload: T;
}

// ── Audit Log ─────────────────────────────────────────────────

export interface AuditLogEntry {
  id: string;
  timestamp: number;
  userId: string;
  username: string;
  action: string;
  details: string;
}

// ── System Settings ───────────────────────────────────────────

export interface SystemSettings {
  appTitle: string;
  logoBase64: string | null;
  timezone: string;
  sessionTimeoutMinutes: number;
  maxFailedLoginAttempts: number;
}

// ── Admin ─────────────────────────────────────────────────────

export interface AdminCredentials {
  username: 'ADMIN';
  password: string;
}

export interface ManagedUser {
  id: string;
  name: string;
  designation: string;
  phone: string;
  email: string;
  username: string;
  passwordHash: string;        // stored hashed, never plain text
  status: 'active' | 'suspended';
  createdAt: number;
  lastLoginAt: number | null;
  loginCount: number;
  lastActiveRoute: string | null;
}

export interface UserAnalytics {
  userId: string;
  username: string;
  name: string;
  designation: string;
  loginCount: number;
  lastLoginAt: number | null;
  lastActiveRoute: string | null;
  status: 'active' | 'suspended';
  camerasAccessed: number;
  alertsTriggered: number;
  sessionsThisWeek: number;
}

export interface CreateUserPayload {
  name: string;
  designation: string;
  phone: string;
  email: string;
  username: string;            // may be same as email if checkbox ticked
  password: string;
}
