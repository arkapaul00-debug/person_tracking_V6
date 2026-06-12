"""
Unified API Layer & Contracts (Phases 76, 77)
Single Source of Truth for all frontend-backend communication.
"""
from typing import List, Dict, Optional, Any
from pydantic import BaseModel, Field
from datetime import datetime

# --- ERROR SCHEMAS ---

class APIError(BaseModel):
    code: str = Field(..., description="Machine-readable error code")
    message: str = Field(..., description="Human-readable error message")
    details: Optional[Dict[str, Any]] = Field(None, description="Additional error context")

class APIResponse(BaseModel):
    success: bool = Field(..., description="Indicates if the request succeeded")
    data: Optional[Any] = Field(None, description="Response payload")
    error: Optional[APIError] = Field(None, description="Error details if success is false")

# --- EVENT SCHEMAS (WebSocket / PubSub) ---

class BaseEvent(BaseModel):
    event_id: str = Field(..., description="Unique event identifier")
    timestamp: float = Field(..., description="Unix timestamp of event generation")
    source: str = Field(..., description="Originating service or camera")
    priority: str = Field("LOW", description="Event priority (LOW, MEDIUM, HIGH, CRITICAL)")

class PersonDetectedEvent(BaseEvent):
    event_type: str = "PersonDetected"
    camera_id: str
    track_id: int
    bbox: List[int]
    confidence: float

class SuspectMatchedEvent(BaseEvent):
    event_type: str = "SuspectMatched"
    camera_id: str
    identity_id: str
    confidence: float
    alert_triggered: bool

class SystemHealthEvent(BaseEvent):
    event_type: str = "SystemHealth"
    cpu_percent: float
    gpu_percent: float
    vram_percent: float
    fps: float
    health_score: float

# --- INVESTIGATION SCHEMAS ---

class TimelineQueryRequest(BaseModel):
    identity_id: str = Field(..., description="The ID of the suspect")
    start_time: Optional[float] = Field(None, description="Start timestamp filter")
    end_time: Optional[float] = Field(None, description="End timestamp filter")

class TimelineQueryResponse(BaseModel):
    identity_id: str
    total_sightings: int
    events: List[Dict[str, Any]]

class NaturalLanguageQuery(BaseModel):
    query: str = Field(..., description="Natural language search (e.g. 'Show suspect X')")

# --- MLOPS SCHEMAS ---

class ModelVersionInfo(BaseModel):
    model_id: str
    version: str
    status: str = Field(..., description="e.g. STAGING, PRODUCTION, SHADOW, RETIRED")
    metrics: Dict[str, float]
