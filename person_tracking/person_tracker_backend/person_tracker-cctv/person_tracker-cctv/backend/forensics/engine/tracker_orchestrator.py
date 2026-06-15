"""
Tracker Orchestrator — Adaptive Multi-Algorithm Tracking with Scene-Aware Switching.

Architecture:
    Primary:   ByteTrack  → High-speed, low-latency for normal scenes
    Secondary: BoT-SORT   → Appearance-based re-ID for long occlusions
    Tertiary:  StrongSORT → Forensic replay ONLY (not for live inference)

Switching Logic (DO NOT run all trackers simultaneously):
    1. ByteTrack is the DEFAULT (99% of live frames)
    2. BoT-SORT activates ONLY when:
       - Track fragmentation rate > 0.3 (too many ID switches)
       - Occlusion duration > 3 seconds (person hidden behind object)
       - Cross-camera re-ID handoff (appearance matching needed)
    3. StrongSORT is NEVER used for live inference:
       - Only activated during forensic batch replay analysis
       - Uses full appearance + Kalman + cascade matching

State Machine:
    FAST (ByteTrack) → [fragmentation/occlusion trigger] → APPEARANCE (BoT-SORT)
    APPEARANCE (BoT-SORT) → [stability restored for 10s] → FAST (ByteTrack)
    FORENSIC (StrongSORT) → [only via explicit API call]
"""
import time
import logging
import numpy as np
from typing import List, Dict, Optional, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class TrackerMode(Enum):
    FAST = 'bytetrack'         # Low-latency, motion-only
    APPEARANCE = 'botsort'     # Re-ID capable, heavier
    FORENSIC = 'strongsort'    # Maximum accuracy, offline only


@dataclass
class TrackState:
    """State of a single tracked object."""
    track_id: int
    bbox: List[int]         # [x1, y1, x2, y2]
    confidence: float
    class_id: int = 0
    is_predicted: bool = False  # True if Kalman prediction (no detection match)
    age: int = 0               # Frames since track was created
    hits: int = 0              # Consecutive detection matches
    time_since_update: int = 0  # Frames since last detection match


@dataclass
class SceneComplexity:
    """Scene complexity metrics for tracker switching decisions."""
    track_count: int = 0
    fragmentation_rate: float = 0.0    # ID switches / total tracks in window
    occlusion_score: float = 0.0       # Fraction of occluded tracks
    avg_track_age: float = 0.0
    lost_track_ratio: float = 0.0      # Lost tracks / total tracks
    needs_appearance_tracker: bool = False
    switch_reason: str = ''


class SceneComplexityAnalyzer:
    """
    Analyzes tracking quality metrics to decide when to switch algorithms.

    Maintains a sliding window of tracking statistics and triggers
    algorithm switches based on degradation patterns.
    """

    def __init__(self,
                 fragmentation_threshold: float = 0.3,
                 occlusion_threshold: float = 0.4,
                 window_size: int = 90,  # ~3 seconds at 30fps
                 stability_window: int = 300):  # ~10 seconds for switch-back
        self.frag_thresh = fragmentation_threshold
        self.occ_thresh = occlusion_threshold
        self.window_size = window_size
        self.stability_window = stability_window

        # Sliding window state
        self._id_history: List[set] = []  # Track IDs per frame
        self._detection_counts: List[int] = []
        self._id_switch_count = 0
        self._frames_since_switch = 0

    def analyze(self, tracks: List[TrackState],
                detections: List[Any]) -> SceneComplexity:
        """
        Analyze current tracking quality.

        Args:
            tracks: Current active tracks.
            detections: Current frame detections.

        Returns:
            SceneComplexity with switching recommendation.
        """
        ctx = SceneComplexity()
        ctx.track_count = len(tracks)

        if not tracks:
            return ctx

        # Track ID continuity analysis
        current_ids = {t.track_id for t in tracks}
        self._id_history.append(current_ids)
        self._detection_counts.append(len(detections))

        # Trim to window
        if len(self._id_history) > self.window_size:
            self._id_history = self._id_history[-self.window_size:]
            self._detection_counts = self._detection_counts[-self.window_size:]

        # Fragmentation rate: new IDs appearing vs total unique IDs
        if len(self._id_history) >= 2:
            all_ids = set()
            new_id_events = 0
            for i, ids in enumerate(self._id_history):
                if i > 0:
                    new_ids = ids - self._id_history[i - 1]
                    new_id_events += len(new_ids)
                all_ids.update(ids)
            ctx.fragmentation_rate = new_id_events / max(len(all_ids), 1)

        # Occlusion score: tracks with no detection match
        predicted_tracks = [t for t in tracks if t.is_predicted or t.time_since_update > 0]
        ctx.occlusion_score = len(predicted_tracks) / max(len(tracks), 1)

        # Lost track ratio
        lost = [t for t in tracks if t.time_since_update > 10]
        ctx.lost_track_ratio = len(lost) / max(len(tracks), 1)

        # Average track age
        if tracks:
            ctx.avg_track_age = float(np.mean([t.age for t in tracks]))

        # Decision logic
        self._frames_since_switch += 1

        if ctx.fragmentation_rate > self.frag_thresh:
            ctx.needs_appearance_tracker = True
            ctx.switch_reason = f'high_fragmentation({ctx.fragmentation_rate:.2f})'
        elif ctx.occlusion_score > self.occ_thresh:
            ctx.needs_appearance_tracker = True
            ctx.switch_reason = f'heavy_occlusion({ctx.occlusion_score:.2f})'
        elif ctx.lost_track_ratio > 0.5:
            ctx.needs_appearance_tracker = True
            ctx.switch_reason = f'many_lost_tracks({ctx.lost_track_ratio:.2f})'

        return ctx


