"""
GPU Infrastructure Package — CUDA stream management, memory pooling,
batch scheduling, TensorRT runtime, and GPU monitoring.

Eliminates the global _inference_lock bottleneck by providing:
  - Per-model CUDA stream isolation
  - Cross-stream dynamic batch aggregation
  - Pinned memory pools for zero-copy transfers
  - TensorRT engine lifecycle management
  - Real-time GPU health monitoring
"""
from .cuda_stream_pool import CUDAStreamPool
from .memory_manager import PinnedMemoryPool, TensorPool
from .batch_scheduler import DynamicBatchScheduler
from .gpu_monitor import GPUMonitor

__all__ = [
    'CUDAStreamPool',
    'PinnedMemoryPool',
    'TensorPool',
    'DynamicBatchScheduler',
    'GPUMonitor',
]
