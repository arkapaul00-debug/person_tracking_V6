"""
Camera Topology Engine (Phase 40)
Models the physical camera network as a directed graph.

Each edge represents a valid transition between two cameras,
weighted by observed travel time statistics. This allows:
  - Pruning impossible cross-camera matches (too fast/too slow)
  - Predicting which camera a suspect will appear on next
  - Calculating transition probabilities for ReID search optimization

Usage:
    topo = CameraTopologyEngine()

    # Learn from observed transitions
    topo.record_transition('cam_lobby', 'cam_hallway', travel_time_s=12.5)

    # Is a transition plausible?
    topo.is_plausible('cam_lobby', 'cam_hallway', elapsed_s=15.0)

    # Predict next camera
    predictions = topo.predict_next_camera('cam_lobby')
"""
import time
import math
import logging
import threading
from typing import Dict, List, Optional, Tuple
from collections import defaultdict
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class TransitionStats:
    """Statistics for a single camera-to-camera transition."""
    count: int = 0
    total_time_s: float = 0.0
    min_time_s: float = float('inf')
    max_time_s: float = 0.0
    last_seen: float = 0.0

    @property
    def avg_time_s(self) -> float:
        return self.total_time_s / max(self.count, 1)

    def record(self, travel_time_s: float):
        self.count += 1
        self.total_time_s += travel_time_s
        self.min_time_s = min(self.min_time_s, travel_time_s)
        self.max_time_s = max(self.max_time_s, travel_time_s)
        self.last_seen = time.time()

    def to_dict(self) -> Dict:
        return {
            'count': self.count,
            'avg_time_s': round(self.avg_time_s, 1),
            'min_time_s': round(self.min_time_s, 1),
            'max_time_s': round(self.max_time_s, 1),
        }


class CameraTopologyEngine:
    """
    Directed graph of camera-to-camera transition statistics.

    Learns transition probabilities from observed movements.
    Enables plausibility filtering and predictive matching.
    """

    def __init__(self, plausibility_margin: float = 2.0):
        """
        Args:
            plausibility_margin: Multiplier for min/max travel time
                when checking plausibility. E.g., 2.0 means we accept
                transitions up to 2x the observed max time.
        """
        self.plausibility_margin = plausibility_margin

        # Adjacency: (cam_from, cam_to) → TransitionStats
        self._transitions: Dict[Tuple[str, str], TransitionStats] = {}
        self._lock = threading.Lock()

        # Total transitions per source camera (for probability computation)
        self._source_totals: Dict[str, int] = defaultdict(int)

        logger.info("CameraTopologyEngine initialized")

    def record_transition(self, cam_from: str, cam_to: str,
                          travel_time_s: float):
        """
        Record an observed camera transition.
        Called every time a suspect is matched across two cameras.
        """
        if cam_from == cam_to:
            return  # Same camera, not a transition

        with self._lock:
            key = (cam_from, cam_to)
            if key not in self._transitions:
                self._transitions[key] = TransitionStats()

            self._transitions[key].record(travel_time_s)
            self._source_totals[cam_from] += 1

    def is_plausible(self, cam_from: str, cam_to: str,
                     elapsed_s: float) -> bool:
        """
        Check if a transition is physically plausible given elapsed time.

        Returns True if:
          - We have no data (assume plausible by default)
          - The elapsed time falls within the observed range (with margin)
        """
        with self._lock:
            key = (cam_from, cam_to)
            stats = self._transitions.get(key)

        if stats is None or stats.count < 2:
            return True  # No data → assume plausible

        # Allow a window around observed times
        min_allowed = stats.min_time_s / self.plausibility_margin
        max_allowed = stats.max_time_s * self.plausibility_margin

        return min_allowed <= elapsed_s <= max_allowed

    def predict_next_camera(self, cam_from: str,
                            top_k: int = 5) -> List[Dict]:
        """
        Predict the most likely next cameras based on historical transitions.

        Returns list of {'camera_id': str, 'probability': float, 'avg_time_s': float}
        sorted by probability descending.
        """
        predictions = []
        with self._lock:
            total = self._source_totals.get(cam_from, 0)
            if total == 0:
                return predictions

            for (src, dst), stats in self._transitions.items():
                if src == cam_from:
                    prob = stats.count / total
                    predictions.append({
                        'camera_id': dst,
                        'probability': round(prob, 4),
                        'avg_time_s': round(stats.avg_time_s, 1),
                        'observations': stats.count,
                    })

        predictions.sort(key=lambda p: p['probability'], reverse=True)
        return predictions[:top_k]

    def get_adjacent_cameras(self, cam_id: str) -> List[str]:
        """Get all cameras that have been reached from cam_id."""
        with self._lock:
            return [
                dst for (src, dst) in self._transitions
                if src == cam_id
            ]

    def get_topology_map(self) -> Dict:
        """Export the full topology as a serializable dict."""
        with self._lock:
            return {
                'transitions': {
                    f"{src}->{dst}": stats.to_dict()
                    for (src, dst), stats in self._transitions.items()
                },
                'total_cameras': len(
                    set(s for s, _ in self._transitions) |
                    set(d for _, d in self._transitions)
                ),
                'total_edges': len(self._transitions),
            }

    def get_metrics(self) -> Dict:
        """Return engine metrics."""
        with self._lock:
            return {
                'known_transitions': len(self._transitions),
                'known_cameras': len(
                    set(s for s, _ in self._transitions) |
                    set(d for _, d in self._transitions)
                ),
                'total_observations': sum(
                    s.count for s in self._transitions.values()
                ),
            }
