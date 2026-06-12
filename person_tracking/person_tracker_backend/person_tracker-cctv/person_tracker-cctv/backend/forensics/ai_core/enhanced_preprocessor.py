import cv2
import numpy as np
import logging
from typing import Tuple, Dict, Any, Optional
from scipy.spatial.distance import cosine, euclidean

# Configure Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("ForensicPreprocessor")

class DomainAdaptivePreprocessor:
    """
    Handles image domain adaptation to bridge the gap between 
    high-quality reference images (phone/DSLR) and low-quality CCTV frames.
    """

    @staticmethod
    def normalize_to_lab(image: np.ndarray, clip_limit: float = 2.0, tile_grid_size: Tuple[int, int] = (8, 8)) -> np.ndarray:
        """
        Converts image to LAB color space and applies CLAHE (Contrast Limited Adaptive Histogram Equalization)
        to the L-channel (Luminance) to normalize lighting conditions without distorting color information.

        Args:
            image: BGR numpy array.
            clip_limit: Threshold for contrast limiting.
            tile_grid_size: Size of grid for histogram equalization.

        Returns:
            BGR numpy array (Lighting normalized).
        """
        try:
            # Convert to LAB
            lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
            l, a, b = cv2.split(lab)

            # Apply CLAHE to L-channel
            clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=tile_grid_size)
            cl = clahe.apply(l)

            # Merge and convert back to BGR
            limg = cv2.merge((cl, a, b))
            final = cv2.cvtColor(limg, cv2.COLOR_LAB2BGR)
            
            return final
        except Exception as e:
            logger.error(f"LAB Normalization failed: {e}")
            return image

    @staticmethod
    def histogram_matching(source: np.ndarray, template: np.ndarray) -> np.ndarray:
        """
        Adjusts the pixel intensity distribution of the source image (reference) 
        to match the template image (CCTV frame crop).
        
        Uses CDF (Cumulative Distribution Function) mapping.
        """
        try:
            src_shape = source.shape
            source = source.ravel()
            template = template.ravel()

            # Get counts and bin locations
            s_values, bin_idx, s_counts = np.unique(source, return_inverse=True, return_counts=True)
            t_values, t_counts = np.unique(template, return_counts=True)

            # Calculate Quantiles
            s_quantiles = np.cumsum(s_counts).astype(np.float64)
            s_quantiles /= s_quantiles[-1]
            
            t_quantiles = np.cumsum(t_counts).astype(np.float64)
            t_quantiles /= t_quantiles[-1]

            # Interpolate
            interp_t_values = np.interp(s_quantiles, t_quantiles, t_values)

            # Map
            matched = interp_t_values[bin_idx].reshape(src_shape).astype(np.uint8)
            return matched
        except Exception as e:
            logger.error(f"Histogram matching failed: {e}")
            return source.reshape(src_shape) if 'src_shape' in locals() else source

    @staticmethod
    def compute_quality_score(image: np.ndarray) -> Dict[str, float]:
        """
        Calculates forensic quality metrics to determine if an image is reliable.

        Returns:
            Dict with 'sharpness', 'brightness', 'contrast', and 'composite_score' (0.0-1.0).
        """
        if image is None or image.size == 0:
            return {'composite_score': 0.0}

        try:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            
            # 1. Sharpness (Variance of Laplacian)
            # Low variance < 100 usually means blurry
            sharpness = cv2.Laplacian(gray, cv2.CV_64F).var()
            
            # 2. Brightness (Mean intensity)
            brightness = np.mean(gray)
            
            # 3. Contrast (Standard Deviation)
            contrast = gray.std()
            
            # Normalize scores roughly to 0-1 range for composition
            # Sigmoid-like normalization or clipping
            norm_sharpness = min(sharpness / 500.0, 1.0)
            norm_brightness = 1.0 - abs(128 - brightness) / 128.0 # 1.0 is ideal (middle grey), 0.0 is pitch black/white
            norm_contrast = min(contrast / 50.0, 1.0)
            
            # Weighted Composite Score
            # Sharpness is most critical for ReID
            composite = (0.5 * norm_sharpness) + (0.3 * norm_contrast) + (0.2 * norm_brightness)

            return {
                'sharpness': sharpness,
                'brightness': brightness,
                'contrast': contrast,
                'composite_score': round(composite, 4)
            }
        except Exception as e:
            logger.error(f"Quality score computation failed: {e}")
            return {'composite_score': 0.0}


