"""
GPU Worker Pool & Load Balancer — Multi-GPU Stream Assignment.

Manages the assignment of camera streams to GPU workers using:
  - VRAM-aware bin-packing (fit max streams per GPU)
  - Health-based routing (avoid overloaded/failed GPUs)
  - Dynamic rebalancing when GPUs join/leave or fail
  - Per-worker pipeline lifecycle management

Architecture:
    LoadBalancer (1 per node)
      └── GPUWorker (1 per GPU)
            └── DAGPipeline (1 per stream on this GPU)

Usage:
    balancer = LoadBalancer(device_ids=[0, 1, 2, 3])

    # Assign a stream to the best GPU
    worker_id = balancer.assign_stream('cam_001', estimated_vram_mb=400)

    # Remove a stream
    balancer.release_stream('cam_001')

    # Health monitoring
    status = balancer.get_cluster_status()
"""
import time
import threading
import logging
from typing import Optional, Dict, List, Set, Any
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class StreamAssignment:
    """Record of a stream assigned to a GPU worker."""
    stream_id: str
    worker_id: str
    device_id: int
    assigned_at: float
    estimated_vram_mb: float = 400.0
    status: str = 'active'  # 'active', 'paused', 'error'


@dataclass
class WorkerState:
    """State of a single GPU worker."""
    worker_id: str
    device_id: int
    max_streams: int = 10
    assigned_streams: Set[str] = field(default_factory=set)
    total_vram_mb: float = 0.0
    used_vram_mb: float = 0.0
    status: str = 'ready'  # 'ready', 'busy', 'overloaded', 'offline'
    last_health_check: float = 0.0
    error_count: int = 0


class GPUWorker:
    """
    Manages all streams assigned to a single GPU.

    Each worker runs on one GPU device and manages multiple DAG pipelines.
    """

    def __init__(self, device_id: int, max_streams: int = 10,
                 vram_budget_mb: float = 0.0):
        """
        Args:
            device_id: CUDA device index.
            max_streams: Maximum concurrent streams on this GPU.
            vram_budget_mb: Total VRAM available (0 = auto-detect).
        """
        self.device_id = device_id
        self.worker_id = f"gpu_{device_id}"
        self.max_streams = max_streams
        self._lock = threading.Lock()

        # Auto-detect VRAM if not specified
        if vram_budget_mb <= 0:
            self.vram_budget_mb = self._detect_vram()
        else:
            self.vram_budget_mb = vram_budget_mb

        # Track streams
        self._assignments: Dict[str, StreamAssignment] = {}
        self._used_vram_mb = 0.0

        # Health
        self._status = 'ready'
        self._error_count = 0
        self._last_health = time.time()

        logger.info(
            f"GPUWorker '{self.worker_id}' initialized: "
            f"device={device_id}, max_streams={max_streams}, "
            f"vram_budget={self.vram_budget_mb:.0f}MB"
        )

    def _detect_vram(self) -> float:
        """Auto-detect available VRAM."""
        try:
            import torch
            if torch.cuda.is_available() and self.device_id < torch.cuda.device_count():
                props = torch.cuda.get_device_properties(self.device_id)
                return props.total_mem / (1024 * 1024)
        except Exception:
            pass

        try:
            from ..gpu.gpu_monitor import GPUMonitor
            monitor = GPUMonitor(device_ids=[self.device_id])
            info = monitor.get_device_info(self.device_id)
            return info.vram_total_mb
        except Exception:
            pass

        return 4096.0  # Default 4GB

    def can_accept(self, estimated_vram_mb: float = 400.0) -> bool:
        """Check if this worker can accept another stream."""
        with self._lock:
            if self._status in ('overloaded', 'offline'):
                return False
            if len(self._assignments) >= self.max_streams:
                return False
            if self._used_vram_mb + estimated_vram_mb > self.vram_budget_mb * 0.85:
                return False  # Keep 15% VRAM headroom
            return True

    def assign(self, stream_id: str, estimated_vram_mb: float = 400.0) -> bool:
        """Assign a stream to this worker."""
        with self._lock:
            if stream_id in self._assignments:
                logger.warning(f"Stream '{stream_id}' already assigned to {self.worker_id}")
                return True

            if not self.can_accept(estimated_vram_mb):
                return False

            assignment = StreamAssignment(
                stream_id=stream_id,
                worker_id=self.worker_id,
                device_id=self.device_id,
                assigned_at=time.time(),
                estimated_vram_mb=estimated_vram_mb,
            )
            self._assignments[stream_id] = assignment
            self._used_vram_mb += estimated_vram_mb

            logger.info(
                f"Stream '{stream_id}' assigned to {self.worker_id} "
                f"(streams={len(self._assignments)}/{self.max_streams}, "
                f"vram={self._used_vram_mb:.0f}/{self.vram_budget_mb:.0f}MB)"
            )
            return True

    def release(self, stream_id: str) -> bool:
        """Release a stream from this worker."""
        with self._lock:
            assignment = self._assignments.pop(stream_id, None)
            if assignment:
                self._used_vram_mb -= assignment.estimated_vram_mb
                self._used_vram_mb = max(0, self._used_vram_mb)
                logger.info(f"Stream '{stream_id}' released from {self.worker_id}")
                return True
            return False

    @property
    def load_score(self) -> float:
        """Compute load score (0.0 = idle, 1.0 = fully loaded)."""
        stream_load = len(self._assignments) / max(self.max_streams, 1)
        vram_load = self._used_vram_mb / max(self.vram_budget_mb, 1)
        return 0.5 * stream_load + 0.5 * vram_load

    @property
    def stream_count(self) -> int:
        return len(self._assignments)

    def get_state(self) -> WorkerState:
        return WorkerState(
            worker_id=self.worker_id,
            device_id=self.device_id,
            max_streams=self.max_streams,
            assigned_streams=set(self._assignments.keys()),
            total_vram_mb=self.vram_budget_mb,
            used_vram_mb=self._used_vram_mb,
            status=self._status,
            last_health_check=self._last_health,
            error_count=self._error_count,
        )


