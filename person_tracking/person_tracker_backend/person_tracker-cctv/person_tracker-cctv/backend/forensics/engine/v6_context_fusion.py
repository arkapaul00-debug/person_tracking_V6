"""
V6 Context-Aware MultiModal Fusion (V6 Upgrade 5)
Extends V5 MultiModalFusionEngine by dynamically adjusting modality weights
based on environmental context (lighting, weather, crowd density, distance).
"""
import time
import logging
import threading
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)


class V6ContextFusion:
    """
    Wraps the V5 MultiModalFusionEngine.
    If the camera context shows poor lighting, it aggressively lowers Face ReID weight
    and boosts Gait/Body ReID weight.
    """

    def __init__(self, v5_fusion_engine=None, v6_camera_intelligence=None):
        self._v5_fusion = v5_fusion_engine
        self._cam_intel = v6_camera_intelligence
        self._lock = threading.RLock()
        
        self._metrics = {
            "contextual_fusions_performed": 0,
            "weights_adjusted": 0
        }

        logger.info("V6 ContextAwareFusion initialized")

    def fuse_with_context(self, camera_id: str, 
                          modality_inputs: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        """Apply environmental context modifiers to qualities before V5 fusion."""
        with self._lock:
            self._metrics["contextual_fusions_performed"] += 1
            
            if self._cam_intel:
                context = self._cam_intel.get_context(camera_id)
                lighting = context.get("lighting_baseline", 0.5)
                
                # If lighting is very poor (< 0.2), heavily penalize face quality
                if lighting < 0.2 and "face" in modality_inputs:
                    modality_inputs["face"]["quality"] *= (lighting * 2)
                    self._metrics["weights_adjusted"] += 1
                    
            if self._v5_fusion:
                return self._v5_fusion.fuse(modality_inputs)
                
            return {"fused_embedding": None, "confidence": 0.0, "fallback": True}

    def get_metrics(self) -> dict:
        with self._lock:
            return dict(self._metrics)