class TrackerOrchestrator:
    """
    Adaptive multi-algorithm tracker with scene-aware switching.

    Usage:
        orch = TrackerOrchestrator()

        # Per-frame update (automatically selects best algorithm)
        tracks = orch.update(detections, frame)

        # Check current mode
        print(f"Active: {orch.active_mode}")

        # Force forensic mode for offline analysis
        orch.set_mode(TrackerMode.FORENSIC)
    """

    def __init__(self,
                 track_thresh: float = 0.3,
                 track_buffer: int = 100,
                 frame_rate: int = 30,
                 auto_switch: bool = True):
        """
        Args:
            track_thresh: ByteTrack detection confidence threshold.
            track_buffer: Frames to keep lost tracks alive.
            frame_rate: Video FPS (affects Kalman filter velocity).
            auto_switch: Enable automatic algorithm switching.
        """
        self.track_thresh = track_thresh
        self.track_buffer = track_buffer
        self.frame_rate = frame_rate
        self.auto_switch = auto_switch

        # V3: Phase 32 - Integrate VRAM Budget Manager for tracking
        try:
            from ..gpu.memory_manager import VRAMBudgetManager
            self.vram_manager = VRAMBudgetManager()
        except ImportError:
            self.vram_manager = None

        # --- Primary: ByteTrack (always loaded) ---
        from boxmot import BYTETracker
        self._bytetrack = BYTETracker(
            track_thresh=track_thresh,
            track_buffer=track_buffer,
            match_thresh=0.8,
            frame_rate=frame_rate,
        )

        # --- Secondary: BoT-SORT (lazy loaded on demand) ---
        self._botsort = None
        self._botsort_available = True  # Assume available until proven otherwise

        # --- Tertiary: StrongSORT (lazy loaded, forensic only) ---
        self._strongsort = None

        # --- State machine ---
        self.active_mode = TrackerMode.FAST
        self._scene_analyzer = SceneComplexityAnalyzer()
        self._mode_lock_until = 0  # Timestamp: don't switch before this time
        self._min_mode_duration = 5.0  # Minimum seconds in a mode before switching

        # --- Metrics ---
        self._total_updates = 0
        self._mode_counts = {m: 0 for m in TrackerMode}
        self._total_tracks_output = 0
        self._switch_events: List[Dict] = []

        logger.info(
            f"TrackerOrchestrator initialized: primary=ByteTrack, "
            f"auto_switch={auto_switch}, buffer={track_buffer}"
        )

    def _lazy_load_botsort(self):
        """Load BoT-SORT on first demand."""
        if self._botsort is not None:
            return

        try:
            from boxmot import BoTSORT
            import torch
            from pathlib import Path
            self._botsort = BoTSORT(
                model_weights=Path('osnet_x0_25_msmt17.pt'),
                device=torch.device('cuda:0' if torch.cuda.is_available() else 'cpu'),
                fp16=False,
                track_high_thresh=self.track_thresh,
                track_buffer=self.track_buffer,
                match_thresh=0.8,
                frame_rate=self.frame_rate,
            )
            logger.info("BoT-SORT loaded (appearance-based tracker)")
        except ImportError:
            logger.warning("BoT-SORT not available — staying in ByteTrack mode")
            self._botsort_available = False
        except Exception as e:
            logger.error(f"BoT-SORT load failed: {e}")
            self._botsort_available = False

    def _lazy_load_strongsort(self):
        """Load StrongSORT on first demand (forensic only)."""
        if self._strongsort is not None:
            return

        try:
            from boxmot import StrongSORT
            import torch
            from pathlib import Path
            self._strongsort = StrongSORT(
                model_weights=Path('osnet_x0_25_msmt17.pt'),
                device=torch.device('cuda:0' if torch.cuda.is_available() else 'cpu'),
                fp16=False,
                max_age=self.track_buffer * 3,  # Longer buffer for forensic
            )
            logger.info("StrongSORT loaded (forensic-grade tracker)")
        except ImportError:
            logger.warning("StrongSORT not available")
        except Exception as e:
            logger.error(f"StrongSORT load failed: {e}")

    def update(self, detections_array: np.ndarray,
               frame: np.ndarray,
               scene_context: Optional[Dict] = None) -> List[TrackState]:
        """
        Update tracks with new detections using the active algorithm.

        Args:
            detections_array: Numpy array [N, 6] of [x1, y1, x2, y2, conf, class_id].
            frame: Current BGR frame (needed by appearance trackers).
            scene_context: Optional external scene info.

        Returns:
            List of TrackState objects for active tracks.
        """
        self._total_updates += 1

        # --- Get active tracker ---
        tracker = self._get_active_tracker()

        # --- Run tracker update ---
        if len(detections_array) == 0:
            detections_array = np.empty((0, 6))

        try:
            raw_tracks = tracker.update(detections_array, frame)
        except Exception as e:
            logger.error(f"Tracker update failed ({self.active_mode.value}): {e}")
            raw_tracks = np.empty((0, 7))

        # --- Convert to TrackState objects ---
        track_states = self._parse_tracks(raw_tracks)
        self._total_tracks_output += len(track_states)
        self._mode_counts[self.active_mode] += 1

        # --- Auto-switch evaluation ---
        if self.auto_switch and self.active_mode != TrackerMode.FORENSIC:
            self._evaluate_switch(track_states, detections_array)

        return track_states

    def _get_active_tracker(self):
        """Return the currently active tracker instance."""
        if self.active_mode == TrackerMode.FAST:
            return self._bytetrack
        elif self.active_mode == TrackerMode.APPEARANCE:
            if self._botsort is None:
                self._lazy_load_botsort()
            if self._botsort is not None:
                return self._botsort
            # Fallback to ByteTrack if BoT-SORT unavailable
            return self._bytetrack
        elif self.active_mode == TrackerMode.FORENSIC:
            if self._strongsort is None:
                self._lazy_load_strongsort()
            if self._strongsort is not None:
                return self._strongsort
            return self._bytetrack
        return self._bytetrack

    def _parse_tracks(self, raw_tracks: np.ndarray) -> List[TrackState]:
        """Convert raw tracker output to TrackState objects."""
        states = []
        if raw_tracks is None or len(raw_tracks) == 0:
            return states

        for track in raw_tracks:
            try:
                x1, y1, x2, y2 = map(int, track[:4])
                track_id = int(track[4])
                conf = float(track[5]) if len(track) > 5 else 0.0

                states.append(TrackState(
                    track_id=track_id,
                    bbox=[x1, y1, x2, y2],
                    confidence=conf,
                    class_id=0,
                ))
            except (IndexError, ValueError) as e:
                logger.warning(f"Failed to parse track: {e}")
                continue

        return states

    def _evaluate_switch(self, tracks: List[TrackState],
                         detections: np.ndarray):
        """Evaluate whether to switch tracker algorithm."""
        now = time.time()
        if now < self._mode_lock_until:
            return  # Still in minimum duration lock

        complexity = self._scene_analyzer.analyze(tracks, detections)

        if self.active_mode == TrackerMode.FAST and complexity.needs_appearance_tracker:
            if self._botsort_available:
                # V3: Phase 32 - Check VRAM Budget before upgrading tracker
                vram_safe = True
                if self.vram_manager and self.vram_manager.is_under_pressure():
                    logger.warning("VRAM under pressure. Denying tracker upgrade to BoT-SORT.")
                    vram_safe = False
                    
                if vram_safe:
                    self._switch_mode(TrackerMode.APPEARANCE, complexity.switch_reason)
        elif self.active_mode == TrackerMode.APPEARANCE and not complexity.needs_appearance_tracker:
            # Scene is stable again — switch back to fast tracker
            self._switch_mode(TrackerMode.FAST, 'scene_stabilized')

    def _switch_mode(self, new_mode: TrackerMode, reason: str):
        """Execute a tracker mode switch."""
        old_mode = self.active_mode
        self.active_mode = new_mode
        self._mode_lock_until = time.time() + self._min_mode_duration

        event = {
            'timestamp': time.time(),
            'from': old_mode.value,
            'to': new_mode.value,
            'reason': reason,
            'frame': self._total_updates,
        }
        self._switch_events.append(event)

        # Keep only last 100 switch events
        if len(self._switch_events) > 100:
            self._switch_events = self._switch_events[-50:]

        logger.info(f"Tracker switch: {old_mode.value} → {new_mode.value} (reason: {reason})")

    def set_mode(self, mode: TrackerMode):
        """Manually set tracker mode (e.g., FORENSIC for batch analysis)."""
        self._switch_mode(mode, 'manual_override')

    def get_metrics(self) -> dict:
        """Return tracker performance metrics."""
        total = max(self._total_updates, 1)
        return {
            'active_mode': self.active_mode.value,
            'total_updates': self._total_updates,
            'total_tracks_output': self._total_tracks_output,
            'avg_tracks_per_frame': round(self._total_tracks_output / total, 1),
            'mode_distribution': {m.value: c for m, c in self._mode_counts.items()},
            'switch_events': len(self._switch_events),
            'recent_switches': self._switch_events[-5:],
            'botsort_available': self._botsort_available,
            'auto_switch': self.auto_switch,
        }

    def reset_metrics(self):
        """Reset performance counters."""
        self._total_updates = 0
        self._total_tracks_output = 0
        self._mode_counts = {m: 0 for m in TrackerMode}
        self._switch_events.clear()
