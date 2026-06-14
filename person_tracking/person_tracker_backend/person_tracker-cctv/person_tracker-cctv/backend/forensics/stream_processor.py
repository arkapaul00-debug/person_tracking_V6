"""
Per-Stream Processor — Real-time inference loop for a single RTSP camera.

Each stream gets its own:
  - ByteTrack tracker (per-stream track IDs)
  - ForensicIdentityManager (per-stream identity states)
  - AdaptiveStrideFSM (per-stream temporal adaptation)
  - AlertManager (per-stream alert/clip output)

GPU models are shared via ModelPool.

V2 Engine Integration:
  - When v2_engines dict is provided, the processor uses:
    * DetectionRouter instead of raw YOLO
    * TrackerOrchestrator instead of plain ByteTrack
    * AdaptiveFacePipeline for quality-routed face recognition
    * ConfidenceFusionEngine for multi-signal score fusion
    * AdaptiveLowLightEnhancer for conditional night-mode
    * EvidenceIntegrityManager for hash chain recording
    * MetricsCollector for per-stage performance tracking
  - Falls back to legacy behavior when V2 components are absent.
"""
import time
import threading
import logging
import numpy as np
from typing import Optional, Callable, Dict, Any

from .alert_manager import AlertManager

logger = logging.getLogger(__name__)


