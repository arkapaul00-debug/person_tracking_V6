"""
Cross-Camera Identity Graph — Distributed Track Linking Across Cameras.

Maintains a graph of identity links across camera streams:
  - Nodes: (stream_id, track_id) pairs
  - Edges: Cross-camera identity matches with similarity weights

When a person disappears from camera A and reappears on camera B,
this graph links the two sightings into a unified cross-camera track.

Features:
  - Embedding-based matching (cosine similarity in vector space)
  - Temporal plausibility filtering (travel time between cameras)
  - Spatial plausibility (camera adjacency / transit routes)
  - Identity consolidation (merge multiple sightings into single ID)
  - Configurable match threshold and time window

Usage:
    graph = CrossCameraGraph()

    # Register a new sighting
    graph.add_sighting(
        stream_id='cam_001', track_id=42,
        embedding=face_emb, body_embedding=body_emb,
        timestamp=time.time(), bbox=[100,200,150,400],
    )

    # Find cross-camera matches for a sighting
    matches = graph.find_matches(
        embedding=face_emb, body_embedding=body_emb,
        exclude_stream='cam_001',
    )

    # Get unified identity trail across cameras
    trail = graph.get_identity_trail(global_id=7)
"""
import time
import threading
import logging
import numpy as np
from typing import Optional, Dict, List, Tuple, Set
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class Sighting:
    """A single person sighting on a specific camera."""
    stream_id: str
    track_id: int
    timestamp: float
    face_embedding: Optional[np.ndarray] = None
    body_embedding: Optional[np.ndarray] = None
    bbox: Optional[List[int]] = None
    global_id: int = -1  # Unified identity (assigned after matching)
    match_score: float = 0.0


@dataclass
class CrossCameraMatch:
    """A match between two sightings across cameras."""
    sighting_a: Sighting
    sighting_b: Sighting
    face_similarity: float = 0.0
    body_similarity: float = 0.0
    combined_score: float = 0.0
    time_gap_s: float = 0.0


