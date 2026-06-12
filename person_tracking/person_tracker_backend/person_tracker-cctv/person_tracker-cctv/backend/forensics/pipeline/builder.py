"""
Pipeline Builder — Factory for wiring DAG pipeline stages.

Creates a fully connected pipeline from configuration, plugging in the
correct engine components (router, tracker, face pipeline, etc.) for
each stage.

Usage:
    from forensics.pipeline.builder import PipelineBuilder
    
    builder = PipelineBuilder(model_pool, config)
    pipeline = builder.build(stream_id='cam_001', capture=rtsp_capture)
    pipeline.start()
"""
import logging
from typing import Optional, Dict, Any

from .dag_executor import DAGPipelineExecutor
from .stages import (
    StageIngest, StagePreprocess, StageDetect,
    StageTrack, StageRecognize, StageEvent, StageEvidence,
)

logger = logging.getLogger(__name__)


class PipelineBuilder:
    """
    Factory that creates and wires a complete DAG pipeline.
    
    Connects new engine components (DetectionRouter, TrackerOrchestrator, etc.)
    when available, falling back to legacy components otherwise.
    """
    
    def __init__(self, model_pool, config: Optional[dict] = None):
        """
        Args:
            model_pool: Shared ModelPool instance.
            config: Pipeline configuration overrides.
        """
        self.model_pool = model_pool
        self.config = config or {}
        
        # Engine components (set externally or auto-created)
        self.detection_router = None
        self.tracker_orchestrator = None
        self.face_pipeline = None
        self.reid_pipeline = None
        self.fusion_engine = None
        self.lowlight_enhancer = None
        self.identity_manager = None
        self.integrity_manager = None
    
    def with_detection_router(self, router):
        """Set the detection router (YOLO + RT-DETR)."""
        self.detection_router = router
        return self
    
    def with_tracker(self, orchestrator):
        """Set the tracker orchestrator (ByteTrack/BoT-SORT)."""
        self.tracker_orchestrator = orchestrator
        return self
    
    def with_face_pipeline(self, pipeline):
        """Set the adaptive face pipeline."""
        self.face_pipeline = pipeline
        return self
    
    def with_reid_pipeline(self, pipeline):
        """Set the ReID pipeline."""
        self.reid_pipeline = pipeline
        return self
    
    def with_fusion_engine(self, engine):
        """Set the confidence fusion engine."""
        self.fusion_engine = engine
        return self
    
    def with_enhancer(self, enhancer):
        """Set the low-light enhancer."""
        self.lowlight_enhancer = enhancer
        return self
    
    def with_identity_manager(self, manager):
        """Set the identity manager."""
        self.identity_manager = manager
        return self
    
    def with_integrity_manager(self, manager):
        """Set the evidence integrity manager."""
        self.integrity_manager = manager
        return self
    
    def build(self, stream_id: str, capture=None,
              alert_manager=None, sighting_manager=None,
              websocket_callback=None,
              adaptive_stride=None,
              legacy_tracker=None) -> DAGPipelineExecutor:
        """
        Build a fully wired DAG pipeline.
        
        Args:
            stream_id: Camera stream identifier.
            capture: RTSP/video capture object.
            alert_manager: AlertManager for clip recording.
            sighting_manager: SightingClipMaker for evidence.
            websocket_callback: Callback for live WebSocket updates.
            adaptive_stride: AdaptiveStride for frame skip control.
            legacy_tracker: Legacy ByteTrack instance (fallback).
            
        Returns:
            Configured and ready-to-start DAGPipelineExecutor.
        """
        pipeline = DAGPipelineExecutor(stream_id=stream_id, config=self.config)
        
        # Queue sizes from config
        q_ingest = self.config.get('queue_ingest', 32)
        q_detect = self.config.get('queue_detect', 16)
        q_track = self.config.get('queue_track', 16)
        q_recognize = self.config.get('queue_recognize', 16)
        q_event = self.config.get('queue_event', 32)
        q_evidence = self.config.get('queue_evidence', 32)
        
        # --- Stage 1: Ingest ---
        pipeline.add_stage(
            'ingest',
            StageIngest(
                capture=capture,
                stream_id=stream_id,
                adaptive_stride=adaptive_stride,
            ),
            workers=1,
            queue_size=q_ingest,
        )
        
        # --- Stage 2: Preprocess ---
        pipeline.add_stage(
            'preprocess',
            StagePreprocess(lowlight_enhancer=self.lowlight_enhancer),
            workers=1,
            queue_size=q_detect,
        )
        
        # --- Stage 3: Detect ---
        pipeline.add_stage(
            'detect',
            StageDetect(
                detection_router=self.detection_router,
                model_pool=self.model_pool,
                conf=self.config.get('detection_conf', 0.3),
            ),
            workers=1,
            queue_size=q_detect,
        )
        
        # --- Stage 4: Track ---
        pipeline.add_stage(
            'track',
            StageTrack(
                tracker_orchestrator=self.tracker_orchestrator,
                legacy_tracker=legacy_tracker,
            ),
            workers=1,
            queue_size=q_track,
        )
        
        # --- Stage 5: Recognize ---
        pipeline.add_stage(
            'recognize',
            StageRecognize(
                model_pool=self.model_pool,
                face_pipeline=self.face_pipeline,
                reid_pipeline=self.reid_pipeline,
                fusion_engine=self.fusion_engine,
                identity_manager=self.identity_manager,
            ),
            workers=1,
            queue_size=q_recognize,
        )
        
        # --- Stage 6: Event ---
        pipeline.add_stage(
            'event',
            StageEvent(
                alert_manager=alert_manager,
                websocket_callback=websocket_callback,
            ),
            workers=1,
            queue_size=q_event,
        )
        
        # --- Stage 7: Evidence ---
        pipeline.add_stage(
            'evidence',
            StageEvidence(
                integrity_manager=self.integrity_manager,
                sighting_manager=sighting_manager,
            ),
            workers=1,
            queue_size=q_evidence,
        )
        
        # --- Wire connections ---
        pipeline.connect('ingest', 'preprocess')
        pipeline.connect('preprocess', 'detect')
        pipeline.connect('detect', 'track')
        pipeline.connect('track', 'recognize')
        pipeline.connect('recognize', 'event')
        pipeline.connect('event', 'evidence')
        
        logger.info(
            f"Pipeline built for '{stream_id}': "
            f"ingest → preprocess → detect → track → recognize → event → evidence | "
            f"router={'V2' if self.detection_router else 'legacy'}, "
            f"tracker={'V2' if self.tracker_orchestrator else 'legacy'}, "
            f"face={'adaptive' if self.face_pipeline else 'insightface'}"
        )
        
        return pipeline
    
    def build_minimal(self, stream_id: str, capture=None,
                      legacy_tracker=None) -> DAGPipelineExecutor:
        """
        Build a minimal pipeline (detect + track only).
        Useful for testing or lightweight deployments.
        """
        pipeline = DAGPipelineExecutor(stream_id=stream_id)
        
        pipeline.add_stage('ingest', StageIngest(capture, stream_id), queue_size=16)
        pipeline.add_stage('detect', StageDetect(model_pool=self.model_pool), queue_size=8)
        pipeline.add_stage('track', StageTrack(legacy_tracker=legacy_tracker), queue_size=8)
        
        pipeline.connect('ingest', 'detect')
        pipeline.connect('detect', 'track')
        
        return pipeline
