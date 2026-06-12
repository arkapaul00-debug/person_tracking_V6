"""
GPU Monitor — Real-Time GPU Health Tracking.

Provides live VRAM usage, SM occupancy, temperature, and power metrics
for load balancing decisions and observability dashboards.

Uses pynvml (NVIDIA Management Library) for hardware-level monitoring
without interfering with CUDA workloads.
"""
import time
import threading
import logging
from typing import Dict, Optional, List

logger = logging.getLogger(__name__)

# Lazy import — pynvml may not be installed in all environments
_nvml_initialized = False
_pynvml = None


def _init_nvml():
    global _nvml_initialized, _pynvml
    if _nvml_initialized:
        return _pynvml is not None

    try:
        import pynvml
        pynvml.nvmlInit()
        _pynvml = pynvml
        _nvml_initialized = True
        logger.info("NVML initialized for GPU monitoring")
        return True
    except ImportError:
        logger.warning("pynvml not installed — GPU monitoring will use torch.cuda fallback")
        _nvml_initialized = True
        return False
    except Exception as e:
        logger.warning(f"NVML initialization failed: {e}")
        _nvml_initialized = True
        return False


class GPUDeviceInfo:
    """Snapshot of a single GPU's state."""

    def __init__(self):
        self.device_id: int = 0
        self.name: str = "Unknown"
        self.vram_total_mb: float = 0.0
        self.vram_used_mb: float = 0.0
        self.vram_free_mb: float = 0.0
        self.vram_utilization: float = 0.0  # 0.0 - 1.0
        self.gpu_utilization: float = 0.0  # SM occupancy 0.0 - 1.0
        self.memory_utilization: float = 0.0  # Memory controller 0.0 - 1.0
        self.temperature_c: int = 0
        self.power_draw_w: float = 0.0
        self.power_limit_w: float = 0.0
        self.clock_sm_mhz: int = 0
        self.clock_mem_mhz: int = 0
        self.timestamp: float = 0.0

    def to_dict(self) -> dict:
        return {
            'device_id': self.device_id,
            'name': self.name,
            'vram_total_mb': round(self.vram_total_mb, 1),
            'vram_used_mb': round(self.vram_used_mb, 1),
            'vram_free_mb': round(self.vram_free_mb, 1),
            'vram_utilization': round(self.vram_utilization, 3),
            'gpu_utilization': round(self.gpu_utilization, 3),
            'temperature_c': self.temperature_c,
            'power_draw_w': round(self.power_draw_w, 1),
            'power_limit_w': round(self.power_limit_w, 1),
            'is_overloaded': self.vram_utilization > 0.90 or self.gpu_utilization > 0.95,
            'timestamp': self.timestamp,
        }


