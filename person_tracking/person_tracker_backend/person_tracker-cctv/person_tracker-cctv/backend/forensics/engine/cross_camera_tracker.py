"""
Cross-Camera Tracker (Phase 41)
Integrates CrossCameraGraph + CameraTopologyEngine + IdentityMemoryBank
to provide seamless identity handoff across all cameras.

This is the top-level coordinator: when a track disappears from Camera A,
it predicts which camera the suspect will appear on next, narrows the
ReID search window, and links the new sighting to the existing global identity.

Usage:
    tracker = CrossCameraTracker()

    # When a track is lost on a camera
    tracker.on_track_lost('cam_lobby', track_id=42, embeddings={...})

    # When a new detection appears on another camera
    global_id = tracker.on_new_detection('cam_hallway', embeddings={...})
"""
import time
import logging
from typing import Dict, List, Optional
import numpy as np

logger = logging.getLogger(__name__)


class CrossCameraTracker:
    """
    Orchestrates cross-camera identity handoff using:
      1. CameraTopologyEngine — for predicting next camera
      2. CrossCameraGraph — for embedding-based matching
      3. IdentityMemoryBank — for long-term appearance history
      4. IdentityGraph — for persistent relationship tracking
    """

    def __init__(self):
        # Lazy-load components to avoid circular imports
        self._topology = None
        self._cross_graph = None
        self._memory_bank = None
        self._identity_graph = None
        self._initialized = False

        # Pending handoffs: camera_id → list of lost track contexts
        self._pending_handoffs: Dict[str, List[Dict]] = {}

        # Metrics
        self._handoffs_attempted = 0
        self._handoffs_successful = 0
        self._handoffs_failed = 0

        logger.info("CrossCameraTracker initialized (lazy-loading components)")

    def _ensure_initialized(self):
        """Lazy-initialize all sub-engines."""
        if self._initialized:
            return

        try:
            from .camera_topology import CameraTopologyEngine
            self._topology = CameraTopologyEngine()
        except ImportError:
            logger.warning("CameraTopologyEngine not available")

        try:
            from .cross_camera_graph import CrossCameraGraph
            self._cross_graph = CrossCameraGraph()
        except ImportError:
            logger.warning("CrossCameraGraph not available")

        try:
            from .identity_memory import IdentityMemoryBank
            self._memory_bank = IdentityMemoryBank()
        except ImportError:
            logger.warning("IdentityMemoryBank not available")

        try:
            from .identity_graph import IdentityGraph
            self._identity_graph = IdentityGraph()
        except ImportError:
            logger.warning("IdentityGraph not available")

        self._initialized = True

    def on_track_lost(self, camera_id: str, track_id: int,
                      face_embedding: Optional[np.ndarray] = None,
                      body_embedding: Optional[np.ndarray] = None,
                      global_id: Optional[int] = None):
        """
        Called when a track disappears from a camera.
        Stores the context for handoff matching on predicted cameras.
        """
        self._ensure_initialized()

        context = {
            'camera_id': camera_id,
            'track_id': track_id,
            'face_embedding': face_embedding,
            'body_embedding': body_embedding,
            'global_id': global_id,
            'lost_at': time.time(),
        }

        # Predict where the suspect will appear next
        predicted_cameras = []
        if self._topology:
            predictions = self._topology.predict_next_camera(camera_id, top_k=3)
            predicted_cameras = [p['camera_id'] for p in predictions]

        # Store as pending handoff on each predicted camera
        for cam in predicted_cameras:
            if cam not in self._pending_handoffs:
                self._pending_handoffs[cam] = []
            self._pending_handoffs[cam].append(context)

        # Also store on all cameras as a fallback (with lower priority)
        if 'all' not in self._pending_handoffs:
            self._pending_handoffs['all'] = []
        self._pending_handoffs['all'].append(context)

        # Update memory bank if available
        if self._memory_bank and global_id is not None:
            self._memory_bank.add_sighting(
                str(global_id), face_embedding, body_embedding
            )

        self._handoffs_attempted += 1

    def on_new_detection(self, camera_id: str,
                         face_embedding: Optional[np.ndarray] = None,
                         body_embedding: Optional[np.ndarray] = None,
                         confidence: float = 0.0) -> Optional[int]:
        """
        Called when a new (unmatched) detection appears on a camera.
        Tries to match it against pending handoffs.

        Returns:
            global_id if a cross-camera match is found, else None.
        """
        self._ensure_initialized()

        # Check predicted handoffs for this camera first, then 'all'
        candidates = self._pending_handoffs.get(camera_id, [])
        candidates += self._pending_handoffs.get('all', [])

        if not candidates:
            return None

        best_match = None
        best_score = 0.5  # Minimum threshold

        now = time.time()
        for ctx in candidates:
            # Skip if too old (> 5 minutes)
            if now - ctx['lost_at'] > 300:
                continue

            # Skip if same camera
            if ctx['camera_id'] == camera_id:
                continue

            # Check plausibility via topology
            elapsed = now - ctx['lost_at']
            if self._topology and not self._topology.is_plausible(
                    ctx['camera_id'], camera_id, elapsed):
                continue

            # Compute similarity
            score = self._compute_match_score(
                face_embedding, body_embedding,
                ctx['face_embedding'], ctx['body_embedding'],
            )

            if score > best_score:
                best_score = score
                best_match = ctx

        if best_match is not None:
            global_id = best_match.get('global_id')

            # Record the transition in topology
            if self._topology:
                travel_time = now - best_match['lost_at']
                self._topology.record_transition(
                    best_match['camera_id'], camera_id, travel_time
                )

            # Record sighting in cross-camera graph
            if self._cross_graph and global_id is not None:
                self._cross_graph.add_sighting(
                    stream_id=camera_id,
                    track_id=-1,
                    face_embedding=face_embedding,
                    body_embedding=body_embedding,
                )

            # Record in identity graph
            if self._identity_graph and global_id is not None:
                self._identity_graph.record_sighting(
                    str(global_id), camera_id,
                    timestamp=now, confidence=best_score,
                )

            # Remove from pending
            self._remove_pending(best_match)

            self._handoffs_successful += 1
            logger.info(
                f"Cross-camera handoff: {best_match['camera_id']} → "
                f"{camera_id} (global_id={global_id}, score={best_score:.3f})"
            )
            return global_id

        self._handoffs_failed += 1
        return None

    def _compute_match_score(self,
                             face_a: Optional[np.ndarray],
                             body_a: Optional[np.ndarray],
                             face_b: Optional[np.ndarray],
                             body_b: Optional[np.ndarray]) -> float:
        """Compute combined similarity between two embedding sets."""
        face_sim = 0.0
        body_sim = 0.0
        has_face = False
        has_body = False

        if face_a is not None and face_b is not None:
            face_sim = self._cosine_sim(face_a, face_b)
            has_face = True

        if body_a is not None and body_b is not None:
            body_sim = self._cosine_sim(body_a, body_b)
            has_body = True

        if has_face and has_body:
            return 0.65 * face_sim + 0.35 * body_sim
        elif has_face:
            return face_sim
        elif has_body:
            return body_sim
        return 0.0

    @staticmethod
    def _cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
        a = a.flatten()
        b = b.flatten()
        dot = np.dot(a, b)
        norm = np.linalg.norm(a) * np.linalg.norm(b)
        if norm < 1e-8:
            return 0.0
        return float(dot / norm)

    def _remove_pending(self, context: Dict):
        """Remove a matched handoff from all pending lists."""
        for cam, contexts in self._pending_handoffs.items():
            self._pending_handoffs[cam] = [
                c for c in contexts if c is not context
            ]

    def cleanup_stale_handoffs(self, max_age_s: float = 300.0):
        """Remove handoff contexts older than max_age_s."""
        now = time.time()
        for cam in list(self._pending_handoffs.keys()):
            self._pending_handoffs[cam] = [
                c for c in self._pending_handoffs[cam]
                if (now - c['lost_at']) < max_age_s
            ]
            if not self._pending_handoffs[cam]:
                del self._pending_handoffs[cam]

    def get_metrics(self) -> Dict:
        return {
            'handoffs_attempted': self._handoffs_attempted,
            'handoffs_successful': self._handoffs_successful,
            'handoffs_failed': self._handoffs_failed,
            'success_rate': round(
                self._handoffs_successful / max(self._handoffs_attempted, 1), 3
            ),
            'pending_handoffs': sum(
                len(v) for v in self._pending_handoffs.values()
            ),
            'topology_metrics': (
                self._topology.get_metrics() if self._topology else {}
            ),
        }