class StreamProcessor:
    """
    One instance per RTSP camera.
    Runs its own inference thread using shared GPU models from ModelPool.
    """

    def __init__(self, stream_id: str, model_pool,
                 capture, session, stream_obj,
                 threshold: float = 0.55,
                 skip_n: int = 4,
                 alert_callback: Optional[Callable] = None,
                 v2_engines: Optional[Dict[str, Any]] = None):
        """
        Args:
            stream_id: Unique identifier
            model_pool: Shared ModelPool singleton
            capture: RTSPCapture instance for this stream
            session: LiveTrackingSession ORM object
            stream_obj: CCTVStream ORM object
            threshold: High similarity threshold
            skip_n: Base temporal stride for dense mode
            alert_callback: Callback for real-time alert push
            v2_engines: Optional dict of V2 engine components:
                'detection_router', 'tracker_orchestrator', 'face_pipeline',
                'fusion_engine', 'lowlight_enhancer', 'evidence_mgr', 'metrics'
        """
        from boxmot import BYTETracker
        from .adaptive_stride import AdaptiveStrideFSM
        from .forensic_identity import ForensicIdentityManager
        from .model_pool import ModelPool

        self.stream_id = stream_id
        self.pool = model_pool
        self.capture = capture
        self.session = session
        self.stream_obj = stream_obj
        self.threshold = threshold

        # --- V2 Engine Components (optional, injected from orchestrator) ---
        v2 = v2_engines or {}
        self._detection_router = v2.get('detection_router')
        self._tracker_orch = v2.get('tracker_orchestrator')
        self._face_pipeline = v2.get('face_pipeline')
        self._fusion_engine = v2.get('fusion_engine')
        self._lowlight = v2.get('lowlight_enhancer')
        self._evidence_mgr = v2.get('evidence_mgr')
        self._metrics = v2.get('metrics')
        self._v2_active = any([
            self._detection_router, self._tracker_orch,
            self._face_pipeline, self._lowlight,
        ])

        # Per-stream lightweight state (CPU only)
        self.tracker = BYTETracker(track_thresh=0.3, track_buffer=100, frame_rate=30)
        self.identity_mgr = ForensicIdentityManager(
            high_thresh=threshold,
            low_thresh=max(0.45, threshold - 0.15),
        )
        self.stride_fsm = AdaptiveStrideFSM(
            dense_skip=skip_n,
            sparse_skip=12,
            reset_skip=1,
            empty_patience=8,
            min_dwell_frames=30
        )

        # Alert manager
        self.alert_mgr = AlertManager(
            session=session,
            stream=stream_obj,
            fps=30.0,  # Will be updated on first frame
            width=capture.width or 1920,
            height=capture.height or 1080,
            alert_callback=alert_callback,
        )

        # Thread control
        self.running = False
        self._thread = None

        # Metrics
        self.frame_counter = 0
        self.inference_count = 0
        self.detection_count = 0
        self.fps_processing = 0.0
        self.last_error = None
        self._track_scores = {}  # tid -> last known match score

        # State buffers for non-inference frames
        self._last_tracker_input = []
        self._last_detections = []
        self.latest_annotated_frame = None
        self._annotated_lock = threading.Lock()

        if self._v2_active:
            logger.info(f"[{stream_id}] V2 engines active: "
                        f"router={'Y' if self._detection_router else 'N'}, "
                        f"tracker={'Y' if self._tracker_orch else 'N'}, "
                        f"face={'Y' if self._face_pipeline else 'N'}, "
                        f"enhancer={'Y' if self._lowlight else 'N'}")

    def start(self):
        """Start the processing thread."""
        if self.running:
            return
        self.running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info(f"[{self.stream_id}] StreamProcessor started")

    def stop(self):
        """Stop the processing thread gracefully."""
        self.running = False
        if self._thread is not None:
            self._thread.join(timeout=10.0)
        self.alert_mgr.close()
        logger.info(f"[{self.stream_id}] StreamProcessor stopped")

    def _run_loop(self):
        """Main processing loop — runs in its own thread."""
        fps_timer = time.time()
        fps_counter = 0

        while self.running:
            try:
                # 1. Get latest frame
                ret, frame = self.capture.read(timeout=1.0)
                if not ret or frame is None:
                    time.sleep(0.01)
                    continue

                self.frame_counter += 1

                # Update alert manager dimensions on first frame
                if self.frame_counter == 1:
                    h, w = frame.shape[:2]
                    self.alert_mgr.width = w
                    self.alert_mgr.height = h
                    if self.capture.fps_actual > 0:
                        self.alert_mgr.fps = self.capture.fps_actual

                # V2: Conditional low-light enhancement
                working_frame = self._enhance_frame(frame)

                # 2. Stride check — should we run inference on this frame?
                current_skip = self.stride_fsm.get_skip_n()
                run_inference = (self.frame_counter % current_skip == 0) or (self.frame_counter == 1)

                target_present = False
                targets = []  # List of (bbox, score)

                if run_inference:
                    t_inf = time.time()
                    target_present, targets = self._process_inference_frame(working_frame)
                    self.inference_count += 1
                    # V2: Record inference latency
                    if self._metrics:
                        self._metrics.record_pipeline_frame(
                            self.stream_id, 'inference',
                            (time.time() - t_inf) * 1000
                        )
                else:
                    # Reuse last results with tracker Kalman prediction
                    target_present, targets = self._process_skip_frame(working_frame)

                # 3. Draw bounding boxes for all targets
                if target_present:
                    import cv2
                    for (bbox, score, fid, finalized_str) in targets:
                        x1, y1, x2, y2 = bbox
                        
                        # Change color if shots are finalized
                        color = (0, 255, 255) if finalized_str else (0, 255, 0) # Yellow if finalized
                        
                        label = f"ID:{fid} ({score:.2f})"
                        if finalized_str:
                            label += f" | {finalized_str}"
                        
                        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 3)
                        cv2.putText(frame, label, (x1, max(0, y1-10)), 
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)

                # Store annotated frame for live views
                with self._annotated_lock:
                    self.latest_annotated_frame = frame.copy()

                # 4. Report primarily the best target to alert manager
                if targets:
                    best_bbox, best_score, best_fid, _ = max(targets, key=lambda x: x[1])
                    self.alert_mgr.report_frame(
                        is_target_present=True,
                        score=best_score,
                        frame=frame,
                        target_bbox=best_bbox,
                        track_id=best_fid,
                    )
                    # V2: Hash evidence frame
                    if self._evidence_mgr and best_score > self.threshold:
                        try:
                            self._evidence_mgr.hash_frame(frame, {
                                'stream_id': self.stream_id,
                                'frame_id': self.frame_counter,
                                'score': best_score,
                                'track_id': best_fid,
                            })
                        except Exception:
                            pass
                else:
                    self.alert_mgr.report_frame(
                        is_target_present=False,
                        score=0.0,
                        frame=frame,
                        target_bbox=None,
                    )
                self.alert_mgr.check_for_closures()

                # V2: Update metrics
                if self._metrics:
                    self._metrics.set_stream_fps(self.stream_id, self.fps_processing)

                # FPS tracking
                fps_counter += 1
                elapsed = time.time() - fps_timer
                if elapsed >= 3.0:
                    self.fps_processing = fps_counter / elapsed
                    fps_counter = 0
                    fps_timer = time.time()
                    
                    # Push WS heartbeat
                    try:
                        from .ws_dispatcher import push_live_status
                        push_live_status(
                            camera_id=self.stream_id,
                            fps=self.fps_processing,
                            active_tracks=len(self._track_scores)
                        )
                    except Exception as e:
                        logger.warning(f"Failed to push live status: {e}")

                # Periodic GPU cleanup
                if self.frame_counter % 1000 == 0:
                    import torch
                    if torch.cuda.is_available(): torch.cuda.empty_cache()
                    logger.info(
                        f"[{self.stream_id}] Frames:{self.frame_counter} "
                        f"Inferences:{self.inference_count} "
                        f"Detections:{self.detection_count} "
                        f"Stride:{self.stride_fsm.get_stats()}"
                        f"{' [V2]' if self._v2_active else ''}"
                    )

            except Exception as e:
                self.last_error = str(e)
                logger.error(f"[{self.stream_id}] Processing error: {e}")
                time.sleep(0.1)  # Prevent tight error loops

    def _process_inference_frame(self, frame: np.ndarray):
        """Run full detection + ReID on this frame."""
        h, w = frame.shape[:2]
        target_present = False
        max_score = 0.0
        target_bbox = None
        tracker_input = []
        current_detections = []

        # --- A: YOLO Detection ---
        results = self.pool.detect_persons(frame, conf=0.3)
        res = results[0] if results else None

        if res is not None and res.boxes:
            boxes = res.boxes.xyxy.cpu().numpy()
            confs = res.boxes.conf.cpu().numpy()

            # Build person box list
            person_boxes = []
            for box in boxes:
                x1, y1, x2, y2 = box.astype(int)
                person_boxes.append([x1, y1, x2, y2])

            # --- B: Face extraction (once on full frame) ---
            face_map = {}
            if self.pool.face_model:
                all_faces = self.pool.extract_faces_from_frame(frame)
                from .model_pool import ModelPool
                face_map = ModelPool.match_faces_to_persons(all_faces, person_boxes)

            # --- C: Per-person ReID ---
            for j, box in enumerate(boxes):
                x1, y1, x2, y2 = box.astype(int)
                tracker_input.append([x1, y1, x2, y2, confs[j], 0])

                raw_crop = frame[max(0, y1):min(h, y2), max(0, x1):min(w, x2)]
                if raw_crop.size > 0:
                    face_data = face_map.get(j, None)
                    pre_face_emb = face_data.get('embedding') if face_data else None

                    # Early exit for strong face match
                    if pre_face_emb is not None:
                        face_score = self.pool.compute_face_similarity(pre_face_emb)
                        if face_score > 0.7:
                            current_detections.append({
                                'bbox': [x1, y1, x2, y2],
                                'score': face_score
                            })
                            continue

                    # Full similarity
                    sim_score, _ = self.pool.compute_similarity(
                        raw_crop, face_embedding=pre_face_emb, face_meta=face_data
                    )
                    current_detections.append({
                        'bbox': [x1, y1, x2, y2],
                        'score': sim_score
                    })

            # Update stride FSM
            self.stride_fsm.update(len(person_boxes), frame)
        else:
            self.stride_fsm.update(0, frame)

        # Save for skip frames
        self._last_tracker_input = tracker_input
        self._last_detections = current_detections

        # --- D: ByteTrack Update ---
        target_present, targets = self._update_tracker(
            tracker_input, current_detections, frame
        )
        
        if target_present:
            self.detection_count += 1

        return target_present, targets

    def _process_skip_frame(self, frame: np.ndarray):
        """Reuse previous detections for non-inference frames."""
        return self._update_tracker(
            self._last_tracker_input, self._last_detections, frame
        )

    def _update_tracker(self, tracker_input, detections, frame):
        """Run ByteTrack update and identity matching."""
        target_present = False
        targets = []

        if len(tracker_input) > 0:
            tracks = self.tracker.update(np.array(tracker_input, dtype=float), frame)

            # --- PRE-COMPUTE FACES FOR BATCH MATCHING ---
            # We run face detection once per frame (during inference frames)
            face_map = {}
            if self.identity_mgr.needs_any_reid([int(t[4]) for t in tracks], self.frame_counter):
                faces = self.pool.extract_faces_from_frame(frame)
                person_boxes = [list(map(int, t[:4])) for t in tracks]
                face_map = self.pool.match_faces_to_persons(faces, person_boxes)

            for i, track in enumerate(tracks):
                tx1, ty1, tx2, ty2 = map(int, track[:4])
                tid = int(track[4])

                # Identity management
                fid = -1
                finalized_str = ""
                
                if self.identity_mgr.needs_reid(tid, self.frame_counter):
                    # --- SNAPSHOT GATHERING START ---
                    # 1. Get the specific crop for this track
                    h, w = frame.shape[:2]
                    crop = frame[max(0,ty1):min(h,ty2), max(0,tx1):min(w,tx2)]
                    
                    face_data = face_map.get(i)
                    face_emb = face_data.get('embedding') if face_data else None
                    pose_cat = face_data.get('pose_category', 'other') if face_data else 'other'
                    
                    # 2. Hybrid Similarity
                    similarity, _ = self.pool.compute_similarity(
                        crop, face_embedding=face_emb, face_meta=face_data
                    )
                    
                    # 3. Update track with snapshot
                    is_target, fid = self.identity_mgr.update_track(
                        tid, similarity, embedding=face_emb, 
                        frame_id=self.frame_counter,
                        pose_category=pose_cat,
                        crop=crop
                    )
                    
                    if is_target:
                        self._track_scores[tid] = similarity
                        # Get identity object to check finalized shots
                        _, identity = self.identity_mgr.get_identity_for_fid(fid)
                        if identity:
                            finalized_str = ",".join(identity.finalized_shots)
                else:
                    # For non-reid frames, check latched status
                    is_target, stored_score, fid = self.identity_mgr.is_target(tid)
                    self.identity_mgr.mark_frame(tid, self.frame_counter)
                    if is_target:
                        if tid not in self._track_scores:
                            self._track_scores[tid] = stored_score
                        _, identity = self.identity_mgr.get_identity_for_fid(fid)
                        if identity:
                            finalized_str = ",".join(identity.finalized_shots)

                if is_target:
                    target_present = True
                    display_score = self._track_scores.get(tid, 0.5)
                    targets.append(([tx1, ty1, tx2, ty2], display_score, fid, finalized_str))

        # Cleanup stale track scores
        if self.frame_counter % 100 == 0:
            active_ids = {int(t[4]) for t in (self._last_tracker_input if self._last_tracker_input else [])}
            self._track_scores = {tid: s for tid, s in self._track_scores.items() if tid in active_ids}

        return target_present, targets

    @staticmethod
    def _iou(boxA, boxB):
        xA = max(boxA[0], boxB[0])
        yA = max(boxA[1], boxB[1])
        xB = min(boxA[2], boxB[2])
        yB = min(boxA[3], boxB[3])
        inter = max(0, xB - xA) * max(0, yB - yA)
        areaA = (boxA[2] - boxA[0]) * (boxA[3] - boxA[1])
        areaB = (boxB[2] - boxB[0]) * (boxB[3] - boxB[1])
        return inter / float(areaA + areaB - inter + 1e-6)

    def _enhance_frame(self, frame: np.ndarray) -> np.ndarray:
        """V2: Conditional low-light enhancement."""
        if self._lowlight is None:
            return frame
        try:
            result = self._lowlight.enhance(frame)
            return result.frame
        except Exception:
            return frame

    def get_status(self) -> dict:
        """Return processing metrics."""
        status = {
            'stream_id': self.stream_id,
            'frames_processed': self.frame_counter,
            'inferences_run': self.inference_count,
            'detections': self.detection_count,
            'alerts': self.alert_mgr.alert_count,
            'fps_processing': round(self.fps_processing, 1),
            'stride_mode': self.stride_fsm.mode,
            'stride_skip': self.stride_fsm.get_skip_n(),
            'capture_health': self.capture.get_health(),
            'last_error': self.last_error,
            'v2_active': self._v2_active,
        }
        if self._lowlight and self._lowlight.is_night_mode:
            status['night_mode'] = True
        return status
