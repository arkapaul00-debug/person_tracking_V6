"""
Views for Live CCTV Tracking — REST API endpoints for managing
real-time RTSP streams and live tracking sessions.
"""
import os
import cv2
import logging
import threading
import numpy as np
from django.conf import settings
from django.http import HttpResponse, StreamingHttpResponse
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt

from .models import ForensicCase, ReferenceImage
from .models_stream import CCTVStream, LiveTrackingSession, LiveAlert
from .cctv_orchestrator import get_orchestrator

logger = logging.getLogger(__name__)

@method_decorator(csrf_exempt, name='dispatch')
class StreamManageView(APIView):
    """CRUD for CCTV streams."""

    def get(self, request):
        """List all registered streams."""
        streams = CCTVStream.objects.filter(is_active=True)
        data = [{
            'id': str(s.id),
            'name': s.name,
            'rtsp_url': s.rtsp_url,
            'location': s.location,
            'status': s.status,
            'last_frame_at': s.last_frame_at.isoformat() if s.last_frame_at else None,
        } for s in streams]
        return Response({'streams': data})

    def post(self, request):
        """Add a new CCTV stream."""
        name = request.data.get('name', 'Unnamed Camera')
        rtsp_url = request.data.get('rtsp_url')
        location = request.data.get('location', '')

        if not rtsp_url:
            return Response({'error': 'rtsp_url is required'}, status=400)

        stream, created = CCTVStream.objects.get_or_create(
            rtsp_url=rtsp_url,
            defaults={'name': name, 'location': location}
        )
        if not created:
            stream.name = name
            stream.location = location
            stream.is_active = True
            stream.save()

        return Response({
            'id': str(stream.id),
            'name': stream.name,
            'created': created,
        })

    def delete(self, request):
        """Remove a stream by ID."""
        stream_id = request.data.get('stream_id')
        if not stream_id:
            return Response({'error': 'stream_id is required'}, status=400)

        try:
            stream = CCTVStream.objects.get(id=stream_id)
            stream.is_active = False
            stream.save()
            return Response({'status': 'removed', 'id': str(stream.id)})
        except CCTVStream.DoesNotExist:
            return Response({'error': 'Stream not found'}, status=404)

