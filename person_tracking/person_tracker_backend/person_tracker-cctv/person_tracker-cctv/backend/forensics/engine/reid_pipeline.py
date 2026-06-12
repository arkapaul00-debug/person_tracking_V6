"""
ReID Pipeline — Multi-Modal Body Re-Identification with Fallback Chain.

Architecture:
    Primary:   FastReID (OSNet backbone) → real-time body appearance matching
    Advanced:  CLIP-ReID → cross-domain matching for difficult visual gaps
    Gait:      GaitGL → back-facing / no-face / distant subjects ONLY

    DO NOT run all models simultaneously.
    Use the primary model always; escalate ONLY when conditions require it.

Gait Recognition Triggers (expensive, use sparingly):
    - Face confidence < 0.2 for > 3 consecutive seconds
    - Subject distance > 50m (estimated from bbox height)
    - Back-facing pose detected (no face visible for extended period)
    - Explicit forensic mode requested

Fallback: If no advanced models are available, uses the existing
OSNet x1_0 body extractor — fully backward compatible.
"""
import time
import logging
import cv2
import numpy as np
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class ReIDResult:
    """Result of body re-identification for a single person."""
    embedding: Optional[np.ndarray]    # Fused body embedding
    primary_embedding: Optional[np.ndarray] = None   # FastReID/OSNet
    clip_embedding: Optional[np.ndarray] = None       # CLIP-ReID (if used)
    gait_embedding: Optional[np.ndarray] = None       # GaitGL (if used)
    model_used: str = 'osnet'
    escalation_reason: str = ''     # Why advanced model was triggered
    match_score: float = 0.0
    processing_time_ms: float = 0.0


@dataclass
class PersonContext:
    """Context for ReID routing decisions."""
    track_id: int = -1
    face_available: bool = False
    face_confidence: float = 0.0
    frames_without_face: int = 0    # Consecutive frames with no face detection
    estimated_distance_m: float = 10.0  # Rough distance estimate from bbox
    is_back_facing: bool = False
    crop_quality: float = 0.5       # Body crop quality (blur, completeness)
    is_forensic_mode: bool = False


