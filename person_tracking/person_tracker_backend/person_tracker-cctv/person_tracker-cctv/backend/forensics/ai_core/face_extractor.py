import cv2
import numpy as np
import logging
from pathlib import Path
from typing import Tuple, Optional, Dict, List
import insightface
from insightface.app import FaceAnalysis

logger = logging.getLogger(__name__)

class FaceReIDExtractor:
    """
    AntelopeV2 Face Extractor for RTX A5000.
    Optimized for CCTV: Low thresholds, Synthetic Augmentation, and Blind Upscaling.
    """
    def __init__(self, device: str = 'cuda:0'):
        self.device = device
        
        # 1. Setup Paths
        base_path = Path(__file__).resolve().parent
        model_root = str(base_path / 'weights')
        model_subfolder = base_path / 'weights' / 'models' / 'antelopev2'
        
        if not model_subfolder.exists():
            logger.critical(f"AntelopeV2 folder missing at: {model_subfolder}")
            raise RuntimeError(f"Directory not found: {model_subfolder}")

        logger.info(f"Initializing FaceReID (AntelopeV2) on GPU: {device}...")
        
        try:
            self.app = FaceAnalysis(
                name='antelopev2', 
                root=model_root, 
                providers=['CUDAExecutionProvider', 'CPUExecutionProvider']
            )
            self.app.prepare(ctx_id=0 if 'cuda' in device else -1, det_size=(640, 640))
            
            # --- AGGRESSIVE FIX 1: LOWER DETECTION THRESHOLD ---
            # Default is usually 0.5. We drop to 0.25 to catch blurry/dark faces.
            if hasattr(self.app, 'det_model'):
                self.app.det_model.score_thresh = 0.25
                logger.info("Forensic Mode: Detection threshold lowered to 0.25")
                
        except Exception as e:
            logger.critical(f"Failed to load InsightFace: {e}")
            raise RuntimeError(f"Face ReID Initialization Failed.")

    def extract_face_embedding(self, image_bgr: np.ndarray) -> Tuple[Optional[np.ndarray], Dict]:
        """
        Extracts face embedding. Includes 'Blind Upscaling' for tiny CCTV faces.
        """
        if image_bgr is None or image_bgr.size == 0:
            return None, {}

        try:
            h, w = image_bgr.shape[:2]
            process_img = image_bgr

            # --- AGGRESSIVE FIX 2: BLIND UPSCALING ---
            # If the crop is tiny (e.g. 25px), the detector fails. 
            # We scale it up 2x so the detector can find landmarks.
            scale_factor = 1.0
            if w < 40:
                scale_factor = 2.0
                process_img = cv2.resize(image_bgr, (0,0), fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)

            faces = self.app.get(process_img)
            if not faces:
                return None, {}

            # Pick largest face
            target_face = max(faces, key=lambda f: (f.bbox[2]-f.bbox[0]) * (f.bbox[3]-f.bbox[1]))

            # --- AGGRESSIVE FIX 3: LOWER SIZE LIMIT ---
            # Adjust bounding box back to original scale to check real size
            real_w = (target_face.bbox[2] - target_face.bbox[0]) / scale_factor
            
            # Accept faces down to 10px (previously 20px)
            if real_w < 10: 
                return None, {"error": "Face too small"}

            embedding = target_face.embedding.flatten()
            norm = np.linalg.norm(embedding)
            if norm > 0:
                embedding = embedding / norm

            meta = {
                "bbox": target_face.bbox.astype(int).tolist(),
                "det_score": float(target_face.det_score)
            }
            return embedding, meta

        except Exception as e:
            logger.error(f"Face extraction error: {e}")
            return None, {}

    def extract_all_face_embeddings(self, frame_bgr: np.ndarray) -> List[Dict]:
        """
        Run InsightFace ONCE on the full frame. Returns all detected faces
        with embeddings and bounding boxes. Much faster than per-crop extraction.
        """
        if frame_bgr is None or frame_bgr.size == 0:
            return []

        try:
            faces = self.app.get(frame_bgr)
            results = []
            for face in faces:
                embedding = face.embedding.flatten()
                norm = np.linalg.norm(embedding)
                if norm > 0:
                    embedding = embedding / norm
                
                pose = self.estimate_pose(face)
                results.append({
                    'bbox': face.bbox.astype(int).tolist(),
                    'embedding': embedding,
                    'det_score': float(face.det_score),
                    'pose': pose,
                    'pose_category': self.get_pose_category(pose)
                })
            return results
        except Exception as e:
            logger.error(f"Batch face extraction error: {e}")
            return []

    def _generate_augmentations(self, image: np.ndarray) -> List[np.ndarray]:
        """
        Creates synthetic degradations AND geometric variants of the reference image.
        Covers: quality degradation, pose variation, and blur simulation.
        """
        augments = [image]
        try:
            h, w = image.shape[:2]
            
            # --- QUALITY DEGRADATIONS ---
            
            # 1. Low-Res Simulation (fixed 40px)
            if w > 60:
                scale = 40.0 / w
                low_res = cv2.resize(image, (0,0), fx=scale, fy=scale, interpolation=cv2.INTER_LINEAR)
                restored = cv2.resize(low_res, (w, h), interpolation=cv2.INTER_NEAREST)
                augments.append(restored)

            # 2. Grayscale
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            gray_bgr = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
            augments.append(gray_bgr)

            # 3. High Contrast (CLAHE)
            lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
            l, a, b = cv2.split(lab)
            clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8,8))
            cl = clahe.apply(l)
            limg = cv2.merge((cl,a,b))
            contrast = cv2.cvtColor(limg, cv2.COLOR_LAB2BGR)
            augments.append(contrast)

            # --- GEOMETRIC VARIANTS ---
            
            # 4. Roll Rotations (±15°, ±30°) — covers tilted head / angled CCTV
            for angle in [15, -15, 30, -30]:
                M = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
                rotated = cv2.warpAffine(image, M, (w, h), borderMode=cv2.BORDER_REPLICATE)
                augments.append(rotated)

            # 5. Horizontal Flip — mirrors left profile to right profile
            augments.append(cv2.flip(image, 1))

            # --- ENHANCED BLUR ---
            
            # 6. Stronger Gaussian Blur (replaces old mild 5x5)
            blur = cv2.GaussianBlur(image, (9, 9), 0)
            augments.append(blur)

            # 7. Directional Motion Blur — simulates camera/subject movement
            motion_kernel = np.zeros((15, 15), dtype=np.float32)
            motion_kernel[7, :] = 1.0 / 15.0
            motion_blur = cv2.filter2D(image, -1, motion_kernel)
            augments.append(motion_blur)

        except Exception as e:
            logger.warning(f"Augmentation skipped: {e}")
        
        return augments

    def _generate_resolution_matched(self, image: np.ndarray, target_face_width: int) -> List[np.ndarray]:
        """
        Creates resolution-matched copies of the reference image.
        Downscales to target_face_width then upscales back to original size,
        so the embedding 'sees' the same quality as the actual video.
        """
        h, w = image.shape[:2]
        if target_face_width >= w or target_face_width < 15:
            return []  # No point if ref is already smaller, or target too tiny
        
        variants = []
        scale = target_face_width / w
        
        try:
            # 1. Exact resolution match
            small = cv2.resize(image, (0, 0), fx=scale, fy=scale, interpolation=cv2.INTER_LINEAR)
            restored = cv2.resize(small, (w, h), interpolation=cv2.INTER_CUBIC)
            variants.append(restored)
            
            # 2. Slightly worse than video (catch degraded frames)
            worse_scale = scale * 0.7
            if worse_scale * w >= 10:
                smaller = cv2.resize(image, (0, 0), fx=worse_scale, fy=worse_scale, interpolation=cv2.INTER_LINEAR)
                restored2 = cv2.resize(smaller, (w, h), interpolation=cv2.INTER_CUBIC)
                variants.append(restored2)
        except Exception as e:
            logger.warning(f"Resolution-matched augmentation skipped: {e}")
        
        return variants

    def extract_gallery_embeddings(self, image_paths: List[str]) -> List[Dict]:
        """
        Processes reference images AND their synthetic variants.
        """
        gallery = []
        for path in image_paths:
            img = cv2.imread(path)
            if img is None: continue
            
            variations = self._generate_augmentations(img)
            
            for i, variant in enumerate(variations):
                emb, meta = self.extract_face_embedding(variant)
                if emb is not None:
                    gallery.append({
                        'path': path, 
                        'embedding': emb, 
                        'meta': meta,
                        'variant': i
                    })
        return gallery

    def estimate_pose(self, face) -> Dict[str, float]:
        """Estimate yaw, pitch, roll from 5-point landmarks."""
        if not hasattr(face, 'kps'):
            return {'yaw': 0.0, 'pitch': 0.0, 'roll': 0.0}
        
        kps = face.kps
        # Basic heuristics for pose from 5 points:
        # 0: Left Eye, 1: Right Eye, 2: Nose, 3: Left Mouth, 4: Right Mouth
        
        # Yaw: difference in eye-to-nose distances
        left_eye_dist = np.linalg.norm(kps[0] - kps[2])
        right_eye_dist = np.linalg.norm(kps[1] - kps[2])
        yaw = (right_eye_dist - left_eye_dist) / (right_eye_dist + left_eye_dist + 1e-6) * 90
        
        # Pitch: nose position relative to eye-mouth bridge
        eye_center = (kps[0] + kps[1]) / 2
        mouth_center = (kps[3] + kps[4]) / 2
        bridge_len = np.linalg.norm(eye_center - mouth_center)
        nose_to_eye = np.linalg.norm(kps[2] - eye_center)
        pitch = (nose_to_eye / (bridge_len + 1e-6) - 0.5) * 90
        
        # Roll: eye tilt
        dy = kps[1][1] - kps[0][1]
        dx = kps[1][0] - kps[0][0]
        roll = np.degrees(np.arctan2(dy, dx))
        
        return {'yaw': yaw, 'pitch': pitch, 'roll': roll}

    def get_pose_category(self, pose: Dict[str, float]) -> str:
        """Categorize pose into 'front', 'side', or 'down'."""
        yaw = abs(pose['yaw'])
        pitch = pose['pitch']
        
        if pitch > 20:
            return 'down'
        if yaw > 30:
            return 'side'
        if yaw < 15 and abs(pitch) < 15:
            return 'front'
        
        return 'other'