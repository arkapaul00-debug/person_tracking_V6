"""
Single Source of Truth for all SENTINEL PRO V3/V4 Events.
These schemas strictly define the data payloads allowed on the EventBus.
"""
from enum import Enum
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field

class SentinelEventChannel(str, Enum):
    LIVE_TRACKING = "live.tracking"
    SYSTEM_HEALTH = "system.health"
    EVIDENCE_VAULT = "evidence.vault"
    IDENTITY_GRAPH = "identity.graph"

# ==========================================
# 1. LIVE TRACKING EVENTS
# ==========================================

class PersonDetectedEvent(BaseModel):
    camera_id: str
    camera_name: str
    bbox: list[int]
    confidence: float
    frame_number: int
    timestamp: str

class SuspectMatchedEvent(BaseModel):
    camera_id: str
    track_id: int
    similarity_score: float
    identity_hash: str
    timestamp: str

# ==========================================
# 2. SYSTEM HEALTH EVENTS
# ==========================================

class CameraConnectedEvent(BaseModel):
    camera_id: str
    rtsp_url: str
    timestamp: str

class CameraDisconnectedEvent(BaseModel):
    camera_id: str
    reason: str
    timestamp: str

class WorkerHeartbeatEvent(BaseModel):
    worker_id: str
    gpu_utilization: float
    vram_used_mb: int
    active_streams: int
    status: str
    timestamp: str

# ==========================================
# 3. EVIDENCE & IDENTITY EVENTS
# ==========================================

class EvidenceGeneratedEvent(BaseModel):
    case_id: str
    camera_id: str
    clip_path: str
    identity_hash: str
    timestamp: str

class IdentityUpdatedEvent(BaseModel):
    identity_hash: str
    new_embedding_vector_count: int
    confidence_tier: str
    timestamp: str
