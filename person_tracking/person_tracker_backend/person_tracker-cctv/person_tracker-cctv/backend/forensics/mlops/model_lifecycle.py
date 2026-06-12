"""
Model Lifecycle Management (Phase 85)
Full model lifecycle tracking: Registration, Versioning, Validation, Promotion, Rollback.
"""
import uuid
import time
import logging
import threading
from typing import Dict, List, Any

logger = logging.getLogger(__name__)


class ModelLifecycleManager:
    """
    Tracks AI model versions across the MLOps lifecycle from STAGING to PRODUCTION.
    """

    def __init__(self):
        self._models: Dict[str, Dict] = {}
        self._active_production: Dict[str, str] = {} # task -> model_id
        self._lock = threading.Lock()
        logger.info("ModelLifecycleManager initialized")

    def register_model(self, task: str, version: str, weights_path: str, metadata: dict = None) -> str:
        """Register a new model version (e.g., from an automated retraining pipeline)."""
        model_id = f"MOD-{uuid.uuid4().hex[:8].upper()}"
        with self._lock:
            self._models[model_id] = {
                "model_id": model_id,
                "task": task,
                "version": version,
                "weights_path": weights_path,
                "status": "STAGING",
                "registered_at": time.time(),
                "metadata": metadata or {},
                "validation_scores": {}
            }
        logger.info(f"Model {model_id} registered for task {task} (v{version})")
        return model_id

    def promote_to_production(self, model_id: str) -> bool:
        """Promote a model from STAGING/SHADOW to PRODUCTION."""
        with self._lock:
            if model_id not in self._models:
                return False
                
            task = self._models[model_id]["task"]
            
            # Retire the old production model
            old_id = self._active_production.get(task)
            if old_id and old_id in self._models:
                self._models[old_id]["status"] = "RETIRED"
                logger.info(f"Model {old_id} RETIRED for task {task}")
                
            # Promote the new one
            self._models[model_id]["status"] = "PRODUCTION"
            self._active_production[task] = model_id
            logger.info(f"Model {model_id} PROMOTED to PRODUCTION for task {task}")
            return True

    def rollback_model(self, task: str, previous_model_id: str) -> bool:
        """Rollback to a previously known good model."""
        with self._lock:
            if previous_model_id not in self._models:
                return False
                
            # Retire the current bad one
            curr_id = self._active_production.get(task)
            if curr_id and curr_id in self._models:
                self._models[curr_id]["status"] = "RETIRED (ROLLED BACK)"
                
            # Restore the old one
            self._models[previous_model_id]["status"] = "PRODUCTION"
            self._active_production[task] = previous_model_id
            logger.critical(f"ROLLED BACK {task} to Model {previous_model_id}")
            return True

    def get_production_model(self, task: str) -> Dict[str, Any]:
        """Fetch the active production model for a task."""
        with self._lock:
            mod_id = self._active_production.get(task)
            if mod_id:
                return self._models[mod_id]
            return {}

    def get_metrics(self) -> dict:
        with self._lock:
            status_counts = {"STAGING": 0, "PRODUCTION": 0, "SHADOW": 0, "RETIRED": 0}
            for m in self._models.values():
                s = m["status"]
                if s.startswith("RETIRED"):
                    status_counts["RETIRED"] += 1
                else:
                    status_counts[s] = status_counts.get(s, 0) + 1
                    
            return {
                "total_registered_models": len(self._models),
                "status_distribution": status_counts
            }
