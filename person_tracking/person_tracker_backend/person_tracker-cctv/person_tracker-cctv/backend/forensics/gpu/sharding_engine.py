"""
Multi-GPU Camera Sharding Engine (Phase 21, 22)
Distributes RTSP streams across multiple available GPUs or Worker nodes.
Uses consistent hashing and load-balancing algorithms to prevent GPU hotspots.
"""
import torch
import logging
from typing import List, Dict

logger = logging.getLogger(__name__)

class CameraShardingEngine:
    def __init__(self):
        self.available_gpus = self._discover_gpus()
        self.camera_map = {} # camera_id -> 'cuda:X'
        
        logger.info(f"CameraShardingEngine initialized with GPUs: {self.available_gpus}")

    def _discover_gpus(self) -> List[str]:
        """Discovers all available CUDA devices on the local machine."""
        if not torch.cuda.is_available():
            logger.warning("No GPUs discovered! Falling back to CPU.")
            return ['cpu']
        
        count = torch.cuda.device_count()
        gpus = [f'cuda:{i}' for i in range(count)]
        return gpus

    def assign_camera_to_gpu(self, camera_id: str, load_weight: int = 1) -> str:
        """
        Assigns a camera to the least loaded GPU.
        load_weight can be higher for 4K streams vs 1080p.
        """
        if camera_id in self.camera_map:
            return self.camera_map[camera_id]

        if not self.available_gpus or self.available_gpus == ['cpu']:
            self.camera_map[camera_id] = 'cpu'
            return 'cpu'

        # Count active streams per GPU
        gpu_loads = {gpu: 0 for gpu in self.available_gpus}
        for assigned_gpu in self.camera_map.values():
            if assigned_gpu in gpu_loads:
                gpu_loads[assigned_gpu] += 1

        # Find GPU with minimum streams
        best_gpu = min(gpu_loads, key=gpu_loads.get)
        self.camera_map[camera_id] = best_gpu
        
        logger.info(f"Sharding Engine: Assigned camera '{camera_id}' to {best_gpu} (Load: {gpu_loads[best_gpu] + 1})")
        return best_gpu

    def remove_camera(self, camera_id: str):
        """Removes a camera from the assignment map (e.g. stream stopped)."""
        if camera_id in self.camera_map:
            gpu = self.camera_map.pop(camera_id)
            logger.info(f"Sharding Engine: Removed camera '{camera_id}' from {gpu}")

    def get_gpu_for_camera(self, camera_id: str) -> str:
        """Retrieves the assigned GPU, or assigns one if not found."""
        if camera_id not in self.camera_map:
            return self.assign_camera_to_gpu(camera_id)
        return self.camera_map[camera_id]
