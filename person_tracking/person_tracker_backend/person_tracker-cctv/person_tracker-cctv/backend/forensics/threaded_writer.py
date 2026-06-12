import cv2
import time
import threading
import queue
import logging

logger = logging.getLogger(__name__)

class ThreadedVideoWriter:
    """
    Asynchronous video writer using a background thread and a fast queue.
    Prevents cv2.VideoWriter from blocking the main AI inference loop on disk I/O.
    """
    def __init__(self, output_path: str, fps: float, size: tuple, queue_size: int = 512):
        self.output_path = output_path
        self.fps = fps
        self.size = size
        
        # Max queue size of 512 frames ~1-2GB of RAM for 1080p, adjust if needed
        self.Q = queue.Queue(maxsize=queue_size)
        self.stopped = False
        self.thread = threading.Thread(target=self._write_frames, args=(), daemon=True)

    def start(self):
        """Start the background writing thread."""
        self.thread.start()
        return self

    def _write_frames(self):
        """Background thread worker handling all VideoWriter ops to prevent FFmpeg crashes."""
        # Initialize writer strictly inside the thread
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        writer = cv2.VideoWriter(self.output_path, fourcc, self.fps, self.size)
        
        if not writer.isOpened():
            logger.error(f"Failed to open VideoWriter for: {self.output_path}")
            # Empty the queue and exit if we can't write
            while not self.stopped:
                try:
                    self.Q.get_nowait()
                    self.Q.task_done()
                except queue.Empty:
                    time.sleep(0.1)
            return

        while not self.stopped or not self.Q.empty():
            try:
                # 1 second timeout to allow checking `self.stopped` gracefully
                frame = self.Q.get(timeout=1.0)
                writer.write(frame)
                self.Q.task_done()
            except queue.Empty:
                pass
            except Exception as e:
                logger.error(f"ThreadedVideoWriter background error: {e}")
                
        # Release writer strictly inside the thread
        writer.release()
        logger.info(f"ThreadedVideoWriter closed: {self.output_path}")

    def write(self, frame):
        """Put a frame onto the queue for asynchronous writing."""
        if self.stopped:
            return
            
        try:
            # Block very briefly if the queue is utterly full (disk is extremely slow)
            self.Q.put(frame, timeout=5.0)
        except queue.Full:
            logger.warning("ThreadedVideoWriter queue full! Dropping frame to preserve pipeline speed.")

    def release(self):
        """Flush all pending frames and signal the thread to stop."""
        # First: wait for ALL queued frames to be written (drain the queue)
        self.Q.join()
        
        # Then: signal the thread to stop and flush/release the writer internally
        self.stopped = True
        if self.thread.is_alive():
            self.thread.join(timeout=5.0)

    def __enter__(self):
        return self.start()

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()
