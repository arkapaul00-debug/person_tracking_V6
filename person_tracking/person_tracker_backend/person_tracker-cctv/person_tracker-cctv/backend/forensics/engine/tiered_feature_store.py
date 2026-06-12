"""
Tiered Global Feature Store (V5 Upgrade 3)
Three-tier storage architecture: Hot (Redis-like), Warm (pgvector-like), Cold (S3-like).
Manages long-term identity embedding retention with lifecycle-aware management.
"""
import time
import logging
import threading
from typing import Dict, List, Any, Optional
from collections import OrderedDict

logger = logging.getLogger(__name__)


class TieredFeatureStore:
    """
    Manages identity embeddings across three storage tiers for optimal
    cost-performance balance.

    Hot Tier:  In-memory (< 24 hours). Ultra-fast retrieval for active tracking.
    Warm Tier: Database-backed (24h – 90 days). Fast retrieval for investigations.
    Cold Tier: Object storage (90d – 7 years). Compressed, for compliance/archival.
    """

    def __init__(self, hot_capacity: int = 50000,
                 warm_retention_days: int = 90,
                 cold_retention_days: int = 2555):
        self._lock = threading.RLock()

        # Hot tier: LRU-style ordered dict (identity_id -> embedding_data)
        self._hot: OrderedDict = OrderedDict()
        self._hot_capacity = hot_capacity

        # Warm tier: simulated database (identity_id -> record)
        self._warm: Dict[str, Dict[str, Any]] = {}
        self._warm_retention_days = warm_retention_days

        # Cold tier: simulated object storage (identity_id -> record)
        self._cold: Dict[str, Dict[str, Any]] = {}
        self._cold_retention_days = cold_retention_days

        self._metrics = {
            "hot_entries": 0,
            "warm_entries": 0,
            "cold_entries": 0,
            "hot_hits": 0,
            "warm_hits": 0,
            "cold_hits": 0,
            "promotions": 0,
            "demotions": 0,
        }

        logger.info(
            f"V5 TieredFeatureStore initialized "
            f"(hot={hot_capacity}, warm={warm_retention_days}d, cold={cold_retention_days}d)"
        )

    # ── Write Operations ─────────────────────────────────────────────

    def store_embedding(self, identity_id: str, embedding: Any,
                        modality: str = "fused", quality: float = 1.0):
        """Store an embedding in the hot tier."""
        with self._lock:
            record = {
                "identity_id": identity_id,
                "embedding": embedding,
                "modality": modality,
                "quality": quality,
                "stored_at": time.time(),
                "last_accessed": time.time(),
            }

            # Evict oldest if at capacity
            if len(self._hot) >= self._hot_capacity:
                evicted_id, evicted_record = self._hot.popitem(last=False)
                self._demote_to_warm(evicted_id, evicted_record)

            self._hot[identity_id] = record
            self._hot.move_to_end(identity_id)
            self._metrics["hot_entries"] = len(self._hot)

    def _demote_to_warm(self, identity_id: str, record: Dict[str, Any]):
        """Move an entry from Hot to Warm tier."""
        record["demoted_at"] = time.time()
        self._warm[identity_id] = record
        self._metrics["warm_entries"] = len(self._warm)
        self._metrics["demotions"] += 1

    def _demote_to_cold(self, identity_id: str, record: Dict[str, Any]):
        """Move an entry from Warm to Cold tier."""
        record["archived_at"] = time.time()
        # In production, this would serialize and upload to S3/MinIO
        self._cold[identity_id] = record
        self._metrics["cold_entries"] = len(self._cold)
        self._metrics["demotions"] += 1

    # ── Read Operations ──────────────────────────────────────────────

    def retrieve_embedding(self, identity_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve an embedding, searching Hot → Warm → Cold.
        Automatically promotes to Hot tier on access.
        """
        with self._lock:
            # Hot tier
            if identity_id in self._hot:
                self._hot.move_to_end(identity_id)
                self._hot[identity_id]["last_accessed"] = time.time()
                self._metrics["hot_hits"] += 1
                return self._hot[identity_id]

            # Warm tier
            if identity_id in self._warm:
                record = self._warm.pop(identity_id)
                self._metrics["warm_hits"] += 1
                self._metrics["warm_entries"] = len(self._warm)
                # Promote back to hot
                self._promote_to_hot(identity_id, record)
                return record

            # Cold tier
            if identity_id in self._cold:
                record = self._cold[identity_id]
                self._metrics["cold_hits"] += 1
                # Promote back to hot
                self._promote_to_hot(identity_id, record)
                return record

            return None

    def _promote_to_hot(self, identity_id: str, record: Dict[str, Any]):
        """Promote an embedding from lower tiers back to Hot."""
        record["last_accessed"] = time.time()
        if len(self._hot) >= self._hot_capacity:
            evicted_id, evicted_record = self._hot.popitem(last=False)
            self._demote_to_warm(evicted_id, evicted_record)
        self._hot[identity_id] = record
        self._hot.move_to_end(identity_id)
        self._metrics["hot_entries"] = len(self._hot)
        self._metrics["promotions"] += 1

    # ── Lifecycle Sweep ──────────────────────────────────────────────

    def run_lifecycle_sweep(self) -> Dict[str, int]:
        """
        Move stale warm entries to cold, and purge expired cold entries.
        Should be called periodically (e.g., hourly via Celery beat).
        """
        now = time.time()
        warm_cutoff = now - (self._warm_retention_days * 86400)
        cold_cutoff = now - (self._cold_retention_days * 86400)
        demoted = 0
        purged = 0

        with self._lock:
            # Warm → Cold
            warm_to_demote = [
                k for k, v in self._warm.items()
                if v.get("demoted_at", v.get("stored_at", now)) < warm_cutoff
            ]
            for k in warm_to_demote:
                self._demote_to_cold(k, self._warm.pop(k))
                demoted += 1
            self._metrics["warm_entries"] = len(self._warm)

            # Purge expired cold entries
            cold_to_purge = [
                k for k, v in self._cold.items()
                if v.get("archived_at", v.get("stored_at", now)) < cold_cutoff
            ]
            for k in cold_to_purge:
                del self._cold[k]
                purged += 1
            self._metrics["cold_entries"] = len(self._cold)

        logger.info(f"Feature Store sweep: demoted={demoted}, purged={purged}")
        return {"demoted_to_cold": demoted, "purged": purged}

    # ── Metrics ──────────────────────────────────────────────────────

    def get_metrics(self) -> dict:
        with self._lock:
            return dict(self._metrics)