class ReIDPipeline:
    """
    Multi-modal body re-identification with conditional escalation.

    Usage:
        pipeline = ReIDPipeline(model_pool, device='cuda:0')

        # Standard ReID (OSNet only — fast)
        result = pipeline.extract(person_crop)

        # Context-aware ReID (may escalate to CLIP-ReID or GaitGL)
        result = pipeline.extract_with_context(
            person_crop, PersonContext(face_available=False, frames_without_face=100)
        )

        # Batch ReID for multiple crops
        results = pipeline.extract_batch(crops)
    """

    def __init__(self, model_pool, device: str = 'cuda:0',
                 clip_escalation_threshold: int = 90,  # ~3s at 30fps
                 gait_distance_threshold: float = 30.0,
                 gait_min_sequence: int = 30):
        """
        Args:
            model_pool: Shared ModelPool with body_model loaded.
            device: CUDA device.
            clip_escalation_threshold: Frames without face before CLIP-ReID.
            gait_distance_threshold: Distance (m) threshold for gait activation.
            gait_min_sequence: Minimum gait frames needed for extraction.
        """
        self.model_pool = model_pool
        self.device = device
        self.clip_threshold = clip_escalation_threshold
        self.gait_distance_thresh = gait_distance_threshold
        self.gait_min_sequence = gait_min_sequence

        # Primary: OSNet (always available from model_pool)
        self._osnet = model_pool.body_model

        # Advanced models (lazy loaded)
        self._clip_reid = None
        self._clip_available = None  # None = unchecked, True/False = known
        self._gaitgl = None
        self._gait_available = None

        # Gait sequence buffer (per track_id)
        self._gait_buffers: Dict[int, List[np.ndarray]] = {}
        self._max_gait_buffer = 60  # Max frames to buffer per track

        # Metrics
        self._total_extractions = 0
        self._osnet_only = 0
        self._clip_escalations = 0
        self._gait_escalations = 0

        logger.info(
            f"ReIDPipeline initialized (primary=OSNet, "
            f"clip_thresh={clip_escalation_threshold}f, "
            f"gait_dist={gait_distance_threshold}m)"
        )

    def extract(self, person_crop: np.ndarray) -> ReIDResult:
        """
        Standard body ReID extraction using primary model (OSNet).

        Args:
            person_crop: BGR person crop.

        Returns:
            ReIDResult with body embedding.
        """
        t_start = time.time()
        self._total_extractions += 1
        self._osnet_only += 1

        embedding = self.model_pool.extract_body_embedding(person_crop)

        return ReIDResult(
            embedding=embedding,
            primary_embedding=embedding,
            model_used='osnet',
            processing_time_ms=(time.time() - t_start) * 1000,
        )

    def extract_with_context(self, person_crop: np.ndarray,
                              context: PersonContext) -> ReIDResult:
        """
        Context-aware ReID with conditional model escalation.

        Args:
            person_crop: BGR person crop.
            context: Routing context (face availability, distance, etc.).

        Returns:
            ReIDResult with potentially fused embeddings.
        """
        t_start = time.time()
        self._total_extractions += 1

        # Step 1: Always extract primary (OSNet)
        primary_emb = self.model_pool.extract_body_embedding(person_crop)

        result = ReIDResult(
            embedding=primary_emb,
            primary_embedding=primary_emb,
            model_used='osnet',
        )

        # Step 2: Check escalation conditions
        escalation = self._should_escalate(context)

        if escalation == 'clip':
            # CLIP-ReID for cross-domain matching
            clip_emb = self._extract_clip(person_crop)
            if clip_emb is not None:
                result.clip_embedding = clip_emb
                result.embedding = self._fuse_embeddings(
                    primary_emb, clip_emb, weights=[0.6, 0.4]
                )
                result.model_used = 'osnet+clip'
                result.escalation_reason = 'no_face_extended'
                self._clip_escalations += 1
            else:
                self._osnet_only += 1

        elif escalation == 'gait':
            # GaitGL for distant/back-facing subjects
            self._buffer_gait_frame(context.track_id, person_crop)
            gait_emb = self._extract_gait(context.track_id)
            if gait_emb is not None:
                result.gait_embedding = gait_emb
                result.embedding = self._fuse_embeddings(
                    primary_emb, gait_emb, weights=[0.5, 0.5]
                )
                result.model_used = 'osnet+gait'
                result.escalation_reason = f'distant({context.estimated_distance_m:.0f}m)'
                self._gait_escalations += 1
            else:
                self._osnet_only += 1
                # Still buffer the frame for future gait extraction
        else:
            self._osnet_only += 1

        result.processing_time_ms = (time.time() - t_start) * 1000
        return result

    def extract_batch(self, crops: List[np.ndarray]) -> List[ReIDResult]:
        """
        Batch body ReID extraction for multiple person crops.
        Uses GPU batching for efficiency.

        Args:
            crops: List of BGR person crops.

        Returns:
            List of ReIDResult, one per crop.
        """
        t_start = time.time()
        self._total_extractions += len(crops)
        self._osnet_only += len(crops)

        embeddings = self.model_pool.extract_body_embeddings_batch(crops)

        results = []
        for emb in embeddings:
            results.append(ReIDResult(
                embedding=emb,
                primary_embedding=emb,
                model_used='osnet',
                processing_time_ms=(time.time() - t_start) * 1000 / max(len(crops), 1),
            ))

        return results

    def _should_escalate(self, ctx: PersonContext) -> Optional[str]:
        """
        Determine if context requires model escalation.

        Returns: 'clip', 'gait', or None.
        """
        # Forensic mode: always use best available
        if ctx.is_forensic_mode:
            if ctx.is_back_facing or ctx.estimated_distance_m > self.gait_distance_thresh:
                return 'gait'
            return 'clip'

        # Gait: back-facing + distant subject
        if (ctx.is_back_facing and
                ctx.estimated_distance_m > self.gait_distance_thresh and
                ctx.frames_without_face > self.clip_threshold):
            return 'gait'

        # CLIP-ReID: extended period without face
        if (not ctx.face_available and
                ctx.frames_without_face > self.clip_threshold):
            return 'clip'

        return None

    def _extract_clip(self, crop: np.ndarray) -> Optional[np.ndarray]:
        """Extract CLIP-ReID embedding (lazy loaded)."""
        if self._clip_available is False:
            return None

        if self._clip_reid is None:
            self._clip_reid = self._load_clip_model()
            if self._clip_reid is None:
                self._clip_available = False
                return None
            self._clip_available = True

        try:
            # CLIP-ReID uses same input format as OSNet (resize + normalize)
            # but produces cross-domain embeddings
            return self._clip_reid.extract(crop)
        except Exception as e:
            logger.error(f"CLIP-ReID extraction failed: {e}")
            return None

    def _load_clip_model(self):
        """Attempt to load CLIP-ReID model."""
        try:
            from pathlib import Path
            weights_dir = Path(__file__).resolve().parent.parent / 'ai_core' / 'weights'
            clip_weights = list(weights_dir.glob('clip_reid_*.onnx'))
            if not clip_weights:
                logger.debug("CLIP-ReID weights not found — feature disabled")
                return None
            logger.info(f"CLIP-ReID weights found: {clip_weights[0].name} — loading not yet implemented")
            return None  # TODO: implement when weights are deployed
        except Exception as e:
            logger.warning(f"CLIP-ReID load failed: {e}")
            return None

    def _buffer_gait_frame(self, track_id: int, crop: np.ndarray):
        """Buffer a person crop for gait sequence extraction."""
        if track_id < 0:
            return

        if track_id not in self._gait_buffers:
            self._gait_buffers[track_id] = []

        buf = self._gait_buffers[track_id]

        # Extract silhouette for gait
        try:
            resized = cv2.resize(crop, (64, 128))
            gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
            buf.append(gray)
        except Exception:
            return

        # Trim buffer
        if len(buf) > self._max_gait_buffer:
            self._gait_buffers[track_id] = buf[-self._max_gait_buffer:]

    def _extract_gait(self, track_id: int) -> Optional[np.ndarray]:
        """Extract gait embedding from buffered sequence."""
        if self._gait_available is False:
            return None

        buf = self._gait_buffers.get(track_id, [])
        if len(buf) < self.gait_min_sequence:
            return None  # Not enough frames yet

        if self._gaitgl is None:
            self._gaitgl = self._load_gait_model()
            if self._gaitgl is None:
                self._gait_available = False
                return None
            self._gait_available = True

        try:
            sequence = np.stack(buf[-self.gait_min_sequence:])
            return self._gaitgl.extract(sequence)
        except Exception as e:
            logger.error(f"Gait extraction failed: {e}")
            return None

    def _load_gait_model(self):
        """Attempt to load GaitGL model."""
        try:
            from pathlib import Path
            weights_dir = Path(__file__).resolve().parent.parent / 'ai_core' / 'weights'
            gait_weights = list(weights_dir.glob('gaitgl_*.onnx'))
            if not gait_weights:
                logger.debug("GaitGL weights not found — feature disabled")
                return None
            logger.info(f"GaitGL weights found: {gait_weights[0].name} — loading not yet implemented")
            return None  # TODO: implement when weights are deployed
        except Exception as e:
            logger.warning(f"GaitGL load failed: {e}")
            return None

    @staticmethod
    def _fuse_embeddings(emb_a: Optional[np.ndarray],
                         emb_b: Optional[np.ndarray],
                         weights: List[float] = None) -> Optional[np.ndarray]:
        """
        Fuse two embeddings with optional weighting.

        Both embeddings must be L2-normalized. Result is L2-normalized.
        """
        if emb_a is None:
            return emb_b
        if emb_b is None:
            return emb_a

        if weights is None:
            weights = [0.5, 0.5]

        a = np.asarray(emb_a).flatten()
        b = np.asarray(emb_b).flatten()

        # Handle different dimensions by padding/truncating
        if len(a) != len(b):
            min_len = min(len(a), len(b))
            a = a[:min_len]
            b = b[:min_len]

        fused = weights[0] * a + weights[1] * b
        norm = np.linalg.norm(fused)
        if norm > 0:
            fused = fused / norm

        return fused

    def cleanup_tracks(self, active_track_ids: set):
        """Remove gait buffers for tracks that no longer exist."""
        stale = [tid for tid in self._gait_buffers if tid not in active_track_ids]
        for tid in stale:
            del self._gait_buffers[tid]

    def get_metrics(self) -> dict:
        """Return pipeline performance metrics."""
        total = max(self._total_extractions, 1)
        return {
            'total_extractions': self._total_extractions,
            'osnet_only': self._osnet_only,
            'clip_escalations': self._clip_escalations,
            'gait_escalations': self._gait_escalations,
            'escalation_ratio': round(
                (self._clip_escalations + self._gait_escalations) / total, 3
            ),
            'active_gait_buffers': len(self._gait_buffers),
            'clip_available': self._clip_available,
            'gait_available': self._gait_available,
        }
