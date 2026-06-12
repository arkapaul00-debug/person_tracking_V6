"""
Model Registry — Dynamic Model Loading, Versioning, and Lifecycle Management.

Provides a centralized registry for all AI models in the pipeline with:
  - Lazy loading: models loaded on first use, not at startup
  - Version tracking: model versions tied to engine files
  - Health monitoring: track inference counts, latencies, failures
  - Hot-swap: replace model weights without restarting the pipeline
  - Resource accounting: track VRAM usage per model

All engine components (DetectionRouter, FacePipeline, ReIDPipeline)
use this registry instead of directly instantiating models.
"""
import os
import time
import hashlib
import threading
import logging
from pathlib import Path
from typing import Optional, Dict, Any, Callable, List
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class ModelStatus(Enum):
    REGISTERED = 'registered'   # Known but not loaded
    LOADING = 'loading'         # Currently loading into VRAM
    READY = 'ready'             # Loaded and warmed up
    FAILED = 'failed'           # Load or inference failure
    UNLOADING = 'unloading'     # Being removed from VRAM
    DISABLED = 'disabled'       # Explicitly disabled


@dataclass
class ModelSpec:
    """Specification for a registered model."""
    name: str                          # Unique identifier (e.g., 'yolov11n')
    category: str                      # 'detection', 'face', 'body', 'enhancement'
    weight_path: str                   # Path to weights file
    framework: str = 'pytorch'         # 'pytorch', 'tensorrt', 'onnx', 'insightface'
    device: str = 'cuda:0'
    precision: str = 'fp16'            # 'fp32', 'fp16', 'int8'
    dynamic_batch: bool = False
    max_batch: int = 1
    lazy: bool = True                  # Load on first use
    priority: int = 0                  # Lower = loaded first at startup
    loader_fn: Optional[Callable] = None  # Custom loader function
    warmup_runs: int = 3
    version: str = ''                  # Auto-computed from file hash


@dataclass
class ModelInstance:
    """A loaded model instance with runtime state."""
    spec: ModelSpec
    model: Any = None                  # The actual model object
    status: ModelStatus = ModelStatus.REGISTERED
    load_time_s: float = 0.0
    vram_mb: float = 0.0
    infer_count: int = 0
    total_infer_ms: float = 0.0
    last_infer_ms: float = 0.0
    failure_count: int = 0
    last_error: str = ''
    loaded_at: float = 0.0
    lock: threading.Lock = field(default_factory=threading.Lock)


