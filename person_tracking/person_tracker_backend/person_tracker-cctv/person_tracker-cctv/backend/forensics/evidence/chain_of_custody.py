"""
Chain of Custody — Forensic Audit Trail for Evidence Lifecycle.

Tracks every action performed on evidence artifacts:
  - Who accessed the evidence (operator, system, API)
  - When it was accessed (timestamp)
  - What action was performed (view, export, annotate, share)
  - Where it was transferred (system, path, external)
  - Cryptographic proof of each custody event

Required for law enforcement evidence submission:
  - Proves unbroken chain from capture to courtroom
  - Every handoff is logged and timestamped
  - Tampering between custody events is detectable
"""
import hashlib
import time
import json
import threading
import logging
import uuid
from typing import Optional, Dict, List, Any
from dataclasses import dataclass, field, asdict
from enum import Enum

logger = logging.getLogger(__name__)


class CustodyAction(Enum):
    CAPTURED = 'captured'           # Initial evidence creation
    ACCESSED = 'accessed'           # Evidence viewed/read
    EXPORTED = 'exported'           # Evidence exported to file/system
    ANNOTATED = 'annotated'         # Evidence annotated (bbox, label)
    TRANSFERRED = 'transferred'     # Custody transferred to another party
    VERIFIED = 'verified'           # Integrity verification performed
    SEALED = 'sealed'               # Evidence sealed (no further modifications)
    DELETED = 'deleted'             # Evidence deleted (with authorization)


@dataclass
class CustodyEvent:
    """A single custody event in the audit trail."""
    event_id: str                      # Unique event identifier (UUID)
    timestamp: float                   # Unix timestamp
    action: str                        # CustodyAction value
    actor: str                         # Who performed the action (user/system)
    evidence_id: str                   # Which evidence artifact
    evidence_hash: str                 # Hash of evidence at time of action
    details: Dict[str, Any] = field(default_factory=dict)
    previous_event_hash: str = ''      # Link to previous event (chain)
    event_hash: str = ''               # Hash of this event

    def to_dict(self) -> dict:
        return asdict(self)


