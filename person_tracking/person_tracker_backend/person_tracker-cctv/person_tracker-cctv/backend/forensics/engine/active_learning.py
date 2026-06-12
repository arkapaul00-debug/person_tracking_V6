"""
Active Learning Collector (Phase 43)
Automatically collects hard examples from the live pipeline for future retraining.

Collects:
  - False positives (high similarity but wrong person)
  - False negatives (missed suspect)
  - ID switches (track ID changed for same person)
  - Operator corrections (manual overrides)

Generates structured datasets that can be used for periodic model fine-tuning.

Usage:
    collector = ActiveLearningCollector(output_dir='./active_learning_data/')

    # Operator flags a false positive
    collector.record_false_positive(
        frame=frame, bbox=[x1,y1,x2,y2], predicted_score=0.72
    )

    # System detects an ID switch
    collector.record_id_switch(
        frame=frame, old_track_id=42, new_track_id=87, bbox=[...]
    )

    # Export dataset for retraining
    stats = collector.get_stats()
"""
import os
import time
import json
import logging
import threading
import numpy as np
from typing import Dict, List, Optional
from pathlib import Path

logger = logging.getLogger(__name__)


class ActiveLearningCollector:
    """
    Collects hard examples from live inference for model improvement.
    """

    def __init__(self, output_dir: str = './active_learning_data/',
                 max_samples_per_category: int = 10000):
        """
        Args:
            output_dir: Directory to store collected samples.
            max_samples_per_category: Max samples per category before rotation.
        """
        self.output_dir = Path(output_dir)
        self.max_samples = max_samples_per_category
        self._lock = threading.Lock()

        # Counters
        self._counts = {
            'false_positive': 0,
            'false_negative': 0,
            'id_switch': 0,
            'operator_correction': 0,
            'low_confidence_match': 0,
        }

        # In-memory log (latest N entries per category)
        self._log: Dict[str, List[Dict]] = {k: [] for k in self._counts}

        # Ensure output dirs exist
        for category in self._counts:
            (self.output_dir / category).mkdir(parents=True, exist_ok=True)

        logger.info(f"ActiveLearningCollector: output={output_dir}")

    def record_false_positive(self, frame: Optional[np.ndarray] = None,
                              bbox: Optional[List[int]] = None,
                              predicted_score: float = 0.0,
                              camera_id: str = '',
                              metadata: Optional[Dict] = None):
        """Record a false positive detection."""
        self._record('false_positive', {
            'score': predicted_score,
            'camera': camera_id,
            'bbox': bbox,
            'metadata': metadata or {},
        }, frame, bbox)

    def record_false_negative(self, frame: Optional[np.ndarray] = None,
                              bbox: Optional[List[int]] = None,
                              camera_id: str = '',
                              metadata: Optional[Dict] = None):
        """Record a missed suspect (false negative)."""
        self._record('false_negative', {
            'camera': camera_id,
            'bbox': bbox,
            'metadata': metadata or {},
        }, frame, bbox)

    def record_id_switch(self, frame: Optional[np.ndarray] = None,
                         old_track_id: int = -1,
                         new_track_id: int = -1,
                         bbox: Optional[List[int]] = None,
                         camera_id: str = ''):
        """Record a track ID switch event."""
        self._record('id_switch', {
            'old_track_id': old_track_id,
            'new_track_id': new_track_id,
            'camera': camera_id,
            'bbox': bbox,
        }, frame, bbox)

    def record_operator_correction(self, frame: Optional[np.ndarray] = None,
                                   correction_type: str = '',
                                   details: Optional[Dict] = None,
                                   camera_id: str = ''):
        """Record a manual correction by an operator."""
        self._record('operator_correction', {
            'correction_type': correction_type,
            'camera': camera_id,
            'details': details or {},
        }, frame, None)

    def record_low_confidence(self, frame: Optional[np.ndarray] = None,
                              bbox: Optional[List[int]] = None,
                              score: float = 0.0,
                              camera_id: str = ''):
        """Record a match that was borderline (for review)."""
        self._record('low_confidence_match', {
            'score': score,
            'camera': camera_id,
            'bbox': bbox,
        }, frame, bbox)

    def _record(self, category: str, info: Dict,
                frame: Optional[np.ndarray] = None,
                bbox: Optional[List[int]] = None):
        """Internal: record a sample."""
        with self._lock:
            self._counts[category] += 1
            count = self._counts[category]

            entry = {
                'timestamp': time.time(),
                'sample_id': count,
                **info,
            }

            # Add to in-memory log (keep last 100)
            self._log[category].append(entry)
            if len(self._log[category]) > 100:
                self._log[category] = self._log[category][-100:]

            # Save frame crop to disk if available
            if frame is not None and bbox is not None:
                try:
                    import cv2
                    x1, y1, x2, y2 = bbox
                    crop = frame[y1:y2, x1:x2]
                    if crop.size > 0:
                        filename = f"{category}_{count:06d}.jpg"
                        filepath = self.output_dir / category / filename
                        cv2.imwrite(str(filepath), crop)
                except Exception as e:
                    logger.debug(f"Failed to save crop: {e}")

            # Save metadata
            try:
                meta_path = self.output_dir / category / f"{category}_{count:06d}.json"
                with open(meta_path, 'w') as f:
                    # Filter out non-serializable items
                    serializable = {
                        k: v for k, v in entry.items()
                        if isinstance(v, (str, int, float, bool, list, dict, type(None)))
                    }
                    json.dump(serializable, f, indent=2)
            except Exception as e:
                logger.debug(f"Failed to save metadata: {e}")

    def get_stats(self) -> Dict:
        """Return collection statistics."""
        return {
            'counts': dict(self._counts),
            'total_samples': sum(self._counts.values()),
            'output_dir': str(self.output_dir),
        }

    def get_recent(self, category: str, n: int = 10) -> List[Dict]:
        """Get the N most recent samples for a category."""
        with self._lock:
            return list(self._log.get(category, [])[-n:])

    def get_metrics(self) -> Dict:
        return self.get_stats()
