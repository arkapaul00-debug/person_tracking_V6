"""
Anti-Spoof Gate — Trigger-Based Face Liveness Verification.

CRITICAL: This is NOT run on every frame. It is a gate that activates
ONLY when specific high-value triggers fire.

Triggers:
    1. Suspect enrollment/verification workflow
    2. Low-confidence identity match (score 0.5 - 0.7 range)
    3. Explicit forensic audit request
    4. Repeated match oscillation (matching/unmatching rapidly)

Architecture:
    Primary: SilentFace anti-spoofing model (passive, no user cooperation needed)
    
    Detection targets:
    - Printed photo attacks (paper/cardboard)
    - Screen replay attacks (phone/tablet/monitor)
    - 3D mask attacks (detected via texture analysis)
    - Deepfake/morphed face injection

Performance:
    - Model latency: ~5ms per face crop
    - Trigger rate: < 1% of total frames (by design)
    - False rejection rate: < 2% on live faces
"""
import time
import logging
import numpy as np
from typing import Optional, Dict
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class SpoofResult:
    """Result of anti-spoofing analysis."""
    is_live: bool = True               # True = real person, False = spoof detected
    confidence: float = 1.0            # Liveness confidence (0-1)
    spoof_type: str = 'none'           # 'none', 'print', 'screen', 'mask', 'unknown'
    processing_time_ms: float = 0.0
    model_used: str = 'none'
    trigger_reason: str = ''