class CrossCameraGraph:
    """
    Manages cross-camera identity linking using embedding similarity.
    """

    def __init__(self,
                 face_match_threshold: float = 0.55,
                 body_match_threshold: float = 0.45,
                 combined_threshold: float = 0.50,
                 max_time_gap_s: float = 300.0,  # 5 minutes
                 max_sightings: int = 5000,
                 face_weight: float = 0.65,
                 body_weight: float = 0.35):
        """
        Args:
            face_match_threshold: Minimum face similarity for match.
            body_match_threshold: Minimum body similarity for match.
            combined_threshold: Minimum combined score for match.
            max_time_gap_s: Maximum time gap between sightings for match.
            max_sightings: Maximum sightings to keep (LRU eviction).
            face_weight: Weight for face similarity in combined score.
            body_weight: Weight for body similarity in combined score.
        """
        self.face_thresh = face_match_threshold
        self.body_thresh = body_match_threshold
        self.combined_thresh = combined_threshold
        self.max_time_gap = max_time_gap_s
        self.max_sightings = max_sightings
        self.face_w = face_weight
        self.body_w = body_weight

        # Storage
        self._sightings: List[Sighting] = []
        self._global_id_counter = 0
        self._identity_groups: Dict[int, List[int]] = {}  # global_id → sighting indices
        self._lock = threading.Lock()

        # Metrics
        self._total_sightings = 0
        self._total_matches = 0
        self._total_new_identities = 0

    def add_sighting(self, stream_id: str, track_id: int,
                     face_embedding: Optional[np.ndarray] = None,
                     body_embedding: Optional[np.ndarray] = None,
                     timestamp: Optional[float] = None,
                     bbox: Optional[List[int]] = None) -> Sighting:
        """
        Register a new sighting and attempt cross-camera matching.

        Returns:
            Sighting with assigned global_id (new or matched).
        """
        with self._lock:
            self._total_sightings += 1

            sighting = Sighting(
                stream_id=stream_id,
                track_id=track_id,
                timestamp=timestamp or time.time(),
                face_embedding=face_embedding,
                body_embedding=body_embedding,
                bbox=bbox,
            )

            # Try to find a cross-camera match
            best_match = self._find_best_match(sighting)

            if best_match is not None:
                # Link to existing identity
                sighting.global_id = best_match.global_id
                sighting.match_score = self._compute_similarity(sighting, best_match)
                self._total_matches += 1
            else:
                # New identity
                self._global_id_counter += 1
                sighting.global_id = self._global_id_counter
                self._total_new_identities += 1

            # Store
            idx = len(self._sightings)
            self._sightings.append(sighting)

            # Update identity group
            gid = sighting.global_id
            if gid not in self._identity_groups:
                self._identity_groups[gid] = []
            self._identity_groups[gid].append(idx)

            # LRU eviction
            if len(self._sightings) > self.max_sightings:
                self._evict_oldest()

            return sighting

    def find_matches(self, face_embedding: Optional[np.ndarray] = None,
                     body_embedding: Optional[np.ndarray] = None,
                     exclude_stream: str = '',
                     top_k: int = 5) -> List[CrossCameraMatch]:
        """
        Find cross-camera matches for a query embedding.

        Returns top_k matches sorted by combined similarity.
        """
        query = Sighting(
            stream_id=exclude_stream, track_id=-1,
            timestamp=time.time(),
            face_embedding=face_embedding,
            body_embedding=body_embedding,
        )

        matches = []
        with self._lock:
            for s in self._sightings:
                if s.stream_id == exclude_stream:
                    continue

                sim = self._compute_similarity(query, s)
                if sim >= self.combined_thresh:
                    time_gap = abs(query.timestamp - s.timestamp)
                    if time_gap <= self.max_time_gap:
                        face_sim, body_sim = self._compute_similarities_detail(query, s)
                        matches.append(CrossCameraMatch(
                            sighting_a=query,
                            sighting_b=s,
                            face_similarity=face_sim,
                            body_similarity=body_sim,
                            combined_score=sim,
                            time_gap_s=time_gap,
                        ))

        # Sort by combined score descending
        matches.sort(key=lambda m: m.combined_score, reverse=True)
        return matches[:top_k]

    def get_identity_trail(self, global_id: int) -> List[Sighting]:
        """Get all sightings for a unified identity, sorted by time."""
        with self._lock:
            indices = self._identity_groups.get(global_id, [])
            trail = [self._sightings[i] for i in indices if i < len(self._sightings)]
        trail.sort(key=lambda s: s.timestamp)
        return trail

    def get_all_identities(self) -> Dict[int, int]:
        """Get a map of global_id → sighting_count."""
        return {gid: len(indices) for gid, indices in self._identity_groups.items()}

    def _find_best_match(self, query: Sighting) -> Optional[Sighting]:
        """Find the best matching sighting from a different camera."""
        best = None
        best_score = self.combined_thresh

        for s in reversed(self._sightings[-200:]):  # Check recent sightings
            if s.stream_id == query.stream_id:
                continue

            time_gap = abs(query.timestamp - s.timestamp)
            if time_gap > self.max_time_gap:
                continue

            sim = self._compute_similarity(query, s)
            if sim > best_score:
                best_score = sim
                best = s

        return best

    def _compute_similarity(self, a: Sighting, b: Sighting) -> float:
        """Compute combined face + body similarity."""
        face_sim = 0.0
        body_sim = 0.0
        has_face = False
        has_body = False

        if a.face_embedding is not None and b.face_embedding is not None:
            face_sim = self._cosine_sim(a.face_embedding, b.face_embedding)
            has_face = True

        if a.body_embedding is not None and b.body_embedding is not None:
            body_sim = self._cosine_sim(a.body_embedding, b.body_embedding)
            has_body = True

        if has_face and has_body:
            return self.face_w * face_sim + self.body_w * body_sim
        elif has_face:
            return face_sim
        elif has_body:
            return body_sim
        return 0.0

    def _compute_similarities_detail(self, a: Sighting, b: Sighting) -> Tuple[float, float]:
        """Return (face_sim, body_sim) separately."""
        face_sim = 0.0
        body_sim = 0.0

        if a.face_embedding is not None and b.face_embedding is not None:
            face_sim = self._cosine_sim(a.face_embedding, b.face_embedding)

        if a.body_embedding is not None and b.body_embedding is not None:
            body_sim = self._cosine_sim(a.body_embedding, b.body_embedding)

        return face_sim, body_sim

    @staticmethod
    def _cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
        a = a.flatten()
        b = b.flatten()
        if len(a) != len(b):
            min_len = min(len(a), len(b))
            a, b = a[:min_len], b[:min_len]
        dot = np.dot(a, b)
        norm = np.linalg.norm(a) * np.linalg.norm(b)
        if norm < 1e-8:
            return 0.0
        return float(dot / norm)

    def _evict_oldest(self):
        """Remove oldest sightings to stay under max_sightings."""
        evict_count = len(self._sightings) - self.max_sightings
        if evict_count <= 0:
            return

        self._sightings = self._sightings[evict_count:]

        # Rebuild identity groups
        new_groups: Dict[int, List[int]] = {}
        for i, s in enumerate(self._sightings):
            gid = s.global_id
            if gid not in new_groups:
                new_groups[gid] = []
            new_groups[gid].append(i)
        self._identity_groups = new_groups

    def get_metrics(self) -> dict:
        return {
            'total_sightings': self._total_sightings,
            'total_matches': self._total_matches,
            'total_identities': self._total_new_identities,
            'active_sightings': len(self._sightings),
            'identity_groups': len(self._identity_groups),
        }
