"""
Facility-Wide Forensic Replay System (V5 Upgrade 9)
Synchronized multi-camera reconstruction and historical navigation
for accelerated forensic investigations.
"""
import time
import logging
import threading
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)


class ForensicReplaySystem:
    """
    Reconstructs synchronized multi-camera timelines for forensic playback.
    Operators can navigate a suspect's entire journey across all cameras
    with temporal alignment.
    """

    def __init__(self, global_graph=None, feature_store=None):
        self._global_graph = global_graph
        self._feature_store = feature_store
        self._lock = threading.RLock()

        # Active replay sessions
        self._sessions: Dict[str, Dict[str, Any]] = {}

        self._metrics = {
            "replay_sessions_created": 0,
            "timeline_reconstructions": 0,
            "total_events_replayed": 0,
        }

        logger.info("V5 ForensicReplaySystem initialized")

    def create_replay_session(self, session_id: str,
                              identity_id: str,
                              start_time: float,
                              end_time: float) -> Dict[str, Any]:
        """
        Create a synchronized replay session for a suspect.
        Reconstructs the complete timeline from the GlobalIdentityGraph.
        """
        with self._lock:
            self._metrics["replay_sessions_created"] += 1

            # Reconstruct timeline from graph
            timeline = []
            if self._global_graph:
                timeline = self._global_graph.reconstruct_timeline(
                    identity_id, start_time, end_time
                )
                self._metrics["timeline_reconstructions"] += 1

            # Group events by camera for synchronized playback
            camera_timelines: Dict[str, List[Dict]] = {}
            for event in timeline:
                cam = event.get("camera_id", "unknown")
                if cam not in camera_timelines:
                    camera_timelines[cam] = []
                camera_timelines[cam].append(event)

            session = {
                "session_id": session_id,
                "identity_id": identity_id,
                "start_time": start_time,
                "end_time": end_time,
                "total_events": len(timeline),
                "cameras_involved": list(camera_timelines.keys()),
                "camera_timelines": camera_timelines,
                "created_at": time.time(),
                "playback_position": start_time,
            }

            self._sessions[session_id] = session
            self._metrics["total_events_replayed"] += len(timeline)

            return {
                "session_id": session_id,
                "total_events": len(timeline),
                "cameras_involved": len(camera_timelines),
                "duration_sec": end_time - start_time,
            }

    def seek(self, session_id: str, timestamp: float) -> Dict[str, Any]:
        """Seek to a specific timestamp in the replay session."""
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return {"error": "Session not found"}

            session["playback_position"] = timestamp

            # Find events at or near this timestamp across all cameras
            active_events = {}
            for cam, events in session["camera_timelines"].items():
                # Find the closest event before or at the seek time
                closest = None
                for evt in events:
                    if evt["timestamp"] <= timestamp:
                        closest = evt
                    else:
                        break
                if closest:
                    active_events[cam] = closest

            return {
                "timestamp": timestamp,
                "active_cameras": len(active_events),
                "events_at_position": active_events,
            }

    def get_session_info(self, session_id: str) -> Dict[str, Any]:
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return {}
            return {
                "session_id": session["session_id"],
                "identity_id": session["identity_id"],
                "total_events": session["total_events"],
                "cameras_involved": session["cameras_involved"],
                "playback_position": session["playback_position"],
            }

    def get_metrics(self) -> dict:
        with self._lock:
            return dict(self._metrics)
