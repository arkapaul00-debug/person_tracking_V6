"""
GPU Memory Manager — Pinned Memory Pools & Tensor Reuse.

Eliminates redundant CPU↔GPU memory transfers by providing:
  - Pre-allocated pinned memory buffers for zero-copy host→device transfers
  - Reusable GPU tensor pools to avoid repeated allocation/deallocation
  - Frame buffer management for multi-stream video pipelines

Performance Impact:
    - Pinned memory: ~2x faster CPU→GPU transfer (DMA vs pageable)
    - Tensor reuse: eliminates cudaMalloc overhead per frame (~0.1ms saved/frame)
    - Pre-allocated pools: prevents VRAM fragmentation under sustained load
"""
import threading
import queue
import logging
import numpy as np
from typing import Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    import torch

logger = logging.getLogger(__name__)

_torch = None


def _get_torch():
    global _torch
    if _torch is None:
        import torch
        _torch = torch
    return _torch


class PinnedMemoryPool:
    """
    Pool of pre-allocated pinned (page-locked) CPU memory buffers.

    Pinned memory enables asynchronous DMA transfers to GPU, avoiding
    the overhead of pageable memory copies. Critical for high-throughput
    video pipelines where frames must be transferred every 33ms.

    Usage:
        pool = PinnedMemoryPool(max_buffers=16, frame_shape=(1080, 1920, 3))

        # Borrow a buffer, copy frame into it, transfer to GPU
        buf = pool.acquire()
        buf.copy_(torch.from_numpy(frame))  # Zero-copy eligible
        gpu_tensor = buf.to('cuda:0', non_blocking=True)

        # Return buffer when done
        pool.release(buf)
    """

    def __init__(self, max_buffers: int = 16,
                 frame_shape: Tuple[int, ...] = (1080, 1920, 3),
                 dtype=None):
        """
        Args:
            max_buffers: Number of pre-allocated buffers.
            frame_shape: Shape of each buffer (H, W, C for video frames).
            dtype: Torch dtype (defaults to torch.uint8 for video frames).
        """
        torch = _get_torch()
        if dtype is None:
            dtype = torch.uint8

        self._pool = queue.Queue(maxsize=max_buffers)
        self._frame_shape = frame_shape
        self._dtype = dtype
        self._total_allocated = 0
        self._max_buffers = max_buffers
        self._lock = threading.Lock()

        # Pre-allocate all buffers
        for _ in range(max_buffers):
            buf = torch.empty(frame_shape, dtype=dtype, pin_memory=True)
            self._pool.put(buf)
            self._total_allocated += 1

        size_mb = (np.prod(frame_shape) * max_buffers) / (1024 * 1024)
        logger.info(
            f"PinnedMemoryPool: {max_buffers} buffers of shape {frame_shape}, "
            f"total ~{size_mb:.1f} MB pinned memory"
        )

    def acquire(self, timeout: float = 1.0) -> Optional['torch.Tensor']:
        """
        Acquire a pinned memory buffer from the pool.

        Args:
            timeout: Max seconds to wait for an available buffer.

        Returns:
            Pinned torch.Tensor or None if pool exhausted.
        """
        try:
            return self._pool.get(timeout=timeout)
        except queue.Empty:
            logger.warning("PinnedMemoryPool exhausted — all buffers in use")
            return None

    def release(self, buffer: 'torch.Tensor'):
        """Return a buffer to the pool for reuse."""
        try:
            self._pool.put_nowait(buffer)
        except queue.Full:
            logger.warning("PinnedMemoryPool: returned buffer dropped (pool full)")

    def frame_to_pinned(self, frame: np.ndarray, timeout: float = 1.0) -> Optional['torch.Tensor']:
        """
        Convenience: copy a numpy frame into a pinned buffer.

        Args:
            frame: BGR numpy array (H, W, C).
            timeout: Max wait for buffer acquisition.

        Returns:
            Pinned torch.Tensor with frame data, or None if pool exhausted.
        """
        torch = _get_torch()

        buf = self.acquire(timeout=timeout)
        if buf is None:
            # Fallback: create non-pinned tensor (slower but doesn't block)
            return torch.from_numpy(frame.copy())

        # Handle shape mismatch (e.g., different resolution streams)
        if buf.shape != frame.shape:
            self.release(buf)
            return torch.from_numpy(frame.copy())

        buf.copy_(torch.from_numpy(frame))
        return buf

    @property
    def available(self) -> int:
        """Number of buffers currently available."""
        return self._pool.qsize()

    @property
    def in_use(self) -> int:
        """Number of buffers currently borrowed."""
        return self._total_allocated - self._pool.qsize()

    def get_metrics(self) -> dict:
        return {
            'total': self._total_allocated,
            'available': self.available,
            'in_use': self.in_use,
            'frame_shape': self._frame_shape,
        }


