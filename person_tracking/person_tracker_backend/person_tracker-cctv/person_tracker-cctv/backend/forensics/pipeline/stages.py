"""
Pipeline Stages — Concrete implementations for each DAG pipeline stage.

Each stage:
  - Receives a FramePacket from the previous stage's output queue
  - Performs its specific processing
  - Returns the modified packet for the next stage

Stages are designed to be composable and independently testable.
"""
import time
import logging
import numpy as np
from typing import Optional, List

from .dag_executor import PipelineStage, FramePacket

logger = logging.getLogger(__name__)


# ============================================================================
# STAGE: INGEST — Frame acquisition from capture source
# ============================================================================

class StageIngest(PipelineStage):
    """
    Acquires frames from the RTSP/video capture and packages them as FramePackets.
    This is the pipeline entry point — it generates packets from the capture source.
    """

    def __init__(self, capture, stream_id: str = '',
                 adaptive_stride=None):
        super().__init__('ingest')
        self.capture = capture
        self.stream_id = stream_id
        self.adaptive_stride = adaptive_stride
        self._frame_counter = 0

    def process(self, packet: FramePacket) -> Optional[FramePacket]:
        """
        Read the next frame from the capture source.
        Note: For ingest, the input packet is a trigger signal (may be empty).
        """
        ret, frame = self.capture.read(timeout=2.0) if hasattr(self.capture, 'read') else (False, None)
        
        if not ret or frame is None:
            return None  # Stream ended or timeout

        self._frame_counter += 1

        # Determine if this frame needs full inference (adaptive stride)
        is_inference = True
        if self.adaptive_stride:
            is_inference = self.adaptive_stride.should_process(self._frame_counter)

        return FramePacket(
            stream_id=self.stream_id,
            frame_id=self._frame_counter,
            timestamp=time.time(),
            frame=frame,
            is_inference_frame=is_inference,
        )


# ============================================================================
# STAGE: PREPROCESS — Low-light enhancement + domain adaptation
# ============================================================================

class StagePreprocess(PipelineStage):
    """
    Conditional frame preprocessing:
      - Low-light enhancement (RetinexFormer / CLAHE)
      - Domain-adaptive normalization (LAB CLAHE)
    Only modifies frames that need it — passes through clean frames unchanged.
    """

    def __init__(self, lowlight_enhancer=None):
        super().__init__('preprocess')
        self.enhancer = lowlight_enhancer

    def process(self, packet: FramePacket) -> Optional[FramePacket]:
        if packet.frame is None:
            return packet

        # Low-light enhancement (conditional)
        if self.enhancer:
            result = self.enhancer.enhance(packet.frame)
            if result.was_enhanced:
                packet.preprocessed_frame = result.frame
            else:
                packet.preprocessed_frame = packet.frame
        else:
            packet.preprocessed_frame = packet.frame

        return packet


# ============================================================================
# STAGE: DETECT — Person detection with adaptive routing
# ============================================================================

class StageDetect(PipelineStage):
    """
    Person detection using DetectionRouter (YOLO primary + RT-DETR fallback).
    Skipped frames use the previous detection results (Kalman prediction).
    """

    def __init__(self, detection_router=None, model_pool=None, conf: float = 0.3):
        super().__init__('detect')
        self.router = detection_router
        self.model_pool = model_pool
        self.conf = conf
        self._last_detections = []
        self._last_person_boxes = []

    def process(self, packet: FramePacket) -> Optional[FramePacket]:
        frame = packet.preprocessed_frame or packet.frame
        if frame is None:
            return packet

        if not packet.is_inference_frame:
            # Skip frame: reuse last detections (Kalman filter handles motion)
            packet.detections = self._last_detections
            packet.person_boxes = self._last_person_boxes
            packet.skip_recognition = True
            return packet

        # Run detection
        if self.router:
            detections, context = self.router.detect(frame, conf=self.conf)
            packet.detections = detections
            packet.scene_context = context
            packet.person_boxes = [d.bbox for d in detections]
        elif self.model_pool:
            # Fallback to model_pool direct detection
            results = self.model_pool.detect_persons(frame, conf=self.conf)
            if results and results[0].boxes:
                boxes = results[0].boxes.xyxy.cpu().numpy()
                confs = results[0].boxes.conf.cpu().numpy()
                packet.person_boxes = [b.astype(int).tolist() for b in boxes]
                packet.detections = list(zip(boxes, confs))

        self._last_detections = packet.detections
        self._last_person_boxes = packet.person_boxes

        return packet


