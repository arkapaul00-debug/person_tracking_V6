import os
import cv2
import torch
import numpy as np
import subprocess
import logging
from django.conf import settings
from .models import AnalysisLog, ForensicCase
from .models_sighting import SuspectSighting
from .ai_core.query_tracker import UnifiedQueryTracker
from .sighting_manager import SightingClipMaker
from .threaded_capture import ThreadedVideoCapture
from .threaded_writer import ThreadedVideoWriter
from .adaptive_stride import AdaptiveStrideFSM
from .video_splitter import split_video
from tqdm import tqdm

logger = logging.getLogger(__name__)

class DjangoTrackerAdapter(UnifiedQueryTracker):
    def __init__(self, case_id, *args, **kwargs):
        self.case_id = case_id
        # Reload object to ensure freshness
        self.case_obj = ForensicCase.objects.get(id=case_id)
        super().__init__(*args, **kwargs)
        
        # DEBUG: Confirm Augmentation
        if self.ref_data.get('face'):
             logger.info(f"Augmentation Verification: Loaded {len(self.ref_data['face'])} face embeddings (Includes synthetics)")

    def log_to_db(self, message, log_type='info'):
        try:
            AnalysisLog.objects.create(
                case=self.case_obj, message=message, log_type=log_type
            )
        except Exception as e:
            logger.error(f"DB Log Error: {e}")

    def _calculate_iou(self, box1, box2):
        x1, y1, x2, y2 = box1
        x3, y3, x4, y4 = box2
        x_inter1 = max(x1, x3)
        y_inter1 = max(y1, y3)
        x_inter2 = min(x2, x4)
        y_inter2 = min(y2, y4)
        width_inter = max(0, x_inter2 - x_inter1)
        height_inter = max(0, y_inter2 - y_inter1)
        area_inter = width_inter * height_inter
        area_box1 = (x2 - x1) * (y2 - y1)
        area_box2 = (x4 - x3) * (y4 - y3)
        area_union = area_box1 + area_box2 - area_inter
        return area_inter / (area_union + 1e-6)

    def process_video_with_sightings(self, video_path, output_path, use_threading=True, write_debug_video=False):
        # Extend gallery with resolution-matched variants for this specific video
        self.extend_gallery_for_video(video_path)

        # USE Threaded Video Capture for Speed (Main Process) or Standard (Worker Process)
        if use_threading:
            cap = ThreadedVideoCapture(video_path).start()
            fps = cap.fps
            w = cap.width
            h = cap.height
            total_frames = cap.total_frames
        else:
            cap = cv2.VideoCapture(video_path)
            fps = cap.get(cv2.CAP_PROP_FPS)
            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        
        # Initialize Manager
        clip_maker = SightingClipMaker(self.case_obj, video_path, fps, w, h)
        
        # Only write debug video if explicitly requested (saves huge I/O)
        writer = None
        if write_debug_video:
            writer = ThreadedVideoWriter(output_path, fps, (w, h)).start()
        
        frame_counter = 0
        pbar = tqdm(total=total_frames, desc="Forensic Scan")
        
        # PHASE 2: Adaptive Stride FSM (replaces fixed skip_n)
        stride_fsm = AdaptiveStrideFSM(
            dense_skip=self.skip_n,   # Default dense = 4
            sparse_skip=12,           # Scan faster when empty
            reset_skip=1,             # Every frame after scene cut
            empty_patience=8,
            min_dwell_frames=30
        )
        
        # Buffers for state persistence across batches
        last_tracker_input = []
        last_detections = []
        
        try:
            while True:
                # 1. READ BATCH OF FRAMES
                batch_frames = []
                for _ in range(self.batch_size):
                    ret, frame = cap.read()
                    if not ret: 
                        break
                    batch_frames.append(frame)
                
                if not batch_frames: 
                    logger.info(f"Video End Reached (Total Frames Processed: {frame_counter})")
                    break
                
                # 2. DETERMINE INFERENCE FRAMES (Adaptive Stride)
                current_skip = stride_fsm.get_skip_n()
                frames_to_infer = []
                indices_to_infer = []
                
                for i, frame in enumerate(batch_frames):
                    global_id = frame_counter + i + 1
                    if (global_id % current_skip == 0) or (global_id == 1):
                        frames_to_infer.append(frame)
                        indices_to_infer.append(i)
                
                # 3. RUN PARALLEL INFERENCE (YOLO Batch)
                inference_results = {}
                batch_success = False
                
                # Attempt Batch Inference first (Much faster on GPU)
                if frames_to_infer:
                    try:
                        # YOLOv10/v8 supports list of images. 
                        # We use verbose=False to reduce console noise
                        batch_results = self.detector(frames_to_infer, conf=0.3, verbose=False)
                        
                        # Verify we got a list of results
                        if isinstance(batch_results, list) and len(batch_results) == len(frames_to_infer):
                            for idx, res in zip(indices_to_infer, batch_results):
                                inference_results[idx] = res
                            batch_success = True
                    except Exception as e:
                        # If batch fails (e.g. input size mismatch), log once and fallback
                        if frame_counter < 500: # Log only early failures
                             logger.warning(f"Batch inference failed (will retry sequentially): {e}")

                    # Fallback to sequential inference if batch failed
                    if not batch_success:
                         for idx, frame in zip(indices_to_infer, frames_to_infer):
                            try:
                                results = self.detector([frame], conf=0.3, verbose=False)
                                if results:
                                    inference_results[idx] = results[0]
                            except Exception as e:
                                logger.error(f"Inference Error on Frame {idx}: {e}")

                # 4. SEQUENTIAL TRACKING & RE-ID
                for i, frame in enumerate(batch_frames):
                    frame_counter += 1
                    pbar.update(1)
                    
                    tracker_input = []
                    current_detections = []
                    
                    # Check if this frame had inference run
                    if i in inference_results:
                        res = inference_results[i]
                        person_boxes = []
                        if res.boxes:
                            boxes = res.boxes.xyxy.cpu().numpy()
                            confs = res.boxes.conf.cpu().numpy()
                            
                            # Build person box list for face matching
                            for box in boxes:
                                x1, y1, x2, y2 = box.astype(int)
                                person_boxes.append([x1, y1, x2, y2])
                            
                            # MEDIUM FIX: Run InsightFace ONCE on full frame
                            face_map = self._match_faces_to_persons(frame, person_boxes)
                            
                            for j, box in enumerate(boxes):
                                x1, y1, x2, y2 = box.astype(int)
                                tracker_input.append([x1, y1, x2, y2, confs[j], 0])
                                
                                # ReID with pre-extracted face embedding
                                raw_crop = frame[max(0,y1):min(h,y2), max(0,x1):min(w,x2)]
                                
                                # Only run expensive ReID if crop is valid
                                if raw_crop.size > 0:
                                    pre_face_emb = face_map.get(j, None)
                                    
                                    # EARLY EXIT: If face match is strong, skip body ReID
                                    if pre_face_emb is not None:
                                        face_score = self._compute_face_similarity(pre_face_emb)
                                        if face_score > 0.7:
                                            current_detections.append({'bbox': [x1, y1, x2, y2], 'score': face_score})
                                            continue
                                    
                                    sim_score, _ = self._compute_best_similarity(
                                        raw_crop, raw_crop, face_embedding=pre_face_emb)
                                    current_detections.append({'bbox': [x1, y1, x2, y2], 'score': sim_score})
                        
                        # Update buffers
                        last_tracker_input = tracker_input
                        last_detections = current_detections
                        
                        # Update stride FSM with detection count
                        stride_fsm.update(len(person_boxes), frame)
                    else:
                        # USE BUFFERED RESULTS (ByteTrack Kalman Filter logic handles motion)
                        tracker_input = last_tracker_input
                        current_detections = last_detections

                    # 5. UPDATE TRACKER
                    target_present = False
                    max_score = 0.0
                    
                    
                    
                    if len(tracker_input) > 0:
                        tracks = self.tracker.update(np.array(tracker_input), frame)
                        
                        for track in tracks:
                            tx1, ty1, tx2, ty2 = map(int, track[:4])
                            tid = int(track[4])
                            
                            # Match score
                            best_score = 0.0
                            for det in current_detections:
                                if self._calculate_iou([tx1, ty1, tx2, ty2], det['bbox']) > 0.4:
                                    best_score = det['score']
                                    break
                            
                            is_target = self.hysteresis.check_match(tid, best_score, frame_counter)
                            
                            if is_target:
                                target_present = True
                                max_score = max(max_score, best_score)
                                
                                # Visualization (Render on frame so it saves to sighting clip)
                                cv2.rectangle(frame, (tx1, ty1), (tx2, ty2), (0, 255, 0), 2)
                                cv2.putText(frame, f"TARGET {best_score:.2f}", (tx1, ty1-10), 0, 0.6, (0,255,0), 2)

                    # 6. REPORT TO CLIP MAKER
                    clip_maker.report_frame(target_present, frame_counter, max_score, frame=frame)
                    clip_maker.check_for_closures(frame_counter)
                    
                    if writer:
                        writer.write(frame)
                    
                    if frame_counter % 200 == 0:
                         self.log_to_db(f"Scanning... {int(frame_counter/total_frames*100)}%")
                    if frame_counter % 1000 == 0:
                         torch.cuda.empty_cache()
                         logger.info(f"Stride FSM: {stride_fsm.get_stats()}")
        except Exception as e:
            logger.critical(f"CRITICAL LOOP FAILURE: {e}")
            import traceback
            self.log_to_db(f"CRITICAL FAILURE: {e}", log_type="alert")
            print(traceback.format_exc())
            raise e

        # Cleanup
        clip_maker.close_all(frame_counter)
        cap.release()
        if writer:
            writer.release()