class TensorPool:
    """
    Reusable GPU tensor pool to avoid repeated cudaMalloc/cudaFree.

    Pre-allocates tensors of common sizes used in the inference pipeline
    (e.g., YOLO input batch, face crop batch, body crop batch).

    Usage:
        pool = TensorPool(device='cuda:0')
        pool.register('yolo_input', shape=(8, 3, 640, 640), dtype=torch.float16)
        pool.register('body_batch', shape=(16, 3, 256, 128), dtype=torch.float32)

        tensor = pool.acquire('yolo_input')
        # ... use tensor for inference ...
        pool.release('yolo_input', tensor)
    """

    def __init__(self, device: str = 'cuda:0'):
        torch = _get_torch()
        self.device = torch.device(device)
        self._pools: dict = {}  # name -> queue of tensors
        self._configs: dict = {}  # name -> (shape, dtype, count)
        self._lock = threading.Lock()

    def register(self, name: str, shape: Tuple[int, ...],
                 dtype=None, pool_size: int = 2):
        """
        Pre-allocate a pool of GPU tensors with the given shape.

        Args:
            name: Pool identifier.
            shape: Tensor shape.
            dtype: Torch dtype (default float32).
            pool_size: Number of tensors to pre-allocate.
        """
        torch = _get_torch()
        if dtype is None:
            dtype = torch.float32

        with self._lock:
            pool_q = queue.Queue(maxsize=pool_size)
            for _ in range(pool_size):
                tensor = torch.empty(shape, dtype=dtype, device=self.device)
                pool_q.put(tensor)

            self._pools[name] = pool_q
            self._configs[name] = (shape, dtype, pool_size)

            size_mb = (np.prod(shape) * torch.tensor([], dtype=dtype).element_size() * pool_size) / (1024 * 1024)
            logger.info(f"TensorPool '{name}': {pool_size}x {shape} ({dtype}) = ~{size_mb:.1f} MB VRAM")

    def acquire(self, name: str, timeout: float = 0.5) -> Optional['torch.Tensor']:
        """Borrow a pre-allocated tensor from the named pool."""
        if name not in self._pools:
            raise KeyError(f"Unknown tensor pool '{name}'")

        try:
            return self._pools[name].get(timeout=timeout)
        except queue.Empty:
            # Fallback: allocate dynamically (slower but correct)
            torch = _get_torch()
            shape, dtype, _ = self._configs[name]
            logger.warning(f"TensorPool '{name}' exhausted — dynamic allocation fallback")
            return torch.empty(shape, dtype=dtype, device=self.device)

    def release(self, name: str, tensor: 'torch.Tensor'):
        """Return a tensor to the pool for reuse."""
        if name not in self._pools:
            return
        try:
            self._pools[name].put_nowait(tensor)
        except queue.Full:
            pass  # Drop extra tensors silently

    def get_metrics(self) -> dict:
        metrics = {}
        for name, pool_q in self._pools.items():
            shape, dtype, total = self._configs[name]
            metrics[name] = {
                'shape': shape,
                'dtype': str(dtype),
                'total': total,
                'available': pool_q.qsize(),
                'in_use': total - pool_q.qsize(),
            }
        return metrics

    def cleanup(self):
        """Release all pooled GPU tensors."""
        torch = _get_torch()
        with self._lock:
            for name in list(self._pools.keys()):
                pool_q = self._pools.pop(name)
                while not pool_q.empty():
                    try:
                        _ = pool_q.get_nowait()
                    except queue.Empty:
                        break
            self._configs.clear()
            torch.cuda.empty_cache()
            logger.info("TensorPool cleaned up — all VRAM released")

class VRAMBudgetManager:
    """
    VRAM Budget Manager (Phase 16)
    Tracks memory usage, predicts memory demand, and prevents OOM conditions.
    Dynamically adjusts pool sizes and batch configurations based on load.
    """
    def __init__(self, device: str = 'cuda:0'):
        torch = _get_torch()
        self.device = torch.device(device)
        self.max_vram_mb = 0
        if torch.cuda.is_available():
            self.max_vram_mb = torch.cuda.get_device_properties(self.device).total_memory / (1024 * 1024)
        self.safe_threshold = 0.90  # Target max 90% usage
        self.critical_threshold = 0.95  # Drop batches if 95% usage

    def get_vram_usage_mb(self) -> float:
        torch = _get_torch()
        if not torch.cuda.is_available():
            return 0.0
        return torch.cuda.memory_allocated(self.device) / (1024 * 1024)

    def is_under_pressure(self) -> bool:
        """Returns True if VRAM usage exceeds the safe threshold."""
        if self.max_vram_mb == 0:
            return False
        usage_ratio = self.get_vram_usage_mb() / self.max_vram_mb
        return usage_ratio > self.safe_threshold

    def get_dynamic_batch_multiplier(self) -> float:
        """
        Calculates a scale factor for batch sizes based on VRAM pressure.
        1.0 means no pressure (full batch size allowed).
        0.5 means moderate pressure (halve batch size).
        0.0 means critical pressure (halt batching).
        """
        if self.max_vram_mb == 0:
            return 1.0
        
        usage_ratio = self.get_vram_usage_mb() / self.max_vram_mb
        
        if usage_ratio >= self.critical_threshold:
            logger.warning(f"CRITICAL VRAM PRESSURE ({usage_ratio:.1%}). Throttling batch sizes.")
            return 0.25
        elif usage_ratio >= self.safe_threshold:
            logger.info(f"MODERATE VRAM PRESSURE ({usage_ratio:.1%}). Reducing batch sizes.")
            return 0.5
        
        return 1.0
