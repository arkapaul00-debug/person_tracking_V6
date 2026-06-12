"""
Service Registry & Discovery Module
Tracks health and availability of all distributed workers, GPUs, and stream processors.
Uses Redis keys with TTL to auto-expire dead services.
"""
import time
import json
import logging
import threading
from typing import Dict, List, Optional
import redis

logger = logging.getLogger(__name__)

class ServiceRegistry:
    """
    Distributed registry utilizing Redis.
    Workers register themselves with a TTL (Time-To-Live).
    If they crash, their key naturally expires.
    """
    def __init__(self, host: str = 'localhost', port: int = 6379, db: int = 0):
        try:
            self._redis = redis.Redis(host=host, port=port, db=db, decode_responses=True)
            self._redis.ping()
        except Exception as e:
            logger.warning(f"ServiceRegistry: Redis unavailable. {e}")
            self._redis = None

        self._heartbeat_thread = None
        self._running = False
        self._my_service_id = None
        self._my_service_type = None

    def start_heartbeat(self, service_id: str, service_type: str, ttl_seconds: int = 10, metadata: dict = None):
        """Starts a background thread that continually pings Redis to say 'I am alive'."""
        if not self._redis:
            return

        self._my_service_id = service_id
        self._my_service_type = service_type
        self._running = True

        def heartbeat_loop():
            key = f"registry:{service_type}:{service_id}"
            while self._running:
                try:
                    payload = {
                        "id": service_id,
                        "type": service_type,
                        "timestamp": time.time(),
                        **(metadata or {})
                    }
                    self._redis.setex(key, ttl_seconds, json.dumps(payload))
                except Exception as e:
                    logger.error(f"Heartbeat failed: {e}")
                time.sleep(ttl_seconds / 2)  # Refresh halfway through TTL

        self._heartbeat_thread = threading.Thread(target=heartbeat_loop, daemon=True, name=f"Heartbeat-{service_id}")
        self._heartbeat_thread.start()
        logger.info(f"Service {service_id} ({service_type}) registered with TTL {ttl_seconds}s")

    def stop_heartbeat(self):
        """Stops the heartbeat and gracefully removes the service from the registry."""
        self._running = False
        if self._heartbeat_thread:
            self._heartbeat_thread.join(timeout=2.0)
        
        if self._redis and self._my_service_id and self._my_service_type:
            key = f"registry:{self._my_service_type}:{self._my_service_id}"
            self._redis.delete(key)
            logger.info(f"Service {self._my_service_id} gracefully deregistered.")

    def get_active_services(self, service_type: str = "*") -> List[Dict]:
        """Fetch all currently alive services of a specific type."""
        if not self._redis:
            return []
        
        services = []
        try:
            keys = self._redis.keys(f"registry:{service_type}:*")
            for key in keys:
                data = self._redis.get(key)
                if data:
                    services.append(json.loads(data))
        except Exception as e:
            logger.error(f"Failed to fetch active services: {e}")
        return services

    def get_healthy_worker(self) -> Optional[Dict]:
        """Load balancing: get the worker with the lowest stream count or highest free VRAM."""
        workers = self.get_active_services(service_type="worker")
        if not workers:
            return None
        
        # Simple heuristic: sort by active_streams (ascending)
        workers.sort(key=lambda w: w.get('active_streams', 999))
        return workers[0]