@method_decorator(csrf_exempt, name='dispatch')
class LiveStartView(APIView):
    """Start a live tracking session across RTSP cameras."""
    parser_classes = (MultiPartParser, FormParser)

    def post(self, request):
        # 1. Extract parameters
        mode = request.data.get('mode', 'hybrid')
        try:
            threshold = float(request.data.get('threshold', 0.55))
        except ValueError:
            threshold = 0.55

        ref_files = request.FILES.getlist('references')
        stream_ids = request.data.getlist('stream_ids')
        if not stream_ids and request.data.get('stream_id'):
            stream_ids = [request.data.get('stream_id')]
            
        # Also support inline stream URLs
        stream_urls = request.data.getlist('stream_urls')
        if not stream_urls and request.data.get('stream_url'):
            stream_urls = [request.data.get('stream_url')]
            
        stream_names = request.data.getlist('stream_names')

        if not stream_ids and not stream_urls:
            logger.error(f"Bad Request: missing streams. Data={request.data}")
            return Response({
                'error': 'Incomplete',
                'message': 'At least one stream_id or stream_url is required.'
            }, status=400)

        # 2. Check if already running or starting
        orch = get_orchestrator()
        if orch.running or orch.is_starting:
            return Response({
                'error': 'System Busy',
                'message': 'A live session is already running or starting.'
            }, status=503)

        # 3. Create forensic case
        case = ForensicCase.objects.create(mode=mode, threshold=threshold, status='PENDING')

        # 4. Save reference images
        ref_paths = []
        for f in ref_files:
            ref = ReferenceImage.objects.create(case=case, file=f)
            ref_paths.append(ref.file.path)

        # 5. Build stream configs
        stream_configs = []

        from django.core.exceptions import ValidationError

        # From existing stream IDs
        for sid in stream_ids:
            try:
                s = CCTVStream.objects.get(id=sid, is_active=True)
                stream_configs.append({
                    'rtsp_url': s.rtsp_url,
                    'name': s.name,
                    'location': s.location,
                })
            except (CCTVStream.DoesNotExist, ValidationError):
                pass

        # From inline URLs
        for i, url in enumerate(stream_urls):
            name = stream_names[i] if i < len(stream_names) else f"Camera {i + 1}"
            stream_configs.append({
                'rtsp_url': url,
                'name': name,
                'location': '',
            })

        if not stream_configs:
            logger.error(f"Bad Request: No valid streams found. IDs provided: {stream_ids}, URLs provided: {stream_urls}")
            return Response({
                'error': 'No valid streams',
                'message': 'None of the specified streams could be found or are active.'
            }, status=400)

        # 6. Start session — prefer local orchestrator (no Redis/Celery needed)
        #    Fall back to distributed Celery dispatch only when USE_CELERY=1
        use_celery = os.environ.get('USE_CELERY', '0') == '1'

        if use_celery:
            # Production: dispatch to distributed Celery worker queue
            try:
                from .distributed.global_orchestrator import GlobalExecutionOrchestrator
                global_orch = GlobalExecutionOrchestrator()
                global_orch.start_live_session(
                    case_id=str(case.id),
                    stream_configs=stream_configs,
                    ref_paths=ref_paths,
                    threshold=threshold
                )
                return Response({
                    "message": "Distributed live tracking session dispatched.",
                    "case_id": case.id
                }, status=200)
            except Exception as e:
                logger.error(f"Celery dispatch failed, falling back to local: {e}")
                # Fall through to local execution below

        # Local: run directly via CCTVOrchestrator in a background thread
        import logging as _logging
        _logger = _logging.getLogger(__name__)

        def _start_local():
            try:
                result = orch.start_session(
                    case_id=case.id,
                    stream_configs=stream_configs,
                    ref_paths=ref_paths,
                    mode=mode,
                    threshold=threshold,
                )
                _logger.info(f"Local live session result: {result}")
            except Exception as exc:
                _logger.error(f"Local live session failed: {exc}")

        t = threading.Thread(target=_start_local, daemon=True)
        t.start()

        return Response({
            "message": "Live tracking session starting locally.",
            "case_id": case.id
        }, status=200)

@method_decorator(csrf_exempt, name='dispatch')
class LiveStopView(APIView):
    """Stop the active live tracking session."""

    def post(self, request):
        orch = get_orchestrator()
        result = orch.stop_session()
        return Response(result)


class LiveStatusView(APIView):
    """Get real-time status of the active session."""

    def get(self, request):
        orch = get_orchestrator()
        status = orch.get_status()
        return Response(status)


class LiveAlertsView(APIView):
    """Fetch alerts for a live tracking session."""

    def get(self, request, session_id):
        try:
            session = LiveTrackingSession.objects.get(id=session_id)
        except LiveTrackingSession.DoesNotExist:
            return Response({'error': 'Session not found'}, status=404)

        alerts = LiveAlert.objects.filter(session=session).order_by('-timestamp')[:50]
        data = []
        for a in alerts:
            thumb_url = None
            clip_url = None
            try:
                if a.thumbnail:
                    thumb_url = a.thumbnail.url
            except Exception:
                pass
            try:
                if a.clip_file:
                    clip_url = a.clip_file.url
            except Exception:
                pass

            data.append({
                'id': str(a.id),
                'stream': a.stream.name,
                'stream_id': str(a.stream.id),
                'timestamp': a.timestamp.isoformat(),
                'confidence': round(a.confidence, 3),
                'frame_number': a.frame_number,
                'thumbnail_url': thumb_url,
                'clip_url': clip_url,
            })

        return Response({'alerts': data, 'total': len(data)})

@method_decorator(csrf_exempt, name='dispatch')
class LiveStreamAddView(APIView):
    """Add a stream to the running session."""

    def post(self, request):
        orch = get_orchestrator()
        if not orch.running:
            return Response({'error': 'No active session'}, status=400)

        rtsp_url = request.data.get('rtsp_url')
        name = request.data.get('name', '')
        location = request.data.get('location', '')

        if not rtsp_url:
            return Response({'error': 'rtsp_url is required'}, status=400)
            
        if not (rtsp_url.startswith('rtsp://') or rtsp_url.startswith('http://') or rtsp_url.startswith('https://')):
            return Response({'error': 'Invalid URL format. Must start with rtsp://, http://, or https://'}, status=400)

        result = orch.add_stream(rtsp_url, name, location)
        return Response(result)

