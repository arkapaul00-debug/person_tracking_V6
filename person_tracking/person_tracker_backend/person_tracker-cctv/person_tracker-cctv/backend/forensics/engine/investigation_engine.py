"""
Investigation Intelligence Engine (Phases 45, 46, 47)
AI-powered investigation support with timeline reconstruction,
forensic search, and natural language query parsing.

Capabilities:
  - Timeline reconstruction for any identity
  - Path reconstruction across cameras
  - Search by face/body/clothing/time/camera
  - Natural language query translation to structured search

Usage:
    engine = InvestigationEngine(identity_graph, memory_bank)

    # Timeline query
    timeline = engine.reconstruct_timeline('suspect_001')

    # Natural language query
    results = engine.query_natural_language(
        "Show all appearances between 10 AM and 2 PM yesterday"
    )

    # Forensic search
    results = engine.search_by_face(face_embedding, time_range=(start, end))
"""
import re
import time
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import numpy as np

logger = logging.getLogger(__name__)


class InvestigationEngine:
    """
    AI-powered investigation engine that wraps the IdentityGraph,
    CrossCameraGraph, and IdentityMemoryBank into high-level
    investigator-facing queries.
    """

    def __init__(self, identity_graph=None, cross_graph=None,
                 memory_bank=None, topology=None):
        self._identity_graph = identity_graph
        self._cross_graph = cross_graph
        self._memory_bank = memory_bank
        self._topology = topology

        # Search metrics
        self._total_queries = 0
        self._total_nl_queries = 0

        logger.info("InvestigationEngine initialized")

    def reconstruct_timeline(self, identity_id: str) -> List[Dict]:
        """
        Build a complete chronological timeline for a suspect.
        Merges data from IdentityGraph and CrossCameraGraph.

        Returns list of events sorted by timestamp:
            [{'timestamp': ..., 'camera': ..., 'event_type': ..., 'details': ...}, ...]
        """
        self._total_queries += 1
        timeline = []

        # From identity graph
        if self._identity_graph:
            graph_events = self._identity_graph.get_identity_timeline(identity_id)
            for event in graph_events:
                timeline.append({
                    'timestamp': event.get('timestamp', 0),
                    'camera': event.get('target', 'unknown'),
                    'event_type': event.get('type', 'sighting'),
                    'confidence': event.get('confidence', 0),
                    'details': event.get('properties', {}),
                })

        # From cross-camera graph
        if self._cross_graph:
            trail = self._cross_graph.get_identity_trail(
                int(identity_id) if identity_id.isdigit() else hash(identity_id)
            )
            for sighting in trail:
                timeline.append({
                    'timestamp': sighting.timestamp,
                    'camera': sighting.stream_id,
                    'event_type': 'cross_camera_sighting',
                    'confidence': sighting.match_score,
                    'details': {
                        'track_id': sighting.track_id,
                        'bbox': sighting.bbox,
                    },
                })

        # Deduplicate and sort
        timeline.sort(key=lambda e: e['timestamp'])
        return timeline

    def reconstruct_path(self, identity_id: str) -> List[Dict]:
        """
        Build the physical path: sequence of cameras visited.
        Returns list of camera transitions with travel times.
        """
        self._total_queries += 1
        timeline = self.reconstruct_timeline(identity_id)

        path = []
        prev = None
        for event in timeline:
            if prev and prev['camera'] != event['camera']:
                travel_time = event['timestamp'] - prev['timestamp']
                path.append({
                    'from_camera': prev['camera'],
                    'to_camera': event['camera'],
                    'departure_time': prev['timestamp'],
                    'arrival_time': event['timestamp'],
                    'travel_time_s': round(travel_time, 1),
                })
            prev = event

        return path

    def search_by_embedding(self,
                            face_embedding: Optional[np.ndarray] = None,
                            body_embedding: Optional[np.ndarray] = None,
                            time_range: Optional[Tuple[float, float]] = None,
                            camera_filter: Optional[str] = None,
                            top_k: int = 20) -> List[Dict]:
        """
        Search all sightings by embedding similarity.

        Args:
            face_embedding: Query face embedding.
            body_embedding: Query body embedding.
            time_range: (start_ts, end_ts) filter.
            camera_filter: Only search on this camera.
            top_k: Max results.
        """
        self._total_queries += 1
        results = []

        if self._cross_graph:
            matches = self._cross_graph.find_matches(
                face_embedding=face_embedding,
                body_embedding=body_embedding,
                exclude_stream='',
                top_k=top_k,
            )
            for match in matches:
                s = match.sighting_b
                # Apply filters
                if time_range:
                    if s.timestamp < time_range[0] or s.timestamp > time_range[1]:
                        continue
                if camera_filter and s.stream_id != camera_filter:
                    continue

                results.append({
                    'camera': s.stream_id,
                    'track_id': s.track_id,
                    'timestamp': s.timestamp,
                    'face_similarity': match.face_similarity,
                    'body_similarity': match.body_similarity,
                    'combined_score': match.combined_score,
                    'global_id': s.global_id,
                })

        results.sort(key=lambda r: r['combined_score'], reverse=True)
        return results[:top_k]

    def query_natural_language(self, query: str) -> Dict:
        """
        Parse a natural language investigation query and return structured results.

        Supported patterns:
          - "Show all appearances of suspect X"
          - "Show all appearances between TIME and TIME"
          - "Show all cameras visited by suspect X"
          - "Show suspect movement timeline"

        Returns:
            {'query_type': str, 'parameters': dict, 'results': list}
        """
        self._total_queries += 1
        self._total_nl_queries += 1

        query_lower = query.lower().strip()
        parsed = self._parse_query(query_lower)

        results = []
        if parsed['type'] == 'timeline':
            if parsed.get('identity_id'):
                results = self.reconstruct_timeline(parsed['identity_id'])
        elif parsed['type'] == 'path':
            if parsed.get('identity_id'):
                results = self.reconstruct_path(parsed['identity_id'])
        elif parsed['type'] == 'cameras_visited':
            if parsed.get('identity_id') and self._identity_graph:
                results = self._identity_graph.get_cameras_for_identity(
                    parsed['identity_id']
                )
        elif parsed['type'] == 'time_range_search':
            time_range = parsed.get('time_range')
            results = self.search_by_embedding(time_range=time_range)
        elif parsed['type'] == 'unknown':
            logger.warning(f"Could not parse NL query: {query}")

        return {
            'original_query': query,
            'query_type': parsed['type'],
            'parameters': parsed,
            'results': results,
            'result_count': len(results),
        }

    def _parse_query(self, query: str) -> Dict:
        """Simple rule-based NL query parser."""
        result = {'type': 'unknown'}

        # Pattern: "timeline for/of suspect X" or "show timeline X"
        timeline_match = re.search(
            r'(?:timeline|movement|journey)\s+(?:for|of)?\s*(\w+)',
            query
        )
        if timeline_match:
            result['type'] = 'timeline'
            result['identity_id'] = timeline_match.group(1)
            return result

        # Pattern: "cameras visited by X"
        cameras_match = re.search(
            r'cameras?\s+visited\s+(?:by)?\s*(\w+)', query
        )
        if cameras_match:
            result['type'] = 'cameras_visited'
            result['identity_id'] = cameras_match.group(1)
            return result

        # Pattern: "path of/for X"
        path_match = re.search(
            r'(?:path|route|trail)\s+(?:of|for)?\s*(\w+)', query
        )
        if path_match:
            result['type'] = 'path'
            result['identity_id'] = path_match.group(1)
            return result

        # Pattern: "between TIME and TIME"
        time_match = re.search(
            r'between\s+(\d{1,2})\s*(am|pm)?\s+and\s+(\d{1,2})\s*(am|pm)?',
            query
        )
        if time_match:
            result['type'] = 'time_range_search'
            start_h = int(time_match.group(1))
            end_h = int(time_match.group(3))
            start_ampm = time_match.group(2)
            end_ampm = time_match.group(4)

            if start_ampm and 'pm' in start_ampm and start_h != 12:
                start_h += 12
            if end_ampm and 'pm' in end_ampm and end_h != 12:
                end_h += 12

            today = datetime.now().replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            start_ts = (today + timedelta(hours=start_h)).timestamp()
            end_ts = (today + timedelta(hours=end_h)).timestamp()
            result['time_range'] = (start_ts, end_ts)
            return result

        # Pattern: "all appearances" (general listing)
        if 'all appearances' in query or 'show all' in query:
            # Try to extract identity
            id_match = re.search(r'(?:of|for)\s+(\w+)', query)
            if id_match:
                result['type'] = 'timeline'
                result['identity_id'] = id_match.group(1)
                return result

        return result

    def get_metrics(self) -> Dict:
        return {
            'total_queries': self._total_queries,
            'nl_queries': self._total_nl_queries,
        }