class AdaptiveThresholdCalculator:
    """
    Dynamically adjusts the cosine similarity threshold based on the input image quality.
    "Garbage in, Lower Threshold out."
    """

    @staticmethod
    def get_adaptive_threshold(ref_image: np.ndarray, base_threshold: float = 0.75) -> Tuple[float, float, Dict]:
        """
        Calculates a dynamic threshold.
        """
        quality = DomainAdaptivePreprocessor.compute_quality_score(ref_image)
        # Handle different naming conventions (score vs composite_score)
        score = quality.get('score', quality.get('composite_score', 0.0))
        
        reasoning = {
            'base_threshold': base_threshold,
            'image_quality_score': score,
            'adjustment': 0.0
        }

        # Logic: If quality is poor, the ReID vector will be noisy.
        # We must relax the threshold to avoid False Negatives.
        if score < 0.3:
            # Very Poor Quality (Blurry/Dark)
            adjustment = -0.15
            reasoning['status'] = "POOR_QUALITY"
            reasoning['reason'] = "Image quality is poor (Blurry/Dark). Relaxing threshold significantly."
        elif score < 0.6:
            # Mediocre Quality
            adjustment = -0.08
            reasoning['status'] = "MEDIOCRE_QUALITY"
            reasoning['reason'] = "Image quality is mediocre. Slightly relaxing threshold."
        else:
            # Good Quality
            adjustment = 0.0
            reasoning['status'] = "GOOD_QUALITY"
            reasoning['reason'] = "Image quality is good. Keeping strict threshold."

        adjusted_thresh = max(0.50, base_threshold + adjustment) # Clamp minimum to 0.50
        reasoning['adjustment'] = adjustment
        reasoning['final_threshold'] = adjusted_thresh
        
        return adjusted_thresh, score, reasoning


class EnsembleSimilarityScorer:
    """
    Combines multiple distance metrics to create a robust similarity score.
    Helps stabilize matching when Cosine Similarity fluctuates due to domain shift.
    """

    @staticmethod
    def compute_ensemble_score(emb1: np.ndarray, emb2: np.ndarray, 
                               weights: Dict[str, float] = {'cosine': 0.60, 'euclidean': 0.25, 'dot': 0.15}) -> Tuple[float, Dict]:
        """
        Compute weighted ensemble score.
        
        Args:
            emb1, emb2: Normalized 1D numpy arrays (embeddings).
            weights: Weight dictionary summing to 1.0.

        Returns:
            Tuple(ensemble_score, individual_scores)
        """
        # Ensure vectors are numpy arrays and check for dicts
        if isinstance(emb1, dict): emb1 = emb1.get('embedding')
        if isinstance(emb2, dict): emb2 = emb2.get('embedding')
        
        if emb1 is None or emb2 is None:
            return 0.0, {'error': 'Invalid embedding'}

        e1 = np.array(emb1).flatten()
        e2 = np.array(emb2).flatten()
        
        # 1. Cosine Similarity (-1 to 1) -> Normalize to (0 to 1) for scoring? 
        # Usually ReID uses raw cosine. Let's assume standard Cosine Similarity.
        # scipy cosine returns Distance (0 to 2). Sim = 1 - Dist.
        cos_dist = cosine(e1, e2)
        cos_sim = 1.0 - cos_dist
        
        # 2. Euclidean Score
        # Distance range for normalized vectors: 0 to 2.
        # We convert distance to a similarity score [0, 1].
        # Score = 1 / (1 + distance) is a standard conversion.
        euc_dist = euclidean(e1, e2)
        euc_sim = 1.0 / (1.0 + euc_dist)
        
        # 3. Dot Product
        # For L2 normalized vectors, Dot == Cosine. 
        # Including it as a separate weighted metric acts as a booster for the Cosine component.
        dot_sim = np.dot(e1, e2)

        # Weighted Ensemble
        ensemble = (
            (cos_sim * weights['cosine']) +
            (euc_sim * weights['euclidean']) +
            (dot_sim * weights['dot'])
        )

        scores = {
            'cosine_sim': round(cos_sim, 4),
            'euclidean_sim': round(euc_sim, 4),
            'dot_product': round(dot_sim, 4),
            'ensemble_weighted': round(ensemble, 4)
        }
        
        return ensemble, scores

