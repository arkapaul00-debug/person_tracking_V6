"""
Health Check — System-Wide Health Probes for All Components.

Provides structured health status for:
  - GPU devices (VRAM, temperature, driver status)
  - AI models (loaded status, inference health)
  - Active streams (FPS, reconnection state)
  - Pipeline stages (queue depth, error rate)
  - External services (Redis, Kafka, database)

Used by:
  - /api/health endpoint → frontend status panel
  - Load balancer → routing decisions
  - Kubernetes → liveness/readiness probes
"""
import time
import logging
from typing import Dict, Any, Optional, List
from enum import Enum

logger = logging.getLogger(__name__)


class HealthStatus(Enum):
    HEALTHY = 'healthy'
    DEGRADED = 'degraded'
    UNHEALTHY = 'unhealthy'
    UNKNOWN = 'unknown'


class HealthCheck:
    """
    System-wide health aggregator.

    Usage:
        health = HealthCheck()
        health.register_probe('gpu', gpu_health_probe)
        health.register_probe('models', model_health_probe)

        result = health.check_all()
        # {'status': 'healthy', 'components': {...}, 'timestamp': ...}

        # Quick liveness check
        is_alive = health.is_alive()
    """

    def __init__(self):
        self._probes: Dict[str, callable] = {}
        self._last_results: Dict[str, Dict] = {}
        self._last_check_time = 0.0

    def register_probe(self, name: str, probe_fn: callable):
        """
        Register a health probe function.

        Probe function signature: () -> dict with keys:
          - 'status': 'healthy'|'degraded'|'unhealthy'
          - 'details': dict with component-specific info
        """
        self._probes[name] = probe_fn

    def check_all(self) -> Dict[str, Any]:
        """
        Run all registered health probes.

        Returns:
            Aggregated health status with per-component details.
        """
        components = {}
        overall_status = HealthStatus.HEALTHY

        for name, probe_fn in self._probes.items():
            try:
                result = probe_fn()
                components[name] = result

                # Aggregate: worst component determines overall
                comp_status = result.get('status', 'unknown')
                if comp_status == 'unhealthy':
                    overall_status = HealthStatus.UNHEALTHY
                elif comp_status == 'degraded' and overall_status != HealthStatus.UNHEALTHY:
                    overall_status = HealthStatus.DEGRADED

            except Exception as e:
                components[name] = {
                    'status': 'unhealthy',
                    'error': str(e),
                }
                overall_status = HealthStatus.UNHEALTHY

        self._last_results = components
        self._last_check_time = time.time()

        return {
            'status': overall_status.value,
            'timestamp': time.time(),
            'components': components,
        }

    def is_alive(self) -> bool:
        """Quick liveness check (no probe execution)."""
        if not self._last_results:
            return True  # No probes registered = assume alive
        return all(
            r.get('status') != 'unhealthy'
            for r in self._last_results.values()
        )

    def is_ready(self) -> bool:
        """Readiness check — all components healthy or degraded."""
        result = self.check_all()
        return result['status'] in ('healthy', 'degraded')


# --- Built-in Probe Factories ---

def create_gpu_probe(gpu_monitor=None) -> callable:
    """Create a GPU health probe."""
    def probe():
        if gpu_monitor is None:
            return {'status': 'unknown', 'details': 'no gpu_monitor'}

        try:
            devices = gpu_monitor.get_all_devices()
            gpu_status = 'healthy'

            device_details = {}
            for did, info in devices.items():
                d = info.to_dict()
                if d.get('is_overloaded'):
                    gpu_status = 'degraded'
                if info.temperature_c > 90:
                    gpu_status = 'unhealthy'
                device_details[str(did)] = d

            return {
                'status': gpu_status,
                'device_count': len(devices),
                'devices': device_details,
            }
        except Exception as e:
            return {'status': 'unhealthy', 'error': str(e)}

    return probe


def create_model_probe(model_pool=None, registry=None) -> callable:
    """Create a model health probe."""
    def probe():
        if model_pool is None:
            return {'status': 'unknown'}

        try:
            models_ok = True
            details = {}

            if hasattr(model_pool, 'detector') and model_pool.detector:
                details['detector'] = 'loaded'
            else:
                details['detector'] = 'missing'
                models_ok = False

            if hasattr(model_pool, 'face_model'):
                details['face'] = 'loaded' if model_pool.face_model else 'disabled'

            if hasattr(model_pool, 'body_model'):
                details['body'] = 'loaded' if model_pool.body_model else 'disabled'

            if registry:
                details['registry'] = registry.get_all_metrics()

            return {
                'status': 'healthy' if models_ok else 'degraded',
                'models': details,
            }
        except Exception as e:
            return {'status': 'unhealthy', 'error': str(e)}

    return probe


def create_pipeline_probe(pipelines: Dict = None) -> callable:
    """Create a pipeline health probe."""
    def probe():
        if not pipelines:
            return {'status': 'healthy', 'active_pipelines': 0}

        try:
            active = 0
            errored = 0
            pipeline_details = {}

            for stream_id, pipeline in pipelines.items():
                metrics = pipeline.get_metrics()
                is_running = metrics.get('running', False)

                if is_running:
                    active += 1
                else:
                    errored += 1

                bottleneck = pipeline.get_bottleneck()
                pipeline_details[stream_id] = {
                    'running': is_running,
                    'bottleneck': bottleneck,
                    'total_latency_ms': metrics.get('total_pipeline_latency_ms', 0),
                }

            status = 'healthy'
            if errored > 0:
                status = 'degraded' if active > 0 else 'unhealthy'

            return {
                'status': status,
                'active_pipelines': active,
                'errored_pipelines': errored,
                'details': pipeline_details,
            }
        except Exception as e:
            return {'status': 'unhealthy', 'error': str(e)}

    return probe


def create_stream_probe(orchestrator=None) -> callable:
    """Create a stream health probe."""
    def probe():
        if orchestrator is None:
            return {'status': 'unknown'}

        try:
            status_data = {}
            if hasattr(orchestrator, 'get_status'):
                status_data = orchestrator.get_status()

            active = status_data.get('active_streams', 0)
            return {
                'status': 'healthy' if active >= 0 else 'degraded',
                'active_streams': active,
            }
        except Exception as e:
            return {'status': 'unhealthy', 'error': str(e)}

    return probe
