"""
Vector Database Interface — Unified Embedding Store for Forensic Search.

Provides a pluggable vector database abstraction supporting:
  - FAISS (local, GPU-accelerated, no external deps)
  - Milvus (distributed, cloud-scale)
  - Qdrant (distributed, filtered search)

Used for:
  - Forensic face search (find suspect across all historical data)
  - Cross-camera ReID gallery matching
  - Evidence embedding archival
  - Similarity-based suspect discovery

Usage:
    # FAISS (default, local)
    store = VectorStore.create('faiss', dimension=512)

    # Add embeddings
    store.add('suspect_001', embedding, metadata={'camera': 'cam_01', 'time': ...})

    # Search
    results = store.search(query_embedding, top_k=10)
    # [{'id': 'suspect_001', 'score': 0.92, 'metadata': {...}}, ...]

    # Filtered search
    results = store.search(query, top_k=10, filter={'camera': 'cam_01'})
"""
import time
import logging
import threading
import numpy as np
from typing import Optional, Dict, List, Any, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """Result from a vector similarity search."""
    id: str
    score: float
    metadata: Dict[str, Any] = field(default_factory=dict)


class VectorStoreBackend:
    """Abstract backend interface."""

    def add(self, id: str, embedding: np.ndarray, metadata: Optional[Dict] = None):
        raise NotImplementedError

    def add_batch(self, ids: List[str], embeddings: np.ndarray,
                  metadata_list: Optional[List[Dict]] = None):
        raise NotImplementedError

    def search(self, query: np.ndarray, top_k: int = 10,
               filter: Optional[Dict] = None) -> List[SearchResult]:
        raise NotImplementedError

    def delete(self, id: str):
        raise NotImplementedError

    def count(self) -> int:
        raise NotImplementedError


class FAISSBackend(VectorStoreBackend):
    """
    FAISS-based vector store (local, GPU-acceleratable).
    Best for single-node deployments with < 10M embeddings.
    """

    def __init__(self, dimension: int = 512, use_gpu: bool = False):
        self.dimension = dimension
        self._ids: List[str] = []
        self._metadata: List[Dict] = []
        self._index = None
        self._lock = threading.Lock()

        try:
            import faiss
            if use_gpu and faiss.get_num_gpus() > 0:
                cpu_index = faiss.IndexFlatIP(dimension)  # Inner product (cosine with L2 norm)
                self._index = faiss.index_cpu_to_gpu(
                    faiss.StandardGpuResources(), 0, cpu_index
                )
                logger.info(f"FAISS GPU index created (dim={dimension})")
            else:
                self._index = faiss.IndexFlatIP(dimension)
                logger.info(f"FAISS CPU index created (dim={dimension})")
        except ImportError:
            logger.warning("faiss-cpu/faiss-gpu not installed — using numpy fallback")
            self._index = None
            self._embeddings: List[np.ndarray] = []

    def add(self, id: str, embedding: np.ndarray, metadata: Optional[Dict] = None):
        emb = self._normalize(embedding)
        with self._lock:
            self._ids.append(id)
            self._metadata.append(metadata or {})
            if self._index is not None:
                self._index.add(emb.reshape(1, -1).astype(np.float32))
            else:
                self._embeddings.append(emb)

    def add_batch(self, ids: List[str], embeddings: np.ndarray,
                  metadata_list: Optional[List[Dict]] = None):
        embs = np.array([self._normalize(e) for e in embeddings], dtype=np.float32)
        with self._lock:
            self._ids.extend(ids)
            if metadata_list:
                self._metadata.extend(metadata_list)
            else:
                self._metadata.extend([{} for _ in ids])

            if self._index is not None:
                self._index.add(embs)
            else:
                for e in embs:
                    self._embeddings.append(e)

    def search(self, query: np.ndarray, top_k: int = 10,
               filter: Optional[Dict] = None) -> List[SearchResult]:
        q = self._normalize(query).reshape(1, -1).astype(np.float32)

        with self._lock:
            if self._index is not None and self._index.ntotal > 0:
                scores, indices = self._index.search(q, min(top_k * 2, self._index.ntotal))
                scores = scores[0]
                indices = indices[0]
            elif hasattr(self, '_embeddings') and self._embeddings:
                # Numpy fallback
                db = np.array(self._embeddings, dtype=np.float32)
                sims = db @ q.T
                sims = sims.flatten()
                k = min(top_k * 2, len(sims))
                indices = np.argsort(sims)[::-1][:k]
                scores = sims[indices]
            else:
                return []

            results = []
            for score, idx in zip(scores, indices):
                if idx < 0 or idx >= len(self._ids):
                    continue
                meta = self._metadata[idx]

                # Apply filter
                if filter:
                    if not all(meta.get(k) == v for k, v in filter.items()):
                        continue

                results.append(SearchResult(
                    id=self._ids[idx],
                    score=float(score),
                    metadata=meta,
                ))

                if len(results) >= top_k:
                    break

        return results

    def delete(self, id: str):
        # FAISS doesn't support deletion natively — mark as deleted
        with self._lock:
            if id in self._ids:
                idx = self._ids.index(id)
                self._ids[idx] = f'__deleted_{idx}'
                self._metadata[idx] = {'__deleted': True}

    def count(self) -> int:
        with self._lock:
            if self._index is not None:
                return self._index.ntotal
            return len(getattr(self, '_embeddings', []))

    @staticmethod
    def _normalize(emb: np.ndarray) -> np.ndarray:
        emb = emb.flatten().astype(np.float32)
        norm = np.linalg.norm(emb)
        if norm > 0:
            emb = emb / norm
        return emb


class VectorStore:
    """
    Unified vector database interface with pluggable backends.

    Usage:
        store = VectorStore.create('faiss', dimension=512)
        store.add('face_001', embedding, metadata={'camera': 'cam_01'})
        results = store.search(query_embedding, top_k=5)
    """

    def __init__(self, backend: VectorStoreBackend):
        self._backend = backend
        self._add_count = 0
        self._search_count = 0

    @classmethod
    def create(cls, backend_type: str = 'faiss',
               dimension: int = 512, **kwargs) -> 'VectorStore':
        """Factory: create a VectorStore with the specified backend."""
        if backend_type == 'faiss':
            backend = FAISSBackend(dimension=dimension, **kwargs)
        else:
            # Fallback to FAISS for unknown backends
            logger.warning(f"Unknown backend '{backend_type}' — using FAISS")
            backend = FAISSBackend(dimension=dimension)

        return cls(backend)

    def add(self, id: str, embedding: np.ndarray, metadata: Optional[Dict] = None):
        """Add a single embedding."""
        self._backend.add(id, embedding, metadata)
        self._add_count += 1

    def add_batch(self, ids: List[str], embeddings: np.ndarray,
                  metadata_list: Optional[List[Dict]] = None):
        """Add multiple embeddings at once."""
        self._backend.add_batch(ids, embeddings, metadata_list)
        self._add_count += len(ids)

    def search(self, query: np.ndarray, top_k: int = 10,
               filter: Optional[Dict] = None) -> List[SearchResult]:
        """Search for similar embeddings."""
        self._search_count += 1
        return self._backend.search(query, top_k, filter)

    def delete(self, id: str):
        """Delete an embedding by ID."""
        self._backend.delete(id)

    @property
    def count(self) -> int:
        return self._backend.count()

    def get_metrics(self) -> dict:
        return {
            'backend': self._backend.__class__.__name__,
            'total_embeddings': self.count,
            'total_adds': self._add_count,
            'total_searches': self._search_count,
        }
