"""
Two-Layer Identity Manager — Safe ReID Skipping.

Decouples ephemeral ByteTrack Track IDs from persistent Forensic IDs.
Prevents the false-positive ID-transfer bug caused by tracker ID switches.

Key mechanisms:
  1. Confidence decay (α=0.97/frame) forces periodic re-verification
  2. Rolling embedding cluster detects appearance drift / ID switches
  3. Occlusion reappearance triggers forced re-verify
"""
import logging
import os
import cv2
import numpy as np
from collections import defaultdict
from typing import Optional, Dict, Tuple, List
from django.conf import settings

logger = logging.getLogger(__name__)


class ForensicIdentity:
    """Persistent identity tracked across the video."""
    
    def __init__(self, forensic_id: int, initial_embedding: np.ndarray, 
                 initial_score: float, frame_id: int):
        self.forensic_id = forensic_id
        self.confirmed = False
        self.confidence = initial_score
        self.last_verified_frame = frame_id
        self.last_seen_frame = frame_id
        
        # Rolling embedding cluster (guards against ID switches)
        self.embedding_cluster = [initial_embedding.flatten().copy()]
        self.max_cluster_size = 8
        
        # Track ID history (which ByteTrack IDs mapped to this identity)
        self.track_ids = set()
        
        # Snapshot Gallery Pool
        self.snapshots = {
            'front': {'image': None, 'score': 0.0, 'finalized': False},
            'side': {'image': None, 'score': 0.0, 'finalized': False},
            'down': {'image': None, 'score': 0.0, 'finalized': False}
        }
    
    @property
    def finalized_shots(self) -> List[str]:
        """Return list of categories that have finalized snapshots."""
        return [cat for cat, s in self.snapshots.items() if s['finalized']]
    
    def update_snapshot(self, category: str, image: np.ndarray, score: float, embedding: Optional[np.ndarray] = None):
        """Update snapshot if score is higher and not finalized."""
        if category not in self.snapshots:
            return
        
        state = self.snapshots[category]
        if not state['finalized'] and score > state['score']:
            state['image'] = image.copy()
            state['score'] = score
            
            # Update identity cluster with this high-quality sample
            if embedding is not None:
                self.add_embedding(embedding)
            
            # High threshold finalization
            if score > 0.85:
                state['finalized'] = True
                self._save_snapshot(category)
    
    def _save_snapshot(self, category: str):
        """Save finalized snapshot to disk."""
        img = self.snapshots[category]['image']
        if img is None:
            return
            
        path = os.path.join(settings.MEDIA_ROOT, 'outputs', 'live_alerts', 'references', 
                            str(self.forensic_id))
        os.makedirs(path, exist_ok=True)
        filename = f"{category}_final.jpg"
        full_path = os.path.join(path, filename)
        cv2.imwrite(full_path, img)
        logger.info(f"FORENSIC ID {self.forensic_id}: Snapshot FINALIZED for {category}")
    
    def add_embedding(self, embedding: np.ndarray):
        """Add new verified embedding to the rolling cluster."""
        self.embedding_cluster.append(embedding.copy())
        if len(self.embedding_cluster) > self.max_cluster_size:
            self.embedding_cluster.pop(0)
    
    def embedding_similarity(self, new_embedding: np.ndarray) -> float:
        """Check if a new embedding matches any of this identity's cluster faces."""
        if not self.embedding_cluster:
            return 0.0
            
        v = np.asarray(new_embedding).reshape(-1)
        norm_v = np.linalg.norm(v)
        if norm_v < 1e-6:
            return 0.0
            
        max_sim = 0.0
        for emb in self.embedding_cluster:
            c = np.asarray(emb).reshape(-1)
            norm_c = np.linalg.norm(c)
            if norm_c > 1e-6:
                sim = float(np.dot(c, v) / (norm_c * norm_v))
                if sim > max_sim:
                    max_sim = sim
                    
        return max_sim


