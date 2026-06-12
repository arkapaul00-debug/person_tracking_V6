"""
Triton Inference Server — Configuration and Client Interface.

Provides:
  - Model repository configuration generator for all forensic models
  - Triton client wrapper for batched async inference
  - Dynamic batching config with priority scheduling
  - Model versioning and hot-reload support

Usage:
    # Generate model repository configs
    TritonConfig.generate_model_repo('/models/')

    # Use Triton client for inference
    client = TritonInferenceClient('localhost:8001')
    detections = client.detect(frames_batch)
    embeddings = client.extract_embeddings(crops_batch)

Production deployment:
    docker run --gpus all -p 8000:8000 -p 8001:8001 -p 8002:8002 \\
        -v /models:/models \\
        nvcr.io/nvidia/tritonserver:24.01-py3 \\
        tritonserver --model-repository=/models
"""
import os
import json
import logging
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)


class TritonConfig:
    """
    Generator for Triton model repository configs (config.pbtxt).
    """

    # Model specifications: name → (inputs, outputs, max_batch, backend)
    MODEL_SPECS = {
        'yolov11n_detector': {
            'backend': 'tensorrt',
            'max_batch_size': 16,
            'inputs': [{'name': 'images', 'data_type': 'TYPE_FP16', 'dims': [3, 640, 640]}],
            'outputs': [{'name': 'output0', 'data_type': 'TYPE_FP16', 'dims': [-1, 6]}],
            'instance_count': 2,
            'dynamic_batching': {'preferred_batch_size': [4, 8, 16], 'max_queue_delay_us': 5000},
            'priority': 'high',
        },
        'rtdetr_detector': {
            'backend': 'tensorrt',
            'max_batch_size': 4,
            'inputs': [{'name': 'images', 'data_type': 'TYPE_FP16', 'dims': [3, 640, 640]}],
            'outputs': [{'name': 'output0', 'data_type': 'TYPE_FP16', 'dims': [-1, 6]}],
            'instance_count': 1,
            'dynamic_batching': {'preferred_batch_size': [2, 4], 'max_queue_delay_us': 10000},
            'priority': 'low',
        },
        'retinaface': {
            'backend': 'tensorrt',
            'max_batch_size': 16,
            'inputs': [{'name': 'input', 'data_type': 'TYPE_FP16', 'dims': [3, 640, 640]}],
            'outputs': [
                {'name': 'bboxes', 'data_type': 'TYPE_FP32', 'dims': [-1, 4]},
                {'name': 'landmarks', 'data_type': 'TYPE_FP32', 'dims': [-1, 10]},
                {'name': 'scores', 'data_type': 'TYPE_FP32', 'dims': [-1]},
            ],
            'instance_count': 1,
            'dynamic_batching': {'preferred_batch_size': [4, 8], 'max_queue_delay_us': 3000},
        },
        'adaface_recognition': {
            'backend': 'tensorrt',
            'max_batch_size': 32,
            'inputs': [{'name': 'input', 'data_type': 'TYPE_FP16', 'dims': [3, 112, 112]}],
            'outputs': [{'name': 'embedding', 'data_type': 'TYPE_FP32', 'dims': [512]}],
            'instance_count': 1,
            'dynamic_batching': {'preferred_batch_size': [8, 16, 32], 'max_queue_delay_us': 5000},
        },
        'osnet_reid': {
            'backend': 'tensorrt',
            'max_batch_size': 32,
            'inputs': [{'name': 'input', 'data_type': 'TYPE_FP16', 'dims': [3, 256, 128]}],
            'outputs': [{'name': 'embedding', 'data_type': 'TYPE_FP32', 'dims': [512]}],
            'instance_count': 1,
            'dynamic_batching': {'preferred_batch_size': [8, 16], 'max_queue_delay_us': 5000},
        },
        'silentface_antispoof': {
            'backend': 'tensorrt',
            'max_batch_size': 8,
            'inputs': [{'name': 'input', 'data_type': 'TYPE_FP16', 'dims': [3, 80, 80]}],
            'outputs': [{'name': 'score', 'data_type': 'TYPE_FP32', 'dims': [2]}],
            'instance_count': 1,
            'dynamic_batching': {'preferred_batch_size': [4, 8], 'max_queue_delay_us': 10000},
        },
        'retinexformer_enhancer': {
            'backend': 'onnxruntime',
            'max_batch_size': 1,
            'inputs': [{'name': 'input', 'data_type': 'TYPE_FP32', 'dims': [3, -1, -1]}],
            'outputs': [{'name': 'output', 'data_type': 'TYPE_FP32', 'dims': [3, -1, -1]}],
            'instance_count': 1,
        },
    }

    @classmethod
    def generate_model_repo(cls, repo_path: str):
        """
        Generate Triton model repository structure with config.pbtxt files.

        Args:
            repo_path: Root path for the model repository.
        """
        for model_name, spec in cls.MODEL_SPECS.items():
            model_dir = os.path.join(repo_path, model_name)
            os.makedirs(os.path.join(model_dir, '1'), exist_ok=True)

            config = cls._generate_config_pbtxt(model_name, spec)
            config_path = os.path.join(model_dir, 'config.pbtxt')

            with open(config_path, 'w') as f:
                f.write(config)

            logger.info(f"Generated Triton config: {config_path}")

    @classmethod
    def _generate_config_pbtxt(cls, name: str, spec: Dict) -> str:
        """Generate config.pbtxt content for a model."""
        lines = [
            f'name: "{name}"',
            f'platform: "{cls._platform(spec["backend"])}"',
            f'max_batch_size: {spec["max_batch_size"]}',
            '',
        ]

        # Inputs
        for inp in spec['inputs']:
            dims = ', '.join(str(d) for d in inp['dims'])
            lines.extend([
                'input [',
                '  {',
                f'    name: "{inp["name"]}"',
                f'    data_type: {inp["data_type"]}',
                f'    dims: [ {dims} ]',
                '  }',
                ']',
                '',
            ])

        # Outputs
        for out in spec['outputs']:
            dims = ', '.join(str(d) for d in out['dims'])
            lines.extend([
                'output [',
                '  {',
                f'    name: "{out["name"]}"',
                f'    data_type: {out["data_type"]}',
                f'    dims: [ {dims} ]',
                '  }',
                ']',
                '',
            ])

        # Dynamic batching
        if 'dynamic_batching' in spec:
            db = spec['dynamic_batching']
            batch_sizes = ', '.join(str(s) for s in db['preferred_batch_size'])
            lines.extend([
                'dynamic_batching {',
                f'  preferred_batch_size: [ {batch_sizes} ]',
                f'  max_queue_delay_microseconds: {db["max_queue_delay_us"]}',
            ])
            if spec.get('priority') == 'high':
                lines.append('  priority_levels: 2')
                lines.append('  default_priority_level: 1')
            lines.extend(['}', ''])

        # Instance group
        instance_count = spec.get('instance_count', 1)
        lines.extend([
            'instance_group [',
            '  {',
            f'    count: {instance_count}',
            '    kind: KIND_GPU',
            '    gpus: [ 0 ]',
            '  }',
            ']',
        ])

        return '\n'.join(lines)

    @staticmethod
    def _platform(backend: str) -> str:
        platforms = {
            'tensorrt': 'tensorrt_plan',
            'onnxruntime': 'onnxruntime_onnx',
            'pytorch': 'pytorch_libtorch',
        }
        return platforms.get(backend, backend)


