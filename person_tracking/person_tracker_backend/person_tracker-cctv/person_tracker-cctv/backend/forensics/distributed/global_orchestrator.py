"""
Global Execution Orchestrator
Replaces local CCTVOrchestrator to allow multi-node distributed processing.
Routes tasks to specific Celery queues based on priority.
"""
import logging
from typing import List, Dict
from ..tasks import run_forensic_pipeline_task
from .service_registry import ServiceRegistry

logger = logging.getLogger(__name__)

class GlobalExecutionOrchestrator:
    """
    Distributes workloads across the cluster using Celery priority queues.
    """
    def __init__(self):
        self.registry = ServiceRegistry()

    def start_live_session(self, case_id: str, stream_configs: List[Dict], ref_paths: List[str], threshold: float):
        """
        Critical Priority: Routes live RTSP streams to healthy workers.
        """
        logger.info(f"Orchestrator: Starting live session for Case {case_id}")
        
        # 1. Find a healthy worker
        worker = self.registry.get_healthy_worker()
        worker_id = worker['id'] if worker else None

        if not worker_id:
            logger.warning("No healthy workers found in ServiceRegistry! Falling back to generic celery queue.")

        # 2. Dispatch to the critical 'live' queue
        # If we had a specific worker queue (e.g. worker.gpu-1), we could route there.
        # For now, we route to the 'live' queue.
        # This requires configuring CELERY_TASK_ROUTES in settings.py
        try:
            # We would normally dispatch a dedicated live task here.
            # For demonstration, we use the existing forensic pipeline task but route it.
            run_forensic_pipeline_task.apply_async(
                args=[case_id, None, ref_paths, 'live', threshold],
                queue='live'
            )
            logger.info("Successfully dispatched live session to 'live' queue.")
        except Exception as e:
            logger.error(f"Failed to dispatch live session: {e}")

    def dispatch_reid_task(self, track_id: str, crop_data: dict):
        """
        High Priority: Extract ReID embeddings.
        """
        # Example dispatch to 'reid' queue
        pass

    def dispatch_analytics(self):
        """
        Medium Priority: Aggregation.
        """
        # Example dispatch to 'analytics' queue
        pass
