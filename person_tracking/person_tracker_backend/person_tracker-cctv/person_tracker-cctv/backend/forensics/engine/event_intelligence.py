"""
Event Intelligence Platform (Phases 53, 54, 55)
Centralized event routing, correlation, and alert intelligence.

Capabilities:
- Standardized event schemas (PersonDetected, IdentityMerged, etc.)
- Event Correlation across cameras and time windows
- Intelligent alert prioritization based on threat and confidence
- Reduce alert fatigue

Usage:
    platform = EventIntelligencePlatform()
    platform.emit_event("PersonDetected", {"camera": "cam_1", "confidence": 0.85})
"""
import time
import uuid
import logging
from typing import Dict, List, Any, Optional
import threading
from collections import deque

logger = logging.getLogger(__name__)


class EventIntelligencePlatform:
    """
    Central nervous system for all operational and intelligence events.
    Handles emission, correlation, and alert prioritization.
    """

    def __init__(self, correlation_window_sec: float = 300.0):
        self.correlation_window = correlation_window_sec
        self._events: deque = deque()
        self._alerts: List[Dict] = []
        self._lock = threading.Lock()
        
        # Metrics
        self._metrics = {
            "total_events": 0,
            "total_alerts": 0,
            "high_priority_alerts": 0,
            "suppressed_alerts": 0
        }
        
        logger.info("EventIntelligencePlatform initialized")

    def emit_event(self, event_type: str, payload: Dict[str, Any], source: str = "system") -> str:
        """
        Emit a structured event into the platform.
        Common types: PersonDetected, SuspectMatched, IdentityMerged, CameraFailure.
        """
        event_id = f"EVT-{uuid.uuid4().hex[:12]}"
        now = time.time()
        
        event = {
            "event_id": event_id,
            "event_type": event_type,
            "timestamp": now,
            "source": source,
            "payload": payload
        }
        
        with self._lock:
            self._events.append(event)
            self._metrics["total_events"] += 1
            self._prune_events()
            
            # Immediately trigger correlation
            self._correlate_and_alert(event)
            
        return event_id

    def _correlate_and_alert(self, new_event: Dict):
        """
        Event Correlation Engine (Phase 54) & Alert Intelligence Engine (Phase 55).
        Evaluates the new event against recent events to detect patterns or escalate alerts.
        """
        # Example Correlation 1: Repeated appearances (Alert fatigue reduction)
        if new_event["event_type"] == "SuspectMatched":
            identity_id = new_event["payload"].get("identity_id")
            camera = new_event["payload"].get("camera")
            
            # Check if we already alerted for this suspect on this camera recently
            recent_alerts = [
                a for a in self._alerts 
                if a["type"] == "SuspectMatched" 
                and a["payload"].get("identity_id") == identity_id
                and a["payload"].get("camera") == camera
                and (new_event["timestamp"] - a["timestamp"]) < 60.0 # 1 minute cooldown
            ]
            
            if recent_alerts:
                self._metrics["suppressed_alerts"] += 1
                return # Suppress duplicate alert
                
            # If not suppressed, calculate priority based on confidence and historical threat
            confidence = new_event["payload"].get("confidence", 0.0)
            priority = "HIGH" if confidence > 0.85 else "MEDIUM"
            
            self._trigger_alert(
                alert_type="SuspectMatched",
                priority=priority,
                message=f"Suspect {identity_id} matched on {camera} (conf: {confidence:.2f})",
                payload=new_event["payload"]
            )

        # Example Correlation 2: Camera Failure detected
        elif new_event["event_type"] == "CameraFailure":
            self._trigger_alert(
                alert_type="CameraFailure",
                priority="CRITICAL",
                message=f"Camera {new_event['payload'].get('camera')} has failed.",
                payload=new_event["payload"]
            )

    def _trigger_alert(self, alert_type: str, priority: str, message: str, payload: dict):
        """Creates a prioritized alert."""
        alert = {
            "alert_id": f"ALT-{uuid.uuid4().hex[:8]}",
            "type": alert_type,
            "priority": priority,
            "message": message,
            "timestamp": time.time(),
            "payload": payload,
            "status": "UNREAD"
        }
        self._alerts.append(alert)
        self._metrics["total_alerts"] += 1
        if priority in ["HIGH", "CRITICAL"]:
            self._metrics["high_priority_alerts"] += 1
            logger.warning(f"[{priority} ALERT] {message}")
        else:
            logger.info(f"[{priority} ALERT] {message}")

    def _prune_events(self):
        """Keep the event window bounded."""
        cutoff = time.time() - self.correlation_window
        while self._events and self._events[0]["timestamp"] < cutoff:
            self._events.popleft()

    def get_active_alerts(self, min_priority: str = "LOW") -> List[Dict]:
        """Fetch unread alerts filtered by priority."""
        priority_levels = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}
        min_level = priority_levels.get(min_priority, 1)
        
        with self._lock:
            return [
                a for a in self._alerts 
                if priority_levels.get(a["priority"], 1) >= min_level
                and a["status"] == "UNREAD"
            ]

    def get_metrics(self) -> dict:
        with self._lock:
            return dict(self._metrics)
