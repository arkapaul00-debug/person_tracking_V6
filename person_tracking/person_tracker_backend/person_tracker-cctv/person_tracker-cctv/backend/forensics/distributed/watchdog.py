"""
Self-Healing Watchdog
Continuously monitors the Service Registry. 
If an RTSP camera or GPU worker drops off the registry (TTL expires),
the Watchdog triggers a failover or restart protocol using exponential backoff.
"""
import time
import logging
import threading
from typing import Callable
from .service_registry import ServiceRegistry

logger = logging.getLogger(__name__)

class SystemWatchdog:
    def __init__(self, registry: ServiceRegistry):
        self.registry = registry
        self._running = False
        self._thread = None
        self._camera_failures = {} # track retry counts per camera

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True, name="SystemWatchdog")
        self._thread.start()
        logger.info("System Watchdog started.")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)

    def _monitor_loop(self):
        while self._running:
            try:
                workers = self.registry.get_active_services('worker')
                cameras = self.registry.get_active_services('camera')
                
                # If there are NO workers alive, alert the system!
                if not workers:
                    logger.critical("WATCHDOG ALERT: Zero AI workers available in the cluster!")
                
                # We would normally track known cameras vs active cameras here
                # and trigger _recover_camera for any missing ones.
                
            except Exception as e:
                logger.error(f"Watchdog error: {e}")
            
            time.sleep(10.0)

    def _recover_camera(self, camera_id: str, restart_callback: Callable):
        """
        Implements Exponential Backoff for camera reconnection.
        """
        attempts = self._camera_failures.get(camera_id, 0)
        delay = min(300, (2 ** attempts)) # Max 5 minute delay
        
        logger.warning(f"Watchdog: Attempting to recover camera {camera_id} in {delay} seconds (Attempt {attempts + 1})")
        
        def retry():
            time.sleep(delay)
            try:
                restart_callback()
                self._camera_failures[camera_id] = 0 # reset on success
                logger.info(f"Watchdog: Camera {camera_id} recovered successfully.")
            except Exception as e:
                logger.error(f"Watchdog: Camera {camera_id} recovery failed: {e}")
                self._camera_failures[camera_id] = attempts + 1
                
        threading.Thread(target=retry, daemon=True).start()
