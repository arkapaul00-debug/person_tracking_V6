"""
Adaptive Temporal Stride FSM for forensic video processing.
3-mode state machine: Dense → Sparse → Reset, based on detection activity.

V2 Enhancements:
  - Motion-triggered acceleration (frame differencing → instant Dense switch)
  - GPU load awareness (widen stride when GPU is overloaded)
  - should_process() API for DAG pipeline integration

Integration: Replace fixed `skip_n=4` with `stride_mgr.get_skip_n()`.
"""
import logging
import numpy as np

logger = logging.getLogger(__name__)


class AdaptiveStrideFSM:
    """
    3-mode Finite State Machine for temporal stride control.
    
    Modes:
        DENSE  (skip=2-4):  Active tracking, persons detected recently
        SPARSE (skip=12-15): Empty scene, scanning for new detections
        RESET  (skip=1):     Scene cut detected, process every frame briefly
    
    Transitions:
        DENSE  → SPARSE:  No detections for `empty_patience` consecutive inference frames
        SPARSE → DENSE:   Any detection found OR significant motion detected
        RESET  → DENSE:   After `reset_duration` frames
        Any    → RESET:   Scene cut detected
    """
    
    MODE_DENSE = 'DENSE'
    MODE_SPARSE = 'SPARSE'
    MODE_RESET = 'RESET'
    
    def __init__(self,
                 dense_skip: int = 4,
                 sparse_skip: int = 12,
                 reset_skip: int = 1,
                 empty_patience: int = 8,      # inference frames without detections before going sparse
                 reset_duration: int = 10,      # frames to stay in reset mode after scene cut
                 min_dwell_frames: int = 30,    # min frames in any mode before switching (hysteresis)
                 scene_cut_threshold: float = 0.65,  # histogram diff threshold for scene cut
                 motion_threshold: float = 15.0,     # V2: pixel diff threshold for motion trigger
                 gpu_overload_skip: int = 20):        # V2: stride when GPU is overloaded
        
        self.dense_skip = dense_skip
        self.sparse_skip = sparse_skip
        self.reset_skip = reset_skip
        self.empty_patience = empty_patience
        self.reset_duration = reset_duration
        self.min_dwell_frames = min_dwell_frames
        self.scene_cut_threshold = scene_cut_threshold
        self.motion_threshold = motion_threshold
        self.gpu_overload_skip = gpu_overload_skip
        
        # State
        self.mode = self.MODE_DENSE
        self.frames_in_mode = 0
        self.empty_streak = 0  # consecutive inference frames with 0 detections
        self.last_histogram = None
        self.reset_counter = 0
        
        # V2: Motion detection state
        self._last_gray_small = None
        self._motion_score = 0.0
        
        # V2: GPU load override
        self._gpu_overloaded = False
        
        # V2: Frame counter for should_process()
        self._total_frames = 0
        
        # Stats
        self.mode_history = {self.MODE_DENSE: 0, self.MODE_SPARSE: 0, self.MODE_RESET: 0}
        self._motion_triggers = 0
    
    def get_skip_n(self) -> int:
        """Return current temporal stride based on FSM mode."""
        # V2: GPU overload override
        if self._gpu_overloaded:
            return self.gpu_overload_skip
        
        if self.mode == self.MODE_DENSE:
            return self.dense_skip
        elif self.mode == self.MODE_SPARSE:
            return self.sparse_skip
        else:  # RESET
            return self.reset_skip
    
    def should_process(self, frame_id: int) -> bool:
        """
        V2: DAG pipeline API — check if this frame should be processed.
        
        Args:
            frame_id: Monotonic frame counter.
            
        Returns:
            True if inference should run on this frame.
        """
        skip = self.get_skip_n()
        return (frame_id % skip == 0) or (frame_id == 1)
    
    def update(self, num_detections: int, frame: np.ndarray = None):
        """
        Call after each inference frame with the number of YOLO detections.
        Optionally pass the frame for scene-cut and motion detection.
        
        Args:
            num_detections: Number of person detections from YOLO on this frame
            frame: BGR frame for scene-cut histogram check (optional)
        """
        self.frames_in_mode += 1
        self._total_frames += 1
        self.mode_history[self.mode] += 1
        
        # Scene cut detection (if frame provided)
        if frame is not None and self._detect_scene_cut(frame):
            self._transition(self.MODE_RESET, reason="Scene cut detected")
            self.reset_counter = 0
            return
        
        # V2: Motion-triggered acceleration (only in SPARSE mode)
        if self.mode == self.MODE_SPARSE and frame is not None:
            if self._detect_motion(frame):
                self._transition(self.MODE_DENSE, reason="Motion detected in sparse mode")
                self._motion_triggers += 1
                self.empty_streak = 0
                return
        
        # State transitions
        if self.mode == self.MODE_RESET:
            self.reset_counter += 1
            if self.reset_counter >= self.reset_duration:
                self._transition(self.MODE_DENSE, reason="Reset complete")
            return
        
        if self.mode == self.MODE_DENSE:
            if num_detections == 0:
                self.empty_streak += 1
                if self.empty_streak >= self.empty_patience and self.frames_in_mode >= self.min_dwell_frames:
                    self._transition(self.MODE_SPARSE, reason=f"No detections for {self.empty_streak} inference frames")
            else:
                self.empty_streak = 0
        
        elif self.mode == self.MODE_SPARSE:
            if num_detections > 0:
                self._transition(self.MODE_DENSE, reason=f"Detection found ({num_detections} persons)")
                self.empty_streak = 0
    
    def set_gpu_overload(self, overloaded: bool):
        """
        V2: Set GPU overload flag to widen stride.
        Called by GPUMonitor when utilization exceeds threshold.
        """
        if overloaded != self._gpu_overloaded:
            self._gpu_overloaded = overloaded
            if overloaded:
                logger.warning("Stride FSM: GPU overload → widening stride")
            else:
                logger.info("Stride FSM: GPU load normal → restoring stride")
    
    def _transition(self, new_mode: str, reason: str = ""):
        """Transition to a new mode."""
        if new_mode != self.mode:
            old_mode = self.mode
            self.mode = new_mode
            self.frames_in_mode = 0
            logger.info(f"Stride FSM: {old_mode} → {new_mode} (skip={self.get_skip_n()}) | {reason}")
    
    def _detect_scene_cut(self, frame: np.ndarray) -> bool:
        """Detect scene cuts via grayscale histogram correlation."""
        try:
            gray = frame[:, :, 0] if frame.ndim == 3 else frame  # Use blue channel (fast)
            # Downsample for speed
            small = gray[::8, ::8]
            hist = np.histogram(small, bins=64, range=(0, 256))[0].astype(np.float32)
            hist /= hist.sum() + 1e-6
            
            if self.last_histogram is not None:
                # Correlation coefficient
                corr = np.corrcoef(hist, self.last_histogram)[0, 1]
                self.last_histogram = hist
                
                if corr < self.scene_cut_threshold:
                    return True
            else:
                self.last_histogram = hist
            
            return False
        except Exception:
            return False
    
    def _detect_motion(self, frame: np.ndarray) -> bool:
        """
        V2: Detect significant motion via frame differencing.
        Used to trigger Dense mode from Sparse when movement occurs.
        """
        try:
            gray = frame[:, :, 0] if frame.ndim == 3 else frame
            small = gray[::16, ::16].astype(np.float32)  # Heavy downsampling for speed
            
            if self._last_gray_small is not None:
                diff = np.abs(small - self._last_gray_small)
                self._motion_score = float(np.mean(diff))
                self._last_gray_small = small
                return self._motion_score > self.motion_threshold
            else:
                self._last_gray_small = small
                return False
        except Exception:
            return False
    
    def get_stats(self) -> dict:
        """Return FSM statistics for logging."""
        total = sum(self.mode_history.values()) or 1
        return {
            'current_mode': self.mode,
            'current_skip': self.get_skip_n(),
            'dense_pct': f"{self.mode_history[self.MODE_DENSE] / total * 100:.1f}%",
            'sparse_pct': f"{self.mode_history[self.MODE_SPARSE] / total * 100:.1f}%",
            'reset_pct': f"{self.mode_history[self.MODE_RESET] / total * 100:.1f}%",
            'motion_triggers': self._motion_triggers,
            'motion_score': round(self._motion_score, 1),
            'gpu_overloaded': self._gpu_overloaded,
        }

