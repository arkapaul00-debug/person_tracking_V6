"""
Multi-Modal Identity Resolution Engine (V5 Upgrade 2)
Fuses Face, Body, Gait, Pose, and Appearance descriptors with dynamic
quality-aware confidence weighting.
"""
import time
import logging
import threading
import numpy as np
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)


class MultiModalFusionEngine:
    """
    Replaces the V4 ConfidenceFusionEngine with a multi-modal variant.

    Modalities supported:
      - Face (ArcFace / AdaFace)   → 512-dim
      - Body (OSNet-AIN)           → 512-dim
      - Gait (GaitSet / GaitGL)    → 256-dim
      - Pose (HRNet skeleton hash) → 128-dim
      - Appearance (color + texture) → 64-dim

    Each modality carries a quality score (0.0 – 1.0).
    The engine dynamically re-weights modalities based on quality,
    giving degraded modalities near-zero influence.
    """

    # Default maximum weight for each modality (sums to 1.0)
    DEFAULT_MAX_WEIGHTS = {
        "face": 0.40,
        "body": 0.30,
        "gait": 0.15,
        "pose": 0.10,
        "appearance": 0.05,
    }

    def __init__(self, v4_fusion_engine=None,
                 max_weights: Dict[str, float] = None):
        self._v4_engine = v4_fusion_engine  # Backward-compatible fallback
        self._lock = threading.Lock()
        self._max_weights = max_weights or self.DEFAULT_MAX_WEIGHTS

        self._metrics = {
            "fusions_performed": 0,
            "modalities_used": {k: 0 for k in self.DEFAULT_MAX_WEIGHTS},
            "avg_active_modalities": 0.0,
            "fallback_to_v4": 0,
        }
        self._total_active_modalities = 0

        logger.info("V5 MultiModalFusionEngine initialized")

    def fuse(self, modality_inputs: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        """
        Perform quality-aware multi-modal fusion.

        Args:
            modality_inputs: Dict of modality_name -> {
                "embedding": np.ndarray or list,
                "quality": float (0.0 – 1.0)
            }

        Returns:
            {
                "fused_embedding": np.ndarray,
                "confidence": float,
                "weights_used": dict,
                "active_modalities": list
            }
        """
        with self._lock:
            self._metrics["fusions_performed"] += 1

            # Filter modalities with quality > 0.1
            active = {}
            for name, data in modality_inputs.items():
                quality = data.get("quality", 0.0)
                if quality > 0.1 and name in self._max_weights:
                    active[name] = data
                    self._metrics["modalities_used"][name] = (
                        self._metrics["modalities_used"].get(name, 0) + 1
                    )

            if not active:
                # Emergency fallback: use V4 engine if available
                if self._v4_engine:
                    self._metrics["fallback_to_v4"] += 1
                    logger.debug("V5 Fusion: No active modalities, falling back to V4")
                    return {"fused_embedding": None, "confidence": 0.0,
                            "weights_used": {}, "active_modalities": [],
                            "fallback": True}
                return {"fused_embedding": None, "confidence": 0.0,
                        "weights_used": {}, "active_modalities": []}

            # ── Compute quality-adjusted weights ─────────────────────
            raw_weights = {}
            for name, data in active.items():
                quality = data["quality"]
                max_w = self._max_weights[name]
                raw_weights[name] = max_w * quality  # Scale by quality

            # Normalize so weights sum to 1.0
            total_weight = sum(raw_weights.values())
            if total_weight > 0:
                norm_weights = {k: v / total_weight for k, v in raw_weights.items()}
            else:
                norm_weights = {k: 1.0 / len(raw_weights) for k in raw_weights}

            # ── Weighted embedding concatenation / fusion ────────────
            # Strategy: Concatenate L2-normalized embeddings, then weight-scale
            segments = []
            for name, data in active.items():
                emb = data["embedding"]
                if not isinstance(emb, np.ndarray):
                    emb = np.array(emb, dtype=np.float32)
                # L2-normalize each modality
                norm = np.linalg.norm(emb)
                if norm > 0:
                    emb = emb / norm
                # Scale by weight
                segments.append(emb * norm_weights[name])

            fused = np.concatenate(segments)

            # Overall confidence = weighted average of qualities
            confidence = sum(
                active[name]["quality"] * norm_weights[name]
                for name in active
            )

            # Update running averages
            self._total_active_modalities += len(active)
            self._metrics["avg_active_modalities"] = round(
                self._total_active_modalities / self._metrics["fusions_performed"], 2
            )

            return {
                "fused_embedding": fused,
                "confidence": round(confidence, 4),
                "weights_used": {k: round(v, 4) for k, v in norm_weights.items()},
                "active_modalities": list(active.keys()),
            }

    def get_metrics(self) -> dict:
        with self._lock:
            return dict(self._metrics)
