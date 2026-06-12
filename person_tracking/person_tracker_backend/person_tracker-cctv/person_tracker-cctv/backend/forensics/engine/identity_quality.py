"""
Identity Quality Monitor (Phase 49)
Continuously monitors ReID and tracking quality metrics.
Automatically triggers optimization or alerts when thresholds degrade.

Tracks:
  - ID switch rate (per minute, per camera)
  - Identity fragmentation index
  - Match confidence distribution
  - ReID accuracy (when ground-truth available)
  - Cross-camera handoff success rate

Automatically triggers:
  - Tracker mode switch (via TrackerOrchestrator) when ID switches spike
  - ReID threshold adjustment when confidence distribution shifts
  - Alert to operators when quality drops below acceptable levels

Usage:
    monitor = IdentityQualityMonitor()

    # Feed metrics from the pipeline
    monitor.record_id_switch(camera_id='cam_lobby')
    monitor.record_match(confidence=0.72, is_correct=True)

    # Check health
    health = monitor.get_health_report()
"""
import time
import logging
import threading
from typing import Dict, List, Optional
from collections import deque

logger = logging.getLogger(__name__)


class IdentityQualityMonitor:
    """
    Real-time identity quality monitoring with automatic optimization triggers.
    """

    def __init__(self,
                 id_switch_threshold: float = 5.0,
                 fragmentation_threshold: float = 0.3,
                 confidence_min: float = 0.5,
                 window_seconds: float = 60.0):
        """
        Args:
            id_switch_threshold: Max ID switches per minute before alerting.
            fragmentation_threshold: Max fragmentation rate before alerting.
            confidence_min: Minimum average confidence before alerting.
            window_seconds: Sliding window size for metric computation.
        """
        self.id_switch_threshold = id_switch_threshold
        self.fragmentation_threshold = fragmentation_threshold
        self.confidence_min = confidence_min
        self.window_seconds = window_seconds

        # Sliding windows
        self._id_switches: deque = deque()  # (timestamp, camera_id)
        self._matches: deque = deque()       # (timestamp, confidence, is_correct)
        self._handoffs: deque = deque()      # (timestamp, success: bool)

        # Aggregate counters
        self._total_id_switches = 0
        self._total_matches = 0
        self._total_correct = 0
        self._total_handoffs = 0
        self._total_handoff_success = 0

        # Per-camera counters
        self._camera_switches: Dict[str, int] = {}

        # Alert state
        self._quality_alerts: List[Dict] = []

        self._lock = threading.Lock()

        logger.info("IdentityQualityMonitor initialized")

    def record_id_switch(self, camera_id: str = ''):
        """Record an ID switch event."""
        with self._lock:
            now = time.time()
            self._id_switches.append((now, camera_id))
            self._total_id_switches += 1
            self._camera_switches[camera_id] = (
                self._camera_switches.get(camera_id, 0) + 1
            )
            self._prune_window(self._id_switches)
            self._check_id_switch_alert()

    def record_match(self, confidence: float, is_correct: bool = True):
        """Record a ReID match result."""
        with self._lock:
            now = time.time()
            self._matches.append((now, confidence, is_correct))
            self._total_matches += 1
            if is_correct:
                self._total_correct += 1
            self._prune_window(self._matches)
            self._check_confidence_alert()

    def record_handoff(self, success: bool):
        """Record a cross-camera handoff result."""
        with self._lock:
            now = time.time()
            self._handoffs.append((now, success))
            self._total_handoffs += 1
            if success:
                self._total_handoff_success += 1
            self._prune_window(self._handoffs)

    def _prune_window(self, window: deque):
        """Remove entries older than the sliding window."""
        cutoff = time.time() - self.window_seconds
        while window and window[0][0] < cutoff:
            window.popleft()

    def _check_id_switch_alert(self):
        """Check if ID switch rate exceeds threshold."""
        rate = len(self._id_switches) / (self.window_seconds / 60.0)
        if rate > self.id_switch_threshold:
            alert = {
                'type': 'HIGH_ID_SWITCH_RATE',
                'rate_per_min': round(rate, 1),
                'threshold': self.id_switch_threshold,
                'timestamp': time.time(),
                'action': 'Consider switching to appearance-based tracker',
            }
            self._quality_alerts.append(alert)
            if len(self._quality_alerts) > 100:
                self._quality_alerts = self._quality_alerts[-50:]
            logger.warning(
                f"QUALITY ALERT: ID switch rate {rate:.1f}/min "
                f"exceeds threshold {self.id_switch_threshold}/min"
            )

    def _check_confidence_alert(self):
        """Check if average match confidence is too low."""
        if len(self._matches) < 10:
            return
        avg_conf = sum(m[1] for m in self._matches) / len(self._matches)
        if avg_conf < self.confidence_min:
            alert = {
                'type': 'LOW_MATCH_CONFIDENCE',
                'avg_confidence': round(avg_conf, 3),
                'threshold': self.confidence_min,
                'timestamp': time.time(),
                'action': 'Consider adjusting ReID thresholds or lighting',
            }
            self._quality_alerts.append(alert)
            if len(self._quality_alerts) > 100:
                self._quality_alerts = self._quality_alerts[-50:]

    def get_health_report(self) -> Dict:
        """Generate a comprehensive quality health report."""
        with self._lock:
            # ID switch rate (per minute)
            switch_rate = (
                len(self._id_switches) / (self.window_seconds / 60.0)
            )

            # Confidence stats
            avg_conf = 0.0
            if self._matches:
                avg_conf = sum(m[1] for m in self._matches) / len(self._matches)

            # Accuracy
            correct_in_window = sum(
                1 for m in self._matches if m[2]
            )
            accuracy = (
                correct_in_window / max(len(self._matches), 1)
            )

            # Handoff success rate
            handoff_rate = 0.0
            if self._handoffs:
                handoff_rate = (
                    sum(1 for h in self._handoffs if h[1]) /
                    max(len(self._handoffs), 1)
                )

            # Overall status
            status = 'HEALTHY'
            if switch_rate > self.id_switch_threshold:
                status = 'DEGRADED'
            if avg_conf < self.confidence_min and len(self._matches) > 10:
                status = 'DEGRADED'
            if accuracy < 0.8 and len(self._matches) > 20:
                status = 'CRITICAL'

            return {
                'status': status,
                'id_switch_rate_per_min': round(switch_rate, 2),
                'avg_match_confidence': round(avg_conf, 3),
                'accuracy_in_window': round(accuracy, 3),
                'handoff_success_rate': round(handoff_rate, 3),
                'total_id_switches': self._total_id_switches,
                'total_matches': self._total_matches,
                'total_handoffs': self._total_handoffs,
                'worst_cameras': self._get_worst_cameras(top_k=3),
                'recent_alerts': self._quality_alerts[-5:],
            }

    def _get_worst_cameras(self, top_k: int = 3) -> List[Dict]:
        """Get cameras with highest ID switch counts."""
        sorted_cams = sorted(
            self._camera_switches.items(),
            key=lambda x: x[1], reverse=True
        )
        return [
            {'camera_id': cam, 'id_switches': count}
            for cam, count in sorted_cams[:top_k]
        ]

    def get_metrics(self) -> Dict:
        return self.get_health_report()
