"""
Adaptive Inference Director (V5 Upgrade 5)
Centralized runtime decision engine that selects detectors, trackers, ReID strategies,
batch sizes, and resource allocation based on real-time system state.
"""
import time
import logging
import threading
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class AdaptiveInferenceDirector:
    """
    The "brain" of V5 runtime inference. Monitors VRAM utilization, GPU load,
    queue depth, and camera quality to make millisecond-level decisions about
    which AI components to activate.

    Decision matrix:
      VRAM < 60%  → Full modalities (Face+Body+Gait+Pose+Appearance)
      VRAM 60-75% → Standard (Face+Body+Gait)
      VRAM 75-85% → Reduced (Face+Body only, matches V4)
      VRAM > 85%  → Emergency (Body only + ByteTrack)
    """

    # Operating modes ordered by resource usage (heaviest first)
    MODES = {
        "FULL": {
            "detector": "yolov11",
            "tracker": "strongsort",
            "modalities": ["face", "body", "gait", "pose", "appearance"],
            "max_batch": 16,
        },
        "STANDARD": {
            "detector": "yolov11",
            "tracker": "botsort",
            "modalities": ["face", "body", "gait"],
            "max_batch": 12,
        },
        "REDUCED": {
            "detector": "yolov11",
            "tracker": "bytetrack",
            "modalities": ["face", "body"],
            "max_batch": 8,
        },
        "EMERGENCY": {
            "detector": "yolov11",
            "tracker": "bytetrack",
            "modalities": ["body"],
            "max_batch": 4,
        },
    }

    def __init__(self, vram_budget_manager=None):
        self._vram_mgr = vram_budget_manager
        self._lock = threading.Lock()
        self._current_mode = "STANDARD"

        self._metrics = {
            "decisions_made": 0,
            "mode_transitions": 0,
            "mode_history": [],
            "current_mode": "STANDARD",
        }

        logger.info("V5 AdaptiveInferenceDirector initialized (mode=STANDARD)")

    def evaluate(self, vram_percent: float = 0.0,
                 gpu_util_percent: float = 0.0,
                 queue_depth: int = 0,
                 active_cameras: int = 0) -> Dict[str, Any]:
        """
        Evaluate current system state and return the optimal inference configuration.
        This should be called once per inference cycle.
        """
        with self._lock:
            self._metrics["decisions_made"] += 1
            prev_mode = self._current_mode

            # ── Determine mode from VRAM pressure ────────────────────
            if vram_percent > 85:
                new_mode = "EMERGENCY"
            elif vram_percent > 75:
                new_mode = "REDUCED"
            elif vram_percent > 60:
                new_mode = "STANDARD"
            else:
                new_mode = "FULL"

            # ── Queue depth override ─────────────────────────────────
            # If the queue is building up, drop to a lighter mode
            if queue_depth > 100 and new_mode in ("FULL", "STANDARD"):
                new_mode = "REDUCED"
            elif queue_depth > 200:
                new_mode = "EMERGENCY"

            # ── Record transition ────────────────────────────────────
            if new_mode != prev_mode:
                self._metrics["mode_transitions"] += 1
                self._metrics["mode_history"].append({
                    "from": prev_mode, "to": new_mode,
                    "timestamp": time.time(),
                    "trigger": {
                        "vram_percent": vram_percent,
                        "queue_depth": queue_depth,
                    },
                })
                # Keep history bounded
                if len(self._metrics["mode_history"]) > 100:
                    self._metrics["mode_history"] = self._metrics["mode_history"][-50:]
                logger.warning(
                    f"InferenceDirector mode transition: {prev_mode} → {new_mode} "
                    f"(VRAM={vram_percent:.1f}%, Queue={queue_depth})"
                )
                self._current_mode = new_mode

            self._metrics["current_mode"] = self._current_mode

            config = dict(self.MODES[self._current_mode])
            config["mode"] = self._current_mode
            return config

    def get_current_mode(self) -> str:
        with self._lock:
            return self._current_mode

    def force_mode(self, mode: str) -> bool:
        """Force a specific mode (for operator override or testing)."""
        if mode not in self.MODES:
            return False
        with self._lock:
            prev = self._current_mode
            self._current_mode = mode
            self._metrics["current_mode"] = mode
            logger.warning(f"InferenceDirector FORCED: {prev} → {mode}")
            return True

    def get_metrics(self) -> dict:
        with self._lock:
            return dict(self._metrics)
