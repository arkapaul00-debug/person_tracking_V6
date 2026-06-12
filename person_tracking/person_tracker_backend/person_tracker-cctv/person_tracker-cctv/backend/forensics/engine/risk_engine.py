"""
AI Risk Engine — Real-Time Behavioral Anomaly Scoring and Prioritization.

Computes per-track risk scores based on:
  - Detection confidence + match confidence (identity signals)
  - Dwell time in sensitive zones (loitering)
  - Trajectory anomaly (unusual movement patterns)
  - Re-appearance frequency (how often a person reappears)
  - Cross-camera sighting count (broader coverage)
  - Time-of-day risk multiplier (late night = higher risk)

Output:
  - Per-track risk_score (0.0 - 1.0)
  - Risk tier: LOW / MEDIUM / HIGH / CRITICAL
  - Anomaly flags: LOITERING, UNUSUAL_PATH, FREQUENT_REAPPEAR, etc.

Usage:
    engine = RiskEngine()

    risk = engine.evaluate(
        track_id=42,
        match_score=0.72,
        dwell_frames=300,
        trajectory=[(100,200), (110,195), ...],
        sighting_count=5,
        time_of_day_hour=2,  # 2 AM
    )

    print(risk.tier)       # 'HIGH'
    print(risk.score)      # 0.81
    print(risk.anomalies)  # ['LOITERING', 'LATE_NIGHT']

    # Batch evaluation for all active tracks
    risks = engine.evaluate_batch(track_data_list)

    # False-positive suppression
    filtered = engine.suppress_false_positives(risks)
"""
import time
import math
import logging
import numpy as np
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


class RiskTier:
    LOW = 'LOW'
    MEDIUM = 'MEDIUM'
    HIGH = 'HIGH'
    CRITICAL = 'CRITICAL'


@dataclass
class RiskAssessment:
    """Risk assessment for a single track."""
    track_id: int
    score: float = 0.0              # Composite risk score (0-1)
    tier: str = 'LOW'               # LOW / MEDIUM / HIGH / CRITICAL
    anomalies: List[str] = field(default_factory=list)
    confidence: float = 0.0         # How confident we are in this assessment
    components: Dict[str, float] = field(default_factory=dict)  # Per-signal breakdown
    suppressed: bool = False        # True if filtered as false-positive
    suppression_reason: str = ''


@dataclass
class TrackRiskState:
    """Persistent risk tracking state for a single track."""
    track_id: int
    first_seen: float = 0.0
    last_seen: float = 0.0
    total_frames: int = 0
    match_scores: List[float] = field(default_factory=list)
    positions: List[Tuple[float, float]] = field(default_factory=list)
    sighting_count: int = 0
    zone_dwell: Dict[str, int] = field(default_factory=dict)  # zone_id -> frames
    risk_history: List[float] = field(default_factory=list)


