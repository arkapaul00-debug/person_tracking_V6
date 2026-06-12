from celery import shared_task
import logging
import traceback
from .ai_wrapper import run_forensic_pipeline
from .models import ForensicCase, AnalysisLog

logger = logging.getLogger(__name__)

@shared_task(bind=True)
def run_forensic_pipeline_task(self, case_id, video_path, ref_paths, mode, threshold):
    """
    Executes the heavy AI tracking pipeline asynchronously via Celery.
    """
    try:
        run_forensic_pipeline(case_id, video_path, ref_paths, mode, threshold)
    except Exception as e:
        logger.error(f"Celery Task Error for Case {case_id}: {e}")
        try:
            case = ForensicCase.objects.get(id=case_id)
            case.status = "ERROR"
            case.save()
            AnalysisLog.objects.create(case=case, message=f"Task Failed: {str(e)}", log_type="alert")
        except Exception:
            pass
        print(traceback.format_exc())

@shared_task
def index_background_evidence_task():
    """
    Event-driven background indexing task.
    Periodically scans the database for un-indexed evidence clips
    and extracts embeddings for faster forensic search.
    """
    logger.info("Starting background indexing of evidence...")
    # Placeholder for indexing logic
    try:
        from .models_stream import LiveAlert
        # Example: Mark unindexed alerts as indexed
        unindexed = LiveAlert.objects.filter(thumbnail__isnull=False)[:50]
        count = 0
        for alert in unindexed:
            # Here we would run Face Recognition to index the face
            count += 1
            
        logger.info(f"Indexed {count} new evidence artifacts.")
    except Exception as e:
        logger.error(f"Error in background indexing: {e}")

