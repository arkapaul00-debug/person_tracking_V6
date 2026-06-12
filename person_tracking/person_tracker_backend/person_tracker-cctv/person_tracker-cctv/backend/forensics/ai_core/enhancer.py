import torch
import numpy as np
import logging
import cv2
import os
from basicsr.archs.rrdbnet_arch import RRDBNet
from realesrgan import RealESRGANer

logger = logging.getLogger(__name__)

class FrameEnhancer:
    """
    Singleton-style wrapper for Real-ESRGAN to perform AI upscaling 
    on low-resolution frames for investigative purposes.
    Optimized for GTX 1050 Ti using SRVGGNetCompact architecture.
    """

    def __init__(self, weights_path: str = 'weights/RealESRGAN_x4plus.pth', device: str = 'cuda:0'):
        """
        Initializes the AI model.

        Args:
            weights_path: Path to .pth model file. Defaults to lightweight x4v3 model.
            device: 'cuda:0' or 'cpu'. Falls back to cpu if cuda unavailable.
        """
        self.device = torch.device(device if torch.cuda.is_available() else 'cpu')
        logger.info(f"Initializing Enhancer on device: {self.device}")

        if not os.path.exists(weights_path):
            raise FileNotFoundError(f"Model weights not found at: {weights_path}")

        # Initialize Model Architecture (SRVGGNetCompact for x4v3)
        # Optimized for speed on mid-range GPUs compared to RRDBNet
        model = RRDBNet(num_in_ch=3, num_out_ch=3, num_feat=64, num_block=23, num_grow_ch=32, scale=4)
        
        # Initialize the Inference wrapper
        # tile=128 saves VRAM for 4GB cards; tile_pad=10 prevents border artifacts
        self.upsampler = RealESRGANer(
            scale=4,
            model_path=weights_path,
            model=model,
            tile=0,         # Reduced from 256 to 128 for GTX 1050 Ti stability
            tile_pad=10,
            pre_pad=0,
            half=True,        # Use FP16 precision for performance
            device=self.device
        )

    def enhance(self, frame_id: int, frame: np.ndarray) -> np.ndarray:
        """
        Enhances the frame if resolution is low.

        Logic:
            - If height < 720: Upscale x4.
            - If height >= 720: Return Original.

        Args:
            frame_id: ID for logging.
            frame: Raw numpy array (BGR).

        Returns:
            np.ndarray: Enhanced or Original frame.
        """
        height, width = frame.shape[:2]

        # Pass-through logic
        if height >= 720:
            return frame

        try:
            # Inference
            output, _ = self.upsampler.enhance(frame, outscale=4)
            
            logger.warning(f"Frame {frame_id} Enhanced (AI Upscaled) - NOT EVIDENCE.")
            return output

        except torch.cuda.OutOfMemoryError:
            logger.warning(f"Frame {frame_id}: CUDA OOM. Attempting CPU fallback.")
            try:
                # Emergency CPU Fallback (Note: This is slow)
                self.upsampler.device = torch.device('cpu')
                self.upsampler.model.to('cpu')
                output, _ = self.upsampler.enhance(frame, outscale=4)
                
                # Restore to GPU for next frames if possible
                if torch.cuda.is_available():
                    self.upsampler.device = self.device
                    self.upsampler.model.to(self.device)
                
                return output
            except Exception as e:
                logger.error(f"Frame {frame_id}: CPU Fallback failed. Returning original. Error: {e}")
                return frame

        except Exception as e:
            logger.error(f"Frame {frame_id}: Enhancement failed. Returning original. Error: {e}")
            return frame

    def __del__(self):
        """Explicitly release GPU memory."""
        if hasattr(self, 'upsampler'):
            del self.upsampler
        torch.cuda.empty_cache()
        logger.info("Enhancer resources released and CUDA cache cleared.")