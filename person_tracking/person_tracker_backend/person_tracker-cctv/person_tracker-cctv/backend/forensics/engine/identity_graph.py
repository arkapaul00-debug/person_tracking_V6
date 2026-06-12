"""
Global Identity Graph (Phase 37)
Persistent identity graph backed by PostgreSQL JSONB.

Tracks:
  - Identity nodes (face/body/gait embeddings, metadata)
  - Camera nodes (location, adjacency)
  - Event nodes (sightings, alerts)
  - Evidence nodes (snapshots, video clips)

Relationships:
  Identity → Camera (seen_at)
  Identity → Event (triggered)
  Identity → Evidence (captured_in)
  Identity → Identity (same_person / associate)
  Identity → Location (visited)

This graph enables:
  - Global identity persistence across sessions
  - Investigation timeline reconstruction
  - Relationship discovery between suspects
"""
import time
import logging
import threading
from typing import Dict, List, Optional, Set, Tuple
from dataclasses import dataclass, field
from collections import defaultdict
from enum import Enum

logger = logging.getLogger(__name__)


class NodeType(Enum):
    IDENTITY = 'identity'
    CAMERA = 'camera'
    EVENT = 'event'
    EVIDENCE = 'evidence'
    LOCATION = 'location'


class EdgeType(Enum):
    SEEN_AT = 'seen_at'
    TRIGGERED = 'triggered'
    CAPTURED_IN = 'captured_in'
    SAME_PERSON = 'same_person'
    ASSOCIATE = 'associate'
    VISITED = 'visited'
    TRANSITION = 'transition'  # Camera → Camera


@dataclass
class GraphNode:
    """A node in the identity graph."""
    node_id: str
    node_type: NodeType
    properties: Dict = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


@dataclass
class GraphEdge:
    """An edge linking two nodes."""
    source_id: str
    target_id: str
    edge_type: EdgeType
    weight: float = 1.0
    properties: Dict = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)


