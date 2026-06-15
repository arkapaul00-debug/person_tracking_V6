import cv2
import torch
import numpy as np
import argparse
import logging
import json
import hashlib
from pathlib import Path
from typing import List, Dict, Any, Tuple
from scipy.spatial.distance import cosine
from tqdm import tqdm

# Imports
from ultralytics import YOLO
from boxmot import BYTETracker

# Relative Imports for Django
from .face_extractor import FaceReIDExtractor
from .body_extractor import BodyReIDExtractor
from .enhanced_preprocessor import DomainAdaptivePreprocessor

# Lazy import for ThreadedVideoWriter (avoid circular import from ai_core)
def _get_threaded_writer():
    from forensics.threaded_writer import ThreadedVideoWriter
    return ThreadedVideoWriter

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class TrackHysteresisManager:
    """
    Manages state for specific Track IDs.
    Implements Identity Latching: Once Confirmed, Stay Confirmed.
    """
    def __init__(self, high_thresh: float, low_thresh: float):
        self.high_thresh = high_thresh
        self.low_thresh = low_thresh
        self.track_states = {}

    def check_match(self, track_id: int, similarity: float, frame_id: int) -> bool:
        if track_id == -1:
            return similarity >= self.high_thresh

        if track_id not in self.track_states:
            self.track_states[track_id] = {'confirmed': False}

        state = self.track_states[track_id]
        
        if state['confirmed']:
            return True
            
        if similarity >= self.high_thresh:
            state['confirmed'] = True
            return True
        
        return False

