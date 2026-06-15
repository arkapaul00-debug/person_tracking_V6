"""
Shared Model Pool — Singleton GPU Model Manager for Real-Time CCTV Tracking.

Loads all AI models ONCE at startup and provides thread-safe inference.
Eliminates redundant model loading across streams/chunks.

Models managed:
    - YOLOv10n (Person Detection) — TensorRT if available, else PyTorch
    - InsightFace AntelopeV2 (Face ReID)
    - OSNet x1_0 (Body ReID)

V2 Architecture (City-Scale):
    - Per-model CUDA streams replace the global _inference_lock
    - Detection, face, and body run concurrently on separate GPU streams
    - Batch detection API for cross-stream frame aggregation
    - CUDAStreamPool integration for managed concurrent execution
"""
import threading
import logging
import cv2
import torch
import numpy as np
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from scipy.spatial.distance import cosine

logger = logging.getLogger(__name__)


class ModelPool:
    """
    Singleton: loads all AI models once, provides thread-safe inference.
    
    Usage:
        pool = ModelPool.get_instance(mode='hybrid', device='cuda:0')
        detections = pool.detect_persons(frame)
        faces = pool.extract_faces(frame)
        body_emb = pool.extract_body_embedding(crop)
    """
    _instance = None
    _lock = threading.Lock()

    def __init__(self, mode: str = 'hybrid', device: str = 'cuda:0'):
        """Do NOT call directly. Use ModelPool.get_instance()."""
        self.mode = mode
        if device.startswith('cuda') and torch.cuda.is_available():
            self.device = device
            self._detection_stream = torch.cuda.Stream(device=self.device)
            self._face_stream = torch.cuda.Stream(device=self.device)
            self._body_stream = torch.cuda.Stream(device=self.device)
        else:
            self.device = 'cpu'
            self._detection_stream = None
            self._face_stream = None
            self._body_stream = None
            
        self._detection_lock = threading.Lock()
        self._face_lock = threading.Lock()
        self._body_lock = threading.Lock()

        # Backward compatibility: keep _inference_lock as alias for legacy code
        # that may reference it (e.g., views.py GPU_LOCK).
        # New code should use the per-model locks above.
        self._inference_lock = self._detection_lock

        base_dir = Path(__file__).resolve().parent / 'ai_core' / 'weights'

        # --- 1. YOLO Person Detector (YOLOv10n for speed) ---
        from ultralytics import YOLO
        yolo_engine = base_dir / 'yolov10n.engine'
        yolo_pt = base_dir / 'yolov10n.pt'
        # Fallback to yolov10s if nano not available
        if not yolo_engine.exists() and not yolo_pt.exists():
            yolo_engine = base_dir / 'yolov10s.engine'
            yolo_pt = base_dir / 'yolov10s.pt'
            logger.warning("YOLOv10n not found, falling back to YOLOv10s")

        if yolo_engine.exists():
            logger.info(f"Loading TensorRT Engine: {yolo_engine}")
            self.detector = YOLO(str(yolo_engine), task='detect')
        else:
            logger.info(f"Loading PyTorch Model: {yolo_pt}")
            self.detector = YOLO(str(yolo_pt))

        # --- 2. Face ReID (InsightFace AntelopeV2) ---
        self.face_model = None
        if mode in ['face', 'hybrid']:
            from .ai_core.face_extractor import FaceReIDExtractor
            try:
                self.face_model = FaceReIDExtractor(device=device)
                logger.info("Face model (InsightFace) loaded")
            except Exception as e:
                logger.error(f"Failed to load Face model: {e}")
                self.face_model = None

        # --- 3. Body ReID (OSNet x1_0) ---
        self.body_model = None
        if mode in ['body', 'hybrid']:
            from .ai_core.body_extractor import BodyReIDExtractor
            try:
                self.body_model = BodyReIDExtractor(device=device)
                logger.info("Body model (OSNet x1_0) loaded")
            except Exception as e:
                logger.error(f"Failed to load Body model: {e}")
                self.body_model = None

        # --- 4. Reference Gallery (populated by build_gallery) ---
        self.ref_data = {'face': [], 'body': []}
        self._gallery_built = False

        # --- 5. Adaptive Feature Fusion Engine (Phase 36) ---
        try:
            from .engine.confidence_fusion import ConfidenceFusionEngine
            self.fusion_engine = ConfidenceFusionEngine()
        except ImportError:
            self.fusion_engine = None

        logger.info(f"ModelPool initialized (mode={mode}, device={device}, concurrent_streams=3)")

    @classmethod
    def get_instance(cls, mode: str = 'hybrid', device: str = 'cuda:0') -> 'ModelPool':
        """Thread-safe singleton accessor."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls(mode=mode, device=device)
        return cls._instance

    @classmethod
    def reset(cls):
        """Reset singleton (for testing or mode change)."""
        with cls._lock:
            if cls._instance is not None:
                cls._instance._cleanup()
                cls._instance = None

    def build_gallery(self, ref_paths: List[str]):
        """
        Process reference images into face/body embedding galleries.
        Must be called before starting any stream processing.
        """
        self.ref_data = {'face': [], 'body': []}

        # Face gallery
        if self.face_model and ref_paths:
            try:
                self.ref_data['face'] = self.face_model.extract_gallery_embeddings(ref_paths)
                logger.info(f"Face gallery: {len(self.ref_data['face'])} embeddings (incl. augmented)")
            except Exception as e:
                logger.warning(f"Face gallery extraction issue: {e}")

        # Body gallery
        if self.body_model and ref_paths:
            from .ai_core.enhanced_preprocessor import DomainAdaptivePreprocessor
            for p in ref_paths:
                img = cv2.imread(p)
                if img is None:
                    continue
                with self._detection_lock:
                    if self._detection_stream:
                        with torch.cuda.stream(self._detection_stream):
                            results = self.detector(img, conf=0.4, classes=[0], verbose=False)
                        self._detection_stream.synchronize()
                    else:
                        results = self.detector(img, conf=0.4, classes=[0], verbose=False)
                if results[0].boxes:
                    boxes = results[0].boxes.xyxy.cpu().numpy()
                    best_box = max(boxes, key=lambda b: (b[2] - b[0]) * (b[3] - b[1]))
                    x1, y1, x2, y2 = best_box.astype(int)
                    person_crop = img[y1:y2, x1:x2]
                    person_crop = DomainAdaptivePreprocessor.normalize_to_lab(person_crop)
                    emb = self.body_model.extract_body_embedding(person_crop)
                    if emb is not None:
                        self.ref_data['body'].append({'path': p, 'embedding': emb})

            logger.info(f"Body gallery: {len(self.ref_data['body'])} embeddings")

        self._gallery_built = True

    # ---- Thread-safe inference methods (V2: per-model CUDA streams) ----

    def detect_persons(self, frame: np.ndarray, conf: float = 0.3) -> list:
        """
        Run YOLO person detection on a frame.
        Returns raw YOLO results object.
        Thread-safe via dedicated detection CUDA stream.
        """
        with self._detection_lock:
            if self._detection_stream:
                with torch.cuda.stream(self._detection_stream):
                    results = self.detector(frame, conf=conf, classes=[0], verbose=False)
                self._detection_stream.synchronize()
            else:
                results = self.detector(frame, conf=conf, classes=[0], verbose=False)
        return results

    def detect_persons_batch(self, frames: List[np.ndarray], conf: float = 0.3) -> list:
        """
        Run YOLO on a batch of frames from multiple streams.
        Used by DynamicBatchScheduler for cross-stream aggregation.

        Args:
            frames: List of BGR numpy arrays from different streams.
            conf: Confidence threshold.

        Returns:
            List of YOLO result objects, one per input frame.
        """
        if not frames:
            return []
        with self._detection_lock:
            if self._detection_stream:
                with torch.cuda.stream(self._detection_stream):
                    results = self.detector(frames, conf=conf, classes=[0], verbose=False)
                self._detection_stream.synchronize()
            else:
                results = self.detector(frames, conf=conf, classes=[0], verbose=False)
        return results

    def extract_faces_from_frame(self, frame: np.ndarray) -> List[Dict]:
        """
        Run InsightFace once on full frame.
        Returns list of {'bbox': [x1,y1,x2,y2], 'embedding': np.ndarray}.
        Thread-safe via dedicated face CUDA stream.
        """
        if not self.face_model:
            return []
        with self._face_lock:
            if self._face_stream:
                with torch.cuda.stream(self._face_stream):
                    result = self.face_model.extract_all_face_embeddings(frame)
                self._face_stream.synchronize()
            else:
                result = self.face_model.extract_all_face_embeddings(frame)
        return result

    def extract_body_embedding(self, crop: np.ndarray) -> Optional[np.ndarray]:
        """Extract body embedding from a person crop. Thread-safe via body stream."""
        if not self.body_model:
            return None
        with self._body_lock:
            if self._body_stream:
                with torch.cuda.stream(self._body_stream):
                    result = self.body_model.extract_body_embedding(crop)
                self._body_stream.synchronize()
            else:
                result = self.body_model.extract_body_embedding(crop)
        return result

    def extract_body_embeddings_batch(self, crops: List[np.ndarray]) -> List[Optional[np.ndarray]]:
        """
        Batch body embedding extraction for multiple crops.
        Much faster than sequential per-crop extraction.
        Thread-safe via body stream.
        """
        if not self.body_model:
            return [None] * len(crops)
        with self._body_lock:
            if self._body_stream:
                with torch.cuda.stream(self._body_stream):
                    results = self.body_model.extract_body_embeddings_batch(crops)
                self._body_stream.synchronize()
            else:
                results = self.body_model.extract_body_embeddings_batch(crops)
        return results

    def compute_face_similarity(self, face_embedding) -> float:
        """Compare face embedding against gallery. CPU-only, no lock needed."""
        if face_embedding is None or not self.ref_data.get('face'):
            return 0.0
            
        # Defensive check: if it's a dict, extract the embedding
        if isinstance(face_embedding, dict):
            face_embedding = face_embedding.get('embedding')
            if face_embedding is None:
                return 0.0

        best_sim = 0.0
        for ref in self.ref_data['face']:
            # Defensive 1D ensure
            u = np.asarray(ref['embedding']).reshape(-1)
            v = np.asarray(face_embedding).reshape(-1)
            sim = 1.0 - cosine(u, v)
            if sim > best_sim:
                best_sim = sim
        return float(best_sim)

    def compute_body_similarity(self, body_embedding: np.ndarray) -> float:
        """Compare body embedding against gallery. CPU-only, no lock needed."""
        if body_embedding is None or not self.ref_data.get('body'):
            return 0.0
        best_sim = 0.0
        for ref in self.ref_data['body']:
            u = np.asarray(ref['embedding']).reshape(-1)
            v = np.asarray(body_embedding).reshape(-1)
            sim = 1.0 - cosine(u, v)
            if sim > best_sim:
                best_sim = sim
        return float(best_sim)

    def compute_similarity(self, raw_crop: np.ndarray,
                           face_embedding: Optional[np.ndarray] = None,
                           face_meta: Optional[Dict] = None) -> Tuple[float, Dict]:
        """
        Full hybrid similarity computation for a person crop.
        Returns (final_score, {'face': score, 'body': score, 'pose': category}).
        """
        scores = {'face': 0.0, 'body': 0.0, 'pose': 'other'}
        
        if face_meta:
            scores['pose'] = face_meta.get('pose_category', 'other')

        # 1. Face score
        if self.face_model and self.ref_data['face']:
            # Defensive check: if it's a dict, extract embedding and metadata
            if isinstance(face_embedding, dict):
                face_meta = face_embedding
                face_embedding = face_meta.get('embedding')
                if face_meta:
                    scores['pose'] = face_meta.get('pose_category', 'other')

            if face_embedding is None:
                face_embedding, _ = self.face_model.extract_face_embedding(raw_crop)
            if face_embedding is not None:
                scores['face'] = self.compute_face_similarity(face_embedding)

        # 2. Body score
        if self.body_model and self.ref_data['body']:
            body_emb = self.extract_body_embedding(raw_crop)
            if body_emb is not None:
                scores['body'] = self.compute_body_similarity(body_emb)

        # 3. Fusion
        if self.mode == 'face':
            final = scores['face']
        elif self.mode == 'body':
            final = scores['body']
        else:  # hybrid
            # V3: Phase 36 - Adaptive Feature Fusion
            if hasattr(self, 'fusion_engine') and self.fusion_engine is not None:
                # Try to extract QualityContext if face_meta has it (or build a simple one)
                from .engine.confidence_fusion import QualityContext
                # Simple fallback heuristic for quality based on pose
                face_q = 0.9 if scores['pose'] == 'frontal' else (0.5 if scores['pose'] == 'profile' else 0.1)
                if face_embedding is None:
                    face_q = 0.0
                
                ctx = QualityContext(face_quality=face_q, body_quality=0.8)
                fused = self.fusion_engine.fuse(
                    face_score=float(scores['face']),
                    body_score=float(scores['body']),
                    quality=ctx,
                    mode='hybrid'
                )
                final = fused.fused_score
            else:
                # Legacy Fallback
                if scores['face'] > 0:
                    final = (0.7 * float(scores['face'])) + (0.3 * float(scores['body']))
                else:
                    final = scores['body']

        return float(final), scores

    @staticmethod
    def match_faces_to_persons(faces: List[Dict], person_boxes: List[list]) -> Dict[int, Dict]:
        """
        Match detected faces to person bounding boxes by containment.
        Returns {person_index: {'embedding': np.ndarray, 'pose_category': str}}.
        """
        face_map = {}
        for face in faces:
            fbbox = face['bbox']
            fx_center = (fbbox[0] + fbbox[2]) / 2
            fy_center = (fbbox[1] + fbbox[3]) / 2
            for pi, pbox in enumerate(person_boxes):
                if pi not in face_map:
                    if (pbox[0] <= fx_center <= pbox[2] and
                            pbox[1] <= fy_center <= pbox[3]):
                        face_map[pi] = {
                            'embedding': face['embedding'],
                            'pose_category': face.get('pose_category', 'other')
                        }
                        break
        return face_map

    def _cleanup(self):
        """Release GPU resources."""
        try:
            if hasattr(self, 'detector'):
                del self.detector
            if hasattr(self, 'face_model'):
                del self.face_model
            if hasattr(self, 'body_model'):
                del self.body_model
            torch.cuda.empty_cache()
        except Exception as e:
            logger.error(f"ModelPool cleanup error: {e}")
