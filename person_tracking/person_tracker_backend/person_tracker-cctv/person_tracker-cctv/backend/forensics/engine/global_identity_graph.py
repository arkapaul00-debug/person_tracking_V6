"""
Global Identity Knowledge Graph (V5 Upgrade 1)
Comprehensive forensic intelligence graph linking identities, cameras, events,
evidence, embeddings, gait signatures, clothing descriptors, locations, and temporal patterns.
"""
import time
import logging
import threading
from typing import Dict, List, Any, Optional, Tuple
from collections import defaultdict

logger = logging.getLogger(__name__)


class GlobalIdentityGraph:
    """
    Expands the V4 IdentityGraph into a multi-modal forensic intelligence graph.
    
    Node types: Identity, Camera, Event, Evidence, Embedding, GaitSignature,
                ClothingDescriptor, Location, TemporalPattern
    Edge types: SEEN_AT, PRODUCED, MATCHES, WORE, WALKED_LIKE, VISITED, FOLLOWS_PATTERN
    """

    def __init__(self, v4_identity_graph=None):
        self._v4_graph = v4_identity_graph  # Backward-compatible fallback
        self._lock = threading.RLock()

        # --- Node stores ---
        self._identities: Dict[str, Dict[str, Any]] = {}
        self._cameras: Dict[str, Dict[str, Any]] = {}
        self._events: Dict[str, Dict[str, Any]] = {}
        self._evidence: Dict[str, Dict[str, Any]] = {}
        self._gait_signatures: Dict[str, Dict[str, Any]] = {}
        self._clothing_descriptors: Dict[str, Dict[str, Any]] = {}
        self._locations: Dict[str, Dict[str, Any]] = {}
        self._temporal_patterns: Dict[str, Dict[str, Any]] = {}

        # --- Edge stores (adjacency lists) ---
        self._edges: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

        # --- Metrics ---
        self._metrics = {
            "total_identities": 0,
            "total_edges": 0,
            "total_events": 0,
            "graph_queries": 0,
            "association_discoveries": 0,
        }

        logger.info("V5 GlobalIdentityGraph initialized")

    # ── Node Operations ──────────────────────────────────────────────

    def upsert_identity(self, identity_id: str, metadata: Dict[str, Any] = None):
        """Create or update an identity node with multi-modal attributes."""
        with self._lock:
            if identity_id not in self._identities:
                self._identities[identity_id] = {
                    "identity_id": identity_id,
                    "created_at": time.time(),
                    "last_seen": time.time(),
                    "sighting_count": 0,
                    "modalities_observed": set(),
                    "metadata": metadata or {},
                }
                self._metrics["total_identities"] = len(self._identities)
            else:
                node = self._identities[identity_id]
                node["last_seen"] = time.time()
                node["sighting_count"] += 1
                if metadata:
                    node["metadata"].update(metadata)

    def register_camera(self, camera_id: str, zone: str = "",
                        coordinates: Optional[Tuple[float, float]] = None):
        """Register a camera node in the graph."""
        with self._lock:
            self._cameras[camera_id] = {
                "camera_id": camera_id,
                "zone": zone,
                "coordinates": coordinates,
                "registered_at": time.time(),
            }

    def add_gait_signature(self, sig_id: str, identity_id: str,
                           embedding: Any, quality: float):
        """Store a gait signature linked to an identity."""
        with self._lock:
            self._gait_signatures[sig_id] = {
                "sig_id": sig_id,
                "identity_id": identity_id,
                "embedding": embedding,
                "quality": quality,
                "timestamp": time.time(),
            }
            self._add_edge(identity_id, sig_id, "WALKED_LIKE")
            if identity_id in self._identities:
                self._identities[identity_id]["modalities_observed"].add("gait")

    def add_clothing_descriptor(self, desc_id: str, identity_id: str,
                                descriptor: Dict[str, Any]):
        """Store a clothing descriptor linked to an identity."""
        with self._lock:
            self._clothing_descriptors[desc_id] = {
                "desc_id": desc_id,
                "identity_id": identity_id,
                "descriptor": descriptor,
                "timestamp": time.time(),
            }
            self._add_edge(identity_id, desc_id, "WORE")
            if identity_id in self._identities:
                self._identities[identity_id]["modalities_observed"].add("clothing")

    # ── Edge Operations ──────────────────────────────────────────────

    def _add_edge(self, src: str, dst: str, edge_type: str,
                  metadata: Dict[str, Any] = None):
        """Internal: create a directed edge."""
        edge = {
            "src": src, "dst": dst, "type": edge_type,
            "timestamp": time.time(),
            "metadata": metadata or {},
        }
        self._edges[src].append(edge)
        self._metrics["total_edges"] += 1

    def record_sighting(self, identity_id: str, camera_id: str,
                        event_id: str, confidence: float):
        """Record that an identity was seen at a camera, producing an event."""
        with self._lock:
            self.upsert_identity(identity_id)
            self._events[event_id] = {
                "event_id": event_id,
                "identity_id": identity_id,
                "camera_id": camera_id,
                "confidence": confidence,
                "timestamp": time.time(),
            }
            self._metrics["total_events"] += 1

            self._add_edge(identity_id, camera_id, "SEEN_AT",
                           {"confidence": confidence})
            self._add_edge(identity_id, event_id, "PRODUCED")

    def link_evidence(self, identity_id: str, evidence_id: str,
                      evidence_type: str = "video_clip"):
        """Link forensic evidence to an identity."""
        with self._lock:
            self._evidence[evidence_id] = {
                "evidence_id": evidence_id,
                "identity_id": identity_id,
                "type": evidence_type,
                "timestamp": time.time(),
            }
            self._add_edge(identity_id, evidence_id, "MATCHES")

    # ── Query Operations ─────────────────────────────────────────────

    def get_identity_profile(self, identity_id: str) -> Dict[str, Any]:
        """Full multi-modal profile of an identity."""
        with self._lock:
            self._metrics["graph_queries"] += 1
            node = self._identities.get(identity_id)
            if not node:
                return {}

            edges = self._edges.get(identity_id, [])
            cameras_seen = [e["dst"] for e in edges if e["type"] == "SEEN_AT"]
            evidence_ids = [e["dst"] for e in edges if e["type"] == "MATCHES"]
            gait_ids = [e["dst"] for e in edges if e["type"] == "WALKED_LIKE"]
            clothing_ids = [e["dst"] for e in edges if e["type"] == "WORE"]

            profile = {
                **node,
                "modalities_observed": list(node.get("modalities_observed", [])),
                "cameras_seen": cameras_seen,
                "evidence_linked": evidence_ids,
                "gait_signatures": len(gait_ids),
                "clothing_descriptors": len(clothing_ids),
                "total_edges": len(edges),
            }
            return profile

    def find_associations(self, identity_id: str,
                          max_depth: int = 2) -> List[Dict[str, Any]]:
        """
        BFS traversal to discover associated identities via shared cameras,
        shared evidence, or shared clothing descriptors.
        """
        with self._lock:
            self._metrics["graph_queries"] += 1
            visited = set()
            queue = [(identity_id, 0)]
            associations = []

            while queue:
                current, depth = queue.pop(0)
                if current in visited or depth > max_depth:
                    continue
                visited.add(current)

                for edge in self._edges.get(current, []):
                    dst = edge["dst"]
                    if dst not in visited:
                        if dst in self._identities and dst != identity_id:
                            associations.append({
                                "identity_id": dst,
                                "linked_via": edge["type"],
                                "depth": depth + 1,
                            })
                            self._metrics["association_discoveries"] += 1
                        queue.append((dst, depth + 1))

            return associations

    def reconstruct_timeline(self, identity_id: str,
                             start_time: float = 0,
                             end_time: float = None) -> List[Dict[str, Any]]:
        """Reconstruct the full chronological timeline for an identity."""
        with self._lock:
            self._metrics["graph_queries"] += 1
            end_time = end_time or time.time()
            events = [
                e for e in self._events.values()
                if e["identity_id"] == identity_id
                and start_time <= e["timestamp"] <= end_time
            ]
            return sorted(events, key=lambda x: x["timestamp"])

    # ── Metrics ──────────────────────────────────────────────────────

    def get_metrics(self) -> dict:
        with self._lock:
            return dict(self._metrics)
