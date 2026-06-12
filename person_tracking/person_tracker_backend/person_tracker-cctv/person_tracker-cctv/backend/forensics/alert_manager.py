"""
Real-Time Alert Manager — Detection alerts + evidence clip recording.

Replaces SightingClipMaker for live RTSP streams:
  - Instant alert emission on target detection
  - Evidence clip recording with pre-buffer
  - Alert deduplication (no flooding when target is continuously visible)
  - Thumbnail capture on first detection
"""
import os
import cv2
import time
import collections
import logging
import subprocess
import numpy as np
from typing import Optional, Callable
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


class AlertManager:
    """
    Manages real-time alerts and evidence clips for a single RTSP stream.
    One instance per StreamProcessor.
    """

    def __init__(self, session, stream, fps: float, width: int, height: int,
                 alert_callback: Optional[Callable] = None):
        """
        Args:
            session: LiveTrackingSession ORM object
            stream: CCTVStream ORM object
            fps: Stream FPS for clip timing
            width: Frame width
            height: Frame height
            alert_callback: Optional function(alert_dict) for real-time push
        """
        self.session = session
        self.stream = stream
        self.fps = max(fps, 1.0)
        self.width = width
        self.height = height
        self.alert_callback = alert_callback

        # Clip recording state
        self.active_clip = None  # {'start_frame', 'last_seen_frame', 'max_score', 'writer', ...}
        
        # "Unlimited" grace period: keep clip open as long as the person is potentially around
        # We'll set it to a massive value (e.g. 24 hours of 30fps)
        self.grace_period_frames = int(86400 * self.fps) 
        self.min_clip_frames = int(1.0 * self.fps)       # Min 1-second clips
        self.pad_frames = int(3.0 * self.fps)            # 3-second pre-buffer
        self.frame_buffer = collections.deque(maxlen=self.pad_frames)

        # Alert deduplication
        self.last_alert_time = 0.0
        self.min_alert_interval = 60.0  # One alert per minute per person
        self.alert_count = 0
        self.frame_counter = 0

    def report_frame(self, is_target_present: bool, score: float,
                     frame: Optional[np.ndarray] = None,
                     target_bbox: Optional[list] = None,
                     track_id: int = -1):
        """
        Called every processed frame by StreamProcessor.

        Args:
            is_target_present: True if target detected in this frame
            score: Confidence score
            frame: BGR frame for clip writing
            target_bbox: [x1,y1,x2,y2] of target for thumbnail
        """
        self.frame_counter += 1

        if is_target_present:
            if self.active_clip is None:
                # --- START NEW CLIP ---
                self._start_clip(score, frame, target_bbox)
            else:
                # --- CONTINUE CLIP ---
                self.active_clip['last_seen_frame'] = self.frame_counter
                self.active_clip['max_score'] = max(self.active_clip['max_score'], score)
                if frame is not None and self.active_clip.get('writer'):
                    self.active_clip['writer'].write(frame)

            # --- EMIT ALERT (deduplicated) ---
            now = time.time()
            if now - self.last_alert_time >= self.min_alert_interval:
                self._emit_alert(score, frame, target_bbox, track_id)
                self.last_alert_time = now
        else:
            if self.active_clip is None:
                # Keep pre-buffer rolling
                if frame is not None:
                    self.frame_buffer.append(frame.copy())
            else:
                # Continue writing during grace period
                if frame is not None and self.active_clip.get('writer'):
                    self.active_clip['writer'].write(frame)

    def check_for_closures(self, force_finish: bool = False):
        """Check if active clip should be finalized."""
        if self.active_clip is None:
            return

        frames_since_seen = self.frame_counter - self.active_clip['last_seen_frame']
        if force_finish or frames_since_seen > self.grace_period_frames:
            self._finalize_clip()

    def _start_clip(self, score: float, frame: Optional[np.ndarray],
                    target_bbox: Optional[list]):
        """Start recording a new evidence clip."""
        from .threaded_writer import ThreadedVideoWriter

        start_f = max(0, self.frame_counter - len(self.frame_buffer))
        start_sec = start_f / self.fps
        timestamp_str = time.strftime('%Y%m%d_%H%M%S')

        filename = f"live_{self.session.id}_{self.stream.id}_{timestamp_str}.mp4"
        abs_path = os.path.join(settings.MEDIA_ROOT, 'outputs', 'live_alerts', 'clips', filename)
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)

        try:
            writer = ThreadedVideoWriter(abs_path, self.fps, (self.width, self.height)).start()
        except Exception as e:
            logger.error(f"Failed to start clip writer: {e}")
            writer = None

        self.active_clip = {
            'start_frame': self.frame_counter,
            'last_seen_frame': self.frame_counter,
            'max_score': score,
            'writer': writer,
            'abs_path': abs_path,
            'filename': filename,
            'start_sec': start_sec,
        }

        # Flush pre-buffer into the writer
        if writer:
            for bf in self.frame_buffer:
                writer.write(bf)
            self.frame_buffer.clear()
            if frame is not None:
                writer.write(frame)

        logger.info(f"[{self.stream.name}] Clip recording started")

    def _finalize_clip(self):
        """Finalize the current clip — save to DB."""
        clip = self.active_clip
        self.active_clip = None

        if clip is None:
            return

        # Release writer
        if clip.get('writer'):
            try:
                clip['writer'].release()
            except Exception as e:
                logger.error(f"Writer release error: {e}")

        # Check minimum duration
        clip_frames = clip['last_seen_frame'] - clip['start_frame']
        if clip_frames < self.min_clip_frames:
            # Too short, delete
            try:
                if os.path.exists(clip['abs_path']):
                    os.remove(clip['abs_path'])
            except Exception:
                pass
            return

        # Transcode to H.264 for web playback
        self._transcode_clip(clip['abs_path'])

        # Update the most recent alert with the clip path
        try:
            from .models_stream import LiveAlert
            latest_alert = LiveAlert.objects.filter(
                session=self.session,
                stream=self.stream
            ).order_by('-timestamp').first()

            if latest_alert and not latest_alert.clip_file:
                rel_path = f"outputs/live_alerts/clips/{clip['filename']}"
                latest_alert.clip_file = rel_path
                latest_alert.save(update_fields=['clip_file'])
                logger.info(f"[{self.stream.name}] Clip saved: {clip['filename']}")
        except Exception as e:
            logger.error(f"Clip DB save error: {e}")

    def _emit_alert(self, score: float, frame: Optional[np.ndarray],
                    target_bbox: Optional[list], track_id: int = -1):
        """Create a LiveAlert in the database with optional thumbnail."""
        thumb_path = None

        # Save thumbnail crop
        if frame is not None and target_bbox is not None:
            try:
                x1, y1, x2, y2 = [int(v) for v in target_bbox]
                h, w = frame.shape[:2]
                x1, y1 = max(0, x1), max(0, y1)
                x2, y2 = min(w, x2), min(h, y2)
                crop = frame[y1:y2, x1:x2]

                if crop.size > 0:
                    timestamp_str = time.strftime('%Y%m%d_%H%M%S')
                    thumb_filename = f"thumb_{self.session.id}_{timestamp_str}.jpg"
                    thumb_abs = os.path.join(
                        settings.MEDIA_ROOT, 'outputs', 'live_alerts', 'thumbs', thumb_filename
                    )
                    os.makedirs(os.path.dirname(thumb_abs), exist_ok=True)
                    cv2.imwrite(thumb_abs, crop)
                    thumb_path = f"outputs/live_alerts/thumbs/{thumb_filename}"
            except Exception as e:
                logger.error(f"Thumbnail save error: {e}")

        # Save to DB
        try:
            from .models_stream import LiveAlert
            alert = LiveAlert.objects.create(
                session=self.session,
                stream=self.stream,
                frame_number=self.frame_counter,
                confidence=round(score, 3),
                track_id=track_id,
                thumbnail=thumb_path,
            )
            self.alert_count += 1

            # Push via callback if registered
            if self.alert_callback:
                alert_data = {
                    'id': str(alert.id),
                    'stream_name': self.stream.name,
                    'stream_id': str(self.stream.id),
                    'confidence': round(score, 3),
                    'track_id': track_id,
                    'frame_number': self.frame_counter,
                    'timestamp': alert.timestamp.isoformat(),
                    'thumbnail_url': alert.thumbnail.url if alert.thumbnail else None,
                }
                try:
                    self.alert_callback(alert_data)
                except Exception as e:
                    logger.error(f"Alert callback error: {e}")

        except Exception as e:
            logger.error(f"Alert DB save error: {e}")

    def _transcode_clip(self, path: str):
        """Transcode mp4v to H.264 for browser playback."""
        if not os.path.exists(path):
            return
        temp_path = path.replace('.mp4', '_temp.mp4')
        os.rename(path, temp_path)
        cmd = (
            f'ffmpeg -i "{temp_path}" '
            f'-c:v libx264 -preset superfast -crf 28 -y "{path}"'
        )
        try:
            subprocess.run(cmd, shell=True, check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=60)
            os.remove(temp_path)
        except Exception as e:
            logger.error(f"Transcode error: {e}")
            if os.path.exists(temp_path):
                os.rename(temp_path, path)

    def close(self):
        """Finalize any active clip."""
        self.check_for_closures(force_finish=True)