# ============================================================================
# STAGE: TRACK — Multi-object tracking with adaptive algorithm selection
# ============================================================================

class StageTrack(PipelineStage):
    """
    Update tracker with detections.
    Uses TrackerOrchestrator for adaptive ByteTrack/BoT-SORT switching.
    """

    def __init__(self, tracker_orchestrator=None, legacy_tracker=None):
        super().__init__('track')
        self.orchestrator = tracker_orchestrator
        self.legacy_tracker = legacy_tracker

    def process(self, packet: FramePacket) -> Optional[FramePacket]:
        frame = packet.preprocessed_frame or packet.frame
        if frame is None:
            return packet

        # Build tracker input array [N, 6]: [x1, y1, x2, y2, conf, class_id]
        tracker_input = []
        
        if self.orchestrator:
            # Use new orchestrator with Detection objects
            for det in packet.detections:
                if hasattr(det, 'bbox'):
                    tracker_input.append(det.bbox + [det.confidence, 0])
                elif isinstance(det, tuple) and len(det) == 2:
                    box, conf = det
                    tracker_input.append(list(box.astype(int)) + [float(conf), 0])

            det_array = np.array(tracker_input) if tracker_input else np.empty((0, 6))
            packet.tracks = self.orchestrator.update(det_array, frame)
            packet.tracker_input = det_array

        elif self.legacy_tracker:
            # Fallback to legacy ByteTrack
            for det in packet.detections:
                if hasattr(det, 'bbox'):
                    tracker_input.append(det.bbox + [det.confidence, 0])
                elif isinstance(det, tuple) and len(det) == 2:
                    box, conf = det
                    tracker_input.append(list(box.astype(int)) + [float(conf), 0])

            if tracker_input:
                det_array = np.array(tracker_input)
                raw_tracks = self.legacy_tracker.update(det_array, frame)
                # Convert to simple track dicts
                for t in raw_tracks:
                    from ..engine.tracker_orchestrator import TrackState
                    packet.tracks.append(TrackState(
                        track_id=int(t[4]),
                        bbox=list(map(int, t[:4])),
                        confidence=float(t[5]) if len(t) > 5 else 0.0,
                    ))

        return packet


# ============================================================================
# STAGE: RECOGNIZE — Face + body recognition and matching
# ============================================================================

class StageRecognize(PipelineStage):
    """
    Face detection + recognition + body ReID + gallery matching.
    Uses AdaptiveFacePipeline and ReIDPipeline for quality-routed recognition.
    Falls back to ModelPool direct methods if pipelines unavailable.
    """

    def __init__(self, model_pool=None,
                 face_pipeline=None, reid_pipeline=None,
                 fusion_engine=None, identity_manager=None):
        super().__init__('recognize')
        self.model_pool = model_pool
        self.face_pipeline = face_pipeline
        self.reid_pipeline = reid_pipeline
        self.fusion = fusion_engine
        self.identity_mgr = identity_manager

    def process(self, packet: FramePacket) -> Optional[FramePacket]:
        frame = packet.preprocessed_frame or packet.frame
        if frame is None or not packet.tracks:
            return packet

        if packet.skip_recognition:
            return packet  # Skipped frame — no ReID needed

        h, w = frame.shape[:2]

        # Step 1: Face detection on full frame (single pass)
        if self.face_pipeline:
            face_results = self.face_pipeline.detect_and_recognize(frame)
            face_map = self.face_pipeline.match_faces_to_persons(
                face_results, packet.person_boxes
            )
        elif self.model_pool:
            faces = self.model_pool.extract_faces_from_frame(frame)
            face_map_raw = self.model_pool.match_faces_to_persons(
                faces, packet.person_boxes
            )
            face_map = face_map_raw
        else:
            face_map = {}

        packet.face_map = face_map

        # Step 2: Per-track recognition + matching
        for track in packet.tracks:
            tid = track.track_id
            bbox = track.bbox
            x1, y1, x2, y2 = bbox

            # Extract person crop
            raw_crop = frame[max(0, y1):min(h, y2), max(0, x1):min(w, x2)]
            if raw_crop.size == 0:
                continue

            # Face embedding for this track
            face_emb = None
            face_meta = None

            # Find matching face in face_map by person index
            for pi, pbox in enumerate(packet.person_boxes):
                if pi in face_map and self._boxes_overlap(bbox, pbox):
                    face_data = face_map[pi]
                    if hasattr(face_data, 'embedding'):
                        face_emb = face_data.embedding
                    elif isinstance(face_data, dict):
                        face_emb = face_data.get('embedding')
                        face_meta = face_data
                    break

            # Compute similarity
            if self.model_pool:
                score, details = self.model_pool.compute_similarity(
                    raw_crop, face_embedding=face_emb, face_meta=face_meta
                )
                packet.match_scores[tid] = score
                packet.match_details[tid] = details

            # Update identity manager
            if self.identity_mgr and tid >= 0:
                score = packet.match_scores.get(tid, 0.0)
                is_target = self.identity_mgr.update_track(
                    track_id=tid,
                    similarity=score,
                    embedding=face_emb,
                    frame_id=packet.frame_id,
                )
                if is_target:
                    packet.confirmed_targets.append(tid)

        return packet

    @staticmethod
    def _boxes_overlap(box_a, box_b, threshold=0.5):
        """Check if two boxes have significant overlap."""
        x_a = max(box_a[0], box_b[0])
        y_a = max(box_a[1], box_b[1])
        x_b = min(box_a[2], box_b[2])
        y_b = min(box_a[3], box_b[3])
        inter = max(0, x_b - x_a) * max(0, y_b - y_a)
        area_a = max(1, (box_a[2] - box_a[0]) * (box_a[3] - box_a[1]))
        area_b = max(1, (box_b[2] - box_b[0]) * (box_b[3] - box_b[1]))
        iou = inter / float(area_a + area_b - inter + 1e-6)
        return iou > threshold