# --- UNIT TESTS & USAGE EXAMPLE ---
if __name__ == "__main__":
    print("--- Running Unit Tests for Enhanced Preprocessor ---")
    
    # 1. Test Image Creation (Synthetic)
    # Create a dummy "Reference" (Bright, High Contrast)
    ref_img = np.zeros((224, 224, 3), dtype=np.uint8)
    cv2.circle(ref_img, (112, 112), 50, (255, 255, 255), -1) # White circle
    
    # Create a dummy "CCTV" (Dark, Low Contrast)
    cctv_img = np.zeros((224, 224, 3), dtype=np.uint8)
    cv2.circle(cctv_img, (112, 112), 50, (100, 100, 100), -1) # Gray circle
    # Add noise
    noise = np.random.randint(0, 50, (224, 224, 3), dtype=np.uint8)
    cctv_img = cv2.add(cctv_img, noise)

    # TEST A: LAB Normalization
    print("\n[TEST A] LAB Normalization")
    norm_img = DomainAdaptivePreprocessor.normalize_to_lab(cctv_img)
    print(f"Original Mean Intensity: {np.mean(cctv_img):.2f}")
    print(f"Normalized Mean Intensity: {np.mean(norm_img):.2f} (Should be higher/balanced)")

    # TEST B: Histogram Matching
    print("\n[TEST B] Histogram Matching")
    matched_img = DomainAdaptivePreprocessor.histogram_matching(ref_img, cctv_img)
    print(f"Reference Mean: {np.mean(ref_img):.2f}")
    print(f"Target (CCTV) Mean: {np.mean(cctv_img):.2f}")
    print(f"Matched Ref Mean: {np.mean(matched_img):.2f} (Should be closer to CCTV)")

    # TEST C: Adaptive Threshold
    print("\n[TEST C] Adaptive Threshold")
    # Using the noisy CCTV image as a 'bad' reference to trigger threshold lowering
    thresh, score, reason = AdaptiveThresholdCalculator.get_adaptive_threshold(cctv_img, base_threshold=0.75)
    print(f"Quality Score: {score}")
    print(f"Reasoning: {reason}")
    if thresh < 0.75:
        print("✅ SUCCESS: Threshold lowered for poor quality image.")
    else:
        print("❌ FAILED: Threshold not adjusted.")

    # TEST D: Ensemble Scoring
    print("\n[TEST D] Ensemble Similarity")
    # Mock Embeddings (Normalized)
    vec1 = np.array([0.5, 0.5, 0.5, 0.5])
    vec2 = np.array([0.55, 0.45, 0.5, 0.5]) # Slightly different
    # Normalize
    vec1 = vec1 / np.linalg.norm(vec1)
    vec2 = vec2 / np.linalg.norm(vec2)
    
    ensemble_score, details = EnsembleSimilarityScorer.compute_ensemble_score(vec1, vec2)
    print(f"Ensemble Score: {ensemble_score:.4f}")
    print(f"Details: {details}")