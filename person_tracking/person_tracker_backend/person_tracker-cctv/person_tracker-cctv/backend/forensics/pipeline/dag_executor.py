"""
DAG Pipeline Executor — Asynchronous Stage-Based Execution Engine.

Replaces the monolithic _run_loop in StreamProcessor with a Directed Acyclic
Graph of independent processing stages, each running in its own thread with
async queue-based communication.

Architecture:
    ┌─────────┐    ┌────────┐    ┌────────────┐    ┌────────┐    ┌───────┐
    │ Ingest  │───→│ Decode │───→│ Preprocess │───→│ Detect │───→│ Track │
    └─────────┘    └────────┘    └────────────┘    └────────┘    └───┬───┘
                                                                     │
    ┌──────────┐    ┌─────────┐    ┌───────────┐    ┌───────────┐    │
    │ Evidence │←───│  Event  │←───│ Analytics │←───│ Recognize │←───┘
    └──────────┘    └─────────┘    └───────────┘    └───────────┘

Benefits:
    - Each stage runs independently (no global blocking)
    - Backpressure handling via bounded queues
    - Per-stage metrics (throughput, latency, queue depth)
    - Stage-level failure isolation (one stage crash doesn't kill pipeline)
    - Dynamic worker count per stage
    - Priority-based scheduling for alert-path frames
"""
import time
import queue
import threading
import logging
from collections import OrderedDict
from typing import Any, Dict, Optional, Callable, List
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class StageStatus(Enum):
    IDLE = 'idle'
    RUNNING = 'running'
    PAUSED = 'paused'
    STOPPED = 'stopped'
    ERROR = 'error'


@dataclass
class FramePacket:
    """
    Unit of data flowing through the pipeline.
    
    Carries the frame, metadata, and accumulated results from each stage.
    Acts as the shared context that all stages read from and write to.
    """
    # Identity
    stream_id: str = ''
    frame_id: int = 0
    timestamp: float = 0.0
    
    # Frame data
    frame: Any = None              # BGR numpy array (raw from camera)
    decoded_frame: Any = None      # GPU-decoded frame (if NVDEC available)
    preprocessed_frame: Any = None # Enhanced frame (if low-light)
    
    # Detection results (filled by stage_detect)
    detections: List[Any] = field(default_factory=list)
    scene_context: Any = None
    person_boxes: List[list] = field(default_factory=list)
    
    # Tracking results (filled by stage_track)
    tracks: List[Any] = field(default_factory=list)
    tracker_input: Any = None
    
    # Recognition results (filled by stage_recognize)
    face_results: List[Any] = field(default_factory=list)
    body_results: List[Any] = field(default_factory=list)
    face_map: Dict[int, Any] = field(default_factory=dict)
    
    # Match results (filled by stage_recognize)
    match_scores: Dict[int, float] = field(default_factory=dict)  # track_id -> score
    match_details: Dict[int, dict] = field(default_factory=dict)  # track_id -> breakdown
    confirmed_targets: List[int] = field(default_factory=list)     # track_ids confirmed
    
    # Analytics (filled by stage_analytics)
    risk_scores: Dict[int, float] = field(default_factory=dict)
    anomalies: List[Any] = field(default_factory=list)
    
    # Evidence (filled by stage_event / stage_evidence)
    alerts_generated: List[Any] = field(default_factory=list)
    evidence_hashes: List[str] = field(default_factory=list)
    
    # Pipeline metadata
    priority: int = 0              # Lower = higher priority
    skip_recognition: bool = False  # True for frames that should skip ReID
    is_inference_frame: bool = True # False for skipped frames (adaptive stride)
    processing_times: Dict[str, float] = field(default_factory=dict)  # stage -> ms
    errors: Dict[str, str] = field(default_factory=dict)


@dataclass
class StageMetrics:
    """Performance metrics for a single pipeline stage."""
    name: str = ''
    status: str = 'idle'
    processed: int = 0
    dropped: int = 0
    errors: int = 0
    avg_latency_ms: float = 0.0
    max_latency_ms: float = 0.0
    total_latency_ms: float = 0.0
    queue_depth: int = 0
    queue_capacity: int = 0
    throughput_fps: float = 0.0
    last_processed_at: float = 0.0


class PipelineStage:
    """
    Base class for all pipeline stages.
    
    Subclasses must implement process(packet) -> packet.
    """
    
    def __init__(self, name: str):
        self.name = name
    
    def process(self, packet: FramePacket) -> Optional[FramePacket]:
        """
        Process a single frame packet.
        
        Args:
            packet: Input frame packet with accumulated data.
            
        Returns:
            Modified packet, or None to drop the frame.
        """
        raise NotImplementedError(f"Stage '{self.name}' must implement process()")
    
    def setup(self):
        """Called once when the stage starts. Override for initialization."""
        pass
    
    def teardown(self):
        """Called once when the stage stops. Override for cleanup."""
        pass


