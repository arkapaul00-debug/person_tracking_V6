import logging
import torch
import numpy as np
from typing import List, Dict, Any, Optional
from ultralytics import YOLO

# Configure Logger
logger = logging.getLogger(__name__)

class PersonDetector:
    """
    Wrapper for YOLOv10-Nano to detect persons in surveillance footage.
    Optimized for forensic recall and speed on GTX 1050 Ti.
    """

    def __init__(self, model_path: str = 'yolov10x.pt', device: str = 'cuda:0', conf_threshold: float = 0.35):
        """
        Initialize YOLOv10-Nano model.

        Args:
            model_path: Path to .pt file (auto-downloads if missing).
            device: Calculation device ('cuda:0' or 'cpu').
            conf_threshold: Confidence floor (default 0.35 for forensic recall).
        """
        self.device = device if torch.cuda.is_available() else 'cpu'
        self.conf_threshold = conf_threshold
        
        logger.info(f"Initializing PersonDetector (YOLOv10x) on {self.device}...")
        try:
            # YOLOv10n is native to Ultralytics >= 8.1
            self.model = YOLO(model_path)
            # Force FP16 for speed on Pascal/Turing GPUs
            if self.device != 'cpu':
                self.model.to(self.device)
        except Exception as e:
            logger.critical(f"Failed to load YOLO model: {e}")
            raise RuntimeError(f"Detector initialization failed: {e}")

    def detect(self, frame: np.ndarray) -> List[Dict[str, Any]]:
        """
        Detect persons in the frame.

        Args:
            frame: Input BGR image (H, W, 3).

        Returns:
            List of dictionaries containing 'bbox', 'confidence', 'class_id'.
        """
        try:
            # Run inference
            # classes=[0] filters for 'person' only
            results = self.model(frame, conf=self.conf_threshold, classes=[0], verbose=False, device=self.device)
            
            detections = []
            
            # Process results (usually only 1 frame per batch here)
            for r in results:
                boxes = r.boxes
                for i, box in enumerate(boxes):
                    # Get coordinates [x1, y1, x2, y2]
                    coords = box.xyxy[0].cpu().numpy().astype(int)
                    conf = float(box.conf[0].cpu().numpy())
                    
                    # Apply 20% Padding (Context Expansion)
                    x1, y1, x2, y2 = coords
                    w, h = x2 - x1, y2 - y1
                    pad_x = int(w * 0.2)
                    pad_y = int(h * 0.2)
                    
                    h_img, w_img = frame.shape[:2]
                    
                    x1_p = max(0, x1 - pad_x)
                    y1_p = max(0, y1 - pad_y)
                    x2_p = min(w_img, x2 + pad_x)
                    y2_p = min(h_img, y2 + pad_y)
                    
                    detections.append({
                        'person_id': i,
                        'bbox': [x1_p, y1_p, x2_p, y2_p],
                        'original_bbox': [x1, y1, x2, y2],
                        'confidence': conf
                    })

            logger.info(f"Frame Detection: {len(detections)} persons found.")
            return detections

        except torch.cuda.OutOfMemoryError:
            logger.warning("GPU OOM during detection. Clearing cache and skipping frame.")
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            return []
        except Exception as e:
            logger.error(f"Detection error: {e}")
            return []

    def __del__(self):
        """Clean up GPU resources."""
        if hasattr(self, 'model'):
            del self.model
        torch.cuda.empty_cache()