class UnifiedQueryTracker:
    def __init__(self, 
                 ref_paths: List[str], 
                 mode: str = 'hybrid', 
                 high_threshold: float = 0.75, 
                 low_threshold: float = 0.60,
                 device: str = 'cuda:0',
                 skip_n: int = 4,
                 batch_size: int = 8): 
        
        self.mode = mode
        self.device = device
        self.skip_n = skip_n
        self.batch_size = batch_size # OPTIMIZATION: Configurable batch size
        
        # 0. Setup Absolute Paths
        base_dir = Path(__file__).resolve().parent 
        weights_dir = base_dir / 'weights'
        
        self.hysteresis = TrackHysteresisManager(high_threshold, low_threshold)
        
        logger.info(f"Initializing Unified Tracker (Mode: {mode}, Skip: {skip_n}, Batch: {self.batch_size})")

        # 1. Load Detection (YOLOv10s) - Lightweight, ~5x faster than v10x for person detection
        yolo_engine = weights_dir / 'yolov10s.engine'
        yolo_pt = weights_dir / 'yolov10s.pt'
        
        if yolo_engine.exists():
            logger.info(f"Loading TensorRT Engine: {yolo_engine}")
            self.detector = YOLO(str(yolo_engine), task='detect')
        else:
            logger.info(f"Loading PyTorch Model: {yolo_pt}")
            self.detector = YOLO(str(yolo_pt))
        self.tracker = BYTETracker(track_thresh=0.3, track_buffer=100, frame_rate=30)
        
        # 2. Load Feature Extractors
        self.face_model = None
        self.body_model = None
        
        if mode in ['face', 'hybrid']:
            self.face_model = FaceReIDExtractor(device=device)
        if mode in ['body', 'hybrid']:
            self.body_model = BodyReIDExtractor(device=device)
            
        # 3. Process Reference Gallery
        self.ref_data = self._process_reference_gallery(ref_paths)

    def _process_reference_gallery(self, paths: List[str]) -> Dict[str, List]:
        data = {'face': [], 'body': []}
        
        if self.face_model:
            try:
                data['face'] = self.face_model.extract_gallery_embeddings(paths)
                logger.info(f"Face Gallery Size: {len(data['face'])}")
            except Exception as e:
                logger.warning(f"Face gallery extraction issue: {e}")

        if self.body_model:
            for p in paths:
                img = cv2.imread(p)
                if img is None: continue
                
                # For body ref, we run simple detection
                results = self.detector(img, conf=0.4, classes=[0], verbose=False)
                if results[0].boxes:
                    boxes = results[0].boxes.xyxy.cpu().numpy()
                    best_box = max(boxes, key=lambda b: (b[2]-b[0])*(b[3]-b[1]))
                    x1, y1, x2, y2 = best_box.astype(int)
                    person_crop = img[y1:y2, x1:x2]
                    person_crop = DomainAdaptivePreprocessor.normalize_to_lab(person_crop)
                    
                    emb = self.body_model.extract_body_embedding(person_crop)
                    if emb is not None:
                        data['body'].append({'path': p, 'embedding': emb})
        return data

    def _compute_face_similarity(self, face_embedding: np.ndarray) -> float:
        """Quick face-only similarity check using pre-extracted embedding.
        No model calls — just cosine comparison against gallery."""
        if face_embedding is None or not self.ref_data.get('face'):
            return 0.0
        best_sim = 0.0
        for ref in self.ref_data['face']:
            # Defensive 1D ensure
            u = np.asarray(ref['embedding']).reshape(-1)
            v = np.asarray(face_embedding).reshape(-1)
            sim = 1.0 - cosine(u, v)
            if sim > best_sim:
                best_sim = sim
        return best_sim

    def _compute_best_similarity(self, raw_crop: np.ndarray, enhanced_crop: np.ndarray, 
                                   face_embedding: np.ndarray = None) -> Tuple[float, Dict]:
        """
        Computes similarity. If face_embedding is provided (from single-pass extraction),
        uses it directly instead of running InsightFace again per-crop.
        """
        scores = {'face': 0.0, 'body': 0.0, 'best_ref': 'None'}
        
        if self.face_model and self.ref_data['face']:
            # Use pre-extracted embedding if available (medium fix), else fallback to per-crop
            face_emb = face_embedding
            if face_emb is None:
                face_emb, _ = self.face_model.extract_face_embedding(raw_crop)
            
            if face_emb is not None:
                best_sim = 0.0
                for ref in self.ref_data['face']:
                    # Defensive 1D ensure
                    u = np.asarray(ref['embedding']).reshape(-1)
                    v = np.asarray(face_emb).reshape(-1)
                    sim = 1.0 - cosine(u, v)
                    if sim > best_sim:
                        best_sim = sim
                        scores['best_ref'] = Path(ref['path']).name
                scores['face'] = best_sim
        
        if self.body_model and self.ref_data['body']:
            body_emb = self.body_model.extract_body_embedding(enhanced_crop)
            if body_emb is not None:
                best_sim = 0.0
                for ref in self.ref_data['body']:
                    # Defensive 1D ensure
                    u = np.asarray(ref['embedding']).reshape(-1)
                    v = np.asarray(body_emb).reshape(-1)
                    sim = 1.0 - cosine(u, v)
                    if sim > best_sim:
                        best_sim = sim
                        if scores['face'] == 0:
                            scores['best_ref'] = Path(ref['path']).name
                scores['body'] = best_sim
        
        final_score = 0.0
        if self.mode == 'face': final_score = scores['face']
        elif self.mode == 'body': final_score = scores['body']
        elif self.mode == 'hybrid':
            if scores['face'] > 0:
                final_score = (0.7 * scores['face']) + (0.3 * scores['body'])
            else:
                final_score = scores['body']
                
        return final_score, scores

    @staticmethod
    def _is_face_inside_person(face_bbox, person_bbox):
        """Check if face bbox center is inside person bbox."""
        fx_center = (face_bbox[0] + face_bbox[2]) / 2
        fy_center = (face_bbox[1] + face_bbox[3]) / 2
        return (person_bbox[0] <= fx_center <= person_bbox[2] and 
                person_bbox[1] <= fy_center <= person_bbox[3])

    def _match_faces_to_persons(self, frame: np.ndarray, person_boxes: list) -> Dict[int, np.ndarray]:
        """
        Run InsightFace ONCE on the full frame, then match each detected face
        to the nearest YOLO person box by containment.
        Returns: {person_index: face_embedding}
        """
        face_map = {}
        if not self.face_model or not person_boxes:
            return face_map
        
        all_faces = self.face_model.extract_all_face_embeddings(frame)
        if not all_faces:
            return face_map
        
        for fi, face in enumerate(all_faces):
            fbbox = face['bbox']
            for pi, pbox in enumerate(person_boxes):
                if pi not in face_map and self._is_face_inside_person(fbbox, pbox):
                    face_map[pi] = face['embedding']
                    break
        
        return face_map

    def _estimate_face_resolution(self, video_path: str, sample_frames: int = 10) -> int:
        """
        Pre-scans video to estimate average face/person width.
        Returns estimated face crop width in pixels.
        """
        cap = cv2.VideoCapture(video_path)
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        step = max(1, total // sample_frames)
        
        widths = []
        for i in range(0, min(total, sample_frames * step), step):
            cap.set(cv2.CAP_PROP_POS_FRAMES, i)
            ret, frame = cap.read()
            if not ret:
                break
            
            results = self.detector(frame, conf=0.35, classes=[0], verbose=False)
            if results[0].boxes:
                boxes = results[0].boxes.xyxy.cpu().numpy()
                for box in boxes:
                    widths.append(int(box[2] - box[0]))
        cap.release()
        
        if not widths:
            return 0
        
        avg_person_w = int(np.median(widths))
        # Face is roughly 25-30% of person crop width
        est_face_w = max(15, int(avg_person_w * 0.27))
        logger.info(f"Video resolution scan: avg person={avg_person_w}px, est face={est_face_w}px")
        return est_face_w

    def extend_gallery_for_video(self, video_path: str):
        """
        Called at start of process_video(). Extends gallery with
        resolution-matched variants specific to this video.
        """
        target_face_w = self._estimate_face_resolution(video_path)
        if target_face_w <= 0:
            logger.warning("Could not estimate face resolution; skipping res-match augmentation")
            return
        
        if self.face_model and self.ref_data['face']:
            # Get unique ref paths
            ref_paths = list(set(r['path'] for r in self.ref_data['face']))
            new_count = 0
            for path in ref_paths:
                img = cv2.imread(path)
                if img is None:
                    continue
                res_variants = self.face_model._generate_resolution_matched(img, target_face_w)
                for variant in res_variants:
                    emb, meta = self.face_model.extract_face_embedding(variant)
                    if emb is not None:
                        self.ref_data['face'].append({
                            'path': path, 'embedding': emb,
                            'meta': meta, 'variant': f'res_match_{target_face_w}px'
                        })
                        new_count += 1
            logger.info(f"Extended gallery with {new_count} resolution-matched embeddings (target: {target_face_w}px)")

    def process_video(self, video_path: str, output_path: str):
        # Extend gallery with resolution-matched variants for this specific video
        self.extend_gallery_for_video(video_path)

        cap = cv2.VideoCapture(video_path)
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        
        try:
            ThreadedVideoWriter = _get_threaded_writer()
            writer = ThreadedVideoWriter(output_path, fps, (w, h)).start()
        except Exception:
            # Fallback to synchronous writer if import fails (e.g. standalone CLI use)
            writer = cv2.VideoWriter(output_path, cv2.VideoWriter_fourcc(*'mp4v'), fps, (w, h))
        
        csv_path = str(Path(output_path).with_suffix('.csv'))
        import csv
        f_csv = open(csv_path, 'w', newline='')
        csv_writer = csv.writer(f_csv)
        csv_writer.writerow(['Frame', 'Track_ID', 'Final_Score', 'Face_Score', 'Body_Score', 'Match_Status'])

        pbar = tqdm(total=min(total_frames, 1000), desc="Batch Tracking")
        
        # Buffers for state persistence across batches
        last_tracker_input = []
        last_detections = []
        
        frame_counter = 0
        
        while cap.isOpened():
            # 1. READ BATCH OF FRAMES
            batch_frames = []
            for _ in range(self.batch_size):
                ret, frame = cap.read()
                if not ret: break
                batch_frames.append(frame)
            
            if not batch_frames: break
            
            # 2. DETERMINE WHICH FRAMES IN BATCH NEED INFERENCE
            # We filter the batch to run YOLO only on specific frames (based on skip_n)
            frames_to_infer = []
            indices_to_infer = []
            
            for i, frame in enumerate(batch_frames):
                global_id = frame_counter + i + 1
                if (global_id % self.skip_n == 0) or (global_id == 1):
                    frames_to_infer.append(frame)
                    indices_to_infer.append(i)
            
            # 3. RUN PARALLEL INFERENCE (YOLO)
            # This is where the A5000 shines: processing multiple frames at once
            inference_results = {} # Map index -> result
            if frames_to_infer:
                # YOLOv10 supports list of images for batch inference
                batch_results = self.detector(frames_to_infer, conf=0.35, classes=[0], verbose=False)
                for idx, res in zip(indices_to_infer, batch_results):
                    inference_results[idx] = res

            # 4. PROCESS EACH FRAME SEQUENTIALLY (Tracking logic is sequential)
            for i, frame in enumerate(batch_frames):
                frame_counter += 1
                pbar.update(1)
                
                tracker_input = []
                current_detections = []
                annotated_frame = frame.copy()
                
                # Check if this frame had inference run
                if i in inference_results:
                    res = inference_results[i]
                    if res.boxes:
                        boxes = res.boxes.xyxy.cpu().numpy()
                        confs = res.boxes.conf.cpu().numpy()
                        
                        # Build person box list for face matching
                        person_boxes = []
                        for box in boxes:
                            x1, y1, x2, y2 = box.astype(int)
                            person_boxes.append([x1, y1, x2, y2])
                        
                        # MEDIUM FIX: Run InsightFace ONCE on full frame
                        face_map = self._match_faces_to_persons(frame, person_boxes)
                        
                        for j, box in enumerate(boxes):
                            x1, y1, x2, y2 = box.astype(int)
                            tracker_input.append([x1, y1, x2, y2, confs[j], 0])
                            
                            # Sequential ReID with pre-extracted face embedding
                            raw_crop = frame[max(0,y1):min(h,y2), max(0,x1):min(w,x2)]
                            enhanced_crop = DomainAdaptivePreprocessor.normalize_to_lab(raw_crop.copy())
                            
                            # Use pre-extracted face embedding if available
                            pre_face_emb = face_map.get(j, None)
                            sim_score, breakdown = self._compute_best_similarity(
                                raw_crop, enhanced_crop, face_embedding=pre_face_emb)
                            
                            current_detections.append({
                                'bbox': [x1, y1, x2, y2],
                                'score': sim_score,
                                'details': breakdown
                            })
                    
                    # Update buffers
                    last_tracker_input = tracker_input
                    last_detections = current_detections
                else:
                    # USE BUFFERED RESULTS (ByteTrack Kalman Filter handles motion)
                    tracker_input = last_tracker_input
                    current_detections = last_detections

                # 5. UPDATE TRACKER
                if len(tracker_input) > 0:
                    tracks = self.tracker.update(np.array(tracker_input), frame)
                    
                    for track in tracks:
                        tx1, ty1, tx2, ty2 = map(int, track[:4])
                        tid = int(track[4])
                        
                        best_match_score = 0.0
                        match_details = {}
                        
                        for det in current_detections:
                            dx1, dy1, dx2, dy2 = det['bbox']
                            if self._calculate_iou([tx1, ty1, tx2, ty2], [dx1, dy1, dx2, dy2]) > 0.5:
                                best_match_score = det['score']
                                match_details = det['details']
                                break
                        
                        is_target = self.hysteresis.check_match(tid, best_match_score, frame_counter)
                        status = "CONFIRMED" if is_target else "Scanning"
                        
                        csv_writer.writerow([frame_counter, tid, f"{best_match_score:.4f}", 
                                           f"{match_details.get('face',0):.4f}", f"{match_details.get('body',0):.4f}", status])
                        
                        if is_target:
                            color = (0, 255, 0)
                            label = f"ID:{tid} {best_match_score:.2f}"
                            cv2.rectangle(annotated_frame, (tx1, ty1), (tx2, ty2), color, 2)
                            cv2.putText(annotated_frame, label, (tx1, ty1-10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
                        else:
                            cv2.rectangle(annotated_frame, (tx1, ty1), (tx2, ty2), (100, 100, 100), 1)

                writer.write(annotated_frame)
            
            if frame_counter % 50 == 0: torch.cuda.empty_cache()
            
        cap.release()
        writer.release()
        f_csv.close()
        logger.info(f"Processing complete. Output: {output_path}")
        return self.hysteresis.track_states

    def _calculate_iou(self, boxA, boxB):
        xA = max(boxA[0], boxB[0])
        yA = max(boxA[1], boxB[1])
        xB = min(boxA[2], boxB[2])
        yB = min(boxA[3], boxB[3])
        interArea = max(0, xB - xA) * max(0, yB - yA)
        boxAArea = (boxA[2] - boxA[0]) * (boxA[3] - boxA[1])
        boxBArea = (boxB[2] - boxB[0]) * (boxB[3] - boxB[1])
        return interArea / float(boxAArea + boxBArea - interArea + 1e-6)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--ref", required=True)
    parser.add_argument("--video", required=True)
    parser.add_argument("--mode", default="hybrid")
    parser.add_argument("--high_thresh", type=float, default=0.75)
    parser.add_argument("--low_thresh", type=float, default=0.60)
    parser.add_argument("--skip_n", type=int, default=2)

    args = parser.parse_args()
    ref_list = [p.strip() for p in args.ref.split(',')]
    
    tracker = UnifiedQueryTracker(ref_list, args.mode, args.high_thresh, args.low_thresh, skip_n=args.skip_n)
    tracker.process_video(args.video, "output/unified_gallery_output.mp4")