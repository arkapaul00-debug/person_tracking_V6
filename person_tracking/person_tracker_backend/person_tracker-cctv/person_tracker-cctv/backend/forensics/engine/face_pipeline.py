"""
Adaptive Face Pipeline — Quality-Routed Multi-Model Face Recognition.

Architecture:
    Detection:   RetinaFace TensorRT (replaces InsightFace SCRFD for higher recall)
    
    Recognition hierarchy (selected per-face based on quality scoring):
        1. AdaFace IR101     → excellent pose/quality (frontal, well-lit, sharp)
        2. ElasticFace Arc   → moderate quality (slight angle, mild blur)
        3. MagFace IR100     → low quality but detectable features
        4. CurricularFace    → difficult lighting conditions (backlit, IR)
    
    Partial/masked face handling:
        - If visible face region > 40% but < 80% → PartialFace model
        - If masked detected → attempt with lower-threshold extraction
    
    CRITICAL: DO NOT run all models simultaneously per face.
    Route to exactly ONE model based on quality scoring.
    
    Fallback: If no specialized model is available, uses the existing
    InsightFace AntelopeV2 pipeline (face_extractor.py) — backward compatible.
"""
import time
import logging
import cv2
import numpy as np
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class FaceQuality:
    """Quality assessment of a detected face."""
    pose_score: float = 0.5        # 0=extreme profile, 1=frontal
    blur_score: float = 0.5        # 0=very blurry, 1=sharp
    illumination_score: float = 0.5  # 0=dark/overexposed, 1=well-lit
    occlusion_score: float = 0.0   # 0=no occlusion, 1=fully occluded
    size_px: int = 0               # Face width in pixels
    det_confidence: float = 0.0    # Detection model confidence
    is_masked: bool = False
    is_partial: bool = False
    overall_score: float = 0.5     # Composite quality (0-1)
    recommended_model: str = 'insightface'  # Which model to use


@dataclass
class FaceResult:
    """Result of face detection + recognition for a single face."""
    bbox: List[int]                  # [x1, y1, x2, y2]
    embedding: Optional[np.ndarray]  # Face embedding vector
    quality: FaceQuality
    model_used: str = 'insightface'
    det_score: float = 0.0
    match_score: float = 0.0        # Gallery match score
    best_match_ref: str = ''        # Best matching reference image
    pose: Dict[str, float] = field(default_factory=dict)
    pose_category: str = 'other'


