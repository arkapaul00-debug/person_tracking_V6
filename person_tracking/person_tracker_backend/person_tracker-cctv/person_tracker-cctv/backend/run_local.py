import os
import sys
import django
from pathlib import Path

# Setup Django environment so we can use its ORM and settings within the script
sys.path.append('/home/temp_user/arjit/backend')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
django.setup()

from forensics.models import ForensicCase, EvidenceVideo, ReferenceImage
from forensics.ai_wrapper import run_forensic_pipeline

def run_local_analysis(video_path: str, ref_image_path: str):
    """
    Creates a mock case in the database and runs the analysis pipeline directly.
    """
    print(f"--- STARTING LOCAL ANALYSIS ---")
    print(f"Video: {video_path}")
    print(f"Reference: {ref_image_path}")
    
    # Check if files exist
    if not os.path.exists(video_path):
        print(f"Error: Video file not found: {video_path}")
        return
    if not os.path.exists(ref_image_path):
        print(f"Error: Reference image not found: {ref_image_path}")
        return

    # 1. Create a DB case (needed by ai_wrapper)
    case = ForensicCase.objects.create(
        mode='hybrid',     # 'face', 'body', or 'hybrid'
        threshold=0.55,     # Confidence threshold
        status='PROCESSING'
    )
    print(f"\nCreated Case ID: {case.id}")

    # (We don't need to actually copy the files into Django's Media roots 
    # since ai_wrapper accepts absolute paths, except EvidenceVideo/ReferenceImage 
    # models technically expect relative paths. We'll use the absolute paths directly)
    # We create the objects just in case any downstream logic queries them.
    EvidenceVideo.objects.create(case=case, file=video_path)
    ReferenceImage.objects.create(case=case, file=ref_image_path)

    # 2. Run Pipeline Bypass
    try:
        print("\n--- LAUNCHING PIPELINE ---")
        # Ensure we pass the paths in a list for references
        run_forensic_pipeline(
            case_id=case.id,
            video_path=video_path,
            ref_paths=[ref_image_path],
            mode='hybrid',
            threshold=0.55
        )
        print("\n--- PIPELINE COMPLETED SUCCESSFULLY ---")
        
        # Check results
        case.refresh_from_db()
        print(f"Final Status: {case.status}")
        print(f"Output Video: {case.output_video}")
        print(f"Total Sightings: {case.sightings.count()}")
        print("\nSighting Clips Generated:")
        for s in case.sightings.all():
            print(f" - [{s.start_time}s - {s.end_time}s] Score: {s.max_score:.2f} -> {s.clip_file}")

    except Exception as e:
        print(f"\n--- PIPELINE FAILED ---")
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    if len(sys.argv) == 3:
        video = sys.argv[1]
        ref = sys.argv[2]
        run_local_analysis(video, ref)
    else:
        # Default fallback to the requested files
        video = "/home/temp_user/arjit/clips2.mp4"
        ref = "/home/temp_user/arjit/civic.jpeg"
        run_local_analysis(video, ref)
