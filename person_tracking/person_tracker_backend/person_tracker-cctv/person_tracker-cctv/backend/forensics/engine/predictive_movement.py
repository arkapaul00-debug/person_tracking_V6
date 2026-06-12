"""
Predictive Movement Intelligence (V5 Upgrade 4)
Learns movement patterns, transition probabilities, and travel-time distributions
to predict likely future camera appearances.
"""
import time
import math
import logging
import threading
from typing import Dict, List, Any, Optional, Tuple
from collections import defaultdict

logger = logging.getLogger(__name__)


class PredictiveMovementEngine:
    """
    Extends V4 CameraTopologyEngine with probabilistic transition modeling.

    Learns:
    - Transition probabilities between camera pairs
    - Travel-time distributions (mean, stddev)
    - Time-of-day patterns

    Predicts:
    - Next-camera probability given current camera
    - Expected arrival time window
    """

    def __init__(self, camera_topology=None):
        self._topology = camera_topology  # V4 fallback
        self._lock = threading.RLock()

        # Transition model: (cam_a, cam_b) -> list of travel times
        self._travel_times: Dict[Tuple[str, str], List[float]] = defaultdict(list)

        # Transition counts: cam_a -> {cam_b: count}
        self._transition_counts: Dict[str, Dict[str, int]] = defaultdict(
            lambda: defaultdict(int)
        )

        # Time-of-day patterns: identity_id -> [(hour, camera_id)]
        self._temporal_patterns: Dict[str, List[Tuple[int, str]]] = defaultdict(list)

        self._metrics = {
            "transitions_learned": 0,
            "predictions_made": 0,
            "prediction_accuracy_sum": 0.0,
            "prediction_count_for_accuracy": 0,
        }

        logger.info("V5 PredictiveMovementEngine initialized")

    # ── Learning ─────────────────────────────────────────────────────

    def record_transition(self, identity_id: str,
                          from_cam: str, to_cam: str,
                          travel_time_sec: float):
        """Record a confirmed camera transition for learning."""
        with self._lock:
            pair = (from_cam, to_cam)
            self._travel_times[pair].append(travel_time_sec)
            self._transition_counts[from_cam][to_cam] += 1
            self._metrics["transitions_learned"] += 1

            # Record temporal pattern
            hour = int(time.localtime().tm_hour)
            self._temporal_patterns[identity_id].append((hour, to_cam))

    def _compute_travel_stats(self, from_cam: str,
                              to_cam: str) -> Optional[Dict[str, float]]:
        """Compute mean and stddev of travel time between two cameras."""
        pair = (from_cam, to_cam)
        times = self._travel_times.get(pair, [])
        if len(times) < 2:
            return None

        mean = sum(times) / len(times)
        variance = sum((t - mean) ** 2 for t in times) / len(times)
        stddev = math.sqrt(variance) if variance > 0 else 0.0

        return {"mean_sec": round(mean, 2), "stddev_sec": round(stddev, 2),
                "samples": len(times)}

    # ── Prediction ───────────────────────────────────────────────────

    def predict_next_cameras(self, current_cam: str,
                             top_k: int = 3) -> List[Dict[str, Any]]:
        """
        Predict the most likely next cameras based on learned transition probabilities.
        Returns up to top_k predictions sorted by probability.
        """
        with self._lock:
            self._metrics["predictions_made"] += 1
            counts = self._transition_counts.get(current_cam, {})
            total = sum(counts.values())
            if total == 0:
                return []

            predictions = []
            for cam, count in counts.items():
                prob = count / total
                travel_stats = self._compute_travel_stats(current_cam, cam)
                predictions.append({
                    "camera_id": cam,
                    "probability": round(prob, 4),
                    "travel_time": travel_stats,
                })

            predictions.sort(key=lambda x: x["probability"], reverse=True)
            return predictions[:top_k]

    def predict_arrival_window(self, from_cam: str,
                               to_cam: str) -> Optional[Dict[str, float]]:
        """
        Predict the arrival window (earliest, latest) at a camera using
        mean ± 2*stddev (95% confidence interval).
        """
        with self._lock:
            self._metrics["predictions_made"] += 1
            stats = self._compute_travel_stats(from_cam, to_cam)
            if not stats:
                return None

            mean = stats["mean_sec"]
            stddev = stats["stddev_sec"]
            now = time.time()

            return {
                "earliest_arrival": now + max(0, mean - 2 * stddev),
                "expected_arrival": now + mean,
                "latest_arrival": now + mean + 2 * stddev,
                "confidence": 0.95,
            }

    def validate_prediction(self, from_cam: str, to_cam: str,
                            actual_travel_time: float):
        """Validate a prediction against actual travel time for accuracy tracking."""
        with self._lock:
            stats = self._compute_travel_stats(from_cam, to_cam)
            if stats:
                expected = stats["mean_sec"]
                error = abs(actual_travel_time - expected) / max(expected, 1.0)
                accuracy = max(0.0, 1.0 - error)
                self._metrics["prediction_accuracy_sum"] += accuracy
                self._metrics["prediction_count_for_accuracy"] += 1

    # ── Metrics ──────────────────────────────────────────────────────

    def get_metrics(self) -> dict:
        with self._lock:
            m = dict(self._metrics)
            count = m.get("prediction_count_for_accuracy", 0)
            if count > 0:
                m["avg_prediction_accuracy"] = round(
                    m["prediction_accuracy_sum"] / count, 4
                )
            else:
                m["avg_prediction_accuracy"] = 0.0
            return m
