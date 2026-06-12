"""
V5 Investigation Copilot Evolution (V5 Upgrade 12)
Expanded investigation intelligence with timeline reconstruction, path reconstruction,
event correlation, association discovery, and behavioral pattern analysis.
"""
import time
import logging
import threading
from typing import Dict, List, Any, Optional
from collections import Counter

logger = logging.getLogger(__name__)


class V5InvestigationCopilot:
    """
    Evolves the V4 InvestigationCopilot into a full behavioral analysis engine.

    New capabilities:
    - Association discovery via graph traversal
    - Behavioral pattern detection (repeated routes, time-of-day habits)
    - Multi-suspect correlation
    - Natural language investigation summaries
    """

    def __init__(self, global_graph=None, predictive_engine=None,
                 v4_copilot=None):
        self._graph = global_graph
        self._predictive = predictive_engine
        self._v4_copilot = v4_copilot  # Backward-compatible fallback
        self._lock = threading.RLock()

        self._metrics = {
            "investigations_run": 0,
            "associations_discovered": 0,
            "patterns_detected": 0,
            "nlp_queries_served": 0,
        }

        logger.info("V5 InvestigationCopilot initialized")

    def investigate_identity(self, identity_id: str) -> Dict[str, Any]:
        """
        Run a comprehensive investigation on an identity.
        Returns profile, timeline, associations, and behavioral patterns.
        """
        with self._lock:
            self._metrics["investigations_run"] += 1

        result = {
            "identity_id": identity_id,
            "profile": {},
            "timeline": [],
            "associations": [],
            "behavioral_patterns": [],
            "movement_predictions": [],
            "summary": "",
        }

        # 1. Profile from graph
        if self._graph:
            result["profile"] = self._graph.get_identity_profile(identity_id)
            result["timeline"] = self._graph.reconstruct_timeline(identity_id)

            # 2. Association discovery
            assocs = self._graph.find_associations(identity_id, max_depth=2)
            result["associations"] = assocs
            with self._lock:
                self._metrics["associations_discovered"] += len(assocs)

        # 3. Behavioral patterns
        result["behavioral_patterns"] = self._analyze_patterns(
            result["timeline"]
        )

        # 4. Movement predictions
        if self._predictive and result["timeline"]:
            last_event = result["timeline"][-1]
            last_cam = last_event.get("camera_id", "")
            if last_cam:
                preds = self._predictive.predict_next_cameras(last_cam)
                result["movement_predictions"] = preds

        # 5. NLP summary
        result["summary"] = self._generate_summary(result)
        with self._lock:
            self._metrics["nlp_queries_served"] += 1

        return result

    def correlate_suspects(self, identity_ids: List[str]) -> Dict[str, Any]:
        """
        Find correlations between multiple suspects.
        Checks for shared cameras, overlapping timelines, and co-occurrence.
        """
        if not self._graph:
            return {"error": "GlobalIdentityGraph unavailable"}

        shared_cameras = None
        timelines = {}

        for ident_id in identity_ids:
            profile = self._graph.get_identity_profile(ident_id)
            cameras = set(profile.get("cameras_seen", []))
            timelines[ident_id] = self._graph.reconstruct_timeline(ident_id)

            if shared_cameras is None:
                shared_cameras = cameras
            else:
                shared_cameras = shared_cameras.intersection(cameras)

        # Find temporal overlap (events within 5 minutes of each other)
        co_occurrences = []
        ids = list(timelines.keys())
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                for evt_a in timelines[ids[i]]:
                    for evt_b in timelines[ids[j]]:
                        if abs(evt_a["timestamp"] - evt_b["timestamp"]) < 300:
                            co_occurrences.append({
                                "suspect_a": ids[i],
                                "suspect_b": ids[j],
                                "time_diff_sec": abs(
                                    evt_a["timestamp"] - evt_b["timestamp"]
                                ),
                                "camera_a": evt_a.get("camera_id"),
                                "camera_b": evt_b.get("camera_id"),
                            })

        return {
            "suspects": identity_ids,
            "shared_cameras": list(shared_cameras or []),
            "co_occurrences": co_occurrences[:50],  # Bounded
            "correlation_strength": min(
                1.0, len(co_occurrences) / max(1, len(identity_ids))
            ),
        }

    def _analyze_patterns(self, timeline: List[Dict]) -> List[Dict[str, Any]]:
        """Detect behavioral patterns from the timeline."""
        patterns = []
        if len(timeline) < 3:
            return patterns

        # Pattern 1: Frequent cameras
        camera_counts = Counter(e.get("camera_id") for e in timeline)
        for cam, count in camera_counts.most_common(3):
            if count >= 3:
                patterns.append({
                    "type": "FREQUENT_LOCATION",
                    "camera_id": cam,
                    "occurrences": count,
                })
                with self._lock:
                    self._metrics["patterns_detected"] += 1

        # Pattern 2: Time-of-day regularity
        import datetime
        hours = []
        for e in timeline:
            ts = e.get("timestamp", 0)
            if ts > 0:
                dt = datetime.datetime.fromtimestamp(ts)
                hours.append(dt.hour)
        if hours:
            hour_counts = Counter(hours)
            most_common_hour, freq = hour_counts.most_common(1)[0]
            if freq >= 3:
                patterns.append({
                    "type": "TIME_OF_DAY_PATTERN",
                    "peak_hour": most_common_hour,
                    "frequency": freq,
                })
                with self._lock:
                    self._metrics["patterns_detected"] += 1

        return patterns

    def _generate_summary(self, investigation: Dict[str, Any]) -> str:
        """Generate a natural language summary of the investigation."""
        ident = investigation.get("identity_id", "Unknown")
        profile = investigation.get("profile", {})
        timeline = investigation.get("timeline", [])
        assocs = investigation.get("associations", [])
        patterns = investigation.get("behavioral_patterns", [])
        preds = investigation.get("movement_predictions", [])

        parts = [f"Investigation Report for {ident}:"]

        sightings = profile.get("sighting_count", len(timeline))
        cameras = len(profile.get("cameras_seen", []))
        modalities = profile.get("modalities_observed", [])
        parts.append(
            f"Subject has been observed {sightings} time(s) across {cameras} camera(s). "
            f"Modalities captured: {', '.join(modalities) if modalities else 'face, body'}."
        )

        if patterns:
            for p in patterns:
                if p["type"] == "FREQUENT_LOCATION":
                    parts.append(
                        f"Frequently seen at camera {p['camera_id']} "
                        f"({p['occurrences']} times)."
                    )
                elif p["type"] == "TIME_OF_DAY_PATTERN":
                    parts.append(
                        f"Shows a pattern of appearing around {p['peak_hour']}:00 "
                        f"({p['frequency']} occurrences)."
                    )

        if assocs:
            parts.append(
                f"{len(assocs)} associated identity(ies) discovered via graph analysis."
            )

        if preds:
            top = preds[0]
            parts.append(
                f"Most likely next camera: {top['camera_id']} "
                f"(probability: {top['probability']:.1%})."
            )

        return " ".join(parts)

    def get_metrics(self) -> dict:
        with self._lock:
            return dict(self._metrics)
