import torch
import numpy as np
import logging
import cv2
from pathlib import Path

try:
    import torchreid
except ImportError:
    raise ImportError("Library 'torchreid' not found. Run: pip install torchreid")

logger = logging.getLogger(__name__)

class BodyReIDExtractor:
    """
    OSNet x1_0 Body Extractor for RTX A5000.
    """
    def __init__(self, device: str = 'cuda:0'):
        self.device = torch.device(device if torch.cuda.is_available() else "cpu")
        
        logger.info(f"Initializing BodyReID (OSNet x1_0) on {self.device}...")

        try:
            # Build model directly (No Hubconf issues)
            self.model = torchreid.models.build_model(
                name='osnet_x1_0',
                num_classes=1000,
                pretrained=True
            )
            self.model.to(self.device)
            self.model.eval()
            
            # V3: CUDA Graph Execution (Phase 14)
            # Dramatically reduces CPU kernel launch overhead.
            try:
                import os
                if os.environ.get('USE_CUDA_GRAPHS', '1') == '1':
                    logger.info("Compiling CUDA Graph for OSNet x1_0...")
                    # Warmup and trace graph with standard input size
                    dummy_input = torch.randn(1, 3, 256, 128, device=self.device)
                    # Run a few times to warm up memory allocator
                    for _ in range(3):
                        self.model(dummy_input)
                    self.model = torch.cuda.make_graphed_callables(self.model, (dummy_input,))
                    logger.info("CUDA Graph compiled successfully.")
            except Exception as cg_err:
                logger.warning(f"Failed to compile CUDA Graph, falling back to eager mode: {cg_err}")

            logger.info("OSNet x1_0 Model loaded successfully.")

        except Exception as e:
            logger.critical(f"Failed to load OSNet: {e}")
            raise RuntimeError(f"Body ReID Initialization Failed: {e}")

    @torch.no_grad()
    def extract_body_embedding(self, body_crop: np.ndarray) -> np.ndarray:
        if body_crop is None or body_crop.size == 0:
            return None

        try:
            # Preprocessing for ImageNet
            img = cv2.resize(body_crop, (128, 256))
            img = img.astype(np.float32) / 255.0
            img -= np.array([0.485, 0.456, 0.406])
            img /= np.array([0.229, 0.224, 0.225])
            
            img = img.transpose(2, 0, 1) # HWC to CHW
            img = torch.from_numpy(img).unsqueeze(0).to(self.device)

            features = self.model(img)
            features = features.cpu().numpy().flatten()
            
            norm = np.linalg.norm(features)
            return features / (norm + 1e-6) if norm > 0 else features

        except Exception as e:
            logger.error(f"Body feature extraction failed: {e}")
            return None

    @torch.no_grad()
    def extract_body_embeddings_batch(self, crops: list) -> list:
        """
        Process all person crops in a single GPU batch.
        Much faster than sequential per-crop extraction.
        Returns list of normalized embeddings (or None for invalid crops).
        """
        if not crops:
            return []

        valid_indices = []
        tensors = []
        
        for i, crop in enumerate(crops):
            if crop is None or crop.size == 0:
                continue
            try:
                img = cv2.resize(crop, (128, 256)).astype(np.float32) / 255.0
                img -= np.array([0.485, 0.456, 0.406])
                img /= np.array([0.229, 0.224, 0.225])
                tensors.append(torch.from_numpy(img.transpose(2, 0, 1)))
                valid_indices.append(i)
            except Exception:
                continue

        if not tensors:
            return [None] * len(crops)

        try:
            batch = torch.stack(tensors).to(self.device)
            features = self.model(batch).cpu().numpy()
            norms = np.linalg.norm(features, axis=1, keepdims=True)
            normalized = features / (norms + 1e-6)

            # Map back to original indices
            results = [None] * len(crops)
            for idx, valid_i in enumerate(valid_indices):
                results[valid_i] = normalized[idx]
            return results
        except Exception as e:
            logger.error(f"Batch body extraction failed: {e}")
            return [None] * len(crops)