class GPUMonitor:
    """
    Real-time GPU health monitor for multi-GPU load balancing.

    Tracks VRAM usage, SM occupancy, temperature, and power per GPU.
    Supports both pynvml (preferred) and torch.cuda (fallback).

    Usage:
        monitor = GPUMonitor()
        info = monitor.get_device_info(0)
        print(f"GPU 0: {info.vram_used_mb}/{info.vram_total_mb} MB, {info.gpu_utilization*100:.0f}% util")

        if monitor.is_overloaded(0):
            # Redirect new streams to another GPU
            ...

        # Background monitoring mode
        monitor.start_background(interval=5.0)
    """

    def __init__(self, device_ids: Optional[List[int]] = None):
        """
        Args:
            device_ids: List of GPU device IDs to monitor. None = auto-detect all.
        """
        self._use_nvml = _init_nvml()
        self._device_ids = device_ids or self._detect_devices()
        self._latest: Dict[int, GPUDeviceInfo] = {}
        self._background_thread: Optional[threading.Thread] = None
        self._running = False
        self._lock = threading.Lock()

        logger.info(f"GPUMonitor tracking devices: {self._device_ids}")

    def _detect_devices(self) -> List[int]:
        """Auto-detect available GPU devices."""
        if self._use_nvml:
            count = _pynvml.nvmlDeviceGetCount()
            return list(range(count))

        try:
            import torch
            return list(range(torch.cuda.device_count()))
        except Exception:
            return []

    def get_device_info(self, device_id: int = 0) -> GPUDeviceInfo:
        """
        Get current state of a specific GPU.

        Args:
            device_id: GPU device index.

        Returns:
            GPUDeviceInfo snapshot.
        """
        info = GPUDeviceInfo()
        info.device_id = device_id
        info.timestamp = time.time()

        if self._use_nvml:
            self._populate_from_nvml(info, device_id)
        else:
            self._populate_from_torch(info, device_id)

        with self._lock:
            self._latest[device_id] = info

        return info

    def _populate_from_nvml(self, info: GPUDeviceInfo, device_id: int):
        """Populate GPU info using NVIDIA Management Library (preferred)."""
        try:
            handle = _pynvml.nvmlDeviceGetHandleByIndex(device_id)

            # Device name
            info.name = _pynvml.nvmlDeviceGetName(handle)
            if isinstance(info.name, bytes):
                info.name = info.name.decode('utf-8')

            # Memory
            mem = _pynvml.nvmlDeviceGetMemoryInfo(handle)
            info.vram_total_mb = mem.total / (1024 * 1024)
            info.vram_used_mb = mem.used / (1024 * 1024)
            info.vram_free_mb = mem.free / (1024 * 1024)
            info.vram_utilization = mem.used / max(mem.total, 1)

            # Utilization
            try:
                util = _pynvml.nvmlDeviceGetUtilizationRates(handle)
                info.gpu_utilization = util.gpu / 100.0
                info.memory_utilization = util.memory / 100.0
            except Exception:
                pass

            # Temperature
            try:
                info.temperature_c = _pynvml.nvmlDeviceGetTemperature(
                    handle, _pynvml.NVML_TEMPERATURE_GPU
                )
            except Exception:
                pass

            # Power
            try:
                info.power_draw_w = _pynvml.nvmlDeviceGetPowerUsage(handle) / 1000.0
                info.power_limit_w = _pynvml.nvmlDeviceGetPowerManagementLimit(handle) / 1000.0
            except Exception:
                pass

            # Clocks
            try:
                info.clock_sm_mhz = _pynvml.nvmlDeviceGetClockInfo(
                    handle, _pynvml.NVML_CLOCK_SM
                )
                info.clock_mem_mhz = _pynvml.nvmlDeviceGetClockInfo(
                    handle, _pynvml.NVML_CLOCK_MEM
                )
            except Exception:
                pass

        except Exception as e:
            logger.error(f"NVML query failed for device {device_id}: {e}")

    def _populate_from_torch(self, info: GPUDeviceInfo, device_id: int):
        """Fallback: populate GPU info using torch.cuda (less detailed)."""
        try:
            import torch
            if not torch.cuda.is_available() or device_id >= torch.cuda.device_count():
                return

            info.name = torch.cuda.get_device_name(device_id)

            mem_allocated = torch.cuda.memory_allocated(device_id) / (1024 * 1024)
            mem_reserved = torch.cuda.memory_reserved(device_id) / (1024 * 1024)

            props = torch.cuda.get_device_properties(device_id)
            info.vram_total_mb = props.total_mem / (1024 * 1024)
            info.vram_used_mb = mem_allocated
            info.vram_free_mb = info.vram_total_mb - mem_reserved
            info.vram_utilization = mem_reserved / max(info.vram_total_mb, 1)

        except Exception as e:
            logger.error(f"torch.cuda query failed for device {device_id}: {e}")

    def get_all_devices(self) -> Dict[int, GPUDeviceInfo]:
        """Get current state of all monitored GPUs."""
        return {did: self.get_device_info(did) for did in self._device_ids}

    def is_overloaded(self, device_id: int = 0,
                      vram_threshold: float = 0.90,
                      util_threshold: float = 0.95) -> bool:
        """
        Check if a GPU is overloaded (for load balancing decisions).

        Args:
            device_id: GPU to check.
            vram_threshold: VRAM usage fraction that triggers overload.
            util_threshold: SM utilization fraction that triggers overload.

        Returns:
            True if the GPU should not accept additional workload.
        """
        info = self.get_device_info(device_id)
        return (info.vram_utilization > vram_threshold or
                info.gpu_utilization > util_threshold)

    def get_least_loaded(self) -> int:
        """Return the device ID of the least loaded GPU (for stream assignment)."""
        if not self._device_ids:
            return 0

        infos = self.get_all_devices()
        # Score = weighted combination of VRAM usage and SM utilization
        scores = {}
        for did, info in infos.items():
            scores[did] = 0.6 * info.vram_utilization + 0.4 * info.gpu_utilization

        return min(scores, key=scores.get)

    def start_background(self, interval: float = 5.0):
        """
        Start background monitoring thread.

        Args:
            interval: Seconds between metric snapshots.
        """
        if self._running:
            return

        self._running = True
        self._background_thread = threading.Thread(
            target=self._monitor_loop, args=(interval,), daemon=True
        )
        self._background_thread.start()
        logger.info(f"GPUMonitor background thread started (interval={interval}s)")

    def _monitor_loop(self, interval: float):
        """Background thread that periodically samples GPU metrics."""
        while self._running:
            try:
                for did in self._device_ids:
                    self.get_device_info(did)
            except Exception as e:
                logger.error(f"GPU monitoring error: {e}")

            time.sleep(interval)

    def stop_background(self):
        """Stop the background monitoring thread."""
        self._running = False
        if self._background_thread is not None:
            self._background_thread.join(timeout=10.0)
            self._background_thread = None

    def get_cached(self, device_id: int = 0) -> Optional[GPUDeviceInfo]:
        """Get the most recent cached snapshot (non-blocking)."""
        with self._lock:
            return self._latest.get(device_id)

    def get_metrics_summary(self) -> dict:
        """Get summary of all GPU metrics for observability export."""
        with self._lock:
            return {
                'devices': {did: info.to_dict() for did, info in self._latest.items()},
                'device_count': len(self._device_ids),
                'monitoring_active': self._running,
            }