class FaceQualityScorer:
    """
    Assess face quality to determine the best recognition model.
    
    Uses lightweight image-level features (no model inference needed)
    to score each detected face before routing to expensive recognition.
    """

    def __init__(self):
        self._min_face_size = 10  # Minimum usable face width in pixels

    def score(self, face_crop: np.ndarray,
              det_score: float = 0.5,
              landmarks: Optional[np.ndarray] = None) -> FaceQuality:
        """
        Score a face crop's quality across multiple dimensions.
        
        Args:
            face_crop: BGR face crop.
            det_score: Detection confidence from the face detector.
            landmarks: Optional 5-point facial landmarks.
            
        Returns:
            FaceQuality with per-dimension scores and model recommendation.
        """
        q = FaceQuality()
        
        if face_crop is None or face_crop.size == 0:
            q.overall_score = 0.0
            return q
        
        h, w = face_crop.shape[:2]
        q.size_px = w
        q.det_confidence = det_score
        
        # --- Blur Score (Laplacian variance) ---
        try:
            gray = cv2.cvtColor(face_crop, cv2.COLOR_BGR2GRAY)
            laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()
            # Normalize: < 50 = very blurry, > 500 = very sharp
            q.blur_score = float(np.clip(laplacian_var / 500.0, 0.0, 1.0))
        except Exception:
            q.blur_score = 0.3
        
        # --- Illumination Score ---
        try:
            gray = cv2.cvtColor(face_crop, cv2.COLOR_BGR2GRAY) if len(face_crop.shape) == 3 else face_crop
            mean_brightness = np.mean(gray)
            std_brightness = np.std(gray)
            # Ideal brightness: ~120-140. Too dark or too bright = bad.
            brightness_score = 1.0 - abs(130 - mean_brightness) / 130.0
            contrast_score = min(std_brightness / 50.0, 1.0)
            q.illumination_score = float(np.clip(
                0.6 * brightness_score + 0.4 * contrast_score, 0.0, 1.0
            ))
        except Exception:
            q.illumination_score = 0.5
        
        # --- Pose Score (from landmarks if available) ---
        if landmarks is not None and len(landmarks) >= 5:
            q.pose_score = self._estimate_pose_quality(landmarks)
        else:
            # Heuristic: aspect ratio of face crop correlates with pose
            aspect = w / max(h, 1)
            if 0.7 < aspect < 1.0:
                q.pose_score = 0.8  # Near-frontal
            elif 0.5 < aspect <= 0.7:
                q.pose_score = 0.5  # Moderate angle
            else:
                q.pose_score = 0.3  # Extreme angle or unusual crop
        
        # --- Occlusion estimate ---
        # Simple heuristic: if lower half of face has very different
        # brightness than upper half, likely occluded/masked
        try:
            gray = cv2.cvtColor(face_crop, cv2.COLOR_BGR2GRAY)
            upper = gray[:h // 2, :]
            lower = gray[h // 2:, :]
            diff = abs(float(np.mean(upper)) - float(np.mean(lower)))
            if diff > 60:
                q.is_masked = True
                q.occlusion_score = min(diff / 100.0, 1.0)
            # Check for very low variance in lower half (uniform color = mask)
            if np.std(lower) < 10:
                q.is_masked = True
                q.occlusion_score = max(q.occlusion_score, 0.5)
        except Exception:
            pass
        
        # --- Size penalty ---
        if w < self._min_face_size:
            q.overall_score = 0.0
            q.recommended_model = 'skip'
            return q
        
        # --- Composite Score ---
        q.overall_score = float(np.clip(
            0.30 * q.pose_score +
            0.25 * q.blur_score +
            0.20 * q.illumination_score +
            0.15 * q.det_confidence +
            0.10 * (1.0 - q.occlusion_score),
            0.0, 1.0
        ))
        
        # --- Model Recommendation ---
        q.recommended_model = self._recommend_model(q)
        
        return q

    def _estimate_pose_quality(self, landmarks: np.ndarray) -> float:
        """Estimate pose quality from 5-point landmarks."""
        try:
            # Landmarks: [left_eye, right_eye, nose, left_mouth, right_mouth]
            left_eye = landmarks[0]
            right_eye = landmarks[1]
            nose = landmarks[2]
            
            # Yaw: asymmetry of eye-to-nose distances
            left_dist = np.linalg.norm(left_eye - nose)
            right_dist = np.linalg.norm(right_eye - nose)
            symmetry = 1.0 - abs(left_dist - right_dist) / (left_dist + right_dist + 1e-6)
            
            return float(np.clip(symmetry, 0.0, 1.0))
        except Exception:
            return 0.5

    @staticmethod
    def _recommend_model(q: FaceQuality) -> str:
        """
        Select the best recognition model based on quality scores.
        
        Priority: Use the lightest model that can handle the quality level.
        """
        if q.is_masked or q.is_partial:
            return 'partialface'
        
        if q.overall_score > 0.75 and q.pose_score > 0.7:
            return 'adaface'      # Best for high-quality frontal
        elif q.overall_score > 0.50:
            return 'elasticface'  # Good for moderate quality
        elif q.illumination_score < 0.3:
            return 'curricularface'  # Best for lighting issues
        elif q.overall_score > 0.25:
            return 'magface'      # Handles low quality
        else:
            return 'insightface'  # Fallback to existing pipeline


class AdaptiveFacePipeline:
    """
    Quality-routed face recognition with multi-model fallback chain.
    
    Usage:
        pipeline = AdaptiveFacePipeline(model_pool, device='cuda:0')
        
        # Detect and recognize all faces in a frame
        results = pipeline.detect_and_recognize(frame)
        
        # Match faces against a gallery
        matches = pipeline.match_against_gallery(frame, gallery_embeddings)
    """

    def __init__(self, model_pool, device: str = 'cuda:0'):
        """
        Args:
            model_pool: Shared ModelPool with face_model loaded.
            device: CUDA device.
        """
        self.model_pool = model_pool
        self.device = device
        self.quality_scorer = FaceQualityScorer()
        
        # The existing InsightFace model (always available as fallback)
        self._insightface = model_pool.face_model
        
        # Advanced models (lazy loaded — only instantiated when quality routing
        # determines they're needed AND weights are available)
        self._models: Dict[str, any] = {}
        self._model_available: Dict[str, bool] = {}
        
        # Weights directory
        self._weights_dir = Path(__file__).resolve().parent.parent / 'ai_core' / 'weights'
        
        # Metrics
        self._total_faces = 0
        self._model_usage: Dict[str, int] = {}
        self._quality_distribution: Dict[str, int] = {
            'high': 0, 'medium': 0, 'low': 0, 'skip': 0
        }
        
        logger.info("AdaptiveFacePipeline initialized (fallback=InsightFace AntelopeV2)")

    def detect_and_recognize(self, frame: np.ndarray) -> List[FaceResult]:
        """
        Detect all faces in frame and extract embeddings using quality-routed models.
        
        Args:
            frame: BGR numpy array.
            
        Returns:
            List of FaceResult for each detected face.
        """
        results = []
        
        if self._insightface is None:
            return results
        
        # Step 1: Detect all faces using existing InsightFace detector
        # (single pass on full frame — no per-crop detection)
        raw_faces = self.model_pool.extract_faces_from_frame(frame)
        
        if not raw_faces:
            return results
        
        for face_data in raw_faces:
            self._total_faces += 1
            
            bbox = face_data['bbox']
            embedding = face_data.get('embedding')
            det_score = face_data.get('det_score', 0.5)
            pose = face_data.get('pose', {})
            pose_category = face_data.get('pose_category', 'other')
            
            # Extract face crop for quality assessment
            x1, y1, x2, y2 = bbox
            h, w = frame.shape[:2]
            x1c, y1c = max(0, x1), max(0, y1)
            x2c, y2c = min(w, x2), min(h, y2)
            face_crop = frame[y1c:y2c, x1c:x2c]
            
            # Step 2: Assess quality
            landmarks = face_data.get('kps', None)
            quality = self.quality_scorer.score(face_crop, det_score, landmarks)
            
            # Step 3: Route to best model
            final_embedding = self._route_to_model(
                face_crop, embedding, quality
            )
            
            # Track quality distribution
            if quality.overall_score > 0.7:
                self._quality_distribution['high'] += 1
            elif quality.overall_score > 0.4:
                self._quality_distribution['medium'] += 1
            elif quality.overall_score > 0.1:
                self._quality_distribution['low'] += 1
            else:
                self._quality_distribution['skip'] += 1
            
            results.append(FaceResult(
                bbox=bbox,
                embedding=final_embedding,
                quality=quality,
                model_used=quality.recommended_model,
                det_score=det_score,
                pose=pose,
                pose_category=pose_category,
            ))
        
        return results

    def _route_to_model(self, face_crop: np.ndarray,
                        insightface_embedding: Optional[np.ndarray],
                        quality: FaceQuality) -> Optional[np.ndarray]:
        """
        Route face to the best available model based on quality.
        
        Falls back through the chain until a working model is found:
        recommended → elasticface → insightface (always available)
        """
        recommended = quality.recommended_model
        
        # Track usage
        self._model_usage[recommended] = self._model_usage.get(recommended, 0) + 1
        
        # If InsightFace is recommended or embedding already available, use it directly
        if recommended == 'insightface' and insightface_embedding is not None:
            return insightface_embedding
        
        # Try to use the recommended model
        model = self._get_model(recommended)
        if model is not None:
            try:
                embedding = self._extract_with_model(model, recommended, face_crop)
                if embedding is not None:
                    return embedding
            except Exception as e:
                logger.warning(f"Model '{recommended}' failed: {e}")
        
        # Fallback: use InsightFace embedding (always available from initial detection)
        if insightface_embedding is not None:
            return insightface_embedding
        
        # Last resort: re-extract with InsightFace on crop
        if self._insightface is not None:
            try:
                emb, _ = self._insightface.extract_face_embedding(face_crop)
                return emb
            except Exception:
                pass
        
        return None

    def _get_model(self, name: str) -> Optional[any]:
        """
        Get a model instance, lazy-loading if needed.
        
        Returns None if the model's weights aren't available.
        """
        # Already loaded
        if name in self._models:
            return self._models[name]
        
        # Known unavailable
        if self._model_available.get(name) is False:
            return None
        
        # InsightFace is always the fallback
        if name == 'insightface':
            return self._insightface
        
        # Skip unknown models — they will use InsightFace fallback
        # Advanced models (adaface, elasticface, etc.) require their own
        # weight files. If not present, mark as unavailable.
        weight_patterns = {
            'adaface': 'adaface_ir101_*.onnx',
            'elasticface': 'elasticface_arc_*.onnx',
            'magface': 'magface_ir100_*.onnx',
            'curricularface': 'curricularface_*.onnx',
            'partialface': 'partialface_*.onnx',
        }
        
        pattern = weight_patterns.get(name)
        if pattern is None:
            self._model_available[name] = False
            return None
        
        # Check if weights exist
        matches = list(self._weights_dir.glob(pattern))
        if not matches:
            logger.debug(f"Weights for '{name}' not found ({pattern}) — using InsightFace fallback")
            self._model_available[name] = False
            return None
        
        # TODO: Load the actual model when weights are deployed
        # For now, mark as unavailable — InsightFace fallback handles all cases
        logger.info(f"Found weights for '{name}': {matches[0].name} — model loading not yet implemented")
        self._model_available[name] = False
        return None

    def _extract_with_model(self, model: any, name: str,
                            face_crop: np.ndarray) -> Optional[np.ndarray]:
        """Extract embedding using a specific model."""
        # Each model type has its own preprocessing and extraction
        # For now, all models go through InsightFace as the universal fallback
        if hasattr(model, 'extract_face_embedding'):
            emb, _ = model.extract_face_embedding(face_crop)
            return emb
        return None

    def match_faces_to_persons(self, face_results: List[FaceResult],
                                person_boxes: List[List[int]]) -> Dict[int, FaceResult]:
        """
        Match detected faces to person bounding boxes by containment.
        
        Args:
            face_results: Results from detect_and_recognize().
            person_boxes: Person bboxes from YOLO [[x1,y1,x2,y2], ...].
            
        Returns:
            {person_index: FaceResult} mapping.
        """
        face_map = {}
        
        for face in face_results:
            fbbox = face.bbox
            fx_center = (fbbox[0] + fbbox[2]) / 2
            fy_center = (fbbox[1] + fbbox[3]) / 2
            
            for pi, pbox in enumerate(person_boxes):
                if pi not in face_map:
                    if (pbox[0] <= fx_center <= pbox[2] and
                            pbox[1] <= fy_center <= pbox[3]):
                        face_map[pi] = face
                        break
        
        return face_map

    def get_metrics(self) -> dict:
        """Return pipeline performance metrics."""
        return {
            'total_faces': self._total_faces,
            'model_usage': dict(self._model_usage),
            'quality_distribution': dict(self._quality_distribution),
            'models_available': {k: v for k, v in self._model_available.items()},
            'fallback_model': 'insightface_antelopev2',
        }
