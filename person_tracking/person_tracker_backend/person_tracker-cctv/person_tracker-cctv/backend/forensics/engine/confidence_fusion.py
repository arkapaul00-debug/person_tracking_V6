"""
Confidence Fusion Engine — Quality-Aware Multi-Modal Score Fusion.

Replaces the fixed-weight fusion (current: 0.7 face + 0.3 body) with
dynamic per-frame quality-weighted fusion that adapts to each detection's
actual signal quality.

Key Insight: A blurry face score of 0.6 is LESS reliable than a
sharp body score of 0.5. Fixed weights cannot capture this.

Architecture:
    1. Quality Assessment: score each modality's input quality
    2. Weight Computation: derive per-frame weights from quality signals
    3. Fusion: weighted combination with temporal smoothing
    4. Confidence Calibration: map raw scores to calibrated probabilities

Backward Compatible: when no quality context is available, falls back
to the original 0.7/0.3 face/body weights.
"""
import time
import logging
import numpy as np
from typing import Dict, Optional, Tuple, List
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class QualityContext:
    """Per-frame quality signals for each modality."""
    # Face quality (0.0 - 1.0, higher = better)
    face_quality: float = 0.5
    face_pose_score: float = 0.5    # 1.0 = frontal, 0.0 = profile
    face_blur_score: float = 0.5    # 1.0 = sharp, 0.0 = very blurry
    face_illumination: float = 0.5  # 1.0 = well-lit, 0.0 = dark/overexposed
    face_occlusion: float = 0.0     # 0.0 = no occlusion, 1.0 = fully occluded
    face_size_px: int = 0           # Face width in pixels

    # Body quality (0.0 - 1.0)
    body_quality: float = 0.5
    body_completeness: float = 1.0  # 1.0 = full body, 0.5 = half body
    body_resolution: float = 0.5    # Normalized crop resolution
    body_blur_score: float = 0.5

    # Gait quality (0.0 - 1.0, only when gait is available)
    gait_quality: float = 0.0
    gait_sequence_length: int = 0   # Number of gait frames captured

    # Scene-level
    is_low_light: bool = False
    is_crowded: bool = False
    detection_confidence: float = 0.5


@dataclass
class FusedResult:
    """Output of the confidence fusion engine."""
    fused_score: float              # Final fused similarity score (0.0 - 1.0)
    calibrated_score: float         # Calibrated probability of identity match
    face_score: float = 0.0
    body_score: float = 0.0
    gait_score: float = 0.0
    weights: Dict[str, float] = field(default_factory=dict)  # Applied weights
    quality: Dict[str, float] = field(default_factory=dict)  # Quality signals
    dominant_modality: str = ''     # Which modality contributed most
    confidence_level: str = ''     # 'high', 'medium', 'low', 'unreliable'


