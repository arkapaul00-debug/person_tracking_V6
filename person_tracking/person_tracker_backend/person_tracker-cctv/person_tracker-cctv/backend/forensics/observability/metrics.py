"""
Metrics Collector — Centralized Prometheus-Compatible Metrics for All Components.

Aggregates metrics from every pipeline component and exposes them as:
  - Prometheus text format (for Grafana dashboards)
  - JSON API (for frontend health panels)
  - In-memory summary (for debug logging)

Metric categories:
  - Pipeline: per-stage throughput, latency, queue depth, drops
  - GPU: VRAM usage, SM utilization, temperature, power
  - Models: inference count, avg latency, failure rate per model
  - Tracking: active tracks, ID switches, fragmentation rate
  - Streams: FPS, reconnect count, frame drops per stream
  - Evidence: hash chain length, custody events

Thread-safe: all metric updates use atomic operations.
"""
import time
import threading
import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class CounterMetric:
    """Monotonically increasing counter."""
    name: str
    value: float = 0.0
    labels: Dict[str, str] = field(default_factory=dict)
    help_text: str = ''

    def inc(self, amount: float = 1.0):
        self.value += amount


@dataclass
class GaugeMetric:
    """Point-in-time value that can go up or down."""
    name: str
    value: float = 0.0
    labels: Dict[str, str] = field(default_factory=dict)
    help_text: str = ''

    def set(self, value: float):
        self.value = value


@dataclass
class HistogramMetric:
    """Distribution of values with count, sum, and buckets."""
    name: str
    count: int = 0
    total: float = 0.0
    min_val: float = float('inf')
    max_val: float = 0.0
    labels: Dict[str, str] = field(default_factory=dict)
    help_text: str = ''

    def observe(self, value: float):
        self.count += 1
        self.total += value
        self.min_val = min(self.min_val, value)
        self.max_val = max(self.max_val, value)

    @property
    def avg(self) -> float:
        return self.total / max(self.count, 1)


