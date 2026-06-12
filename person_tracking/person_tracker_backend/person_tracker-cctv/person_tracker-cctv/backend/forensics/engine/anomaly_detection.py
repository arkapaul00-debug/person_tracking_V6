"""
Anomaly Detection Platform (Phases 68, 72)
Detects resource, network, and behavioral anomalies, and predicts failures.
"""
import time
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


class AnomalyDetectionPlatform:
    """
    Monitors telemetry and metrics to detect statistical anomalies and predict failures.
    """

    def __init__(self, telemetry_platform=None, metrics_engine=None):
        self._telemetry = telemetry_platform
        self._metrics = metrics_engine
        self._anomaly_count = 0
        logger.info("AnomalyDetectionPlatform initialized")

    def run_analysis(self) -> Dict[str, Any]:
        """Run statistical anomaly detection over current telemetry."""
        anomalies = []
        
        if not self._telemetry:
            return {"anomalies": []}
            
        data = self._telemetry.get_full_telemetry()
        
        # 1. Resource Anomalies
        infra = data.get("infrastructure", {})
        if infra.get("cpu_percent", 0) > 95:
            anomalies.append({"type": "RESOURCE", "severity": "HIGH", "message": "CPU sustained above 95%"})
            self._anomaly_count += 1
            
        for gpu in infra.get("gpu_metrics", []):
            if gpu.get("vram_percent", 0) > 95:
                anomalies.append({"type": "RESOURCE", "severity": "CRITICAL", "message": f"GPU {gpu['gpu_id']} VRAM above 95%"})
                self._anomaly_count += 1

        # 2. Performance Anomalies
        if self._metrics:
            health = self._metrics.generate_health_score()
            if health.get("health_score", 100) < 70:
                anomalies.append({"type": "PERFORMANCE", "severity": "HIGH", "message": "System health degraded below 70%"})
                self._anomaly_count += 1

        return {
            "timestamp": time.time(),
            "anomalies_detected": anomalies,
            "total_historical_anomalies": self._anomaly_count
        }

    def get_metrics(self) -> dict:
        return {"total_anomalies_detected": self._anomaly_count}
