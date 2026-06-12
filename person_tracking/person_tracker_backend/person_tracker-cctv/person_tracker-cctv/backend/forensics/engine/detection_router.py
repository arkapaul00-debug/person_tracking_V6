"""
Detection Router — Adaptive Hierarchical Dual-Detector with Scene-Aware Routing.

Architecture:
    Primary:   YOLOv11 TensorRT FP16/INT8 — runs on EVERY inference frame (~2ms)
    Secondary: RT-DETR (Transformer) — runs ONLY on difficult scenes (~8ms)

Routing Logic (DO NOT run both on every frame):
    1. YOLO runs first (always). If all detections > 0.5 confidence → done.
    2. RT-DETR triggers ONLY when:
       - Any YOLO detection < confidence_floor (0.35) → low-confidence rescue
       - Scene density > density_threshold (15+ persons) → crowded scene
       - Heavy occlusion detected → overlapping bboxes > 40%
       - Explicit forensic mode → maximum recall required
    3. RT-DETR cooldown: at most once every N inference frames (budget control)
    4. Results are merged via IoU-based NMS to eliminate duplicates

Performance:
    - 90% of frames: YOLO only (~2ms per frame)
    - 10% of frames: YOLO + RT-DETR (~10ms per frame)
    - Average: ~2.8ms per frame (vs 10ms if both ran every frame)
"""
import time
import logging
import numpy as np
from typing import List, Dict, Optional, Tuple, Any
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class Detection:
    """Unified detection result from any detector."""
    bbox: List[int]             # [x1, y1, x2, y2]
    confidence: float           # 0.0 - 1.0
    class_id: int = 0           # 0 = person
    source: str = 'yolo'        # 'yolo' or 'rtdetr'
    area: float = 0.0           # bbox area in pixels


@dataclass
class SceneContext:
    """Scene-level analysis for routing decisions."""
    person_count: int = 0
    avg_confidence: float = 0.0
    min_confidence: float = 1.0
    occlusion_ratio: float = 0.0    # Fraction of overlapping bboxes
    density_zone: str = 'normal'    # 'sparse', 'normal', 'dense', 'crowded'
    brightness: float = 128.0       # Average luminance (0-255)
    needs_rtdetr: bool = False
    rtdetr_reason: str = ''