class StageRunner:
    """
    Wraps a PipelineStage with threading, queuing, and metrics.
    
    Manages the lifecycle of a stage: queue → process → output.
    """
    
    def __init__(self, stage: PipelineStage,
                 input_queue: queue.Queue,
                 output_queue: Optional[queue.Queue],
                 num_workers: int = 1):
        self.stage = stage
        self.input_queue = input_queue
        self.output_queue = output_queue
        self.num_workers = num_workers
        self.status = StageStatus.IDLE
        self._threads: List[threading.Thread] = []
        self._running = False
        
        # Metrics
        self._processed = 0
        self._dropped = 0
        self._errors = 0
        self._total_latency = 0.0
        self._max_latency = 0.0
        self._metrics_lock = threading.Lock()
        self._start_time = 0.0
    
    def start(self):
        """Start stage worker threads."""
        self._running = True
        self._start_time = time.time()
        self.status = StageStatus.RUNNING
        
        try:
            self.stage.setup()
        except Exception as e:
            logger.error(f"Stage '{self.stage.name}' setup failed: {e}")
            self.status = StageStatus.ERROR
            return
        
        for i in range(self.num_workers):
            t = threading.Thread(
                target=self._worker_loop,
                name=f"Stage-{self.stage.name}-{i}",
                daemon=True,
            )
            t.start()
            self._threads.append(t)
        
        logger.debug(f"Stage '{self.stage.name}' started ({self.num_workers} workers)")
    
    def stop(self):
        """Stop stage gracefully."""
        self._running = False
        self.status = StageStatus.STOPPED
        
        # Drain input queue to unblock workers
        for _ in range(self.num_workers):
            try:
                self.input_queue.put_nowait(None)  # Sentinel
            except queue.Full:
                pass
        
        for t in self._threads:
            t.join(timeout=5.0)
        
        try:
            self.stage.teardown()
        except Exception as e:
            logger.error(f"Stage '{self.stage.name}' teardown error: {e}")
        
        logger.debug(f"Stage '{self.stage.name}' stopped")
    
    def _worker_loop(self):
        """Main worker loop: dequeue → process → enqueue."""
        while self._running:
            try:
                # Dequeue with timeout (allows checking _running flag)
                try:
                    packet = self.input_queue.get(timeout=0.5)
                except queue.Empty:
                    continue
                
                if packet is None:
                    break  # Sentinel
                
                # Process
                t_start = time.time()
                try:
                    result = self.stage.process(packet)
                except Exception as e:
                    logger.error(f"Stage '{self.stage.name}' process error: {e}")
                    with self._metrics_lock:
                        self._errors += 1
                    packet.errors[self.stage.name] = str(e)
                    result = packet  # Pass through on error
                
                latency_ms = (time.time() - t_start) * 1000
                
                # Update metrics
                with self._metrics_lock:
                    self._processed += 1
                    self._total_latency += latency_ms
                    self._max_latency = max(self._max_latency, latency_ms)
                
                # Record timing in packet
                if result is not None:
                    result.processing_times[self.stage.name] = latency_ms
                
                # Enqueue to next stage
                if result is not None and self.output_queue is not None:
                    try:
                        self.output_queue.put(result, timeout=1.0)
                    except queue.Full:
                        with self._metrics_lock:
                            self._dropped += 1
                        logger.warning(
                            f"Stage '{self.stage.name}' output full — dropping frame "
                            f"{result.frame_id} from {result.stream_id}"
                        )
                
            except Exception as e:
                logger.error(f"Stage '{self.stage.name}' worker error: {e}")
                with self._metrics_lock:
                    self._errors += 1
    
    def get_metrics(self) -> StageMetrics:
        """Get current stage metrics."""
        with self._metrics_lock:
            elapsed = max(time.time() - self._start_time, 1.0)
            return StageMetrics(
                name=self.stage.name,
                status=self.status.value,
                processed=self._processed,
                dropped=self._dropped,
                errors=self._errors,
                avg_latency_ms=round(
                    self._total_latency / max(self._processed, 1), 2
                ),
                max_latency_ms=round(self._max_latency, 2),
                total_latency_ms=round(self._total_latency, 2),
                queue_depth=self.input_queue.qsize(),
                queue_capacity=self.input_queue.maxsize,
                throughput_fps=round(self._processed / elapsed, 1),
                last_processed_at=time.time(),
            )


