"""
WebSocket Consumers — Real-Time Event Push for Sentinel PRO.

Consumers:
    DashboardConsumer — /ws/dashboard/
        Generic dashboard status updates (metrics, activity feed).

    LiveCCTVConsumer — /ws/live/
        Real-time alerts, stream status, and detection events during
        active live CCTV tracking sessions. Supports per-stream
        subscription so the frontend only receives events for cameras
        it is currently viewing.
"""
import json
import logging
from channels.generic.websocket import AsyncWebsocketConsumer

logger = logging.getLogger(__name__)


class DashboardConsumer(AsyncWebsocketConsumer):
    """Push dashboard metrics and activity updates to the admin panel."""

    async def connect(self):
        self.group_name = 'dashboard_updates'
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data):
        pass  # Handle incoming messages from UI if needed

    # Helper to send generic events from the backend to the UI
    async def send_dashboard_update(self, event):
        await self.send(text_data=json.dumps({
            'type': event.get('update_type', 'generic'),
            'payload': event.get('payload', {})
        }))


class LiveCCTVConsumer(AsyncWebsocketConsumer):
    """
    Real-time alert and status push for live CCTV tracking sessions.

    The frontend connects here when a user starts a live monitoring session.
    It can subscribe to specific stream IDs to filter the event stream.

    Outbound message types:
        live.alert  — Suspect detection alert with confidence, camera info
        live.status — Periodic FPS / health heartbeat per stream
    """

    async def connect(self):
        # All live clients join the broadcast group
        self.group_name = 'live_cctv'
        self.subscribed_streams = set()  # optional per-stream filtering

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        logger.info(f"[WS] Live CCTV client connected: {self.channel_name}")

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)
        logger.info(f"[WS] Live CCTV client disconnected: {self.channel_name}")

    async def receive(self, text_data):
        """Handle inbound commands from the frontend."""
        try:
            data = json.loads(text_data)
            action = data.get('action')

            if action == 'subscribe':
                # Subscribe to specific stream IDs for filtered alerts
                stream_ids = data.get('streams', [])
                self.subscribed_streams = set(stream_ids)
                await self.send(text_data=json.dumps({
                    'type': 'live.subscribed',
                    'data': {'streams': list(self.subscribed_streams)}
                }))

            elif action == 'unsubscribe':
                stream_ids = data.get('streams', [])
                self.subscribed_streams -= set(stream_ids)

        except json.JSONDecodeError:
            logger.warning(f"[WS] Invalid JSON from live client: {text_data[:100]}")

    # ---- Channel layer event handlers (called by backend code) ----

    async def live_alert(self, event):
        """
        Push a detection alert to connected clients.

        Expected event payload:
            {
                'type': 'live.alert',
                'data': {
                    'camera_id': str,
                    'camera_name': str,
                    'confidence': float,
                    'timestamp': str,
                    'frame_number': int,
                    ...
                }
            }
        """
        alert_data = event.get('data', {})
        camera_id = alert_data.get('camera_id', '')

        # Filter: if this client subscribed to specific streams,
        # only forward alerts for those streams.
        if self.subscribed_streams and camera_id not in self.subscribed_streams:
            return

        await self.send(text_data=json.dumps({
            'type': 'live.alert',
            'data': alert_data
        }))

    async def live_status(self, event):
        """
        Push periodic status/heartbeat for a stream.

        Expected event payload:
            {
                'type': 'live.status',
                'data': {
                    'camera_id': str,
                    'fps': float,
                    'active_tracks': int,
                    ...
                }
            }
        """
        await self.send(text_data=json.dumps({
            'type': 'live.status',
            'data': event.get('data', {})
        }))
