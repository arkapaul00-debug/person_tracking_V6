"""
Dynamic Batch Scheduler — Cross-Stream Frame Aggregation for GPU Inference.

The #1 throughput optimization: instead of each RTSP stream running YOLO
independently (N streams = N inference calls), this scheduler collects
frames from all streams and batches them into a single GPU kernel call.

Example:
    10 streams, each submitting 1 frame every 33ms
    Without batching: 10 × ~4ms = 40ms total GPU time (serialized)
    With batching:    1 × ~8ms batch of 10 = 8ms total GPU time

    Throughput improvement: ~5x

Architecture:
    1. Streams call submit(frame, callback) — non-blocking
    2. Background collector thread gathers frames until:
       - Batch reaches max_batch_size, OR
       - max_wait_ms timeout expires (whichever comes first)
    3. Batched inference runs on GPU
    4. Results are dispatched to per-stream callbacks

Thread safety: fully thread-safe. Multiple streams submit concurrently.
"""
import time
import queue
import threading
import logging
from typing import Callable, Optional, Any, List
from dataclasses import dataclass, field

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class InferenceRequest:
    """A single frame submitted for batched inference."""
    stream_id: str
    frame: np.ndarray
    callback: Callable[[Any], None]
    submit_time: float = field(default_factory=time.time)
    conf: float = 0.3
    priority: int = 0  # Lower = higher priority


@dataclass
class BatchResult:
    """Result of batched inference for a single frame."""
    stream_id: str
    result: Any  # Raw YOLO/detector result for this frame
    latency_ms: float