@method_decorator(csrf_exempt, name='dispatch')
class LiveStreamRemoveView(APIView):
    """Remove a stream from the running session."""

    def post(self, request):
        orch = get_orchestrator()
        if not orch.running:
            return Response({'error': 'No active session'}, status=400)

        stream_id = request.data.get('stream_id')
        if not stream_id:
            return Response({'error': 'stream_id is required'}, status=400)

        result = orch.remove_stream(stream_id)
        return Response(result)


class LiveSnapshotView(APIView):
    """Return the latest JPEG frame from a running stream (peek — doesn't consume frame event)."""

    def get(self, request, stream_id):
        orch = get_orchestrator()
        frame = None
        
        if orch.running:
            info = orch.processors.get(stream_id)
            if info is not None:
                # Try to pull from the annotated buffer of the StreamProcessor first
                with info.processor._annotated_lock:
                    frame = info.processor.latest_annotated_frame

                if frame is None:
                    # Fallback to the raw capture buffer if no annotated frame exists yet
                    capture = info.capture
                    with capture._frame_lock:
                        frame = capture._frame

        if frame is None:
            placeholder = np.zeros((180, 320, 3), dtype=np.uint8)
            cv2.putText(placeholder, 'CONNECTING...', (55, 95),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.65, (60, 60, 60), 2, cv2.LINE_AA)
            _, jpg = cv2.imencode('.jpg', placeholder)
        else:
            _, jpg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 70])

        response = HttpResponse(jpg.tobytes(), content_type='image/jpeg')
        response['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response['Pragma'] = 'no-cache'
        return response


import asyncio

async def _mjpeg_generator(stream_id: str):
    """Async generator that yields MJPEG frames, peeking at buffer without consuming the event."""
    boundary = b'--frame\r\nContent-Type: image/jpeg\r\n\r\n'
    placeholder = np.zeros((180, 320, 3), dtype=np.uint8)
    cv2.putText(placeholder, 'CONNECTING...', (55, 95),
                cv2.FONT_HERSHEY_SIMPLEX, 0.65, (60, 60, 60), 2, cv2.LINE_AA)
    _, placeholder_jpg = cv2.imencode('.jpg', placeholder)
    placeholder_bytes = placeholder_jpg.tobytes()

    # Yield initial padding to instantly flush ASGI buffers before the loop
    yield b' ' * 4096

    while True:
        orch = get_orchestrator()
        info = orch.processors.get(stream_id) if orch.running else None
        if info is None:
            yield boundary + placeholder_bytes + b'\r\n'
            await asyncio.sleep(0.5)
            continue

        # Try to pull from the annotated buffer of the StreamProcessor first
        frame = None
        with info.processor._annotated_lock:
            frame = info.processor.latest_annotated_frame

        if frame is None:
            # Fallback to the raw capture buffer if no annotated frame exists yet
            with info.capture._frame_lock:
                frame = info.capture._frame

        if frame is None:
            yield boundary + placeholder_bytes + b'\r\n'
            await asyncio.sleep(0.1)
            continue

        ret, jpg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 65])
        if not ret or jpg is None:
            yield boundary + placeholder_bytes + b'\r\n'
            await asyncio.sleep(0.1)
            continue
            
        yield boundary + jpg.tobytes() + b'\r\n'
        await asyncio.sleep(0.067)  # ~15 fps cap to reduce CPU load

from django.views import View

class LiveMJPEGView(View):
    """Stream MJPEG video from a running RTSP capture directly to the browser."""

    async def get(self, request, stream_id, *args, **kwargs):
        response = StreamingHttpResponse(
            _mjpeg_generator(stream_id),
            content_type='multipart/x-mixed-replace; boundary=frame'
        )
        response['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response['Pragma'] = 'no-cache'
        return response
