"""
V6 Explainable Identity Resolution (V6 Upgrade 10)
Increases trust by generating an explainability payload for every match,
detailing confidence, modality contributions, and historical support.
"""
import time
import logging
import threading
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)


class V6ExplainableResolution:
    """
    Wraps the identity resolution process to output JSON artifacts explaining *why*
    the system believes two identities match.
    """

    def __init__(self, v5_fusion_engine=None):
        self._fusion = v5_fusion_engine
        self._lock = threading.RLock()
        
        self._metrics = {
            "explanations_generated": 0
        }

        logger.info("V6 ExplainableResolution initialized")

    def generate_explanation(self, match_score: float, 
                             active_modalities: List[str],
                             weights_used: Dict[str, float]) -> Dict[str, Any]:
        """Generate human-readable explanation for a match decision."""
        with self._lock:
            self._metrics["explanations_generated"] += 1
            
            top_factors = sorted(weights_used.items(), key=lambda x: x[1], reverse=True)
            
            explanation = {
                "match_confidence": round(match_score, 4),
                "decision_tier": "HIGH_CONFIDENCE" if match_score > 0.8 else "MEDIUM_CONFIDENCE",
                "active_modalities": active_modalities,
                "modality_contributions": weights_used,
                "top_contributing_factor": top_factors[0][0] if top_factors else "unknown",
                "human_summary": (
                    f"Match was driven primarily by {top_factors[0][0]} "
                    f"({top_factors[0][1]*100:.1f}% weight) with a total confidence of {match_score*100:.1f}%."
                ) if top_factors else "Insufficient modalities."
            }
            
            return explanation

    def get_metrics(self) -> dict:
        with self._lock:
            return dict(self._metrics)
