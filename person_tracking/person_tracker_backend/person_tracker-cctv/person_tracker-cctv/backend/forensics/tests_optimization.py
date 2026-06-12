import os
import cv2
import numpy as np
import time
import shutil
import logging
from unittest.mock import MagicMock, patch

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("OptimizationTest")

# Mock Django settings and models
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings")
import django
from django.conf import settings

# Setup dummy media root for testing
TEST_MEDIA_ROOT = "/tmp/test_media"
settings.MEDIA_ROOT = TEST_MEDIA_ROOT
os.makedirs(TEST_MEDIA_ROOT, exist_ok=True)
os.makedirs(os.path.join(TEST_MEDIA_ROOT, 'outputs'), exist_ok=True)

# Mock models
sys_modules_mock = {
    'backend.forensics.models': MagicMock(),
    'backend.forensics.sighting_manager': MagicMock(),
    # 'backend.forensics.ai_core.query_tracker': MagicMock(), # We want to test logic, but maybe mock heavy imports?
}

# We actually want to import the REAL wrapper class to test its LOOP logic
# But we need to mock the Heavy AI parts (YOLO, InsightFace) so this test runs fast on CPU
with patch.dict('sys.modules', sys_modules_mock):
    # We need to do some tricky patching because ai_wrapper imports from models
    pass

# Let's create a simpler integration test that imports the wrapper 
# but mocks the internal "detector" and "tracker" of the parent class.

from backend.forensics.ai_wrapper import DjangoTrackerAdapter, run_forensic_pipeline
from backend.forensics.models import ForensicCase

def create_dummy_video(path, duration=5, fps=30):
    h, w = 480, 640
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(path, fourcc, fps, (w, h))
    for i in range(duration * fps):
        frame = np.random.randint(0, 255, (h, w, 3), dtype=np.uint8)
        # Draw a fake "person" (green rectangle) moving
        x = int(i * 2) % w
        cv2.rectangle(frame, (x, 100), (x+50, 200), (0, 255, 0), -1)
        out.write(frame)
    out.release()
    logger.info(f"Created dummy video at {path}")

def test_pipeline_speed():
    video_path = os.path.join(TEST_MEDIA_ROOT, "test_video.mp4")
    create_dummy_video(video_path, duration=10) # 300 frames
    
    # Mock the DB Case Object
    mock_case = MagicMock()
    mock_case.id = "test_case_123"
    
    with patch('backend.forensics.models.ForensicCase.objects.get', return_value=mock_case):
        # Instantiate Adapter
        # We also need to mock the SUPER class init to avoid loading YOLO weights
        with patch('backend.forensics.ai_core.query_tracker.UnifiedQueryTracker.__init__', return_value=None):
            adapter = DjangoTrackerAdapter("test_case_123", ref_paths=[], mode='hybrid')
            
            # Manually set attributes that __init__ would have set
            adapter.detector = MagicMock()
            # Mock detector return: a list of Results (one per frame in batch)
            # We use batch_size=8
            
            # Mock Tracker
            adapter.tracker = MagicMock()
            adapter.tracker.update.return_value = np.array([[10, 10, 60, 200, 1, 0.9, 0]]) # Sim track output
            
            adapter.hysteresis = MagicMock()
            adapter.hysteresis.check_match.return_value = True # Always match
            
            adapter._compute_best_similarity = MagicMock(return_value=(0.95, {}))
            
            adapter.batch_size = 8
            adapter.skip_n = 2
            
            # Mock Detection Logic
            def mock_detect(frames, **kwargs):
                # Return len(frames) dummy results
                results = []
                for _ in frames:
                    m = MagicMock()
                    board = MagicMock()
                    board.xyxy.cpu().numpy.return_value = np.array([[10, 100, 50, 200]])
                    board.conf.cpu().numpy.return_value = np.array([0.9])
                    m.boxes = board
                    results.append(m)
                return results
            
            adapter.detector.side_effect = mock_detect
            
            # RUN TIMING
            start_time = time.time()
            adapter.process_video_with_sightings(video_path, "/dev/null")
            end_time = time.time()
            
            duration = end_time - start_time
            fps = 300 / duration
            logger.info(f"Processed 300 frames in {duration:.2f}s ({fps:.2f} FPS)")
            
            if fps > 100:
                logger.info("PASS: Speed is acceptable for optimized pipeline (Mocked AI).")
            else:
                logger.warning("FAIL: Speed is too slow even with mocked AI.")

if __name__ == "__main__":
    try:
        test_pipeline_speed()
        print("Test Complete")
    except Exception as e:
        print(f"Test Failed: {e}")
        import traceback
        traceback.print_exc()