class IdentityGraph:
    """
    In-memory identity graph with adjacency-list representation.

    Designed for PostgreSQL JSONB persistence (serialize/deserialize methods).
    For deployments needing deep graph queries (6+ hops), can be exported
    to Neo4j via the export_cypher() method.

    Usage:
        graph = IdentityGraph()

        # Add an identity
        graph.add_identity('suspect_001', properties={
            'name': 'Unknown Male',
            'first_seen': time.time(),
        })

        # Record a sighting
        graph.record_sighting('suspect_001', 'cam_lobby', timestamp=time.time())

        # Query: where was this person seen?
        cameras = graph.get_cameras_for_identity('suspect_001')

        # Query: who was seen on this camera?
        identities = graph.get_identities_on_camera('cam_lobby')

        # Timeline
        trail = graph.get_identity_timeline('suspect_001')
    """

    def __init__(self):
        self._nodes: Dict[str, GraphNode] = {}
        self._edges: List[GraphEdge] = []
        self._adjacency: Dict[str, List[int]] = defaultdict(list)  # node_id → edge indices
        self._lock = threading.Lock()

        # Metrics
        self._total_nodes = 0
        self._total_edges = 0

        logger.info("IdentityGraph initialized (in-memory, JSONB-ready)")

    # ---- Node Operations ----

    def add_identity(self, identity_id: str,
                     properties: Optional[Dict] = None) -> GraphNode:
        """Add or update an identity node."""
        with self._lock:
            if identity_id in self._nodes:
                node = self._nodes[identity_id]
                if properties:
                    node.properties.update(properties)
                node.updated_at = time.time()
                return node

            node = GraphNode(
                node_id=identity_id,
                node_type=NodeType.IDENTITY,
                properties=properties or {},
            )
            self._nodes[identity_id] = node
            self._total_nodes += 1
            return node

    def add_camera(self, camera_id: str, location: str = '',
                   properties: Optional[Dict] = None) -> GraphNode:
        """Add or update a camera node."""
        with self._lock:
            props = {'location': location}
            if properties:
                props.update(properties)

            if camera_id in self._nodes:
                self._nodes[camera_id].properties.update(props)
                self._nodes[camera_id].updated_at = time.time()
                return self._nodes[camera_id]

            node = GraphNode(
                node_id=camera_id,
                node_type=NodeType.CAMERA,
                properties=props,
            )
            self._nodes[camera_id] = node
            self._total_nodes += 1
            return node

    def add_event(self, event_id: str,
                  properties: Optional[Dict] = None) -> GraphNode:
        """Add an event node (alert, sighting, etc.)."""
        with self._lock:
            node = GraphNode(
                node_id=event_id,
                node_type=NodeType.EVENT,
                properties=properties or {},
            )
            self._nodes[event_id] = node
            self._total_nodes += 1
            return node

    # ---- Edge Operations ----

    def _add_edge(self, source_id: str, target_id: str,
                  edge_type: EdgeType, weight: float = 1.0,
                  properties: Optional[Dict] = None) -> GraphEdge:
        """Internal: add an edge (caller must hold lock)."""
        edge = GraphEdge(
            source_id=source_id,
            target_id=target_id,
            edge_type=edge_type,
            weight=weight,
            properties=properties or {},
        )
        idx = len(self._edges)
        self._edges.append(edge)
        self._adjacency[source_id].append(idx)
        self._adjacency[target_id].append(idx)
        self._total_edges += 1
        return edge

    # ---- High-Level Operations ----

    def record_sighting(self, identity_id: str, camera_id: str,
                        timestamp: Optional[float] = None,
                        bbox: Optional[List[int]] = None,
                        confidence: float = 0.0):
        """Record that an identity was seen on a camera."""
        ts = timestamp or time.time()
        with self._lock:
            # Ensure nodes exist
            if identity_id not in self._nodes:
                self._nodes[identity_id] = GraphNode(
                    node_id=identity_id,
                    node_type=NodeType.IDENTITY,
                )
                self._total_nodes += 1

            if camera_id not in self._nodes:
                self._nodes[camera_id] = GraphNode(
                    node_id=camera_id,
                    node_type=NodeType.CAMERA,
                )
                self._total_nodes += 1

            # Create edge
            self._add_edge(
                identity_id, camera_id,
                EdgeType.SEEN_AT,
                weight=confidence,
                properties={
                    'timestamp': ts,
                    'bbox': bbox,
                },
            )

    def link_identities(self, id_a: str, id_b: str,
                        confidence: float = 1.0,
                        reason: str = 'reid_match'):
        """Link two identities as the same person."""
        with self._lock:
            self._add_edge(
                id_a, id_b,
                EdgeType.SAME_PERSON,
                weight=confidence,
                properties={'reason': reason},
            )

    def record_camera_transition(self, cam_a: str, cam_b: str,
                                 travel_time_s: float,
                                 count: int = 1):
        """Record a learned camera-to-camera transition."""
        with self._lock:
            self._add_edge(
                cam_a, cam_b,
                EdgeType.TRANSITION,
                weight=float(count),
                properties={'avg_travel_time_s': travel_time_s},
            )

    # ---- Query Operations ----

    def get_cameras_for_identity(self, identity_id: str) -> List[Dict]:
        """Get all cameras where an identity was seen, with timestamps."""
        results = []
        with self._lock:
            for edge_idx in self._adjacency.get(identity_id, []):
                edge = self._edges[edge_idx]
                if (edge.edge_type == EdgeType.SEEN_AT and
                        edge.source_id == identity_id):
                    results.append({
                        'camera_id': edge.target_id,
                        'timestamp': edge.properties.get('timestamp', 0),
                        'confidence': edge.weight,
                    })
        results.sort(key=lambda r: r['timestamp'])
        return results

    def get_identities_on_camera(self, camera_id: str) -> List[Dict]:
        """Get all identities seen on a specific camera."""
        results = []
        with self._lock:
            for edge_idx in self._adjacency.get(camera_id, []):
                edge = self._edges[edge_idx]
                if (edge.edge_type == EdgeType.SEEN_AT and
                        edge.target_id == camera_id):
                    results.append({
                        'identity_id': edge.source_id,
                        'timestamp': edge.properties.get('timestamp', 0),
                        'confidence': edge.weight,
                    })
        results.sort(key=lambda r: r['timestamp'], reverse=True)
        return results

    def get_identity_timeline(self, identity_id: str) -> List[Dict]:
        """
        Build a complete timeline for an identity: 
        all cameras visited, events triggered, evidence collected.
        """
        timeline = []
        with self._lock:
            for edge_idx in self._adjacency.get(identity_id, []):
                edge = self._edges[edge_idx]
                if edge.source_id == identity_id:
                    entry = {
                        'type': edge.edge_type.value,
                        'target': edge.target_id,
                        'timestamp': edge.properties.get('timestamp', edge.created_at),
                        'confidence': edge.weight,
                        'properties': edge.properties,
                    }
                    timeline.append(entry)

        timeline.sort(key=lambda e: e['timestamp'])
        return timeline

    def get_linked_identities(self, identity_id: str) -> List[str]:
        """Get all identity IDs linked as the same person."""
        linked: Set[str] = set()
        visited: Set[str] = set()
        queue = [identity_id]

        with self._lock:
            while queue:
                current = queue.pop(0)
                if current in visited:
                    continue
                visited.add(current)

                for edge_idx in self._adjacency.get(current, []):
                    edge = self._edges[edge_idx]
                    if edge.edge_type == EdgeType.SAME_PERSON:
                        other = (edge.target_id if edge.source_id == current
                                 else edge.source_id)
                        if other not in visited:
                            linked.add(other)
                            queue.append(other)

        return list(linked)

    # ---- Serialization (JSONB-ready) ----

    def to_dict(self) -> Dict:
        """Serialize the entire graph to a dict (for PostgreSQL JSONB)."""
        return {
            'nodes': {
                nid: {
                    'type': n.node_type.value,
                    'properties': n.properties,
                    'created_at': n.created_at,
                    'updated_at': n.updated_at,
                }
                for nid, n in self._nodes.items()
            },
            'edges': [
                {
                    'source': e.source_id,
                    'target': e.target_id,
                    'type': e.edge_type.value,
                    'weight': e.weight,
                    'properties': e.properties,
                    'created_at': e.created_at,
                }
                for e in self._edges
            ],
        }

    def get_metrics(self) -> Dict:
        """Return graph metrics."""
        return {
            'total_nodes': self._total_nodes,
            'total_edges': self._total_edges,
            'active_nodes': len(self._nodes),
            'active_edges': len(self._edges),
            'identity_count': sum(
                1 for n in self._nodes.values()
                if n.node_type == NodeType.IDENTITY
            ),
            'camera_count': sum(
                1 for n in self._nodes.values()
                if n.node_type == NodeType.CAMERA
            ),
        }