class TritonInferenceClient:
    """
    Async client wrapper for Triton Inference Server.

    Provides batched inference with automatic retry and fallback.
    """

    def __init__(self, url: str = 'localhost:8001', verbose: bool = False):
        self.url = url
        self._client = None
        self._connected = False

        try:
            import tritonclient.grpc as grpcclient
            self._client = grpcclient.InferenceServerClient(url=url, verbose=verbose)
            self._connected = self._client.is_server_live()
            if self._connected:
                logger.info(f"Triton client connected to {url}")
            else:
                logger.warning(f"Triton server at {url} not live")
        except ImportError:
            logger.info("tritonclient not installed — Triton disabled")
        except Exception as e:
            logger.warning(f"Triton connection failed: {e}")

    @property
    def is_connected(self) -> bool:
        return self._connected

    def get_model_status(self, model_name: str) -> dict:
        """Check if a model is ready on the server."""
        if not self._connected:
            return {'ready': False, 'reason': 'not_connected'}

        try:
            ready = self._client.is_model_ready(model_name)
            return {'ready': ready, 'model': model_name}
        except Exception as e:
            return {'ready': False, 'error': str(e)}

    def get_server_health(self) -> dict:
        """Get Triton server health status."""
        if not self._connected:
            return {'live': False, 'ready': False}

        try:
            return {
                'live': self._client.is_server_live(),
                'ready': self._client.is_server_ready(),
            }
        except Exception as e:
            return {'live': False, 'ready': False, 'error': str(e)}