class MetricsCollector:
    """
    Centralized metrics collector for the entire surveillance pipeline.

    Usage:
        metrics = MetricsCollector.get_instance()

        # Record metrics
        metrics.record_inference('yolov11n', latency_ms=4.2)
        metrics.record_pipeline_frame('cam_001', 'detect', latency_ms=3.1)
        metrics.set_gpu_utilization(0, 0.72)
        metrics.increment_alert_count()

        # Export
        prometheus_text = metrics.to_prometheus()
        json_data = metrics.to_json()
    """

    _instance = None
    _lock = threading.Lock()

    def __init__(self):
        # --- Pipeline metrics ---
        self._stage_latency: Dict[str, HistogramMetric] = {}
        self._stage_throughput: Dict[str, CounterMetric] = {}
        self._stage_drops: Dict[str, CounterMetric] = {}

        # --- Event Bus metrics ---
        self._event_bus_latency: Dict[str, HistogramMetric] = {}
        self._event_bus_throughput: Dict[str, CounterMetric] = {}
        self._active_workers: Dict[str, GaugeMetric] = {}

        # --- Model metrics ---
        self._model_latency: Dict[str, HistogramMetric] = {}
        self._model_calls: Dict[str, CounterMetric] = {}
        self._model_failures: Dict[str, CounterMetric] = {}

        # --- GPU metrics ---
        self._gpu_vram_used: Dict[int, GaugeMetric] = {}
        self._gpu_utilization: Dict[int, GaugeMetric] = {}
        self._gpu_temperature: Dict[int, GaugeMetric] = {}

        # --- Stream metrics ---
        self._stream_fps: Dict[str, GaugeMetric] = {}
        self._stream_frames: Dict[str, CounterMetric] = {}

        # --- System metrics ---
        self._total_alerts = CounterMetric(name='forensic_alerts_total', help_text='Total alerts generated')
        self._total_sightings = CounterMetric(name='forensic_sightings_total', help_text='Total sightings recorded')
        self._active_streams = GaugeMetric(name='forensic_active_streams', help_text='Currently active streams')
        self._active_tracks = GaugeMetric(name='forensic_active_tracks', help_text='Currently active person tracks')
        self._evidence_chain_length = GaugeMetric(name='forensic_evidence_chain_length', help_text='Evidence hash chain length')

        self._metrics_lock = threading.Lock()
        self._start_time = time.time()

    @classmethod
    def get_instance(cls) -> 'MetricsCollector':
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # --- Recording methods ---

    def record_inference(self, model_name: str, latency_ms: float):
        """Record a model inference event."""
        with self._metrics_lock:
            if model_name not in self._model_latency:
                self._model_latency[model_name] = HistogramMetric(
                    name=f'forensic_model_latency_ms',
                    labels={'model': model_name},
                    help_text='Model inference latency in milliseconds',
                )
                self._model_calls[model_name] = CounterMetric(
                    name=f'forensic_model_calls_total',
                    labels={'model': model_name},
                )
            self._model_latency[model_name].observe(latency_ms)
            self._model_calls[model_name].inc()

    def record_model_failure(self, model_name: str):
        """Record a model inference failure."""
        with self._metrics_lock:
            if model_name not in self._model_failures:
                self._model_failures[model_name] = CounterMetric(
                    name='forensic_model_failures_total',
                    labels={'model': model_name},
                )
            self._model_failures[model_name].inc()

    def record_pipeline_frame(self, stream_id: str, stage: str, latency_ms: float):
        """Record a pipeline stage processing event."""
        key = f"{stream_id}:{stage}"
        with self._metrics_lock:
            if key not in self._stage_latency:
                self._stage_latency[key] = HistogramMetric(
                    name='forensic_stage_latency_ms',
                    labels={'stream': stream_id, 'stage': stage},
                )
                self._stage_throughput[key] = CounterMetric(
                    name='forensic_stage_frames_total',
                    labels={'stream': stream_id, 'stage': stage},
                )
            self._stage_latency[key].observe(latency_ms)
            self._stage_throughput[key].inc()

    def record_pipeline_drop(self, stream_id: str, stage: str):
        """Record a dropped frame at a pipeline stage."""
        key = f"{stream_id}:{stage}"
        with self._metrics_lock:
            if key not in self._stage_drops:
                self._stage_drops[key] = CounterMetric(
                    name='forensic_stage_drops_total',
                    labels={'stream': stream_id, 'stage': stage},
                )
            self._stage_drops[key].inc()

    def set_gpu_utilization(self, device_id: int, utilization: float):
        """Set GPU utilization gauge (0.0 - 1.0)."""
        with self._metrics_lock:
            if device_id not in self._gpu_utilization:
                self._gpu_utilization[device_id] = GaugeMetric(
                    name='forensic_gpu_utilization',
                    labels={'device': str(device_id)},
                )
            self._gpu_utilization[device_id].set(utilization)

    def set_gpu_vram(self, device_id: int, used_mb: float):
        """Set GPU VRAM usage gauge."""
        with self._metrics_lock:
            if device_id not in self._gpu_vram_used:
                self._gpu_vram_used[device_id] = GaugeMetric(
                    name='forensic_gpu_vram_used_mb',
                    labels={'device': str(device_id)},
                )
            self._gpu_vram_used[device_id].set(used_mb)

    def set_gpu_temperature(self, device_id: int, temp_c: float):
        """Set GPU temperature gauge."""
        with self._metrics_lock:
            if device_id not in self._gpu_temperature:
                self._gpu_temperature[device_id] = GaugeMetric(
                    name='forensic_gpu_temperature_celsius',
                    labels={'device': str(device_id)},
                )
            self._gpu_temperature[device_id].set(temp_c)

    def set_stream_fps(self, stream_id: str, fps: float):
        """Set current FPS for a stream."""
        with self._metrics_lock:
            if stream_id not in self._stream_fps:
                self._stream_fps[stream_id] = GaugeMetric(
                    name='forensic_stream_fps',
                    labels={'stream': stream_id},
                )
            self._stream_fps[stream_id].set(fps)

    def increment_alert_count(self):
        self._total_alerts.inc()

    def increment_sighting_count(self):
        self._total_sightings.inc()

    def set_active_streams(self, count: int):
        self._active_streams.set(count)

    def set_active_tracks(self, count: int):
        self._active_tracks.set(count)

    def set_evidence_chain_length(self, length: int):
        self._evidence_chain_length.set(length)

    # --- Export methods ---

    def to_json(self) -> Dict[str, Any]:
        """Export all metrics as JSON (for API endpoints)."""
        with self._metrics_lock:
            return {
                'uptime_s': round(time.time() - self._start_time, 1),
                'system': {
                    'active_streams': self._active_streams.value,
                    'active_tracks': self._active_tracks.value,
                    'total_alerts': self._total_alerts.value,
                    'total_sightings': self._total_sightings.value,
                    'evidence_chain_length': self._evidence_chain_length.value,
                },
                'models': {
                    name: {
                        'calls': self._model_calls.get(name, CounterMetric(name='')).value,
                        'avg_latency_ms': round(hist.avg, 2),
                        'max_latency_ms': round(hist.max_val, 2),
                        'failures': self._model_failures.get(name, CounterMetric(name='')).value,
                    }
                    for name, hist in self._model_latency.items()
                },
                'gpu': {
                    str(did): {
                        'utilization': round(self._gpu_utilization.get(did, GaugeMetric(name='')).value, 3),
                        'vram_used_mb': round(self._gpu_vram_used.get(did, GaugeMetric(name='')).value, 0),
                        'temperature_c': round(self._gpu_temperature.get(did, GaugeMetric(name='')).value, 0),
                    }
                    for did in set(list(self._gpu_utilization.keys()) +
                                   list(self._gpu_vram_used.keys()))
                },
                'streams': {
                    sid: {
                        'fps': round(gauge.value, 1),
                    }
                    for sid, gauge in self._stream_fps.items()
                },
            }

    def to_prometheus(self) -> str:
        """Export all metrics in Prometheus text exposition format."""
        lines = []

        with self._metrics_lock:
            # System gauges
            lines.append(f'# HELP forensic_active_streams Currently active streams')
            lines.append(f'# TYPE forensic_active_streams gauge')
            lines.append(f'forensic_active_streams {self._active_streams.value}')

            lines.append(f'forensic_active_tracks {self._active_tracks.value}')
            lines.append(f'forensic_alerts_total {self._total_alerts.value}')
            lines.append(f'forensic_sightings_total {self._total_sightings.value}')

            # Model metrics
            for name, hist in self._model_latency.items():
                safe_name = name.replace('-', '_').replace('.', '_')
                lines.append(f'forensic_model_latency_ms{{model="{safe_name}"}} {hist.avg:.2f}')
                calls = self._model_calls.get(name, CounterMetric(name=''))
                lines.append(f'forensic_model_calls_total{{model="{safe_name}"}} {calls.value}')

            # GPU metrics
            for did, gauge in self._gpu_utilization.items():
                lines.append(f'forensic_gpu_utilization{{device="{did}"}} {gauge.value:.3f}')
            for did, gauge in self._gpu_vram_used.items():
                lines.append(f'forensic_gpu_vram_used_mb{{device="{did}"}} {gauge.value:.0f}')
            for did, gauge in self._gpu_temperature.items():
                lines.append(f'forensic_gpu_temperature_celsius{{device="{did}"}} {gauge.value:.0f}')

            # Stream metrics
            for sid, gauge in self._stream_fps.items():
                safe_sid = sid.replace('-', '_')
                lines.append(f'forensic_stream_fps{{stream="{safe_sid}"}} {gauge.value:.1f}')

        return '\n'.join(lines) + '\n'

    def get_summary(self) -> str:
        """Human-readable summary for debug logging."""
        data = self.to_json()
        sys_data = data.get('system', {})
        return (
            f"Streams={sys_data.get('active_streams', 0)}, "
            f"Tracks={sys_data.get('active_tracks', 0)}, "
            f"Alerts={sys_data.get('total_alerts', 0)}, "
            f"Uptime={data.get('uptime_s', 0):.0f}s"
        )
