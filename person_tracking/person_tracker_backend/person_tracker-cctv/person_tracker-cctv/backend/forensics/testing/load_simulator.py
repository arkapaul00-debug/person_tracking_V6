"""
Load Testing Platform (Phase 92)
Simulates massive scale (100 to 5000 cameras) and extreme WebSocket traffic.
"""
import time
import logging
import threading
from typing import Dict

logger = logging.getLogger(__name__)


class LoadTestingPlatform:
    """
    Simulates high-load scenarios to benchmark system bottlenecks.
    """

    def __init__(self):
        self._is_running = False
        self._metrics = {
            "simulated_cameras": 0,
            "events_generated_per_sec": 0,
            "total_events_simulated": 0
        }
        self._lock = threading.Lock()
        logger.info("LoadTestingPlatform initialized")

    def start_simulation(self, camera_count: int, events_per_cam_per_sec: float) -> bool:
        """Start a load simulation."""
        with self._lock:
            if self._is_running:
                return False
            self._is_running = True
            self._metrics["simulated_cameras"] = camera_count
            self._metrics["events_generated_per_sec"] = camera_count * events_per_cam_per_sec
            
        logger.warning(f"STARTING LOAD SIMULATION: {camera_count} cameras at {events_per_cam_per_sec} evt/sec")
        
        # In a real scenario, this would spin up worker threads to hammer the API/WebSockets
        # We will just simulate the counter incrementing
        def run_sim():
            while self._is_running:
                time.sleep(1)
                with self._lock:
                    self._metrics["total_events_simulated"] += int(self._metrics["events_generated_per_sec"])
                    
        threading.Thread(target=run_sim, daemon=True).start()
        return True

    def stop_simulation(self):
        """Stop the load simulation."""
        with self._lock:
            self._is_running = False
        logger.info("Load simulation stopped.")

    def get_metrics(self) -> dict:
        with self._lock:
            return dict(self._metrics)