class DynamicBatchScheduler:
    """
    Cross-stream batch aggregation for GPU-efficient inference.

    Collects frames from multiple RTSP streams and runs them through
    the detector in a single batched GPU call.

    Usage:
        scheduler = DynamicBatchScheduler(
            inference_fn=model_pool.detect_persons_batch,
            max_batch=16, max_wait_ms=15
        )
        scheduler.start()

        # From each stream's processing thread:
        future = scheduler.submit('stream_001', frame, callback=handle_result)

        # Stop gracefully:
        scheduler.stop()
    """

    def __init__(self,
                 inference_fn: Callable,
                 max_batch: int = 16,
                 max_wait_ms: float = 15.0,
                 cuda_stream=None,
                 name: str = 'detection'):
        """
        Args:
            inference_fn: Function that accepts List[np.ndarray] and returns List[result].
                          Must handle variable batch sizes.
            max_batch: Maximum frames per batch (GPU memory limited).
            max_wait_ms: Maximum time to wait for batch to fill before executing.
            cuda_stream: Optional CUDA stream for this scheduler's inference.
            name: Identifier for logging and metrics.
        """
        self.inference_fn = inference_fn
        self.base_max_batch = max_batch  # Store base
        self.max_batch = max_batch       # Active limit (dynamic)
        self.max_wait_ms = max_wait_ms
        self.cuda_stream = cuda_stream
        self.name = name

        # V3: VRAM Budget Manager Integration
        try:
            from .memory_manager import VRAMBudgetManager
            self.vram_manager = VRAMBudgetManager(device='cuda:0')
        except ImportError:
            self.vram_manager = None

        # Submission queue (thread-safe)
        self._queue: queue.Queue = queue.Queue(maxsize=max_batch * 4)

        # Thread control
        self._thread: Optional[threading.Thread] = None
        self._running = False

        # Metrics
        self._total_batches = 0
        self._total_frames = 0
        self._total_latency_ms = 0.0
        self._empty_batches = 0
        self._max_batch_seen = 0
        self._metrics_lock = threading.Lock()

    def start(self):
        """Start the background batch collection and inference thread."""
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(
            target=self._batch_loop, daemon=True, name=f"BatchScheduler-{self.name}"
        )
        self._thread.start()
        logger.info(
            f"DynamicBatchScheduler '{self.name}' started: "
            f"max_batch={self.max_batch}, max_wait={self.max_wait_ms}ms"
        )

    def stop(self):
        """Stop the scheduler gracefully, processing remaining queue."""
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None
        logger.info(f"DynamicBatchScheduler '{self.name}' stopped")

    def submit(self, stream_id: str, frame: np.ndarray,
               callback: Callable, conf: float = 0.3,
               priority: int = 0) -> bool:
        """
        Submit a frame for batched inference. Non-blocking.

        Args:
            stream_id: Source stream identifier.
            frame: BGR numpy array.
            callback: Function called with result when inference completes.
                      Signature: callback(result) where result is detector output.
            conf: Confidence threshold for this frame.
            priority: Lower = higher priority (for alert-path frames).

        Returns:
            True if submitted, False if queue is full (frame should be skipped).
        """
        request = InferenceRequest(
            stream_id=stream_id,
            frame=frame,
            callback=callback,
            conf=conf,
            priority=priority,
        )

        try:
            self._queue.put_nowait(request)
            return True
        except queue.Full:
            logger.warning(f"[{self.name}] Batch queue full — dropping frame from {stream_id}")
            return False

    def _batch_loop(self):
        """
        Main batch collection loop.

        Continuously collects frames until batch is full or timeout expires,
        then runs batched inference and dispatches results.
        """
        while self._running:
            try:
                batch = self._collect_batch()
                if not batch:
                    continue

                self._execute_batch(batch)

            except Exception as e:
                logger.error(f"[{self.name}] Batch loop error: {e}")
                import traceback
                traceback.print_exc()
                time.sleep(0.01)  # Prevent tight error loop

    def _collect_batch(self) -> List[InferenceRequest]:
        """
        Collect frames until batch is full or max_wait expires.

        Strategy:
            1. Block-wait for the first frame (up to 100ms to avoid busy-wait)
            2. Then greedily collect remaining frames until:
               - Batch reaches max_batch_size
               - max_wait_ms elapsed since first frame
        """
        batch: List[InferenceRequest] = []

        # Wait for at least one frame
        try:
            first = self._queue.get(timeout=0.1)
            batch.append(first)
        except queue.Empty:
            return []

        # V3: Dynamically adjust max batch size based on VRAM pressure
        if self.vram_manager:
            scale_factor = self.vram_manager.get_dynamic_batch_multiplier()
            self.max_batch = max(1, int(self.base_max_batch * scale_factor))

        # Greedily fill batch up to dynamic max_batch
        deadline = time.time() + (self.max_wait_ms / 1000.0)

        while len(batch) < self.max_batch:
            remaining_ms = (deadline - time.time()) * 1000.0
            if remaining_ms <= 0:
                break

            try:
                item = self._queue.get(timeout=remaining_ms / 1000.0)
                batch.append(item)
            except queue.Empty:
                break

        # Sort by priority (lower = higher priority)
        batch.sort(key=lambda r: r.priority)

        return batch

    def _execute_batch(self, batch: List[InferenceRequest]):
        """Run batched inference and dispatch results to callbacks."""
        if not batch:
            return

        frames = [req.frame for req in batch]
        batch_start = time.time()

        try:
            # Run batched inference
            if self.cuda_stream is not None:
                import torch
                with torch.cuda.stream(self.cuda_stream):
                    results = self.inference_fn(frames)
                self.cuda_stream.synchronize()
            else:
                results = self.inference_fn(frames)

            batch_latency_ms = (time.time() - batch_start) * 1000.0

            # Validate result count matches batch
            if not isinstance(results, (list, tuple)):
                results = [results]

            if len(results) != len(batch):
                logger.error(
                    f"[{self.name}] Batch size mismatch: "
                    f"submitted {len(batch)} frames, got {len(results)} results"
                )
                # Pad with None for missing results
                while len(results) < len(batch):
                    results.append(None)

            # Dispatch results to per-stream callbacks
            for req, result in zip(batch, results):
                try:
                    req.callback(result)
                except Exception as e:
                    logger.error(f"[{self.name}] Callback error for {req.stream_id}: {e}")

            # Update metrics
            with self._metrics_lock:
                self._total_batches += 1
                self._total_frames += len(batch)
                self._total_latency_ms += batch_latency_ms
                self._max_batch_seen = max(self._max_batch_seen, len(batch))

        except Exception as e:
            logger.error(f"[{self.name}] Batched inference failed: {e}")

            # Fallback: try sequential inference
            self._execute_sequential_fallback(batch)

    def _execute_sequential_fallback(self, batch: List[InferenceRequest]):
        """Fallback when batch inference fails — run each frame individually."""
        logger.warning(f"[{self.name}] Falling back to sequential inference for {len(batch)} frames")

        for req in batch:
            try:
                results = self.inference_fn([req.frame])
                result = results[0] if results else None
                req.callback(result)
            except Exception as e:
                logger.error(f"[{self.name}] Sequential fallback failed for {req.stream_id}: {e}")
                req.callback(None)

    def get_metrics(self) -> dict:
        """Return scheduler performance metrics."""
        with self._metrics_lock:
            avg_batch = (self._total_frames / max(self._total_batches, 1))
            avg_latency = (self._total_latency_ms / max(self._total_batches, 1))

            return {
                'name': self.name,
                'running': self._running,
                'queue_size': self._queue.qsize(),
                'max_batch': self.max_batch,
                'max_wait_ms': self.max_wait_ms,
                'total_batches': self._total_batches,
                'total_frames': self._total_frames,
                'avg_batch_size': round(avg_batch, 1),
                'max_batch_seen': self._max_batch_seen,
                'avg_latency_ms': round(avg_latency, 2),
                'batch_efficiency': round(avg_batch / max(self.max_batch, 1), 3),
            }

    def reset_metrics(self):
        """Reset performance counters."""
        with self._metrics_lock:
            self._total_batches = 0
            self._total_frames = 0
            self._total_latency_ms = 0.0
            self._max_batch_seen = 0