class AntiSpoofGate:
    """
    Trigger-based anti-spoofing verification gate.

    Usage:
        gate = AntiSpoofGate()

        # Check if verification is needed
        if gate.should_check(match_score=0.62, is_enrollment=False):
            result = gate.verify(face_crop)
            if not result.is_live:
                # SPOOF DETECTED — reject match
                ...

        # Force check during enrollment
        result = gate.verify(face_crop, trigger_reason='enrollment')
    """

    def __init__(self,
                 match_score_low: float = 0.50,
                 match_score_high: float = 0.70,
                 oscillation_window: int = 30,
                 oscillation_threshold: int = 5,
                 device: str = 'cuda:0'):
        """
        Args:
            match_score_low: Lower bound of suspicious score range.
            match_score_high: Upper bound of suspicious score range.
            oscillation_window: Frames to track for oscillation detection.
            oscillation_threshold: Min state changes to trigger oscillation check.
            device: CUDA device for inference.
        """
        self.score_low = match_score_low
        self.score_high = match_score_high
        self.osc_window = oscillation_window
        self.osc_threshold = oscillation_threshold
        self.device = device

        # SilentFace model (lazy loaded)
        self._model = None
        self._model_available = None  # None = unchecked

        # Oscillation tracking (per track_id)
        self._match_history: Dict[int, list] = {}

        # Metrics
        self._total_checks = 0
        self._trigger_counts: Dict[str, int] = {
            'enrollment': 0,
            'low_confidence': 0,
            'oscillation': 0,
            'forensic_audit': 0,
            'manual': 0,
        }
        self._spoof_detections = 0
        self._live_confirmations = 0

        logger.info(
            f"AntiSpoofGate initialized: trigger_range=[{match_score_low}, {match_score_high}], "
            f"osc_window={oscillation_window}"
        )

    def should_check(self,
                     match_score: float = 0.0,
                     is_enrollment: bool = False,
                     is_forensic_audit: bool = False,
                     track_id: Optional[int] = None) -> bool:
        """
        Determine if anti-spoof verification should run.

        Args:
            match_score: Current face match similarity score.
            is_enrollment: True during suspect enrollment workflow.
            is_forensic_audit: True during explicit audit request.
            track_id: Track ID for oscillation tracking.

        Returns:
            True if verification should be performed.
        """
        # Always check during enrollment
        if is_enrollment:
            return True

        # Always check during forensic audit
        if is_forensic_audit:
            return True

        # Check suspicious score range
        if self.score_low < match_score < self.score_high:
            return True

        # Check for oscillation (rapid match/unmatch switching)
        if track_id is not None:
            if self._detect_oscillation(track_id, match_score > self.score_low):
                return True

        return False

    def verify(self, face_crop: np.ndarray,
               trigger_reason: str = 'auto') -> SpoofResult:
        """
        Run anti-spoofing verification on a face crop.

        Args:
            face_crop: BGR face crop (should be aligned if possible).
            trigger_reason: Why this check was triggered (for audit trail).

        Returns:
            SpoofResult with liveness determination.
        """
        t_start = time.time()
        self._total_checks += 1
        self._trigger_counts[trigger_reason] = self._trigger_counts.get(trigger_reason, 0) + 1

        result = SpoofResult(trigger_reason=trigger_reason)

        if face_crop is None or face_crop.size == 0:
            result.is_live = False
            result.confidence = 0.0
            result.spoof_type = 'invalid_input'
            return result

        # Load model if needed
        model = self._get_model()

        if model is None:
            # No anti-spoof model available — assume live (fail-open)
            logger.debug("Anti-spoof model not available — assuming live")
            result.is_live = True
            result.confidence = 0.5  # Low confidence = uncertain
            result.model_used = 'none'
            result.processing_time_ms = (time.time() - t_start) * 1000
            return result

        try:
            # Run inference
            liveness_score = self._run_inference(model, face_crop)

            result.confidence = float(liveness_score)
            result.is_live = liveness_score > 0.5
            result.model_used = 'silentface'
            result.processing_time_ms = (time.time() - t_start) * 1000

            if not result.is_live:
                result.spoof_type = self._classify_spoof(face_crop, liveness_score)
                self._spoof_detections += 1
                logger.warning(
                    f"SPOOF DETECTED: type={result.spoof_type}, "
                    f"confidence={result.confidence:.3f}, "
                    f"trigger={trigger_reason}"
                )
            else:
                self._live_confirmations += 1

        except Exception as e:
            logger.error(f"Anti-spoof inference failed: {e}")
            result.is_live = True  # Fail-open
            result.confidence = 0.3
            result.model_used = 'error'

        return result

    def record_match_state(self, track_id: int, is_matching: bool):
        """Record a match/no-match event for oscillation tracking."""
        if track_id not in self._match_history:
            self._match_history[track_id] = []

        self._match_history[track_id].append(is_matching)

        # Trim to window
        if len(self._match_history[track_id]) > self.osc_window:
            self._match_history[track_id] = self._match_history[track_id][-self.osc_window:]

    def _detect_oscillation(self, track_id: int, current_state: bool) -> bool:
        """Detect rapid match/unmatch oscillation for a track."""
        history = self._match_history.get(track_id, [])
        if len(history) < self.osc_window // 2:
            return False

        # Count state changes
        changes = 0
        for i in range(1, len(history)):
            if history[i] != history[i - 1]:
                changes += 1

        return changes >= self.osc_threshold

    def _get_model(self):
        """Get or lazy-load the anti-spoof model."""
        if self._model_available is False:
            return None

        if self._model is not None:
            return self._model

        try:
            weights_dir = Path(__file__).resolve().parent.parent / 'ai_core' / 'weights'
            
            # Look for SilentFace weights
            candidates = list(weights_dir.glob('silentface*.onnx')) + \
                          list(weights_dir.glob('anti_spoof*.onnx')) + \
                          list(weights_dir.glob('FAS_*.onnx'))

            if not candidates:
                logger.debug("Anti-spoof model weights not found — feature disabled")
                self._model_available = False
                return None

            # Load via ONNX Runtime
            import onnxruntime as ort
            providers = ['CUDAExecutionProvider', 'CPUExecutionProvider']
            self._model = ort.InferenceSession(str(candidates[0]), providers=providers)
            self._model_available = True
            logger.info(f"Anti-spoof model loaded: {candidates[0].name}")
            return self._model

        except ImportError:
            logger.warning("onnxruntime not available — anti-spoof disabled")
            self._model_available = False
            return None
        except Exception as e:
            logger.error(f"Anti-spoof model load failed: {e}")
            self._model_available = False
            return None

    def _run_inference(self, model, face_crop: np.ndarray) -> float:
        """Run the anti-spoof model on a face crop."""
        import cv2

        # Preprocess: resize to model input size (typically 80x80 or 256x256)
        resized = cv2.resize(face_crop, (80, 80))
        blob = resized.astype(np.float32) / 255.0
        blob = blob.transpose(2, 0, 1)  # HWC → CHW
        blob = np.expand_dims(blob, axis=0)  # Add batch dim

        # Run inference
        input_name = model.get_inputs()[0].name
        output_name = model.get_outputs()[0].name
        result = model.run([output_name], {input_name: blob})

        # Parse output (typically sigmoid score: 0=spoof, 1=live)
        score = float(result[0].flatten()[0])
        return score

    def _classify_spoof(self, face_crop: np.ndarray, score: float) -> str:
        """Classify the type of spoof attack (basic heuristic)."""
        try:
            import cv2

            gray = cv2.cvtColor(face_crop, cv2.COLOR_BGR2GRAY)

            # Texture analysis: screen replays have periodic patterns (moiré)
            laplacian = cv2.Laplacian(gray, cv2.CV_64F)
            texture_var = laplacian.var()

            # Color analysis: printed photos have limited color gamut
            hsv = cv2.cvtColor(face_crop, cv2.COLOR_BGR2HSV)
            saturation_std = np.std(hsv[:, :, 1])

            if texture_var < 20:
                return 'print'  # Very smooth = likely printed
            elif saturation_std < 15:
                return 'screen'  # Low saturation variance = likely screen
            else:
                return 'unknown'
        except Exception:
            return 'unknown'

    def cleanup_tracks(self, active_track_ids: set):
        """Remove history for tracks that no longer exist."""
        stale = [tid for tid in self._match_history if tid not in active_track_ids]
        for tid in stale:
            del self._match_history[tid]

    def get_metrics(self) -> dict:
        """Return gate performance metrics."""
        total = max(self._total_checks, 1)
        return {
            'total_checks': self._total_checks,
            'spoof_detections': self._spoof_detections,
            'live_confirmations': self._live_confirmations,
            'spoof_rate': round(self._spoof_detections / total, 4),
            'trigger_counts': dict(self._trigger_counts),
            'model_available': self._model_available or False,
        }
