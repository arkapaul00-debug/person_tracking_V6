"""
Enterprise WebSocket Manager (Phase 78)
Optimized for high-frequency updates, large-scale concurrent clients, and event prioritization.
"""
import time
import json
import asyncio
import logging
from typing import Dict, List, Set, Any
from .contracts import BaseEvent

logger = logging.getLogger(__name__)


class EnterpriseWebSocketManager:
    """
    Manages WebSocket connections with intelligent event dropping under load.
    Ensures CRITICAL events are always delivered, while LOW priority events 
    (like raw bounding box updates) can be rate-limited to prevent UI freezes (Phase 80).
    """

    def __init__(self):
        # In a real ASGI app (FastAPI), this holds fastapi.WebSocket objects
        self.active_connections: List[Any] = []
        
        # State tracking
        self.connected_clients = 0
        self.events_sent = 0
        self.events_dropped = 0
        
        # Rate limiting logic (e.g., max 30 updates per second per client)
        self.max_events_per_sec = 30
        self._client_last_event_time: Dict[int, float] = {}
        
        logger.info("EnterpriseWebSocketManager initialized")

    async def connect(self, websocket: Any):
        """Accept a new connection."""
        await websocket.accept()
        self.active_connections.append(websocket)
        self.connected_clients += 1
        self._client_last_event_time[id(websocket)] = time.time()
        logger.info(f"Client connected. Total: {self.connected_clients}")

    def disconnect(self, websocket: Any):
        """Remove a connection."""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            self.connected_clients -= 1
            self._client_last_event_time.pop(id(websocket), None)
            logger.info(f"Client disconnected. Total: {self.connected_clients}")

    async def broadcast_event(self, event: BaseEvent):
        """
        Broadcast an event to all connected clients.
        Implements intelligent dropping based on priority and client rate limits.
        """
        if not self.active_connections:
            return

        payload = event.model_dump_json()
        priority = event.priority
        now = time.time()

        for connection in list(self.active_connections):
            # Throttle LOW priority events if sending too fast (Phase 80 UI Freeze Prevention)
            if priority in ["LOW", "MEDIUM"]:
                last_time = self._client_last_event_time.get(id(connection), 0)
                if (now - last_time) < (1.0 / self.max_events_per_sec):
                    self.events_dropped += 1
                    continue # Skip sending to this client to prevent UI stutter

            try:
                await connection.send_text(payload)
                self.events_sent += 1
                self._client_last_event_time[id(connection)] = now
            except Exception as e:
                logger.error(f"Failed to send to client: {e}")
                self.disconnect(connection)

    def get_metrics(self) -> dict:
        return {
            "connected_clients": self.connected_clients,
            "events_sent": self.events_sent,
            "events_dropped_for_ui_perf": self.events_dropped
        }
