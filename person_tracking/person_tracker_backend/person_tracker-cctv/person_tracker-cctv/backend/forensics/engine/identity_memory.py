"""
Identity Memory Bank (Phase 38)
Provides persistent identity memory to track suspects across multiple days and varying appearances.
Instead of a single reference embedding, this maintains a rolling histogram of appearance vectors.
"""
import time
import logging
import numpy as np
from typing import Dict, List, Optional
from collections import deque
from scipy.spatial.distance import cosine

logger = logging.getLogger(__name__)

class IdentityMemoryBank:
    def __init__(self, max_history: int = 50, similarity_threshold: float = 0.55):
        """
        Args:
            max_history: Number of historical embeddings to keep per identity.
            similarity_threshold: Base threshold for matching.
        """
        self.max_history = max_history
        self.similarity_threshold = similarity_threshold
        
        # In-memory storage: identity_id -> dict of features
        self._identities: Dict[str, Dict] = {}

    def register_identity(self, identity_id: str, face_emb: Optional[np.ndarray], body_emb: Optional[np.ndarray]):
        """Register a new identity or overwrite an existing one."""
        self._identities[identity_id] = {
            'face_history': deque(maxlen=self.max_history),
            'body_history': deque(maxlen=self.max_history),
            'last_seen': time.time(),
            'total_sightings': 1
        }
        
        if face_emb is not None:
            self._identities[identity_id]['face_history'].append(face_emb)
        if body_emb is not None:
            self._identities[identity_id]['body_history'].append(body_emb)
            
        logger.info(f"Registered new identity: {identity_id}")

    def add_sighting(self, identity_id: str, face_emb: Optional[np.ndarray], body_emb: Optional[np.ndarray]):
        """Append new embeddings to an existing identity's history."""
        if identity_id not in self._identities:
            self.register_identity(identity_id, face_emb, body_emb)
            return

        record = self._identities[identity_id]
        record['last_seen'] = time.time()
        record['total_sightings'] += 1
        
        if face_emb is not None:
            record['face_history'].append(face_emb)
        if body_emb is not None:
            record['body_history'].append(body_emb)

    def compute_historical_similarity(self, identity_id: str, face_emb: Optional[np.ndarray], body_emb: Optional[np.ndarray]) -> float:
        """
        Compute similarity against the historical rolling window.
        Returns the best matching score found in the identity's history.
        """
        if identity_id not in self._identities:
            return 0.0

        record = self._identities[identity_id]
        
        best_face = 0.0
        if face_emb is not None and record['face_history']:
            v = np.asarray(face_emb).reshape(-1)
            for hist_emb in record['face_history']:
                u = np.asarray(hist_emb).reshape(-1)
                sim = 1.0 - cosine(u, v)
                if sim > best_face:
                    best_face = sim

        best_body = 0.0
        if body_emb is not None and record['body_history']:
            v = np.asarray(body_emb).reshape(-1)
            for hist_emb in record['body_history']:
                u = np.asarray(hist_emb).reshape(-1)
                sim = 1.0 - cosine(u, v)
                if sim > best_body:
                    best_body = sim

        # Temporal fusion (highest quality wins)
        if best_face > 0 or best_body > 0:
            if best_face > best_body:
                return float((best_face * 0.8) + (best_body * 0.2))
            else:
                return float((best_face * 0.3) + (best_body * 0.7))
                
        return 0.0

    def prune_stale_identities(self, max_age_seconds: int = 86400 * 30):
        """Remove identities not seen in the last 30 days."""
        now = time.time()
        stale = [uid for uid, rec in self._identities.items() if (now - rec['last_seen']) > max_age_seconds]
        for uid in stale:
            del self._identities[uid]
            
        if stale:
            logger.info(f"Pruned {len(stale)} stale identities from Memory Bank.")
