"""
Centralized Telemetry Platform & Observability 2.0 (Phases 63, 65)
"""
import time
import psutil
import logging
import threading
from typing import Dict, Any

logger = logging.getLogger(__name__)


class CentralizedTelemetryPlatform:
    """
    Aggregates telemetry from Infrastructure (CPU/RAM/GPU), AI (Latency), and Platform (API/WebSockets).
    """

    def __init__(self):
        self._telemetry: Dict[str, Any] = {
            "infrastructure": {},
            "ai_pipeline": {},
            "platform": {}
        }
        self._lock = threading.Lock()
        
        # GPU detection (simulated if no nvml)
        self.has_gpu = False
        try:
            import pynvml
            pynvml.nvmlInit()
            self.has_gpu = True
        except:
            pass
            
        logger.info(f"CentralizedTelemetryPlatform initialized (GPU Support: {self.has_gpu})")

    def _collect_infrastructure(self):
        """Collect CPU, RAM, and GPU metrics."""
        infra = {
            "cpu_percent": psutil.cpu_percent(interval=None),
            "ram_percent": psutil.virtual_memory().percent,
            "gpu_metrics": []
        }
        
        if self.has_gpu:
            try:
                import pynvml
                device_count = pynvml.nvmlDeviceGetCount()
                for i in range(device_count):
                    handle = pynvml.nvmlDeviceGetHandleByIndex(i)
                    util = pynvml.nvmlDeviceGetUtilizationRates(handle)
                    mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
                    infra["gpu_metrics"].append({
                        "gpu_id": i,
                        "utilization": util.gpu,
                        "vram_used_mb": mem.used // (1024 * 1024),
                        "vram_total_mb": mem.total // (1024 * 1024),
                        "vram_percent": (mem.used / mem.total) * 100
                    })
            except Exception as e:
                logger.debug(f"Failed to collect GPU telemetry: {e}")
                
        return infra

    def record_ai_latency(self, component: str, latency_ms: float):
        """Record latency for AI components (Detection, Tracking, ReID)."""
        with self._lock:
            comp_stats = self._telemetry["ai_pipeline"].setdefault(component, {"total_ms": 0, "count": 0, "avg_ms": 0})
            comp_stats["total_ms"] += latency_ms
            comp_stats["count"] += 1
            comp_stats["avg_ms"] = comp_stats["total_ms"] / comp_stats["count"]

    def record_platform_metric(self, metric_name: str, value: float):
        """Record platform metrics like API latency, Queue depth."""
        with self._lock:
            self._telemetry["platform"][metric_name] = value

    def get_full_telemetry(self) -> Dict[str, Any]:
        """Aggregate and return all telemetry."""
        with self._lock:
            # Refresh infrastructure right before returning
            self._telemetry["infrastructure"] = self._collect_infrastructure()
            return dict(self._telemetry)
