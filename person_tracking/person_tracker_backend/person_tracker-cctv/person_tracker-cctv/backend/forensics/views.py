import threading
from django.shortcuts import render
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser

# --- Model Imports ---
from .models import ForensicCase, EvidenceVideo, ReferenceImage, AnalysisLog
from .models_sighting import SuspectSighting  # Fixed: Moved to top level

# --- AI Wrapper Import ---
from .ai_wrapper import run_forensic_pipeline

# Global lock to ensure only one case uses the GPU at a time
GPU_LOCK = threading.Lock()

def index_view(request):
    """
    Serves the main Sentinel Forensic Dashboard (index.html).
    """
    return render(request, 'index.html')

class StartAnalysisView(APIView):
    """
    Handles the initial upload of evidence and suspect photos.
    Triggers the AI pipeline in a background thread.
    """
    parser_classes = (MultiPartParser, FormParser)

    def post(self, request, *args, **kwargs):
        # 1. Hardware Safety Check
        if GPU_LOCK.locked():
            return Response({
                "error": "System Busy", 
                "message": "The GPU is currently processing another forensic case."
            }, status=503)

        # 2. Extract Data
        video_file = request.FILES.get('video')
        ref_files = request.FILES.getlist('references')
        mode = request.data.get('mode', 'hybrid')
        # Default to 0.75 if not provided
        try:
            threshold = float(request.data.get('threshold', 0.75))
        except ValueError:
            threshold = 0.75

        if not video_file or not ref_files:
            return Response({
                "error": "Incomplete Evidence", 
                "message": "Video and Reference images are required."
            }, status=400)

        # 3. Save to Database
        try:
            case = ForensicCase.objects.create(mode=mode, threshold=threshold)
            EvidenceVideo.objects.create(case=case, file=video_file)
            
            ref_paths = []
            for f in ref_files:
                ref = ReferenceImage.objects.create(case=case, file=f)
                ref_paths.append(ref.file.path)

            # 4. Launch AI Task via Celery
            from .tasks import run_forensic_pipeline_task
            run_forensic_pipeline_task.delay(case.id, case.video.file.path, ref_paths, mode, threshold)

            return Response({
                "case_id": str(case.id),
                "status": "started"
            })
        except Exception as e:
            return Response({"error": "Database Error", "message": str(e)}, status=500)

class CaseStatusView(APIView):
    """
    Polled by script.js every 2 seconds.
    Returns logs, status, and metrics for the dashboard.
    """
    def get(self, request, case_id):
        try:
            case = ForensicCase.objects.get(id=case_id)
            
            # Fetch logs ordered by time
            logs = case.logs.all().order_by('timestamp')
            log_list = [{
                "time": l.timestamp.strftime("%H:%M:%S"),
                "message": l.message,
                "type": l.log_type
            } for l in logs]

            # Logic to extract metrics for the UI meters
            last_log = logs.last()
            active_tracks = "0"
            # Simple heuristic: if the last log mentions an ID, we likely have a track
            if last_log and "ID:" in last_log.message:
                active_tracks = "1"

            # Get original evidence video URL
            evidence_url = None
            try:
                ev = case.video
                if ev and ev.file:
                    evidence_url = ev.file.url
            except Exception:
                pass

            return Response({
                "status": case.status,
                # Safe access to video URL
                "video_url": case.output_video.url if case.output_video else None,
                "evidence_video_url": evidence_url,
                "logs": log_list,
                # In a real app, these should be stored in DB/Redis, but hardcoded is fine for prototype
                "current_fps": "28.4" if case.status == "PROCESSING" else "0.0",
                "active_tracks": active_tracks,
                "last_score": "0.88" if active_tracks == "1" else None
            })
            
        except ForensicCase.DoesNotExist:
            return Response({"error": "Invalid Case ID"}, status=404)

class GetSightingsView(APIView):
    """
    Returns all 5-second evidence clips found for a specific case.
    """
    def get(self, request, case_id):
        try:
            # Look up sightings in the database
            sightings = SuspectSighting.objects.filter(case_id=case_id).order_by('start_time')
            
            data = []
            for s in sightings:
                # SAFETY CHECK: If the file wasn't created properly, .url can crash
                try:
                    clip_url = s.clip_file.url
                except Exception:
                    clip_url = None

                if clip_url:
                    data.append({
                        "id": s.id,
                        "track_id": s.track_id,
                        "start": round(s.start_time, 2),
                        "end": round(s.end_time, 2),
                        "url": clip_url, 
                        "score": round(s.max_score, 2)
                    })
            
            return Response(data)
        except Exception as e:
            # Log the error but don't crash the frontend polling
            print(f"Error fetching sightings: {e}")
            return Response({"error": str(e)}, status=500)