class RiskEngine:
    """
    Real-time AI risk scoring engine with false-positive suppression.
    """

    def __init__(self,
                 loiter_threshold_frames: int = 300,   # ~10s at 30fps
                 trajectory_anomaly_threshold: float = 0.3,
                 reappearance_threshold: int = 3,
                 late_night_start: int = 22,  # 10 PM
                 late_night_end: int = 5,     # 5 AM
                 ema_alpha: float = 0.3,      # Score smoothing
                 fp_min_frames: int = 10,     # Min frames before scoring
                 fp_score_consistency: float = 0.15):
        """
        Args:
            loiter_threshold_frames: Frames of dwell before flagging loitering.
            trajectory_anomaly_threshold: Movement irregularity threshold.
            reappearance_threshold: Min cross-camera sightings for flag.
            late_night_start: Hour when late-night risk multiplier starts.
            late_night_end: Hour when late-night risk multiplier ends.
            ema_alpha: EMA alpha for score smoothing.
            fp_min_frames: Minimum frames before risk assessment is valid.
            fp_score_consistency: Max score variance to suppress as false positive.
        """
        self.loiter_thresh = loiter_threshold_frames
        self.traj_thresh = trajectory_anomaly_threshold
        self.reappear_thresh = reappearance_threshold
        self.night_start = late_night_start
        self.night_end = late_night_end
        self.ema_alpha = ema_alpha
        self.fp_min_frames = fp_min_frames
        self.fp_consistency = fp_score_consistency

        # Per-track state
        self._track_states: Dict[int, TrackRiskState] = {}

        # Metrics
        self._total_evaluations = 0
        self._suppressed_count = 0

    def evaluate(self,
                 track_id: int,
                 match_score: float = 0.0,
                 dwell_frames: int = 0,
                 trajectory: Optional[List[Tuple[float, float]]] = None,
                 sighting_count: int = 0,
                 time_of_day_hour: Optional[int] = None,
                 zone_id: str = '') -> RiskAssessment:
        """
        Evaluate risk for a single track.

        Args:
            track_id: Track identifier.
            match_score: Identity match confidence (0-1).
            dwell_frames: Frames the track has been in current zone.
            trajectory: List of (x, y) centroid positions.
            sighting_count: Cross-camera sighting count.
            time_of_day_hour: Current hour (0-23).
            zone_id: ID of the zone the track is currently in.

        Returns:
            RiskAssessment with composite score and anomaly flags.
        """
        self._total_evaluations += 1

        # Get or create track state
        state = self._get_state(track_id)
        state.total_frames += 1
        state.last_seen = time.time()
        state.match_scores.append(match_score)
        state.sighting_count = max(state.sighting_count, sighting_count)

        if trajectory:
            state.positions.extend(trajectory)
            # Trim to last 500 positions
            if len(state.positions) > 500:
                state.positions = state.positions[-500:]

        if zone_id:
            state.zone_dwell[zone_id] = state.zone_dwell.get(zone_id, 0) + 1

        # --- Score Components ---
        components = {}
        anomalies = []

        # 1. Identity match signal
        identity_score = self._score_identity(match_score, state)
        components['identity'] = identity_score

        # 2. Loitering detection
        loiter_score = self._score_loitering(dwell_frames, state)
        components['loitering'] = loiter_score
        if loiter_score > 0.6:
            anomalies.append('LOITERING')

        # 3. Trajectory anomaly
        traj_score = self._score_trajectory(trajectory, state)
        components['trajectory'] = traj_score
        if traj_score > 0.5:
            anomalies.append('UNUSUAL_PATH')

        # 4. Reappearance frequency
        reappear_score = self._score_reappearance(sighting_count)
        components['reappearance'] = reappear_score
        if sighting_count >= self.reappear_thresh:
            anomalies.append('FREQUENT_REAPPEAR')

        # 5. Time-of-day risk
        time_score = self._score_time_of_day(time_of_day_hour)
        components['time_of_day'] = time_score
        if time_score > 0.5:
            anomalies.append('LATE_NIGHT')

        # --- Composite Score ---
        # Weighted combination (identity is dominant signal)
        raw_score = (
            0.45 * identity_score +
            0.20 * loiter_score +
            0.15 * traj_score +
            0.10 * reappear_score +
            0.10 * time_score
        )
        raw_score = float(np.clip(raw_score, 0.0, 1.0))

        # EMA smoothing
        if state.risk_history:
            smoothed = self.ema_alpha * raw_score + (1 - self.ema_alpha) * state.risk_history[-1]
        else:
            smoothed = raw_score
        state.risk_history.append(smoothed)

        # Trim history
        if len(state.risk_history) > 100:
            state.risk_history = state.risk_history[-100:]

        # --- Risk Tier ---
        tier = self._compute_tier(smoothed)

        # --- Confidence ---
        confidence = min(state.total_frames / max(self.fp_min_frames, 1), 1.0)

        return RiskAssessment(
            track_id=track_id,
            score=round(smoothed, 3),
            tier=tier,
            anomalies=anomalies,
            confidence=round(confidence, 3),
            components=components,
        )

    def evaluate_batch(self, tracks: List[Dict]) -> List[RiskAssessment]:
        """Evaluate risk for multiple tracks."""
        return [
            self.evaluate(
                track_id=t.get('track_id', 0),
                match_score=t.get('match_score', 0.0),
                dwell_frames=t.get('dwell_frames', 0),
                trajectory=t.get('trajectory'),
                sighting_count=t.get('sighting_count', 0),
                time_of_day_hour=t.get('hour'),
            )
            for t in tracks
        ]

    def suppress_false_positives(self, assessments: List[RiskAssessment]) -> List[RiskAssessment]:
        """
        Filter assessments to suppress likely false positives.

        Suppression criteria:
          - Track has fewer than fp_min_frames
          - Score is oscillating with high variance (unstable identity)
          - Match score is consistently below threshold
        """
        for assessment in assessments:
            state = self._track_states.get(assessment.track_id)
            if state is None:
                continue

            # Not enough frames for reliable assessment
            if state.total_frames < self.fp_min_frames:
                assessment.suppressed = True
                assessment.suppression_reason = 'insufficient_frames'
                self._suppressed_count += 1
                continue

            # High score variance = unstable identity match
            if len(state.match_scores) > 5:
                recent = state.match_scores[-10:]
                score_var = float(np.var(recent))
                if score_var > self.fp_consistency and assessment.score < 0.6:
                    assessment.suppressed = True
                    assessment.suppression_reason = f'score_variance={score_var:.3f}'
                    self._suppressed_count += 1

        return assessments

    def _get_state(self, track_id: int) -> TrackRiskState:
        if track_id not in self._track_states:
            self._track_states[track_id] = TrackRiskState(
                track_id=track_id,
                first_seen=time.time(),
                last_seen=time.time(),
            )
        return self._track_states[track_id]

    @staticmethod
    def _score_identity(match_score: float, state: TrackRiskState) -> float:
        """Score based on identity match confidence."""
        if not state.match_scores:
            return match_score

        # Use rolling average for stability
        recent = state.match_scores[-10:]
        avg_score = float(np.mean(recent))
        return float(np.clip(avg_score, 0.0, 1.0))

    def _score_loitering(self, dwell_frames: int, state: TrackRiskState) -> float:
        """Score based on how long a person has been stationary."""
        if dwell_frames < self.loiter_thresh * 0.3:
            return 0.0
        ratio = dwell_frames / self.loiter_thresh
        return float(np.clip(ratio, 0.0, 1.0))

    def _score_trajectory(self, trajectory: Optional[List], state: TrackRiskState) -> float:
        """Score based on trajectory irregularity."""
        positions = state.positions if state.positions else (trajectory or [])
        if len(positions) < 10:
            return 0.0

        # Compute direction changes (angular variance)
        recent = positions[-30:]
        if len(recent) < 5:
            return 0.0

        angles = []
        for i in range(2, len(recent)):
            dx1 = recent[i-1][0] - recent[i-2][0]
            dy1 = recent[i-1][1] - recent[i-2][1]
            dx2 = recent[i][0] - recent[i-1][0]
            dy2 = recent[i][1] - recent[i-1][1]
            a1 = math.atan2(dy1, dx1 + 1e-6)
            a2 = math.atan2(dy2, dx2 + 1e-6)
            angles.append(abs(a2 - a1))

        angular_var = float(np.var(angles)) if angles else 0.0
        return float(np.clip(angular_var / math.pi, 0.0, 1.0))

    def _score_reappearance(self, sighting_count: int) -> float:
        """Score based on how often a person reappears across cameras."""
        if sighting_count <= 1:
            return 0.0
        return float(np.clip(sighting_count / (self.reappear_thresh * 2), 0.0, 1.0))

    def _score_time_of_day(self, hour: Optional[int]) -> float:
        """Score based on time of day (late night = higher risk)."""
        if hour is None:
            import datetime
            hour = datetime.datetime.now().hour

        if self.night_start <= hour or hour < self.night_end:
            return 0.7  # Late night risk
        elif 5 <= hour < 7 or 20 <= hour < 22:
            return 0.3  # Dawn/dusk
        return 0.0

    @staticmethod
    def _compute_tier(score: float) -> str:
        if score >= 0.8:
            return RiskTier.CRITICAL
        elif score >= 0.6:
            return RiskTier.HIGH
        elif score >= 0.35:
            return RiskTier.MEDIUM
        return RiskTier.LOW

    def cleanup_tracks(self, active_track_ids: set):
        """Remove state for tracks that no longer exist."""
        stale = [tid for tid in self._track_states if tid not in active_track_ids]
        for tid in stale:
            del self._track_states[tid]

    def get_metrics(self) -> dict:
        return {
            'total_evaluations': self._total_evaluations,
            'active_tracks': len(self._track_states),
            'suppressed': self._suppressed_count,
        }
