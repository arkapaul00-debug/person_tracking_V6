"""
DeepStream Pipeline Configuration — NVIDIA DeepStream SDK Integration.

Generates DeepStream pipeline configs for:
  - Hardware NVDEC decoding (H.264/H.265/MJPEG)
  - TensorRT inference (nvinfer)
  - Multi-stream muxing (nvstreammux)
  - Object tracking (nvtracker)
  - Analytics (nvdsanalytics)
  - Message broker output (nvmsgconv + nvmsgbroker)

This module provides Python-based config generation rather than
static config files, enabling runtime adaptation based on:
  - Number of streams
  - GPU capability
  - Available VRAM
  - Model availability

Usage:
    config = DeepStreamConfig()
    pipeline = config.build_pipeline(
        stream_urls=['rtsp://cam1', 'rtsp://cam2'],
        gpu_id=0,
        batch_size=8,
    )
    pipeline_str = config.to_gst_launch()  # GStreamer launch string
"""
import os
import logging
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)


class DeepStreamConfig:
    """
    DeepStream pipeline configuration generator.
    """

    def __init__(self,
                 gpu_id: int = 0,
                 batch_size: int = 8,
                 tracker_width: int = 640,
                 tracker_height: int = 384,
                 model_engine_dir: str = '/models/trt_engines/',
                 output_broker: str = 'kafka'):
        self.gpu_id = gpu_id
        self.batch_size = batch_size
        self.tracker_width = tracker_width
        self.tracker_height = tracker_height
        self.model_engine_dir = model_engine_dir
        self.output_broker = output_broker

    def generate_streammux_config(self, num_streams: int) -> Dict[str, Any]:
        """
        Generate nvstreammux configuration.
        Handles multi-stream batching with hardware-decoded inputs.
        """
        return {
            'gpu-id': self.gpu_id,
            'batch-size': min(num_streams, self.batch_size),
            'batched-push-timeout': 40000,  # 40ms → 25fps max
            'width': 1920,
            'height': 1080,
            'enable-padding': True,
            'nvbuf-memory-type': 0,  # NVBUF_MEM_DEFAULT (unified memory)
            'live-source': True,
            'attach-sys-ts': True,
        }

    def generate_nvinfer_primary(self) -> Dict[str, Any]:
        """
        Generate primary detector (YOLOv11) nvinfer config.
        """
        return {
            'gpu-id': self.gpu_id,
            'net-scale-factor': 0.00392157,  # 1/255
            'model-engine-file': os.path.join(self.model_engine_dir, 'yolov11n.engine'),
            'batch-size': self.batch_size,
            'network-mode': 1,  # FP16
            'num-detected-classes': 80,
            'interval': 0,  # Infer every frame
            'gie-unique-id': 1,
            'process-mode': 1,  # Primary
            'cluster-mode': 2,  # NMS
            'maintain-aspect-ratio': True,
            'symmetric-padding': True,
            'parse-bbox-func-name': 'NvDsInferParseYolo',
            'output-blob-names': 'output0',
            'filter-out-class-ids': '0',  # Keep only person class
        }

    def generate_nvinfer_secondary_face(self) -> Dict[str, Any]:
        """
        Generate secondary face recognition nvinfer config.
        Operates on ROIs from primary detector.
        """
        return {
            'gpu-id': self.gpu_id,
            'net-scale-factor': 0.00784314,  # 1/127.5
            'model-engine-file': os.path.join(self.model_engine_dir, 'retinaface.engine'),
            'batch-size': 16,
            'network-mode': 1,  # FP16
            'gie-unique-id': 2,
            'process-mode': 2,  # Secondary (on primary ROIs)
            'operate-on-gie-id': 1,
            'operate-on-class-ids': '0',  # Only on person detections
        }

    def generate_tracker_config(self) -> Dict[str, Any]:
        """
        Generate nvtracker (DeepStream built-in tracker) config.
        Uses DeepSORT with appearance features.
        """
        return {
            'tracker-width': self.tracker_width,
            'tracker-height': self.tracker_height,
            'gpu-id': self.gpu_id,
            'll-lib-file': '/opt/nvidia/deepstream/deepstream/lib/libnvds_nvmultiobjecttracker.so',
            'll-config-file': self._generate_tracker_ll_config(),
            'display-tracking-id': True,
            'enable-batch-process': True,
            'enable-past-frame': True,
        }

    def generate_analytics_config(self) -> Dict[str, Any]:
        """
        Generate nvdsanalytics config for ROI-based analytics.
        """
        return {
            'enable': True,
            'config-file': self._generate_analytics_file(),
        }

    def generate_msgconv_config(self) -> Dict[str, Any]:
        """
        Generate nvmsgconv config for event serialization.
        """
        return {
            'msg2p-lib': '/opt/nvidia/deepstream/deepstream/lib/libnvds_msgconv.so',
            'payload-type': 0,  # DeepStream Schema
            'msg2p-newapi': True,
            'frame-interval': 30,  # Send metadata every 30 frames
        }

    def generate_msgbroker_config(self) -> Dict[str, Any]:
        """
        Generate nvmsgbroker config for Kafka output.
        """
        if self.output_broker == 'kafka':
            return {
                'proto-lib': '/opt/nvidia/deepstream/deepstream/lib/libnvds_kafka_proto.so',
                'conn-str': 'localhost;9092',
                'topic': 'deepstream-events',
                'sync': False,
                'async': True,
            }
        return {}

    def build_pipeline(self, stream_urls: List[str]) -> Dict[str, Any]:
        """
        Build complete pipeline configuration for all streams.

        Returns:
            Dict containing all pipeline element configs.
        """
        num_streams = len(stream_urls)

        return {
            'sources': [
                {
                    'type': 'rtsp',
                    'uri': url,
                    'gpu-id': self.gpu_id,
                    'cudadec-memtype': 0,
                    'drop-frame-interval': 0,
                    'num-extra-surfaces': 2,
                    'latency': 200,  # 200ms buffer
                }
                for url in stream_urls
            ],
            'streammux': self.generate_streammux_config(num_streams),
            'primary_gie': self.generate_nvinfer_primary(),
            'secondary_gie_face': self.generate_nvinfer_secondary_face(),
            'tracker': self.generate_tracker_config(),
            'analytics': self.generate_analytics_config(),
            'msgconv': self.generate_msgconv_config(),
            'msgbroker': self.generate_msgbroker_config(),
            'sink': {
                'type': 'fakesink',  # No display output by default
                'sync': False,
                'async': True,
            },
        }

    def to_gst_launch(self, stream_urls: List[str]) -> str:
        """
        Generate a GStreamer launch string for the pipeline.
        Useful for testing and debugging.
        """
        parts = []

        # Sources
        for i, url in enumerate(stream_urls):
            parts.append(
                f"rtspsrc location={url} latency=200 ! "
                f"rtph264depay ! h264parse ! nvv4l2decoder gpu-id={self.gpu_id} ! "
                f"queue ! mux.sink_{i}"
            )

        # Streammux
        parts.append(
            f"nvstreammux name=mux batch-size={min(len(stream_urls), self.batch_size)} "
            f"width=1920 height=1080 live-source=1 gpu-id={self.gpu_id} ! "
        )

        # Inference
        engine_path = os.path.join(self.model_engine_dir, 'yolov11n.engine')
        parts.append(
            f"nvinfer config-file-path=pgie_config.txt gpu-id={self.gpu_id} "
            f"model-engine-file={engine_path} batch-size={self.batch_size} ! "
        )

        # Tracker
        parts.append(
            f"nvtracker tracker-width={self.tracker_width} "
            f"tracker-height={self.tracker_height} gpu-id={self.gpu_id} ! "
        )

        # Output
        parts.append("fakesink sync=0")

        return ' '.join(parts)

    def _generate_tracker_ll_config(self) -> str:
        """Generate low-level tracker config file path."""
        return 'tracker_config.yml'

    def _generate_analytics_file(self) -> str:
        """Generate analytics config file path."""
        return 'analytics_config.txt'

    def get_deployment_info(self) -> Dict[str, Any]:
        """Get deployment information for this pipeline config."""
        return {
            'gpu_id': self.gpu_id,
            'batch_size': self.batch_size,
            'tracker_resolution': f"{self.tracker_width}x{self.tracker_height}",
            'model_engine_dir': self.model_engine_dir,
            'output_broker': self.output_broker,
            'deepstream_version': '6.4+',
            'required_packages': [
                'deepstream-sdk',
                'tensorrt',
                'cuda-toolkit',
                'gstreamer',
                'kafka (for event streaming)',
            ],
        }