class ChainOfCustody:
    """
    Audit trail manager for evidence lifecycle tracking.

    Usage:
        custody = ChainOfCustody(persist_path='evidence/custody.jsonl')

        # Record evidence creation
        custody.record(
            action=CustodyAction.CAPTURED,
            actor='system:camera_001',
            evidence_id='clip_20240301_143022',
            evidence_hash='abc123...',
            details={'stream_id': 'cam_001', 'duration_s': 15}
        )

        # Record access
        custody.record(
            action=CustodyAction.ACCESSED,
            actor='officer:badge_12345',
            evidence_id='clip_20240301_143022',
            evidence_hash='abc123...',
        )

        # Record export with digital signature
        custody.record(
            action=CustodyAction.EXPORTED,
            actor='officer:badge_12345',
            evidence_id='clip_20240301_143022',
            evidence_hash='abc123...',
            details={'export_path': '/exports/case_42.zip', 'format': 'mp4+json'}
        )

        # Verify custody chain
        is_valid, errors = custody.verify(evidence_id='clip_20240301_143022')

        # Get full audit trail
        trail = custody.get_trail(evidence_id='clip_20240301_143022')
    """

    def __init__(self, persist_path: Optional[str] = None):
        """
        Args:
            persist_path: Path for persistent storage (JSONL format).
        """
        self._events: List[CustodyEvent] = []
        self._evidence_index: Dict[str, List[int]] = {}  # evidence_id → event indices
        self._lock = threading.Lock()
        self._persist_path = persist_path

        # Load existing events
        if persist_path:
            self._load(persist_path)

        logger.info(
            f"ChainOfCustody initialized: {len(self._events)} events, "
            f"persist={'yes' if persist_path else 'no'}"
        )

    def record(self, action: CustodyAction,
               actor: str,
               evidence_id: str,
               evidence_hash: str,
               details: Optional[Dict] = None) -> CustodyEvent:
        """
        Record a custody event.

        Args:
            action: What happened to the evidence.
            actor: Who did it (format: 'type:identifier').
            evidence_id: Which evidence artifact.
            evidence_hash: Current hash of the evidence.
            details: Additional context.

        Returns:
            The recorded CustodyEvent.
        """
        with self._lock:
            # Get previous event hash for this evidence
            prev_hash = ''
            if evidence_id in self._evidence_index:
                prev_idx = self._evidence_index[evidence_id][-1]
                prev_hash = self._events[prev_idx].event_hash

            # Create event
            event = CustodyEvent(
                event_id=str(uuid.uuid4()),
                timestamp=time.time(),
                action=action.value,
                actor=actor,
                evidence_id=evidence_id,
                evidence_hash=evidence_hash,
                details=details or {},
                previous_event_hash=prev_hash,
            )

            # Compute event hash (includes all fields for tamper-proofing)
            event.event_hash = self._compute_event_hash(event)

            # Store
            idx = len(self._events)
            self._events.append(event)

            if evidence_id not in self._evidence_index:
                self._evidence_index[evidence_id] = []
            self._evidence_index[evidence_id].append(idx)

            # Persist
            if self._persist_path:
                self._persist_event(event)

            logger.info(
                f"Custody: {action.value} by {actor} on {evidence_id} "
                f"(event={event.event_id[:8]})"
            )

            return event

    def get_trail(self, evidence_id: str) -> List[CustodyEvent]:
        """Get the complete custody trail for an evidence artifact."""
        indices = self._evidence_index.get(evidence_id, [])
        return [self._events[i] for i in indices]

    def verify(self, evidence_id: str) -> tuple:
        """
        Verify the custody chain for a specific evidence artifact.

        Returns:
            (is_valid, list_of_errors)
        """
        trail = self.get_trail(evidence_id)
        errors = []

        if not trail:
            return True, []

        for i, event in enumerate(trail):
            # Check event hash integrity
            expected_hash = self._compute_event_hash(event)
            if event.event_hash != expected_hash:
                errors.append(
                    f"Event hash tampered at {event.event_id[:8]}: "
                    f"action={event.action}"
                )

            # Check chain linkage
            if i > 0:
                expected_prev = trail[i - 1].event_hash
                if event.previous_event_hash != expected_prev:
                    errors.append(
                        f"Chain break at {event.event_id[:8]}: "
                        f"previous_event_hash mismatch"
                    )

            # Check timestamp ordering
            if i > 0 and event.timestamp < trail[i - 1].timestamp:
                errors.append(
                    f"Timestamp regression at {event.event_id[:8]}"
                )

        is_valid = len(errors) == 0
        return is_valid, errors

    def get_all_evidence_ids(self) -> List[str]:
        """List all evidence IDs with custody records."""
        return list(self._evidence_index.keys())

    def get_last_action(self, evidence_id: str) -> Optional[CustodyEvent]:
        """Get the most recent custody event for an evidence artifact."""
        indices = self._evidence_index.get(evidence_id, [])
        if indices:
            return self._events[indices[-1]]
        return None

    def is_sealed(self, evidence_id: str) -> bool:
        """Check if evidence has been sealed (no further modifications allowed)."""
        trail = self.get_trail(evidence_id)
        return any(e.action == CustodyAction.SEALED.value for e in trail)

    @staticmethod
    def _compute_event_hash(event: CustodyEvent) -> str:
        """Compute SHA-256 hash of a custody event (excluding event_hash field)."""
        hash_input = (
            event.event_id +
            str(event.timestamp) +
            event.action +
            event.actor +
            event.evidence_id +
            event.evidence_hash +
            json.dumps(event.details, sort_keys=True) +
            event.previous_event_hash
        )
        return hashlib.sha256(hash_input.encode()).hexdigest()

    def _persist_event(self, event: CustodyEvent):
        """Append event to persistent storage."""
        try:
            from pathlib import Path
            Path(self._persist_path).parent.mkdir(parents=True, exist_ok=True)
            with open(self._persist_path, 'a') as f:
                f.write(json.dumps(event.to_dict()) + '\n')
        except Exception as e:
            logger.error(f"Failed to persist custody event: {e}")

    def _load(self, path: str):
        """Load events from persistent storage."""
        try:
            from pathlib import Path
            if not Path(path).exists():
                return
            with open(path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        data = json.loads(line)
                        event = CustodyEvent(**data)
                        idx = len(self._events)
                        self._events.append(event)
                        eid = event.evidence_id
                        if eid not in self._evidence_index:
                            self._evidence_index[eid] = []
                        self._evidence_index[eid].append(idx)
            logger.info(f"Loaded {len(self._events)} custody events from {path}")
        except Exception as e:
            logger.error(f"Failed to load custody events: {e}")

    def get_metrics(self) -> dict:
        return {
            'total_events': len(self._events),
            'evidence_count': len(self._evidence_index),
            'actions': {},
        }