class DetectionRouter:
    """
    Adaptive dual-detector with confidence-aware routing.

    Uses YOLO as the fast primary detector and RT-DETR as the
    high-accuracy fallback for challenging scenes.

    Usage:
        router = DetectionRouter(model_pool, device='cuda:0')

        # Per-frame detection with automatic routing
        detections, context = router.detect(frame)

        # Force high-recall mode (forensic analysis)
        detections, context = router.detect(frame, force_rtdetr=True)
    """

    def __init__(self, model_pool, device: str = 'cuda:0',
                 confidence_floor: float = 0.35,
                 density_threshold: int = 15,
                 occlusion_threshold: float = 0.40,
                 rtdetr_cooldown: int = 5,
                 rtdetr_enabled: bool = True):
        """
        Args:
            model_pool: Shared ModelPool instance with YOLO detector.
            device: CUDA device.
            confidence_floor: Detections below this trigger RT-DETR rescue.
            density_threshold: Person count that triggers RT-DETR for crowded scenes.
            occlusion_threshold: IoU overlap ratio that indicates heavy occlusion.
            rtdetr_cooldown: Minimum frames between RT-DETR activations.
            rtdetr_enabled: Set False to disable RT-DETR entirely (YOLO-only mode).
        """
        self.model_pool = model_pool
        self.device = device
        self.confidence_floor = confidence_floor
        self.density_threshold = density_threshold
        self.occlusion_threshold = occlusion_threshold
        self.rtdetr_cooldown_max = rtdetr_cooldown
        self.rtdetr_enabled = rtdetr_enabled

        # RT-DETR model (lazy loaded — not all deployments have it)
        self._rtdetr_model = None
        self._rtdetr_available = False

        # Cooldown counter (decrements each call, RT-DETR only fires when <= 0)
        self._cooldown_counter = 0

        # Metrics
        self._total_frames = 0
        self._yolo_only_frames = 0
        self._rtdetr_frames = 0
        self._total_detections = 0

        logger.info(
            f"DetectionRouter initialized: floor={confidence_floor}, "
            f"density_thresh={density_threshold}, cooldown={rtdetr_cooldown}, "
            f"rtdetr_enabled={rtdetr_enabled}"
        )

    def _lazy_load_rtdetr(self):
        """Load RT-DETR model on first use (saves startup time + VRAM if unused)."""
        if self._rtdetr_model is not None:
            return

        try:
            from ultralytics import RTDETR
            from pathlib import Path

            weights_dir = Path(__file__).resolve().parent.parent / 'ai_core' / 'weights'

            # Try TensorRT engine first, then ONNX, then PyTorch
            engine_path = weights_dir / 'rtdetr-l.engine'
            onnx_path = weights_dir / 'rtdetr-l.onnx'
            pt_path = weights_dir / 'rtdetr-l.pt'

            if engine_path.exists():
                self._rtdetr_model = RTDETR(str(engine_path))
                logger.info(f"RT-DETR loaded (TensorRT): {engine_path}")
            elif onnx_path.exists():
                self._rtdetr_model = RTDETR(str(onnx_path))
                logger.info(f"RT-DETR loaded (ONNX): {onnx_path}")
            elif pt_path.exists():
                self._rtdetr_model = RTDETR(str(pt_path))
                logger.info(f"RT-DETR loaded (PyTorch): {pt_path}")
            else:
                logger.warning("RT-DETR weights not found — operating in YOLO-only mode")
                self._rtdetr_available = False
                return

            self._rtdetr_available = True

        except ImportError:
            logger.warning("RT-DETR not available (ultralytics version too old?) — YOLO-only mode")
            self._rtdetr_available = False
        except Exception as e:
            logger.error(f"RT-DETR load failed: {e}")
            self._rtdetr_available = False

    def detect(self, frame: np.ndarray,
               conf: float = 0.3,
               force_rtdetr: bool = False,
               scene_hint: Optional[Dict] = None) -> Tuple[List[Detection], SceneContext]:
        """
        Run detection with adaptive routing.

        Args:
            frame: BGR numpy array.
            conf: Base confidence threshold for YOLO.
            force_rtdetr: Force RT-DETR activation (forensic mode).
            scene_hint: Optional external scene information (e.g., from motion detector).

        Returns:
            Tuple of (detections list, scene context).
        """
        self._total_frames += 1
        self._cooldown_counter = max(0, self._cooldown_counter - 1)

        # --- Step 1: ALWAYS run YOLO (primary, fast) ---
        yolo_results = self.model_pool.detect_persons(frame, conf=conf)
        yolo_detections = self._parse_yolo_results(yolo_results, frame.shape)

        # --- Step 2: Analyze scene ---
        context = self._analyze_scene(yolo_detections, frame, scene_hint)

        # --- Step 3: Decide if RT-DETR is needed ---
        if force_rtdetr:
            context.needs_rtdetr = True
            context.rtdetr_reason = 'forced_forensic_mode'

        if not context.needs_rtdetr or not self.rtdetr_enabled:
            # YOLO-only path (90% of frames)
            self._yolo_only_frames += 1
            self._total_detections += len(yolo_detections)
            return yolo_detections, context

        # --- Step 4: RT-DETR activation (cooldown check) ---
        if self._cooldown_counter > 0 and not force_rtdetr:
            # Still in cooldown — use YOLO results
            self._yolo_only_frames += 1
            self._total_detections += len(yolo_detections)
            return yolo_detections, context

        # --- Step 5: Run RT-DETR and merge ---
        self._lazy_load_rtdetr()

        if not self._rtdetr_available:
            self._total_detections += len(yolo_detections)
            return yolo_detections, context

        rtdetr_detections = self._run_rtdetr(frame, conf=max(0.25, conf - 0.1))
        merged = self._merge_detections(yolo_detections, rtdetr_detections)

        self._cooldown_counter = self.rtdetr_cooldown_max
        self._rtdetr_frames += 1
        self._total_detections += len(merged)

        logger.debug(
            f"RT-DETR activated ({context.rtdetr_reason}): "
            f"YOLO={len(yolo_detections)}, RT-DETR={len(rtdetr_detections)}, "
            f"merged={len(merged)}"
        )

        return merged, context

    def _parse_yolo_results(self, results: list, frame_shape: tuple) -> List[Detection]:
        """Convert YOLO results to unified Detection objects."""
        detections = []
        if not results or not results[0].boxes:
            return detections

        boxes = results[0].boxes.xyxy.cpu().numpy()
        confs = results[0].boxes.conf.cpu().numpy()

        h, w = frame_shape[:2]
        for box, conf in zip(boxes, confs):
            x1, y1, x2, y2 = box.astype(int)
            # Clamp to frame bounds
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(w, x2), min(h, y2)

            area = (x2 - x1) * (y2 - y1)
            detections.append(Detection(
                bbox=[x1, y1, x2, y2],
                confidence=float(conf),
                class_id=0,
                source='yolo',
                area=float(area),
            ))

        return detections

    def _analyze_scene(self, detections: List[Detection],
                       frame: np.ndarray,
                       scene_hint: Optional[Dict] = None) -> SceneContext:
        """Analyze scene complexity for routing decisions."""
        ctx = SceneContext()
        ctx.person_count = len(detections)

        if not detections:
            ctx.density_zone = 'empty'
            return ctx

        confs = [d.confidence for d in detections]
        ctx.avg_confidence = float(np.mean(confs))
        ctx.min_confidence = float(np.min(confs))

        # Density classification
        if ctx.person_count <= 3:
            ctx.density_zone = 'sparse'
        elif ctx.person_count <= 10:
            ctx.density_zone = 'normal'
        elif ctx.person_count <= self.density_threshold:
            ctx.density_zone = 'dense'
        else:
            ctx.density_zone = 'crowded'

        # Occlusion analysis (pairwise IoU)
        if len(detections) >= 2:
            overlap_count = 0
            pair_count = 0
            for i in range(len(detections)):
                for j in range(i + 1, len(detections)):
                    iou = self._calculate_iou(detections[i].bbox, detections[j].bbox)
                    if iou > 0.3:  # Significant overlap
                        overlap_count += 1
                    pair_count += 1
            ctx.occlusion_ratio = overlap_count / max(pair_count, 1)

        # Brightness estimation (for low-light routing)
        try:
            import cv2
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            ctx.brightness = float(np.mean(gray))
        except Exception:
            ctx.brightness = 128.0

        # RT-DETR trigger decision
        if ctx.min_confidence < self.confidence_floor:
            ctx.needs_rtdetr = True
            ctx.rtdetr_reason = f'low_confidence({ctx.min_confidence:.2f})'
        elif ctx.density_zone == 'crowded':
            ctx.needs_rtdetr = True
            ctx.rtdetr_reason = f'crowded_scene({ctx.person_count})'
        elif ctx.occlusion_ratio > self.occlusion_threshold:
            ctx.needs_rtdetr = True
            ctx.rtdetr_reason = f'heavy_occlusion({ctx.occlusion_ratio:.2f})'

        # External hints
        if scene_hint:
            if scene_hint.get('heavy_occlusion'):
                ctx.needs_rtdetr = True
                ctx.rtdetr_reason = 'external_hint_occlusion'
            if scene_hint.get('force_high_recall'):
                ctx.needs_rtdetr = True
                ctx.rtdetr_reason = 'external_hint_high_recall'

        return ctx

    def _run_rtdetr(self, frame: np.ndarray, conf: float = 0.25) -> List[Detection]:
        """Run RT-DETR detector on the frame."""
        detections = []
        try:
            results = self._rtdetr_model(frame, conf=conf, classes=[0], verbose=False)
            if results and results[0].boxes:
                boxes = results[0].boxes.xyxy.cpu().numpy()
                confs = results[0].boxes.conf.cpu().numpy()
                h, w = frame.shape[:2]

                for box, c in zip(boxes, confs):
                    x1, y1, x2, y2 = box.astype(int)
                    x1, y1 = max(0, x1), max(0, y1)
                    x2, y2 = min(w, x2), min(h, y2)

                    detections.append(Detection(
                        bbox=[x1, y1, x2, y2],
                        confidence=float(c),
                        class_id=0,
                        source='rtdetr',
                        area=float((x2 - x1) * (y2 - y1)),
                    ))
        except Exception as e:
            logger.error(f"RT-DETR inference failed: {e}")

        return detections

    def _merge_detections(self, primary: List[Detection],
                          secondary: List[Detection],
                          iou_threshold: float = 0.5) -> List[Detection]:
        """
        Merge detections from two detectors via IoU-based NMS.

        Strategy:
        - Keep ALL primary (YOLO) detections
        - Add secondary (RT-DETR) detections that don't overlap with primary
        - If overlap exists, keep the higher-confidence detection
        """
        if not secondary:
            return primary

        merged = list(primary)  # Start with all YOLO detections

        for sec_det in secondary:
            is_novel = True
            for i, pri_det in enumerate(merged):
                iou = self._calculate_iou(sec_det.bbox, pri_det.bbox)
                if iou > iou_threshold:
                    # Overlap: keep higher confidence
                    if sec_det.confidence > pri_det.confidence:
                        merged[i] = sec_det  # RT-DETR was better
                    is_novel = False
                    break

            if is_novel:
                # New detection from RT-DETR (missed by YOLO)
                merged.append(sec_det)

        return merged

    @staticmethod
    def _calculate_iou(box_a: List[int], box_b: List[int]) -> float:
        """Calculate Intersection over Union between two bboxes."""
        x_a = max(box_a[0], box_b[0])
        y_a = max(box_a[1], box_b[1])
        x_b = min(box_a[2], box_b[2])
        y_b = min(box_a[3], box_b[3])
        inter = max(0, x_b - x_a) * max(0, y_b - y_a)
        area_a = (box_a[2] - box_a[0]) * (box_a[3] - box_a[1])
        area_b = (box_b[2] - box_b[0]) * (box_b[3] - box_b[1])
        return inter / float(area_a + area_b - inter + 1e-6)

    def get_metrics(self) -> dict:
        """Return routing performance metrics."""
        total = max(self._total_frames, 1)
        return {
            'total_frames': self._total_frames,
            'yolo_only_frames': self._yolo_only_frames,
            'rtdetr_frames': self._rtdetr_frames,
            'rtdetr_ratio': round(self._rtdetr_frames / total, 3),
            'total_detections': self._total_detections,
            'avg_detections_per_frame': round(self._total_detections / total, 1),
            'rtdetr_available': self._rtdetr_available,
            'rtdetr_enabled': self.rtdetr_enabled,
            'cooldown_remaining': self._cooldown_counter,
        }

    def reset_metrics(self):
        """Reset performance counters."""
        self._total_frames = 0
        self._yolo_only_frames = 0
        self._rtdetr_frames = 0
        self._total_detections = 0