class DAGPipelineExecutor:
    """
    Asynchronous pipeline executor connecting stages via queues.
    
    Usage:
        pipeline = DAGPipelineExecutor(stream_id='cam_001')
        
        pipeline.add_stage('ingest', StageIngest(capture), workers=1, queue_size=32)
        pipeline.add_stage('detect', StageDetect(router), workers=1, queue_size=16)
        pipeline.add_stage('track', StageTrack(tracker), workers=1, queue_size=16)
        pipeline.add_stage('recognize', StageRecognize(face, body), workers=1, queue_size=16)
        pipeline.add_stage('event', StageEvent(alert_mgr), workers=1, queue_size=32)
        
        pipeline.connect('ingest', 'detect')
        pipeline.connect('detect', 'track')
        pipeline.connect('track', 'recognize')
        pipeline.connect('recognize', 'event')
        
        pipeline.start()
        
        # Monitor
        metrics = pipeline.get_metrics()
        
        pipeline.stop()
    """
    
    def __init__(self, stream_id: str = '', config: Optional[dict] = None):
        self.stream_id = stream_id
        self.config = config or {}
        
        self._stages: OrderedDict[str, StageRunner] = OrderedDict()
        self._queues: Dict[str, queue.Queue] = {}  # stage_name -> input_queue
        self._connections: List[tuple] = []  # (source, target) pairs
        self._running = False
        
        logger.info(f"DAGPipelineExecutor created for stream '{stream_id}'")
    
    def add_stage(self, name: str, stage: PipelineStage,
                  workers: int = 1, queue_size: int = 32):
        """
        Add a stage to the pipeline.
        
        Args:
            name: Unique stage identifier.
            stage: PipelineStage instance.
            workers: Number of worker threads for this stage.
            queue_size: Input queue capacity (backpressure control).
        """
        input_q = queue.Queue(maxsize=queue_size)
        self._queues[name] = input_q
        
        runner = StageRunner(
            stage=stage,
            input_queue=input_q,
            output_queue=None,  # Set during connect()
            num_workers=workers,
        )
        self._stages[name] = runner
    
    def connect(self, source: str, target: str):
        """
        Connect the output of one stage to the input of another.
        
        Args:
            source: Source stage name.
            target: Target stage name.
        """
        if source not in self._stages:
            raise KeyError(f"Unknown source stage '{source}'")
        if target not in self._stages:
            raise KeyError(f"Unknown target stage '{target}'")
        
        self._stages[source].output_queue = self._queues[target]
        self._connections.append((source, target))
    
    def start(self):
        """Start all stages in the pipeline."""
        if self._running:
            return
        
        self._running = True
        
        # Start stages in order
        for name, runner in self._stages.items():
            runner.start()
        
        logger.info(
            f"Pipeline started for '{self.stream_id}': "
            f"{' → '.join(self._stages.keys())}"
        )
    
    def stop(self):
        """Stop all stages gracefully."""
        self._running = False
        
        # Stop in reverse order (drain from end to start)
        for name in reversed(list(self._stages.keys())):
            self._stages[name].stop()
        
        logger.info(f"Pipeline stopped for '{self.stream_id}'")
    
    def submit(self, packet: FramePacket):
        """
        Submit a frame packet to the first stage.
        
        Args:
            packet: Frame packet to process.
        """
        if not self._stages:
            return
        
        first_stage = next(iter(self._stages.keys()))
        first_queue = self._queues[first_stage]
        
        try:
            first_queue.put(packet, timeout=0.5)
        except queue.Full:
            logger.warning(f"Pipeline input full for '{self.stream_id}' — dropping frame")
    
    @property
    def is_running(self) -> bool:
        return self._running
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get metrics for all stages."""
        stage_metrics = {}
        total_latency = 0.0
        
        for name, runner in self._stages.items():
            m = runner.get_metrics()
            stage_metrics[name] = {
                'status': m.status,
                'processed': m.processed,
                'dropped': m.dropped,
                'errors': m.errors,
                'avg_latency_ms': m.avg_latency_ms,
                'max_latency_ms': m.max_latency_ms,
                'queue_depth': m.queue_depth,
                'queue_capacity': m.queue_capacity,
                'throughput_fps': m.throughput_fps,
            }
            total_latency += m.avg_latency_ms
        
        return {
            'stream_id': self.stream_id,
            'running': self._running,
            'stage_count': len(self._stages),
            'stages': stage_metrics,
            'total_pipeline_latency_ms': round(total_latency, 2),
            'connections': self._connections,
        }
    
    def get_stage_fps(self) -> Dict[str, float]:
        """Get per-stage throughput in FPS."""
        return {
            name: runner.get_metrics().throughput_fps
            for name, runner in self._stages.items()
        }
    
    def get_bottleneck(self) -> Optional[str]:
        """Identify the slowest stage (pipeline bottleneck)."""
        slowest = None
        max_latency = 0.0
        
        for name, runner in self._stages.items():
            m = runner.get_metrics()
            if m.avg_latency_ms > max_latency:
                max_latency = m.avg_latency_ms
                slowest = name
        
        return slowest
