import time
import os
import cv2
import numpy as np
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings")
import django
django.setup()
from backend.forensics.ai_wrapper import DjangoTrackerAdapter
from collections import defaultdict

# 1. Create a dummy video
video_path = "/tmp/test_profile.mp4"
fourcc = cv2.VideoWriter_fourcc(*'mp4v')
out = cv2.VideoWriter(video_path, fourcc, 30, (640, 480))
for i in range(150): # 5 seconds
    frame = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
    # Add a fake person
    cv2.rectangle(frame, (200, 100), (300, 400), (0, 255, 0), -1)
    out.write(frame)
out.release()

# 2. Add profiler decorators
import cProfile
import pstats
import io

def profile_it(func):
    def wrapper(*args, **kwargs):
        pr = cProfile.Profile()
        pr.enable()
        res = func(*args, **kwargs)
        pr.disable()
        s = io.StringIO()
        ps = pstats.Stats(pr, stream=s).sort_stats('tottime')
        ps.print_stats(20)
        print(s.getvalue())
        return res
    return wrapper

# 3. Create dummy case
from backend.forensics.models import ForensicCase
case = ForensicCase.objects.create(status="PROCESSING", title="Test")

# 4. Run profiling
tracker = DjangoTrackerAdapter(
    case_id=case.id, ref_paths=[], mode='hybrid',
    high_threshold=0.75, low_threshold=0.60,
    batch_size=32, skip_n=4
)
tracker.process_video_with_sightings = profile_it(tracker.process_video_with_sightings)

print("Starting profiling...")
tracker.process_video_with_sightings(video_path, "/tmp/out.mp4", use_threading=False)
