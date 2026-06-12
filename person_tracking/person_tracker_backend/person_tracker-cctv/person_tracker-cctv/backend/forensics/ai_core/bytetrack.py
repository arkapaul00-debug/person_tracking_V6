import numpy as np
import logging
from typing import List, Dict, Any
from boxmot import ByteTrack  # Standard industry implementation of ByteTrack

# Configure Logger
logger = logging.getLogger(__name__)

class ByteTracker:
    """
    Wrapper for ByteTrack (Zhang et al. ECCV 2022) for low-confidence association.
    Handles persistent ID assignment across occlusions.
    """

    def __init__(self, track_thresh: float = 0.3, track_buffer: int = 30, frame_rate: int = 30):
        """
        Initialize the ByteTracker.

        Args:
            track_thresh: Detection confidence threshold for high-confidence matching.
            track_buffer: Number of frames to keep a lost track alive (buffer).
            frame_rate: FPS of the input video (affects Kalman filter velocity).
        """
        logger.info(f"Initializing ByteTracker (thresh={track_thresh}, buffer={track_buffer})")
        
        # Initialize BoxMOT's ByteTrack implementation
        # per_class=False ensures ID uniqueness across classes (though we only have 'person')
        self.tracker = ByteTrack(
            track_thresh=track_thresh,
            track_buffer=track_buffer,
            match_thresh=0.8,
            frame_rate=frame_rate
        )

    def update(self, detections: List[Dict[str, Any]], frame: np.ndarray) -> List[Dict[str, Any]]:
        """
        Update tracks with new detections.

        Args:
            detections: List of dicts from PersonDetector {'bbox': [x1,y1,x2,y2], 'confidence': float}
            frame: The current video frame (numpy array) - required by some trackers for flow, unused by ByteTrack logic but kept for interface consistency.

        Returns:
            List[Dict]: Updated detections with added 'track_id' key.
        """
        if not detections:
            # BoxMOT expects an empty array if no detections
            # Format: [x1, y1, x2, y2, conf, class_id]
            empty_dets = np.empty((0, 6))
            tracks = self.tracker.update(empty_dets, frame)
            return []

        # 1. Convert Dictionaries to Numpy Array [N, 6] for ByteTrack
        # [x1, y1, x2, y2, conf, class_id]
        det_array = []
        for d in detections:
            bbox = d['bbox']
            conf = d['confidence']
            # Class ID 0 for person
            det_array.append([bbox[0], bbox[1], bbox[2], bbox[3], conf, 0])
        
        det_array = np.array(det_array, dtype=float)

        # 2. Update Tracker
        # Returns: [x1, y1, x2, y2, id, conf, class_id]
        tracked_objects = self.tracker.update(det_array, frame)

        # 3. Map Track IDs back to Detection Objects
        # We need to associate the returned tracks with the original detection metadata (like masks)
        # using IoU matching or coordinate proximity.
        
        tracked_results = []
        
        for track in tracked_objects:
            # BoxMOT output format varies slightly by version, usually:
            # [x1, y1, x2, y2, id, conf, class_id]
            tx1, ty1, tx2, ty2 = map(int, track[:4])
            track_id = int(track[4])
            conf = track[5]
            
            # Find the original detection that matches this track best (IoU)
            # This preserves original masks/metadata from Phase 2
            best_match = None
            max_iou = 0.0
            
            track_box = [tx1, ty1, tx2, ty2]
            
            for orig in detections:
                iou = self._calculate_iou(track_box, orig['bbox'])
                if iou > 0.5 and iou > max_iou:
                    max_iou = iou
                    best_match = orig
            
            if best_match:
                # Append track_id to the existing detection dict
                result = best_match.copy()
                result['track_id'] = track_id
                # Update bbox to the smoothed Kalman filter bbox if desired, 
                # but usually detector bbox is more pixel-accurate for crops.
                # We'll keep detector bbox for ReID, but log track ID.
                tracked_results.append(result)
            else:
                # If track exists but no detection matched (Kalman prediction),
                # we create a new entry (ghost track)
                tracked_results.append({
                    'bbox': [tx1, ty1, tx2, ty2],
                    'confidence': conf,
                    'track_id': track_id,
                    'is_predicted': True # Flag this as a prediction, not a raw detection
                })

        return tracked_results

    def _calculate_iou(self, boxA, boxB):
        """Helper to match tracks to detections."""
        xA = max(boxA[0], boxB[0])
        yA = max(boxA[1], boxB[1])
        xB = min(boxA[2], boxB[2])
        yB = min(boxA[3], boxB[3])
        interArea = max(0, xB - xA) * max(0, yB - yA)
        boxAArea = (boxA[2] - boxA[0]) * (boxA[3] - boxA[1])
        boxBArea = (boxB[2] - boxB[0]) * (boxB[3] - boxB[1])
        iou = interArea / float(boxAArea + boxBArea - interArea + 1e-6)
        return iou