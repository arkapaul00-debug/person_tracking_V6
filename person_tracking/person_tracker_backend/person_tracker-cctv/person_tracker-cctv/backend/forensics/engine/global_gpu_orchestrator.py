"""
Global GPU Orchestrator (V5 Upgrade 6)
Cluster-wide workload balancing, resource-aware scheduling, and fault tolerance
across multiple GPU nodes (Edge + Central).
"""
import time
import logging
import threading
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)


class GPUNodeState:
    """Represents the state of a single GPU node in the cluster."""

    def __init__(self, node_id: str, gpu_count: int, role: str = "EDGE"):
        self.node_id = node_id
        self.gpu_count = gpu_count
        self.role = role  # EDGE or CENTRAL
        self.status = "ONLINE"
        self.vram_percent = 0.0
        self.gpu_util_percent = 0.0
        self.assigned_cameras: List[str] = []
        self.last_heartbeat = time.time()


class GlobalGPUOrchestrator:
    """
    Manages a fleet of GPU nodes across Edge and Central sites.
    Performs workload balancing, automatic redistribution on failure,
    and capacity-aware camera assignment.
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._nodes: Dict[str, GPUNodeState] = {}
        self._heartbeat_timeout = 60  # seconds

        self._metrics = {
            "total_nodes": 0,
            "online_nodes": 0,
            "offline_nodes": 0,
            "total_gpus": 0,
            "rebalances_performed": 0,
            "failovers_triggered": 0,
        }

        logger.info("V5 GlobalGPUOrchestrator initialized")

    # ── Node Registration ────────────────────────────────────────────

    def register_node(self, node_id: str, gpu_count: int,
                      role: str = "EDGE") -> bool:
        """Register a GPU node in the cluster."""
        with self._lock:
            self._nodes[node_id] = GPUNodeState(node_id, gpu_count, role)
            self._update_node_counts()
            logger.info(f"Node {node_id} registered ({role}, {gpu_count} GPUs)")
            return True

    def update_heartbeat(self, node_id: str, vram_percent: float,
                         gpu_util_percent: float):
        """Receive a heartbeat from a node with current resource state."""
        with self._lock:
            node = self._nodes.get(node_id)
            if node:
                node.last_heartbeat = time.time()
                node.vram_percent = vram_percent
                node.gpu_util_percent = gpu_util_percent
                if node.status == "OFFLINE":
                    node.status = "ONLINE"
                    logger.info(f"Node {node_id} recovered (back ONLINE)")
                    self._update_node_counts()

    # ── Health Monitoring ────────────────────────────────────────────

    def check_node_health(self) -> List[str]:
        """Detect offline nodes based on heartbeat timeout."""
        now = time.time()
        newly_offline = []
        with self._lock:
            for nid, node in self._nodes.items():
                if (node.status == "ONLINE"
                        and (now - node.last_heartbeat) > self._heartbeat_timeout):
                    node.status = "OFFLINE"
                    newly_offline.append(nid)
                    logger.critical(f"Node {nid} detected OFFLINE (no heartbeat)")

            if newly_offline:
                self._metrics["failovers_triggered"] += len(newly_offline)
                self._update_node_counts()

        return newly_offline

    # ── Workload Balancing ───────────────────────────────────────────

    def assign_camera(self, camera_id: str) -> Optional[str]:
        """
        Assign a camera to the least-loaded online node.
        Prefers EDGE nodes. Falls back to CENTRAL if all EDGE nodes are saturated.
        """
        with self._lock:
            online = [n for n in self._nodes.values() if n.status == "ONLINE"]
            if not online:
                logger.error("No online nodes available for camera assignment")
                return None

            # Sort by VRAM usage (least loaded first), prefer EDGE
            edge_nodes = sorted(
                [n for n in online if n.role == "EDGE"],
                key=lambda n: n.vram_percent
            )
            central_nodes = sorted(
                [n for n in online if n.role == "CENTRAL"],
                key=lambda n: n.vram_percent
            )

            # Assign to least-loaded edge node if VRAM < 80%
            for node in edge_nodes:
                if node.vram_percent < 80:
                    node.assigned_cameras.append(camera_id)
                    logger.info(f"Camera {camera_id} → Node {node.node_id}")
                    return node.node_id

            # Fallback to central
            for node in central_nodes:
                if node.vram_percent < 80:
                    node.assigned_cameras.append(camera_id)
                    logger.info(f"Camera {camera_id} → Central {node.node_id}")
                    return node.node_id

            logger.warning(f"All nodes saturated. Camera {camera_id} queued.")
            return None

    def rebalance(self) -> Dict[str, Any]:
        """
        Redistribute cameras from overloaded or offline nodes
        to healthy ones.
        """
        with self._lock:
            orphaned_cameras = []

            # Collect cameras from offline nodes
            for node in self._nodes.values():
                if node.status == "OFFLINE" and node.assigned_cameras:
                    orphaned_cameras.extend(node.assigned_cameras)
                    node.assigned_cameras = []

            # Reassign orphaned cameras
            reassigned = 0
            for cam_id in orphaned_cameras:
                target = self.assign_camera(cam_id)
                if target:
                    reassigned += 1

            self._metrics["rebalances_performed"] += 1

            return {
                "orphaned_cameras": len(orphaned_cameras),
                "reassigned": reassigned,
                "failed": len(orphaned_cameras) - reassigned,
            }

    # ── Internal ─────────────────────────────────────────────────────

    def _update_node_counts(self):
        online = sum(1 for n in self._nodes.values() if n.status == "ONLINE")
        self._metrics["total_nodes"] = len(self._nodes)
        self._metrics["online_nodes"] = online
        self._metrics["offline_nodes"] = len(self._nodes) - online
        self._metrics["total_gpus"] = sum(
            n.gpu_count for n in self._nodes.values() if n.status == "ONLINE"
        )

    def get_metrics(self) -> dict:
        with self._lock:
            return dict(self._metrics)