class ForensicIdentityManager:
    """
    Two-layer identity management with safe ReID skipping.
    
    Layer 1: ByteTrack Track IDs (ephemeral, can switch during occlusion)
    Layer 2: Forensic IDs (persistent, verified by embeddings)
    
    Usage in pipeline:
        mgr = ForensicIdentityManager(high_thresh=0.75)
        
        # On each inference frame, AFTER ByteTrack assigns track IDs:
        for track_id, bbox in tracks:
            needs_reid = mgr.needs_reid(track_id, frame_id)
            if needs_reid:
                embedding, score = run_reid(crop)
                is_target = mgr.update_track(track_id, score, embedding, frame_id)
            else:
                is_target = mgr.is_target(track_id)
    """
    
    def __init__(self,
                 high_thresh: float = 0.48,
                 low_thresh: float = 0.35,
                 decay_alpha: float = 0.97,       # Per-frame confidence decay
                 reverify_thresh: float = 0.45,    # Below this → force re-verify
                 drift_thresh: float = 0.35,       # Embedding drift → force re-verify
                 max_missing_frames: int = 30):     # Frames before track considered gone
        
        self.high_thresh = high_thresh
        self.low_thresh = low_thresh
        self.decay_alpha = decay_alpha
        self.reverify_thresh = reverify_thresh
        self.drift_thresh = drift_thresh
        self.max_missing_frames = max_missing_frames
        
        # Track ID → Forensic Identity mapping
        self.track_to_forensic: Dict[int, ForensicIdentity] = {}
        
        # All forensic identities
        self.forensic_ids: Dict[int, ForensicIdentity] = {}
        self._next_forensic_id = 0
        
        # Track visibility state (for occlusion detection)
        self.track_last_seen: Dict[int, int] = {}
        
        # Stats
        self.total_reid_calls = 0
        self.skipped_reid_calls = 0
    
    def needs_any_reid(self, track_ids: List[int], frame_id: int) -> bool:
        """Helper for batch optimization: returns True if any track in the list needs ReID."""
        if not track_ids:
            return False
        return any(self.needs_reid(tid, frame_id) for tid in track_ids)

    def needs_reid(self, track_id: int, frame_id: int) -> bool:
        """
        Determine if this track needs ReID on the current frame.
        Returns False (skip ReID) only when ALL of these are true:
          1. Track is mapped to a confirmed forensic identity
          2. Confidence hasn't decayed below reverify_thresh
          3. Track wasn't recently lost (no occlusion reappearance)
        """
        self.total_reid_calls += 1
        
        # Unknown track → always needs ReID
        if track_id not in self.track_to_forensic:
            return True
        
        identity = self.track_to_forensic[track_id]
        
        # Not confirmed → needs ReID
        if not identity.confirmed:
            return True
        
        # Apply confidence decay — but be more lenient for confirmed targets
        frames_since_verify = frame_id - identity.last_verified_frame
        decay_rate = self.decay_alpha if not identity.confirmed else 0.99  # Slower decay for targets
        decayed_confidence = identity.confidence * (decay_rate ** frames_since_verify)
        
        # Confidence too low → force re-verify
        if decayed_confidence < self.reverify_thresh:
            # logger.debug(f"Track {track_id}: Confidence decayed to {decayed_confidence:.3f}, forcing re-verify")
            return True
        
        # Occlusion reappearance check
        if track_id in self.track_last_seen:
            gap = frame_id - self.track_last_seen[track_id]
            if gap > 20:  # Even more lenient for targets
                # logger.debug(f"Track {track_id}: Reappeared after {gap} frame gap, forcing re-verify")
                return True
        
        # Safe to skip!
        self.skipped_reid_calls += 1
        return False
    
    def update_track(self, track_id: int, similarity: float, 
                     embedding: Optional[np.ndarray], frame_id: int,
                     pose_category: str = 'other', crop: Optional[np.ndarray] = None) -> Tuple[bool, int]:
        """
        Update a track with fresh ReID results.
        Returns (is_target, forensic_id).
        """
        self.track_last_seen[track_id] = frame_id
        
        if track_id in self.track_to_forensic:
            identity = self.track_to_forensic[track_id]
            
            # Update snapshots if this is a confirmed target
            if identity.confirmed and pose_category != 'other' and crop is not None:
                identity.update_snapshot(pose_category, crop, similarity, embedding)
            
            # Check for ID switch via embedding drift
            if embedding is not None and identity.confirmed:
                cluster_sim = identity.embedding_similarity(embedding)
                # Only unconfirm if it's wildly different (sim < 0.10) AND gallery similarity is also low
                if cluster_sim < 0.10 and similarity < self.low_thresh:
                    # Embedding doesn't match cluster AND doesn't match gallery → likely ID switch!
                    logger.warning(f"Track {track_id}: Embedding drift detected (sim={cluster_sim:.3f}). "
                                   f"Unconfirming forensic ID {identity.forensic_id}.")
                    identity.confirmed = False
                    identity.confidence = 0.0
                    # Unmap this track
                    self.track_to_forensic.pop(track_id, None)
                    # Re-evaluate as new track below
                    return self._evaluate_new_track(track_id, similarity, embedding, frame_id)
            
            # Update confidence and embeddings
            identity.confidence = similarity
            identity.last_verified_frame = frame_id
            identity.last_seen_frame = frame_id
            
            if embedding is not None and similarity >= self.low_thresh:
                identity.add_embedding(embedding)
            
            # Check confirmation
            if similarity >= self.high_thresh:
                identity.confirmed = True
                return True, identity.forensic_id
            elif identity.confirmed:
                # STICKY LATCH: If already confirmed, stay confirmed
                return True, identity.forensic_id
            
            return False, identity.forensic_id
        else:
            return self._evaluate_new_track(track_id, similarity, embedding, frame_id)

    def get_identity_for_fid(self, fid: int) -> Tuple[bool, Optional[ForensicIdentity]]:
        """Get the identity object if it exists and is confirmed."""
        if fid in self.forensic_ids:
            ident = self.forensic_ids[fid]
            return ident.confirmed, ident
        return False, None
    
    def _evaluate_new_track(self, track_id: int, similarity: float,
                            embedding: Optional[np.ndarray], frame_id: int) -> Tuple[bool, int]:
        """Handle a track not yet mapped to a forensic identity."""
        self.track_last_seen[track_id] = frame_id
        
        if embedding is None:
            # If no embedding (e.g. crop failed), we can't create a persistent identity
            # but we can return based on similarity score directly
            return similarity >= self.high_thresh, -1
        
        # Check if this embedding matches any existing forensic identity
        best_match_fid = None
        best_match_sim = 0.0
        
        for fid, identity in self.forensic_ids.items():
            sim = identity.embedding_similarity(embedding)
            if sim > best_match_sim:
                best_match_sim = sim
                best_match_fid = fid
        
        if best_match_fid is not None and best_match_sim > self.low_thresh:
            # Re-associate this track with an existing forensic identity
            identity = self.forensic_ids[best_match_fid]
            self.track_to_forensic[track_id] = identity
            identity.track_ids.add(track_id)
            identity.confidence = similarity
            identity.last_verified_frame = frame_id
            identity.last_seen_frame = frame_id
            identity.add_embedding(embedding)
            
            if similarity >= self.high_thresh:
                identity.confirmed = True
                return True, identity.forensic_id
            return identity.confirmed, identity.forensic_id
        
        # Create new forensic identity - use track_id as FID for better latching
        fid = track_id
        # Ensure we don't collide with existing IDs (though unlikely with ByteTrack IDs)
        while fid in self.forensic_ids:
            fid += 10000 
            
        identity = ForensicIdentity(fid, embedding, similarity, frame_id)
        identity.track_ids.add(track_id)
        self.forensic_ids[fid] = identity
        self.track_to_forensic[track_id] = identity
        
        if similarity >= self.high_thresh:
            identity.confirmed = True
            return True, identity.forensic_id
        
        return False, identity.forensic_id
    
    def mark_frame(self, track_id: int, frame_id: int):
        """Mark a track as visible on a non-inference frame (for gap detection)."""
        self.track_last_seen[track_id] = frame_id
    
    def is_target(self, track_id: int) -> Tuple[bool, float, int]:
        """Quick check if track is a confirmed target (for non-inference frames)."""
        if track_id in self.track_to_forensic:
            id_obj = self.track_to_forensic[track_id]
            return id_obj.confirmed, id_obj.confidence, id_obj.forensic_id
        return False, 0.0, -1
    
    def cleanup_stale(self, current_frame: int):
        """Remove mappings for tracks not seen recently."""
        stale = [tid for tid, last in self.track_last_seen.items()
                 if current_frame - last > self.max_missing_frames]
        for tid in stale:
            self.track_to_forensic.pop(tid, None)
            self.track_last_seen.pop(tid, None)
    
    def get_stats(self) -> dict:
        """Return performance statistics."""
        total = self.total_reid_calls or 1
        return {
            'total_reid_checks': self.total_reid_calls,
            'skipped': self.skipped_reid_calls,
            'skip_rate': f"{self.skipped_reid_calls / total * 100:.1f}%",
            'active_forensic_ids': len(self.forensic_ids),
            'active_track_mappings': len(self.track_to_forensic),
        }