class LoadBalancer:
    """
    Multi-GPU load balancer with health-aware stream assignment.

    Assigns camera streams to GPU workers using bin-packing with
    VRAM and stream count constraints.

    Usage:
        balancer = LoadBalancer(device_ids=[0, 1])

        worker_id = balancer.assign_stream('cam_001', estimated_vram_mb=350)
        worker_id = balancer.assign_stream('cam_002', estimated_vram_mb=350)

        status = balancer.get_cluster_status()
        balancer.release_stream('cam_001')
    """

    def __init__(self, device_ids: Optional[List[int]] = None,
                 max_streams_per_gpu: int = 10,
                 strategy: str = 'least_loaded'):
        """
        Args:
            device_ids: GPU device IDs. None = auto-detect.
            max_streams_per_gpu: Max concurrent streams per GPU.
            strategy: 'least_loaded', 'round_robin', or 'bin_pack'.
        """
        if device_ids is None:
            device_ids = self._detect_gpus()

        self.strategy = strategy
        self._workers: Dict[str, GPUWorker] = {}
        self._stream_map: Dict[str, str] = {}  # stream_id → worker_id
        self._lock = threading.Lock()
        self._round_robin_idx = 0

        for did in device_ids:
            worker = GPUWorker(
                device_id=did,
                max_streams=max_streams_per_gpu,
            )
            self._workers[worker.worker_id] = worker

        logger.info(
            f"LoadBalancer initialized: {len(device_ids)} GPUs, "
            f"strategy={strategy}, max_streams/gpu={max_streams_per_gpu}"
        )

    def _detect_gpus(self) -> List[int]:
        """Auto-detect available GPUs."""
        try:
            import torch
            return list(range(torch.cuda.device_count()))
        except Exception:
            return [0]

    def assign_stream(self, stream_id: str,
                      estimated_vram_mb: float = 400.0) -> Optional[str]:
        """
        Assign a stream to the best available GPU worker.

        Args:
            stream_id: Camera stream identifier.
            estimated_vram_mb: Estimated VRAM needed for this stream's pipeline.

        Returns:
            worker_id if assigned, None if no capacity available.
        """
        with self._lock:
            if stream_id in self._stream_map:
                return self._stream_map[stream_id]

            worker = self._select_worker(estimated_vram_mb)
            if worker is None:
                logger.error(f"No GPU capacity for stream '{stream_id}'")
                return None

            if worker.assign(stream_id, estimated_vram_mb):
                self._stream_map[stream_id] = worker.worker_id
                return worker.worker_id

            return None

    def release_stream(self, stream_id: str):
        """Release a stream assignment."""
        with self._lock:
            worker_id = self._stream_map.pop(stream_id, None)
            if worker_id and worker_id in self._workers:
                self._workers[worker_id].release(stream_id)

    def _select_worker(self, estimated_vram_mb: float) -> Optional[GPUWorker]:
        """Select the best worker based on strategy."""
        candidates = [
            w for w in self._workers.values()
            if w.can_accept(estimated_vram_mb)
        ]

        if not candidates:
            return None

        if self.strategy == 'least_loaded':
            return min(candidates, key=lambda w: w.load_score)
        elif self.strategy == 'round_robin':
            idx = self._round_robin_idx % len(candidates)
            self._round_robin_idx += 1
            return candidates[idx]
        elif self.strategy == 'bin_pack':
            # Bin-pack: prefer the most loaded GPU that still has room
            return max(candidates, key=lambda w: w.load_score)
        else:
            return candidates[0]

    def get_stream_worker(self, stream_id: str) -> Optional[str]:
        """Get the worker assigned to a stream."""
        return self._stream_map.get(stream_id)

    def get_cluster_status(self) -> Dict[str, Any]:
        """Get status of all GPU workers."""
        workers = {}
        total_streams = 0
        total_capacity = 0

        for wid, worker in self._workers.items():
            state = worker.get_state()
            workers[wid] = {
                'device_id': state.device_id,
                'streams': len(state.assigned_streams),
                'max_streams': state.max_streams,
                'vram_used_mb': round(state.used_vram_mb, 0),
                'vram_total_mb': round(state.total_vram_mb, 0),
                'load_score': round(worker.load_score, 3),
                'status': state.status,
            }
            total_streams += len(state.assigned_streams)
            total_capacity += state.max_streams

        return {
            'worker_count': len(self._workers),
            'total_streams': total_streams,
            'total_capacity': total_capacity,
            'utilization': round(total_streams / max(total_capacity, 1), 3),
            'strategy': self.strategy,
            'workers': workers,
        }

    @property
    def total_streams(self) -> int:
        return len(self._stream_map)

    @property
    def available_capacity(self) -> int:
        return sum(
            w.max_streams - w.stream_count
            for w in self._workers.values()
        )
