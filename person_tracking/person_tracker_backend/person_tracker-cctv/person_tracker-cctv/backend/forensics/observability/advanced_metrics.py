"""
Advanced Metrics Engine (Phase 64)
Tracks complex AI performance metrics like ID Switch Rate, Fragmentation, Precision, and Recall.
Generates continuous health scoring.
"""
import time
import logging
import threading
from typing import Dict, Any

logger = logging.getLogger(__name__)


class AdvancedMetricsEngine:
    """
    Computes real-time, complex AI metrics beyond simple latency.
    Includes continuous health scoring based on multiple factors.
    """

    def __init__(self):
        self._metrics = {
            "true_positives": 0,
            "false_positives": 0,
            "false_negatives": 0,
            "id_switches": 0,
            "track_fragments": 0,
            "total_tracks": 0
        }
        self._lock = threading.Lock()
        logger.info("AdvancedMetricsEngine initialized")

    def record_detection(self, is_true_positive: bool):
        with self._lock:
            if is_true_positive:
                self._metrics["true_positives"] += 1
            else:
                self._metrics["false_positives"] += 1

    def record_missed_detection(self):
        with self._lock:
            self._metrics["false_negatives"] += 1

    def record_tracking_event(self, event_type: str):
        """event_type: 'new_track', 'id_switch', 'fragmentation'"""
        with self._lock:
            if event_type == "new_track":
                self._metrics["total_tracks"] += 1
            elif event_type == "id_switch":
                self._metrics["id_switches"] += 1
            elif event_type == "fragmentation":
                self._metrics["track_fragments"] += 1

    def _calculate_derived_metrics(self) -> Dict[str, float]:
        tp = self._metrics["true_positives"]
        fp = self._metrics["false_positives"]
        fn = self._metrics["false_negatives"]
        
        precision = tp / (tp + fp) if (tp + fp) > 0 else 1.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 1.0
        
        total_tracks = max(1, self._metrics["total_tracks"])
        id_switch_rate = self._metrics["id_switches"] / total_tracks
        fragmentation_rate = self._metrics["track_fragments"] / total_tracks
        
        return {
            "detection_precision": round(precision, 3),
            "detection_recall": round(recall, 3),
            "id_switch_rate": round(id_switch_rate, 3),
            "fragmentation_rate": round(fragmentation_rate, 3)
        }

    def generate_health_score(self) -> Dict[str, Any]:
        """Generate a 0-100 system health score based on advanced metrics."""
        with self._lock:
            derived = self._calculate_derived_metrics()
            
            # Base score 100
            score = 100.0
            
            # Deduct for poor precision/recall
            if derived["detection_precision"] < 0.9:
                score -= (0.9 - derived["detection_precision"]) * 50
            if derived["detection_recall"] < 0.85:
                score -= (0.85 - derived["detection_recall"]) * 50
                
            # Deduct for tracking instability
            if derived["id_switch_rate"] > 0.05:
                score -= derived["id_switch_rate"] * 100
                
            score = max(0.0, min(100.0, score))
            
            return {
                "health_score": round(score, 1),
                "status": "HEALTHY" if score >= 80 else "DEGRADED" if score >= 60 else "CRITICAL",
                "derived_metrics": derived,
                "raw_metrics": dict(self._metrics)
            }
