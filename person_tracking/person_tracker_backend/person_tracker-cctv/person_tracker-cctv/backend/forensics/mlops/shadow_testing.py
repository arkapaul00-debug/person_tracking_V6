"""
Shadow Testing & Canary Deployment Framework (Phases 86, 87)
Safely evaluates new candidate models against production data.
"""
import time
import logging
import threading
from typing import Dict, Any

logger = logging.getLogger(__name__)


class ShadowTestingFramework:
    """
    Routes a percentage of inference traffic to a shadow (candidate) model.
    Records metrics but does not affect the production output stream.
    """

    def __init__(self, lifecycle_manager=None):
        self._lifecycle = lifecycle_manager
        self._lock = threading.Lock()
        
        # Traffic routing config
        self._shadow_config: Dict[str, Dict] = {} # task -> {shadow_model_id, percentage}
        
        # Results comparison
        self._shadow_metrics = {
            "shadow_inferences_run": 0,
            "discrepancies_flagged": 0
        }
        
        logger.info("ShadowTestingFramework initialized")

    def start_shadow_test(self, task: str, shadow_model_id: str, traffic_percentage: int = 10):
        """Route X% of traffic to the shadow model."""
        with self._lock:
            self._shadow_config[task] = {
                "shadow_model_id": shadow_model_id,
                "percentage": traffic_percentage,
                "started_at": time.time()
            }
            if self._lifecycle and self._lifecycle._models.get(shadow_model_id):
                self._lifecycle._models[shadow_model_id]["status"] = "SHADOW"
        logger.info(f"Started SHADOW test for {task} using {shadow_model_id} ({traffic_percentage}% traffic)")

    def should_run_shadow(self, task: str) -> bool:
        """Determines if a given inference should also trigger the shadow model."""
        # Simplified statistical router based on timestamp modulo
        config = self._shadow_config.get(task)
        if not config:
            return False
            
        pct = config["percentage"]
        # If pct=10, run if current time milliseconds ends in 0
        return int(time.time() * 1000) % 100 < pct

    def record_shadow_result(self, task: str, prod_output: Any, shadow_output: Any, discrepancy: bool):
        """Records the results of a shadow inference."""
        with self._lock:
            self._shadow_metrics["shadow_inferences_run"] += 1
            if discrepancy:
                self._shadow_metrics["discrepancies_flagged"] += 1
                logger.debug(f"Shadow test discrepancy flagged for {task}")

    def promote_if_successful(self, task: str, discrepancy_threshold: float = 0.05) -> bool:
        """
        Phase 87 Canary auto-promotion: If discrepancies are below threshold, promote to production.
        """
        config = self._shadow_config.get(task)
        if not config or not self._lifecycle:
            return False
            
        runs = self._shadow_metrics["shadow_inferences_run"]
        errors = self._shadow_metrics["discrepancies_flagged"]
        
        if runs < 100:
            logger.warning(f"Not enough shadow runs to promote {task} (need 100, have {runs})")
            return False
            
        error_rate = errors / runs
        if error_rate <= discrepancy_threshold:
            logger.info(f"Shadow test passed (Error rate: {error_rate:.2%}). Auto-promoting canary.")
            self._lifecycle.promote_to_production(config["shadow_model_id"])
            with self._lock:
                del self._shadow_config[task]
            return True
        else:
            logger.critical(f"Shadow test FAILED (Error rate: {error_rate:.2%}). Aborting canary.")
            return False

    def get_metrics(self) -> dict:
        with self._lock:
            return dict(self._shadow_metrics)
