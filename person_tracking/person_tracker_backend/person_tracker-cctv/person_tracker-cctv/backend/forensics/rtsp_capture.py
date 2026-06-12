"""
RTSP Stream Capture — Robust RTSP reader with auto-reconnect.

Designed for live CCTV: always serves the LATEST frame (drops stale ones),
handles network drops with exponential backoff reconnection.
"""
import cv2
import threading
import time
import logging
import numpy as np
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


class RTSPCapture:
    """
    Thread-safe RTSP stream reader for real-time CCTV.
    
    Key differences from ThreadedVideoCapture:
      - Single-slot buffer (always latest frame, no queue buildup)
      - Auto-reconnect with exponential backoff
      - Health monitoring (fps, reconnect count, status)
      - No total_frames / finite video assumptions
    """

    STATUS_CONNECTING = 'CONNECTING'
    STATUS_CONNECTED = 'CONNECTED'
    STATUS_RECONNECTING = 'RECONNECTING'
    STATUS_STOPPED = 'STOPPED'
    STATUS_ERROR = 'ERROR'

    def __init__(self, rtsp_url: str, stream_id: str,
                 reconnect_delay: float = 2.0,
                 max_reconnect_delay: float = 30.0,
                 connection_timeout: float = 10.0):
        """
        Args:
            rtsp_url: Full RTSP URL (e.g., rtsp://192.168.1.100:554/stream)
            stream_id: Unique identifier for this stream
            reconnect_delay: Initial delay between reconnect attempts (seconds)
            max_reconnect_delay: Maximum reconnect delay (exponential backoff cap)
            connection_timeout: Timeout for initial connection (seconds)
        """
        self.rtsp_url = rtsp_url
        self.stream_id = stream_id
        self.reconnect_delay = reconnect_delay
        self.max_reconnect_delay = max_reconnect_delay
        self.connection_timeout = connection_timeout

        # State
        self.status = self.STATUS_CONNECTING
        self.stopped = False
        self._cap = None
        self._thread = None

        # Single-slot frame buffer (always latest)
        self._frame = None
        self._frame_lock = threading.Lock()
        self._new_frame_event = threading.Event()

        # Metrics
        self.fps_actual = 0.0
        self.reconnect_count = 0
        self.last_frame_time = 0.0
        self.width = 0
        self.height = 0
        self.frames_read = 0

    def start(self) -> 'RTSPCapture':
        """Start the capture thread."""
        self.stopped = False
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()
        return self

    def _open_stream(self) -> bool:
        """Attempt to open the RTSP stream with optimized settings."""
        try:
            if self._cap is not None:
                self._cap.release()

            # Pre-process URL to handle unencoded passwords with '@'
            # e.g. rtsp://admin:Faceoff@123@192.168...
            url_to_open = self.rtsp_url
            if "://" in url_to_open:
                scheme, rest = url_to_open.split("://", 1)
                if rest.count("@") > 1:
                    creds, host_path = rest.rsplit("@", 1)
                    if ":" in creds:
                        user, pwd = creds.split(":", 1)
                        import urllib.parse
                        pwd_encoded = urllib.parse.quote(pwd)
                        url_to_open = f"{scheme}://{user}:{pwd_encoded}@{host_path}"

            import os
            
            # V3: Hardware Accelerated Decoding (Phase 26)
            hw_options = ""
                
            if os.environ.get('USE_HW_DECODER', '0') == '1':
                # Force FFmpeg to use NVIDIA's dedicated NVDEC silicon
                if hw_options:
                    hw_options += "|"
                hw_options += "video_codec;h264_cuvid"
                logger.info(f"[{self.stream_id}] Hardware decoding (NVDEC) ENABLED.")
            
            if hw_options:
                os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = hw_options
            elif "OPENCV_FFMPEG_CAPTURE_OPTIONS" in os.environ:
                del os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"]

            # Try FFmpeg first since we configured options above
            cap = cv2.VideoCapture(url_to_open, cv2.CAP_FFMPEG)
            
            if not cap.isOpened():
                # Fallback to GStreamer
                cap = cv2.VideoCapture(url_to_open, cv2.CAP_GSTREAMER)

            if not cap.isOpened():
                # Final fallback: auto backend
                cap = cv2.VideoCapture(url_to_open)

            if not cap.isOpened():
                return False

            # RTSP optimizations
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # Minimal buffer

            self._cap = cap
            self.width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            self.height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            return True

        except Exception as e:
            logger.error(f"[{self.stream_id}] Failed to open stream: {e}")
            return False

    def _capture_loop(self):
        """Main capture thread — reads frames continuously."""
        current_delay = self.reconnect_delay
        fps_counter = 0
        fps_timer = time.time()

        while not self.stopped:
            # Connect / Reconnect
            if self._cap is None or not self._cap.isOpened():
                self.status = self.STATUS_RECONNECTING if self.reconnect_count > 0 else self.STATUS_CONNECTING
                logger.info(f"[{self.stream_id}] Connecting to {self.rtsp_url}...")

                if self._open_stream():
                    self.status = self.STATUS_CONNECTED
                    current_delay = self.reconnect_delay  # Reset backoff
                    logger.info(f"[{self.stream_id}] Connected ({self.width}x{self.height})")
                else:
                    self.reconnect_count += 1
                    logger.warning(
                        f"[{self.stream_id}] Connection failed. "
                        f"Retry #{self.reconnect_count} in {current_delay:.1f}s"
                    )
                    time.sleep(current_delay)
                    current_delay = min(current_delay * 2, self.max_reconnect_delay)
                    continue

            # Read frame
            try:
                ret, frame = self._cap.read()
                if not ret or frame is None:
                    logger.warning(f"[{self.stream_id}] Frame read failed, reconnecting...")
                    self._cap.release()
                    self._cap = None
                    self.reconnect_count += 1
                    time.sleep(self.reconnect_delay)
                    continue

                # Update single-slot buffer (always latest frame)
                with self._frame_lock:
                    self._frame = frame
                    self.last_frame_time = time.time()
                    self.frames_read += 1
                self._new_frame_event.set()

                # FPS calculation
                fps_counter += 1
                elapsed = time.time() - fps_timer
                if elapsed >= 2.0:
                    self.fps_actual = fps_counter / elapsed
                    fps_counter = 0
                    fps_timer = time.time()

            except Exception as e:
                logger.error(f"[{self.stream_id}] Capture error: {e}")
                if self._cap is not None:
                    self._cap.release()
                    self._cap = None
                time.sleep(self.reconnect_delay)

        # Cleanup
        if self._cap is not None:
            self._cap.release()
        self.status = self.STATUS_STOPPED

    def read(self, timeout: float = 1.0) -> Tuple[bool, Optional[np.ndarray]]:
        """
        Get the latest frame. Blocks until a new frame is available or timeout.
        
        Args:
            timeout: Max seconds to wait for a new frame
            
        Returns:
            (success, frame) tuple — frame is always the latest available
        """
        if self.stopped:
            return False, None

        # Wait for a NEW frame to be signaled
        if not self._new_frame_event.wait(timeout=timeout):
            return False, None

        with self._frame_lock:
            if self._frame is None:
                return False, None
            frame = self._frame.copy()
            self._new_frame_event.clear()

        return True, frame

    def get_health(self) -> dict:
        """Return stream health metrics."""
        time_since_frame = time.time() - self.last_frame_time if self.last_frame_time > 0 else -1
        return {
            'stream_id': self.stream_id,
            'status': self.status,
            'rtsp_url': self.rtsp_url,
            'resolution': f"{self.width}x{self.height}",
            'fps_actual': round(self.fps_actual, 1),
            'reconnect_count': self.reconnect_count,
            'frames_read': self.frames_read,
            'seconds_since_last_frame': round(time_since_frame, 1),
            'is_alive': (self.status == self.STATUS_CONNECTED and
                         time_since_frame < 5.0 and
                         time_since_frame >= 0),
        }

    def stop(self):
        """Stop the capture thread."""
        self.stopped = True
        self._new_frame_event.set()  # Unblock any waiting read()
        if self._thread is not None:
            self._thread.join(timeout=5.0)

    def release(self):
        """Alias for stop()."""
        self.stop()
