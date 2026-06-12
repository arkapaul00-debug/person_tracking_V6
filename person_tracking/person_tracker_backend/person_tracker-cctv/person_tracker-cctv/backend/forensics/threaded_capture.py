import cv2
import threading
import queue
import time
import logging

logger = logging.getLogger(__name__)

class ThreadedVideoCapture:
    def __init__(self, src, queue_size=128):
        self.src = src
        self.cap = cv2.VideoCapture(src)
        if not self.cap.isOpened():
            raise ValueError(f"Could not open video source: {src}")
            
        self.q = queue.Queue(maxsize=queue_size)
        self.stopped = False
        self.thread = None
        
        # Properties (Using integer constants for compatibility)
        self.width = int(self.cap.get(3))  # cv2.CAP_PROP_FRAME_WIDTH
        self.height = int(self.cap.get(4)) # cv2.CAP_PROP_FRAME_HEIGHT
        self.fps = self.cap.get(5)         # cv2.CAP_PROP_FPS
        self.total_frames = int(self.cap.get(7)) # cv2.CAP_PROP_FRAME_COUNT

    def start(self):
        self.thread = threading.Thread(target=self._update, args=())
        self.thread.daemon = True
        self.thread.start()
        return self

    def _update(self):
        while not self.stopped:
            if not self.q.full():
                ret, frame = self.cap.read()
                if not ret:
                    self.stopped = True
                    self.q.put(None) # Sentinel
                    break
                self.q.put(frame)
            else:
                time.sleep(0.01) # Avoid busy wait
        self.cap.release()

    def read(self):
        # Return (ret, frame) format to match cv2
        # Block until frame available or sentinel
        try:
            frame = self.q.get(timeout=5.0) # 5s timeout just in case of dead thread
        except queue.Empty:
            return False, None

        if frame is None: # Sentinel
            return False, None
            
        return True, frame

    def stop(self):
        self.stopped = True
        if self.thread:
            self.thread.join()
            
    def release(self):
        self.stop()