class ConfidenceFusionEngine:
    """
    Quality-aware multi-modal score fusion.

    Usage:
        engine = ConfidenceFusionEngine()

        # With quality context (V2: adaptive weights)
        result = engine.fuse(
            face_score=0.72,
            body_score=0.55,
            quality=QualityContext(face_quality=0.9, body_quality=0.4)
        )

        # Without quality context (V1 backward-compatible: fixed weights)
        result = engine.fuse(face_score=0.72, body_score=0.55)
    """

    def __init__(self,
                 default_face_weight: float = 0.70,
                 default_body_weight: float = 0.30,
                 min_face_weight: float = 0.10,
                 max_face_weight: float = 0.90,
                 temporal_smoothing: float = 0.3,
                 calibration_enabled: bool = True):
        """
        Args:
            default_face_weight: Default face weight (backward compatible).
            default_body_weight: Default body weight (backward compatible).
            min_face_weight: Minimum face weight even with terrible quality.
            max_face_weight: Maximum face weight even with perfect quality.
            temporal_smoothing: EMA alpha for score smoothing across frames.
            calibration_enabled: Apply score calibration mapping.
        """
        self.default_face_w = default_face_weight
        self.default_body_w = default_body_weight
        self.min_face_w = min_face_weight
        self.max_face_w = max_face_weight
        self.temporal_alpha = temporal_smoothing
        self.calibration_enabled = calibration_enabled

        # Temporal smoothing state (per track_id)
        self._track_history: Dict[int, List[float]] = {}
        self._track_window = 10  # Keep last N scores for smoothing

        # Metrics
        self._total_fusions = 0
        self._quality_weighted_fusions = 0
        self._fallback_fusions = 0

        logger.info(
            f"ConfidenceFusionEngine: default_weights=({default_face_weight}/{default_body_weight}), "
            f"temporal_alpha={temporal_smoothing}"
        )

    def fuse(self,
             face_score: float = 0.0,
             body_score: float = 0.0,
             gait_score: float = 0.0,
             quality: Optional[QualityContext] = None,
             track_id: Optional[int] = None,
             mode: str = 'hybrid') -> FusedResult:
        """
        Compute fused similarity score.

        Args:
            face_score: Face similarity (0.0 - 1.0).
            body_score: Body similarity (0.0 - 1.0).
            gait_score: Gait similarity (0.0 - 1.0), optional.
            quality: Per-frame quality context for adaptive weighting.
            track_id: Track ID for temporal smoothing.
            mode: 'face', 'body', 'hybrid', or 'auto'.

        Returns:
            FusedResult with scores and diagnostics.
        """
        self._total_fusions += 1

        result = FusedResult(
            fused_score=0.0,
            calibrated_score=0.0,
            face_score=face_score,
            body_score=body_score,
            gait_score=gait_score,
        )

        # --- Single-modality modes ---
        if mode == 'face':
            result.fused_score = face_score
            result.weights = {'face': 1.0, 'body': 0.0}
            result.dominant_modality = 'face'
        elif mode == 'body':
            result.fused_score = body_score
            result.weights = {'face': 0.0, 'body': 1.0}
            result.dominant_modality = 'body'
        else:
            # --- Hybrid fusion ---
            weights = self._compute_weights(face_score, body_score, gait_score, quality)
            result.weights = weights

            result.fused_score = (
                face_score * weights.get('face', 0.0) +
                body_score * weights.get('body', 0.0) +
                gait_score * weights.get('gait', 0.0)
            )

            # Determine dominant modality
            if weights.get('face', 0) >= weights.get('body', 0):
                result.dominant_modality = 'face'
            else:
                result.dominant_modality = 'body'

        # --- Temporal smoothing ---
        if track_id is not None:
            result.fused_score = self._apply_temporal_smoothing(
                track_id, result.fused_score
            )

        # --- Calibration ---
        if self.calibration_enabled:
            result.calibrated_score = self._calibrate(result.fused_score)
        else:
            result.calibrated_score = result.fused_score

        # --- Confidence level ---
        result.confidence_level = self._classify_confidence(result)

        # --- Quality diagnostics ---
        if quality:
            result.quality = {
                'face_quality': quality.face_quality,
                'body_quality': quality.body_quality,
                'face_pose': quality.face_pose_score,
                'is_low_light': quality.is_low_light,
            }

        return result

    def _compute_weights(self,
                         face_score: float,
                         body_score: float,
                         gait_score: float,
                         quality: Optional[QualityContext]) -> Dict[str, float]:
        """
        Compute adaptive weights based on quality context.

        Falls back to default fixed weights when no quality info is available.
        """
        if quality is None:
            # --- Backward compatible: fixed weights ---
            self._fallback_fusions += 1
            if face_score > 0:
                return {'face': self.default_face_w, 'body': self.default_body_w}
            else:
                return {'face': 0.0, 'body': 1.0}

        self._quality_weighted_fusions += 1

        # --- Quality-aware dynamic weights ---
        # Start with quality-scaled base weights
        face_w = self.default_face_w * quality.face_quality
        body_w = self.default_body_w * quality.body_quality

        # Boost face weight for frontal poses with good illumination
        if quality.face_pose_score > 0.8 and quality.face_illumination > 0.6:
            face_w *= 1.3

        # Penalize face weight for occluded or very small faces
        if quality.face_occlusion > 0.3:
            face_w *= (1.0 - quality.face_occlusion)
        if quality.face_size_px > 0 and quality.face_size_px < 20:
            face_w *= 0.5  # Very small face = unreliable

        # Boost body weight when face is unavailable/poor
        if face_score == 0.0 or quality.face_quality < 0.2:
            body_w = max(body_w, 0.8)
            face_w = min(face_w, 0.2)

        # Add gait weight if available
        gait_w = 0.0
        if gait_score > 0 and quality.gait_quality > 0.3:
            gait_w = 0.15 * quality.gait_quality
            # Redistribute from body (gait is body-related)
            body_w *= 0.8

        # Clamp face weight
        face_w = np.clip(face_w, self.min_face_w, self.max_face_w)

        # Normalize to sum to 1.0
        total = face_w + body_w + gait_w
        if total > 0:
            face_w /= total
            body_w /= total
            gait_w /= total
        else:
            face_w = self.default_face_w
            body_w = self.default_body_w

        return {'face': float(face_w), 'body': float(body_w), 'gait': float(gait_w)}

    def _apply_temporal_smoothing(self, track_id: int, score: float) -> float:
        """
        Apply exponential moving average across frames for the same track.

        Prevents single-frame score spikes/drops from causing flickering.
        """
        if track_id not in self._track_history:
            self._track_history[track_id] = []

        history = self._track_history[track_id]
        history.append(score)

        # Trim to window
        if len(history) > self._track_window:
            self._track_history[track_id] = history[-self._track_window:]
            history = self._track_history[track_id]

        if len(history) == 1:
            return score

        # EMA: smoothed = alpha * current + (1-alpha) * previous_smoothed
        smoothed = history[0]
        for s in history[1:]:
            smoothed = self.temporal_alpha * s + (1.0 - self.temporal_alpha) * smoothed

        return smoothed

    def _calibrate(self, raw_score: float) -> float:
        """
        Map raw similarity scores to calibrated match probabilities.

        Raw cosine similarity doesn't map linearly to match probability.
        This applies a learned sigmoid calibration.
        """
        # Sigmoid calibration: P(match) = 1 / (1 + exp(-k * (score - midpoint)))
        # Parameters tuned for face+body ReID on surveillance data
        k = 12.0       # Steepness
        midpoint = 0.55  # Score at which P(match) = 0.5

        import math
        try:
            calibrated = 1.0 / (1.0 + math.exp(-k * (raw_score - midpoint)))
            return calibrated
        except OverflowError:
            return 1.0 if raw_score > midpoint else 0.0

    def _classify_confidence(self, result: FusedResult) -> str:
        """Classify the overall confidence level of the match."""
        score = result.calibrated_score

        if score > 0.85:
            return 'high'
        elif score > 0.65:
            return 'medium'
        elif score > 0.45:
            return 'low'
        else:
            return 'unreliable'

    def cleanup_tracks(self, active_track_ids: set):
        """Remove history for tracks that no longer exist."""
        stale = [tid for tid in self._track_history if tid not in active_track_ids]
        for tid in stale:
            del self._track_history[tid]

    def get_metrics(self) -> dict:
        """Return fusion engine metrics."""
        total = max(self._total_fusions, 1)
        return {
            'total_fusions': self._total_fusions,
            'quality_weighted': self._quality_weighted_fusions,
            'fallback_fixed': self._fallback_fusions,
            'quality_weighted_ratio': round(self._quality_weighted_fusions / total, 3),
            'active_tracks_smoothing': len(self._track_history),
        }
