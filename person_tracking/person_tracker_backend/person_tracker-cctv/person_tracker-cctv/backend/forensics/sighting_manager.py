import os
import subprocess
import collections
from django.conf import settings
from .models_sighting import SuspectSighting
from .threaded_writer import ThreadedVideoWriter

class SightingClipMaker:
    def __init__(self, case, video_path, fps, width, height):
        self.case = case
        self.video_path = video_path
        self.fps = fps
        self.width = width
        self.height = height
        
        # TARGET-CENTRIC STATE
        self.active_session = None # {'start_frame', 'last_seen_frame', 'max_score'}
        
        # 5 Second Cooldown (Wait 5s before cutting the clip)
        self.grace_period_frames = int(5.0 * fps) 
        self.min_clip_duration = int(1.0 * fps) # Ignore < 1s clips
        
        # Buffer to keep pre-event padded frames (2 seconds)
        self.pad_frames = int(2.0 * fps)
        self.frame_buffer = collections.deque(maxlen=self.pad_frames)
        self.writer = None
        self.current_start_sec = 0

    def report_frame(self, is_target_present, current_frame, score, frame=None):
        """
        Called every frame. 
        is_target_present: True if ANY matching person is in the frame.
        """
        if is_target_present:
            if self.active_session is None:
                # START RECORDING
                self.active_session = {
                    'start_frame': current_frame,
                    'last_seen_frame': current_frame,
                    'max_score': score
                }
                start_f = max(0, current_frame - len(self.frame_buffer))
                self.current_start_sec = start_f / self.fps
                
                filename = f"case_{self.case.id}_sight_{int(self.current_start_sec)}s.mp4"
                abs_path = os.path.join(settings.MEDIA_ROOT, 'outputs', 'sightings', filename)
                os.makedirs(os.path.dirname(abs_path), exist_ok=True)
                self.current_abs_path = abs_path
                self.current_filename = filename
                
                self.writer = ThreadedVideoWriter(abs_path, self.fps, (self.width, self.height)).start()
                
                # Flush the entire buffer into the writer
                for bf in self.frame_buffer:
                    self.writer.write(bf)
                self.frame_buffer.clear()
                
                if frame is not None:
                    self.writer.write(frame)
            else:
                # KEEP RECORDING
                self.active_session['last_seen_frame'] = current_frame
                self.active_session['max_score'] = max(
                    self.active_session['max_score'], score
                )
                if frame is not None:
                    self.writer.write(frame)
        else:
            if self.active_session is None:
                # Keep maintaining the pre-event buffer
                if frame is not None:
                    self.frame_buffer.append(frame.copy())
            else:
                # In grace period, keep writing
                if self.writer is not None and frame is not None:
                    self.writer.write(frame)

    def check_for_closures(self, current_frame, force_finish=False):
        """
        Checks if the target has been gone for > 5 seconds.
        """
        if self.active_session is None:
            return

        frames_since_seen = current_frame - self.active_session['last_seen_frame']
        
        # If gone for too long, OR video ended (force_finish)
        if force_finish or (frames_since_seen > self.grace_period_frames):
            self._finalize_clip(current_frame)

    def _finalize_clip(self, current_frame_for_end=0):
        """Internal method to save the file."""
        data = self.active_session
        self.active_session = None # Reset state
        
        if self.writer is not None:
            self.writer.release()
            self.writer = None

        start_f = data['start_frame']
        end_f = data['last_seen_frame']
        
        # Filter noise
        if (end_f - start_f) < self.min_clip_duration:
            if hasattr(self, 'current_abs_path') and os.path.exists(self.current_abs_path):
                try: os.remove(self.current_abs_path)
                except: pass
            return

        end_sec = current_frame_for_end / self.fps if current_frame_for_end > 0 else end_f / self.fps

        # Transcode strictly to H.264 so web browsers can play it
        if hasattr(self, 'current_abs_path') and os.path.exists(self.current_abs_path):
            temp_path = self.current_abs_path.replace('.mp4', '_temp.mp4')
            os.rename(self.current_abs_path, temp_path)
            cmd = (
                f'ffmpeg -i "{temp_path}" '
                f'-c:v libx264 -preset superfast -crf 28 -y "{self.current_abs_path}"'
            )
            try:
                subprocess.run(cmd, shell=True, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                os.remove(temp_path)
            except Exception as e:
                print(f"Transcode error: {e}")
                os.rename(temp_path, self.current_abs_path) # Fallback

        try:
            # Save to DB
            SuspectSighting.objects.create(
                case=self.case,
                track_id=999, # Generic ID for fused track
                start_time=self.current_start_sec,
                end_time=end_sec,
                max_score=data['max_score'],
                clip_file=f"outputs/sightings/{self.current_filename}"
            )
            print(f"Generated Clip: {self.current_start_sec}s - {end_sec}s")
        except Exception as e:
            print(f"Clip Gen Error: {e}")

    def close_all(self, current_frame):
        self.check_for_closures(current_frame, force_finish=True)