# ============================================================================
# STAGE: EVENT — Alert generation and notification
# ============================================================================

class StageEvent(PipelineStage):
    """
    Generate alerts for confirmed target detections.
    Integrates with AlertManager for clip recording and WebSocket notifications.
    """

    def __init__(self, alert_manager=None, websocket_callback=None):
        super().__init__('event')
        self.alert_manager = alert_manager
        self.ws_callback = websocket_callback

    def process(self, packet: FramePacket) -> Optional[FramePacket]:
        frame = packet.preprocessed_frame or packet.frame
        if frame is None:
            return packet

        has_target = len(packet.confirmed_targets) > 0
        best_score = max(packet.match_scores.values()) if packet.match_scores else 0.0

        # Update alert manager (handles clip recording)
        if self.alert_manager:
            best_bbox = None
            if has_target and packet.tracks:
                for t in packet.tracks:
                    if t.track_id in packet.confirmed_targets:
                        best_bbox = t.bbox
                        break

            self.alert_manager.report_frame(
                is_target_present=has_target,
                score=best_score,
                frame=frame,
                target_bbox=best_bbox,
            )

        # WebSocket notification for live UI updates
        if self.ws_callback and has_target:
            try:
                self.ws_callback({
                    'stream_id': packet.stream_id,
                    'frame_id': packet.frame_id,
                    'confirmed_targets': packet.confirmed_targets,
                    'best_score': best_score,
                    'timestamp': packet.timestamp,
                })
            except Exception as e:
                logger.error(f"WebSocket callback error: {e}")

        return packet


# ============================================================================
# STAGE: EVIDENCE — Forensic evidence recording with integrity
# ============================================================================

class StageEvidence(PipelineStage):
    """
    Record forensic evidence with cryptographic integrity hashing.
    Produces tamper-proof evidence artifacts for confirmed detections.
    """

    def __init__(self, integrity_manager=None, sighting_manager=None):
        super().__init__('evidence')
        self.integrity = integrity_manager
        self.sighting_mgr = sighting_manager

    def process(self, packet: FramePacket) -> Optional[FramePacket]:
        frame = packet.preprocessed_frame or packet.frame
        if frame is None:
            return packet

        has_target = len(packet.confirmed_targets) > 0
        best_score = max(packet.match_scores.values()) if packet.match_scores else 0.0

        # Update sighting clip maker
        if self.sighting_mgr:
            self.sighting_mgr.report_frame(
                is_target_present=has_target,
                current_frame=packet.frame_id,
                score=best_score,
                frame=frame,
            )
            self.sighting_mgr.check_for_closures(packet.frame_id)

        # Hash evidence frame (if integrity manager available)
        if self.integrity and has_target:
            try:
                evidence_hash = self.integrity.hash_frame(frame, {
                    'stream_id': packet.stream_id,
                    'frame_id': packet.frame_id,
                    'targets': packet.confirmed_targets,
                    'score': best_score,
                    'timestamp': packet.timestamp,
                })
                packet.evidence_hashes.append(evidence_hash)
            except Exception as e:
                logger.error(f"Evidence hashing error: {e}")

        return packet