def merge_videos(video_paths, output_path):
    """Merges multiple video files into one using ffmpeg."""
    if not video_paths:
        return False
        
    list_file = output_path + ".txt"
    with open(list_file, 'w') as f:
        for path in video_paths:
            f.write(f"file '{path}'\n")
            
    cmd = f"ffmpeg -f concat -safe 0 -i {list_file} -c copy {output_path} -y"
    subprocess.run(cmd, shell=True, check=True)
    os.remove(list_file)
    return True

def run_forensic_pipeline(case_id, video_path, ref_paths, mode, threshold):
    try:
        case = ForensicCase.objects.get(id=case_id)
        case.status = "PROCESSING"
        case.save()

        # 1. SPLIT VIDEO
        AnalysisLog.objects.create(case=case, message="Splitting video into chunks for processing...")
        
        chunk_dir = os.path.join(settings.MEDIA_ROOT, 'temp_chunks', str(case_id))
        chunks = split_video(video_path, chunk_dir, chunk_duration_sec=900)
        
        AnalysisLog.objects.create(case=case, message=f"Created {len(chunks)} chunk(s). Starting inference...")

        # 2. PROCESS CHUNKS SEQUENTIALLY (single GPU — parallel causes CUDA deadlocks)
        processed_chunks = []
        
        for chunk_idx, chunk_path in enumerate(chunks):
            AnalysisLog.objects.create(
                case=case, 
                message=f"Processing chunk {chunk_idx + 1}/{len(chunks)}..."
            )
            
            try:
                tracker = DjangoTrackerAdapter(
                    case_id=case_id, ref_paths=ref_paths, mode=mode,
                    high_threshold=float(threshold),
                    low_threshold=max(0.5, float(threshold) - 0.15),
                    batch_size=32,
                    skip_n=6
                )
                
                output_filename = f"processed_{case_id}_chunk_{chunk_idx:03d}.mp4"
                output_abs_path = os.path.join(
                    settings.MEDIA_ROOT, 'outputs', f'case_{case_id}', output_filename
                )
                os.makedirs(os.path.dirname(output_abs_path), exist_ok=True)
                
                write_debug_video = False  # Enabled for speed optimization
                tracker.process_video_with_sightings(
                    chunk_path, output_abs_path, use_threading=True, write_debug_video=write_debug_video
                )
                
                if write_debug_video:
                    processed_chunks.append(output_abs_path)
                
                AnalysisLog.objects.create(
                    case=case,
                    message=f"Chunk {chunk_idx + 1}/{len(chunks)} complete."
                )
                
                torch.cuda.empty_cache()
                
            except Exception as e:
                logger.error(f"Chunk {chunk_idx} failed: {e}")
                import traceback
                traceback.print_exc()
                AnalysisLog.objects.create(
                    case=case, 
                    message=f"Chunk {chunk_idx + 1} failed: {str(e)}", 
                    log_type="alert"
                )
        
        if write_debug_video and not processed_chunks:
            raise RuntimeError("All chunks failed processing.")
        
        if write_debug_video and len(processed_chunks) != len(chunks):
            AnalysisLog.objects.create(
                case=case, 
                message=f"Warning: {len(chunks) - len(processed_chunks)} chunk(s) failed.", 
                log_type="alert"
            )

        if write_debug_video:
            # 3. MERGE RESULTS
            output_filename = f"processed_{case_id}.mp4"
            output_abs_path = os.path.join(settings.MEDIA_ROOT, 'outputs', output_filename)
            os.makedirs(os.path.dirname(output_abs_path), exist_ok=True)
            
            if len(processed_chunks) == 1:
                import shutil
                shutil.copy2(processed_chunks[0], output_abs_path)
            else:
                AnalysisLog.objects.create(case=case, message="Merging processed chunks...")
                merge_videos(processed_chunks, output_abs_path)

            # 4. TRANSCODE FOR WEB
            AnalysisLog.objects.create(case=case, message="Analysis complete. Transcoding for web...")
            web_ready_path = output_abs_path.replace('.mp4', '_web.mp4')
            cmd = f"ffmpeg -i {output_abs_path} -vcodec libx264 -crf 28 -preset ultrafast {web_ready_path} -y"
            subprocess.run(cmd, shell=True, timeout=3600)

            case.output_video = f"outputs/processed_{case_id}_web.mp4"
        else:
            # Debug video skipped for speed -> use original video for playback
            # Convert absolute path to relative path for Django Media
            try:
                rel_video_path = os.path.relpath(video_path, settings.MEDIA_ROOT)
                case.output_video = rel_video_path
            except ValueError:
                # Fallback if path manipulation fails
                case.output_video = video_path
        case.status = "COMPLETED"
        case.save()
        
        AnalysisLog.objects.create(case=case, message="Pipeline complete!", log_type="success")

    except Exception as e:
        try:
            case = ForensicCase.objects.get(id=case_id)
            case.status = "ERROR"
            case.save()
            AnalysisLog.objects.create(case=case, message=f"Pipeline Error: {str(e)}", log_type="alert")
        except Exception:
            pass
        import traceback
        print(traceback.format_exc())