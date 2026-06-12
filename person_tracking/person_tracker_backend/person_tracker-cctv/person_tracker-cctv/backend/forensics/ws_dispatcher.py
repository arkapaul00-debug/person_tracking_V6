"""
WebSocket Event Dispatcher — Synchronous helper to push events
through Django Channels from non-async code (stream processors, orchestrator).

Usage from any synchronous backend code:

    from .ws_dispatcher import push_live_alert, push_live_status

    push_live_alert(
        camera_id='abc-123',
        camera_name='Main Gate',
        confidence=0.87,
        frame_number=1234,
    )

    push_live_status(
        camera_id='abc-123',
        fps=28.5,
        active_tracks=3,
    )
"""
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def _get_channel_layer():
    """Lazy import to avoid import-time Django setup issues."""
    try:
        from channels.layers import get_channel_layer
        return get_channel_layer()
    except Exception as e:
        logger.debug(f"Channel layer unavailable: {e}")
        return None


def _send_group_event(group_name: str, event: dict):
    """
    Send an event to a Channel Layer group from synchronous code.
    Uses async_to_sync to bridge the sync/async boundary.
    Fails silently if the channel layer is not configured.
    """
    layer = _get_channel_layer()
    if layer is None:
        return

    try:
        from asgiref.sync import async_to_sync
        async_to_sync(layer.group_send)(group_name, event)
    except Exception as e:
        logger.warning(f"Failed to dispatch WS event to '{group_name}': {e}")


def push_live_alert(camera_id: str, camera_name: str = '',
                    confidence: float = 0.0, frame_number: int = 0,
                    track_id: int = -1, **extra):
    """
    Push a suspect detection alert to all connected Live CCTV clients.

    Args:
        camera_id: Stream/camera identifier (matches frontend stream.id).
        camera_name: Human-readable camera name.
        confidence: Detection confidence score (0.0 - 1.0).
        frame_number: Frame number in the video stream.
        track_id: Assigned tracker ID for the suspect.
        **extra: Additional metadata forwarded to the frontend.
    """
    _send_group_event('live_cctv', {
        'type': 'live.alert',
        'data': {
            'camera_id': camera_id,
            'camera_name': camera_name,
            'confidence': round(confidence, 4),
            'frame_number': frame_number,
            'track_id': track_id,
            'timestamp': datetime.now().isoformat(),
            **extra,
        }
    })


def push_live_status(camera_id: str, fps: float = 0.0,
                     active_tracks: int = 0, **extra):
    """
    Push a periodic status heartbeat for a camera stream.

    Args:
        camera_id: Stream/camera identifier.
        fps: Current processing FPS.
        active_tracks: Number of active tracked persons.
        **extra: Additional fields.
    """
    _send_group_event('live_cctv', {
        'type': 'live.status',
        'data': {
            'camera_id': camera_id,
            'fps': round(fps, 1),
            'active_tracks': active_tracks,
            'timestamp': datetime.now().isoformat(),
            **extra,
        }
    })


def push_dashboard_update(update_type: str, payload: dict):
    """
    Push a generic dashboard update (admin panel metrics, activity feed).

    Args:
        update_type: Event category string (e.g., 'metrics', 'activity').
        payload: Event data dict.
    """
    _send_group_event('dashboard_updates', {
        'type': 'send_dashboard_update',
        'update_type': update_type,
        'payload': payload,
    })