class ModelRegistry:
    """
    Centralized model lifecycle manager.

    Usage:
        registry = ModelRegistry()

        # Register models (does NOT load them yet if lazy=True)
        registry.register(ModelSpec(
            name='yolov11n', category='detection',
            weight_path='weights/yolov11n.engine',
            framework='tensorrt', precision='fp16',
        ))

        # Get a model (loads on first access if lazy)
        model = registry.get('yolov11n')

        # Check status
        info = registry.get_info('yolov11n')
        print(f"Status: {info.status}, Inferences: {info.infer_count}")

        # Hot-swap weights
        registry.reload('yolov11n', new_weight_path='weights/yolov11n_v2.engine')
    """

    def __init__(self):
        self._models: Dict[str, ModelInstance] = {}
        self._lock = threading.Lock()
        self._default_loaders: Dict[str, Callable] = {
            'pytorch': self._load_pytorch,
            'tensorrt': self._load_tensorrt,
            'onnx': self._load_onnx,
            'insightface': self._load_insightface,
            'ultralytics': self._load_ultralytics,
        }

        logger.info("ModelRegistry initialized")

    def register(self, spec: ModelSpec) -> bool:
        """
        Register a model specification.

        Args:
            spec: Model specification.

        Returns:
            True if registered successfully.
        """
        with self._lock:
            if spec.name in self._models:
                logger.warning(f"Model '{spec.name}' already registered — overwriting")

            # Compute version from file hash (if file exists)
            if spec.version == '' and os.path.exists(spec.weight_path):
                spec.version = self._compute_file_hash(spec.weight_path)

            instance = ModelInstance(spec=spec)
            self._models[spec.name] = instance

            logger.info(
                f"Registered: '{spec.name}' ({spec.framework}/{spec.precision}) "
                f"lazy={spec.lazy}, version={spec.version[:8] if spec.version else 'N/A'}"
            )

            # Load immediately if not lazy
            if not spec.lazy:
                self._load_model(instance)

            return True

    def get(self, name: str) -> Optional[Any]:
        """
        Get a loaded model instance. Triggers lazy loading if needed.

        Args:
            name: Model identifier.

        Returns:
            The model object, or None if unavailable.
        """
        instance = self._models.get(name)
        if instance is None:
            logger.error(f"Model '{name}' not registered")
            return None

        # Lazy load
        if instance.status == ModelStatus.REGISTERED:
            self._load_model(instance)

        if instance.status == ModelStatus.READY:
            return instance.model

        logger.warning(f"Model '{name}' not ready (status={instance.status.value})")
        return None

    def get_info(self, name: str) -> Optional[ModelInstance]:
        """Get model instance info (for monitoring)."""
        return self._models.get(name)

    def record_inference(self, name: str, latency_ms: float):
        """Record an inference event for metrics tracking."""
        instance = self._models.get(name)
        if instance:
            instance.infer_count += 1
            instance.total_infer_ms += latency_ms
            instance.last_infer_ms = latency_ms

    def record_failure(self, name: str, error: str):
        """Record an inference failure."""
        instance = self._models.get(name)
        if instance:
            instance.failure_count += 1
            instance.last_error = error

    def reload(self, name: str, new_weight_path: Optional[str] = None) -> bool:
        """
        Hot-swap model weights without pipeline restart.

        Args:
            name: Model identifier.
            new_weight_path: New weights file (None = reload same file).

        Returns:
            True if reload successful.
        """
        instance = self._models.get(name)
        if instance is None:
            logger.error(f"Cannot reload '{name}' — not registered")
            return False

        with instance.lock:
            # Unload current
            self._unload_model(instance)

            # Update path if provided
            if new_weight_path:
                instance.spec.weight_path = new_weight_path
                instance.spec.version = self._compute_file_hash(new_weight_path)

            # Reload
            return self._load_model(instance)

    def unload(self, name: str):
        """Unload a model from VRAM."""
        instance = self._models.get(name)
        if instance:
            with instance.lock:
                self._unload_model(instance)

    def _load_model(self, instance: ModelInstance) -> bool:
        """Internal: load a model into VRAM."""
        spec = instance.spec

        with instance.lock:
            if instance.status == ModelStatus.READY:
                return True

            instance.status = ModelStatus.LOADING
            t_start = time.time()

            try:
                # Use custom loader if provided
                if spec.loader_fn:
                    instance.model = spec.loader_fn(spec)
                else:
                    loader = self._default_loaders.get(spec.framework)
                    if loader is None:
                        raise ValueError(f"No loader for framework '{spec.framework}'")
                    instance.model = loader(spec)

                instance.load_time_s = time.time() - t_start
                instance.loaded_at = time.time()
                instance.status = ModelStatus.READY

                # Estimate VRAM usage
                instance.vram_mb = self._estimate_vram(spec)

                logger.info(
                    f"Loaded: '{spec.name}' in {instance.load_time_s:.1f}s "
                    f"(~{instance.vram_mb:.0f} MB VRAM)"
                )
                return True

            except Exception as e:
                instance.status = ModelStatus.FAILED
                instance.last_error = str(e)
                logger.error(f"Failed to load '{spec.name}': {e}")
                return False

    def _unload_model(self, instance: ModelInstance):
        """Internal: remove model from VRAM."""
        instance.status = ModelStatus.UNLOADING
        try:
            if instance.model is not None:
                del instance.model
                instance.model = None
            import torch
            torch.cuda.empty_cache()
            instance.status = ModelStatus.REGISTERED
            logger.info(f"Unloaded: '{instance.spec.name}'")
        except Exception as e:
            logger.error(f"Unload error for '{instance.spec.name}': {e}")
            instance.status = ModelStatus.FAILED

    # --- Default Loaders ---

    def _load_ultralytics(self, spec: ModelSpec) -> Any:
        """Load Ultralytics YOLO/RTDETR model."""
        from ultralytics import YOLO
        model = YOLO(spec.weight_path)
        if 'cuda' in spec.device:
            model.to(spec.device)
        # Warmup
        import numpy as np
        dummy = np.zeros((640, 640, 3), dtype=np.uint8)
        for _ in range(spec.warmup_runs):
            model(dummy, verbose=False)
        return model

    def _load_pytorch(self, spec: ModelSpec) -> Any:
        """Load a generic PyTorch model."""
        import torch
        model = torch.load(spec.weight_path, map_location=spec.device)
        if hasattr(model, 'eval'):
            model.eval()
        if spec.precision == 'fp16' and hasattr(model, 'half'):
            model.half()
        return model

    def _load_tensorrt(self, spec: ModelSpec) -> Any:
        """Load a TensorRT engine via the TRT runtime manager."""
        from ..gpu.trt_runtime import TRTEngineManager, EngineProfile
        manager = TRTEngineManager(device=spec.device)
        profile = EngineProfile(
            name=spec.name,
            engine_path=spec.weight_path,
            input_names=['images'],
            output_names=['output0'],
            input_shapes={'images': (spec.max_batch, 3, 640, 640)},
            output_shapes={'output0': (spec.max_batch, 8400, 85)},
            dtype=spec.precision.replace('fp', 'float'),
        )
        manager.register_engine(profile)
        manager.warmup(spec.name, num_runs=spec.warmup_runs)
        return manager

    def _load_onnx(self, spec: ModelSpec) -> Any:
        """Load an ONNX model via ONNX Runtime."""
        import onnxruntime as ort
        providers = ['CUDAExecutionProvider', 'CPUExecutionProvider']
        session = ort.InferenceSession(spec.weight_path, providers=providers)
        return session

    def _load_insightface(self, spec: ModelSpec) -> Any:
        """Load InsightFace model."""
        from ..ai_core.face_extractor import FaceReIDExtractor
        return FaceReIDExtractor(device=spec.device)

    # --- Utilities ---

    @staticmethod
    def _compute_file_hash(path: str, chunk_size: int = 8192) -> str:
        """Compute SHA-256 hash of a file for versioning."""
        sha = hashlib.sha256()
        try:
            with open(path, 'rb') as f:
                while True:
                    chunk = f.read(chunk_size)
                    if not chunk:
                        break
                    sha.update(chunk)
            return sha.hexdigest()[:16]
        except Exception:
            return ''

    @staticmethod
    def _estimate_vram(spec: ModelSpec) -> float:
        """Rough VRAM estimate based on file size and precision."""
        try:
            file_size_mb = os.path.getsize(spec.weight_path) / (1024 * 1024)
            # TRT engines: ~1.5x file size in VRAM (context + buffers)
            # PyTorch: ~2x file size (weights + gradients/buffers)
            multiplier = 1.5 if spec.framework == 'tensorrt' else 2.0
            if spec.precision == 'fp16':
                multiplier *= 0.6
            elif spec.precision == 'int8':
                multiplier *= 0.35
            return file_size_mb * multiplier
        except Exception:
            return 0.0

    # --- Monitoring ---

    def get_all_metrics(self) -> Dict[str, dict]:
        """Get metrics for all registered models."""
        metrics = {}
        for name, inst in self._models.items():
            avg_ms = (inst.total_infer_ms / max(inst.infer_count, 1))
            metrics[name] = {
                'status': inst.status.value,
                'framework': inst.spec.framework,
                'precision': inst.spec.precision,
                'version': inst.spec.version[:8] if inst.spec.version else 'N/A',
                'vram_mb': round(inst.vram_mb, 1),
                'load_time_s': round(inst.load_time_s, 2),
                'infer_count': inst.infer_count,
                'avg_infer_ms': round(avg_ms, 2),
                'last_infer_ms': round(inst.last_infer_ms, 2),
                'failure_count': inst.failure_count,
                'last_error': inst.last_error[:100] if inst.last_error else '',
            }
        return metrics

    def get_loaded_models(self) -> List[str]:
        """Return names of all loaded (READY) models."""
        return [name for name, inst in self._models.items()
                if inst.status == ModelStatus.READY]

    def get_total_vram_mb(self) -> float:
        """Estimate total VRAM used by all loaded models."""
        return sum(inst.vram_mb for inst in self._models.values()
                   if inst.status == ModelStatus.READY)

    def cleanup(self):
        """Unload all models."""
        for name in list(self._models.keys()):
            self.unload(name)
        logger.info("ModelRegistry cleanup complete")
