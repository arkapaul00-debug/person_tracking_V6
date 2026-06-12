"""
Evidence Integrity Manager — Cryptographic Hashing for Forensic Evidence.

Produces tamper-proof evidence artifacts by:
  - Hashing every evidence frame with SHA-256
  - Linking hashes in a blockchain-style chain (each hash includes the previous)
  - Recording timestamps, stream IDs, and detection metadata
  - Verifying chain integrity on demand

Court-admissible evidence requires proving that no frame was:
  1. Modified after capture (hash verification)
  2. Inserted or deleted (chain continuity)
  3. Reordered (monotonic timestamps + sequence numbers)

Usage:
    mgr = EvidenceIntegrityManager()

    # Hash a detection frame
    entry = mgr.hash_frame(frame, metadata={'stream_id': 'cam_001', 'score': 0.92})

    # Hash a video clip
    entry = mgr.hash_file('/path/to/clip.mp4', metadata={...})

    # Verify chain integrity
    is_valid, errors = mgr.verify_chain()

    # Export chain for audit
    chain_data = mgr.export_chain()
"""
import hashlib
import time
import json
import threading
import logging
from pathlib import Path
from typing import Optional, Dict, List, Tuple, Any
from dataclasses import dataclass, field, asdict

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class EvidenceEntry:
    """A single entry in the evidence hash chain."""
    sequence: int                    # Monotonic sequence number
    timestamp: float                 # Unix timestamp of capture
    evidence_hash: str               # SHA-256 of the evidence content
    previous_hash: str               # Hash of the previous entry (chain link)
    chain_hash: str                  # SHA-256(evidence_hash + previous_hash + metadata)
    evidence_type: str               # 'frame', 'clip', 'snapshot', 'export'
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


class EvidenceIntegrityManager:
    """
    Blockchain-style evidence hash chain manager.

    Every piece of evidence (frame, clip, snapshot) gets:
      1. A SHA-256 content hash
      2. A chain link to the previous evidence entry
      3. Metadata (stream, scores, timestamps)

    The chain can be independently verified to prove no evidence
    was modified, inserted, deleted, or reordered.
    """

    def __init__(self, persist_path: Optional[str] = None):
        """
        Args:
            persist_path: Path to persist the hash chain (JSON file).
                          None = in-memory only.
        """
        self._chain: List[EvidenceEntry] = []
        self._sequence = 0
        self._lock = threading.Lock()
        self._persist_path = persist_path

        # Genesis hash (seed for the chain)
        self._genesis_hash = hashlib.sha256(b'EVIDENCE_CHAIN_GENESIS_v1').hexdigest()

        # Load existing chain if persisted
        if persist_path and Path(persist_path).exists():
            self._load_chain(persist_path)

        logger.info(
            f"EvidenceIntegrityManager initialized: "
            f"chain_length={len(self._chain)}, persist={'yes' if persist_path else 'no'}"
        )

    def hash_frame(self, frame: np.ndarray,
                   metadata: Optional[Dict] = None) -> EvidenceEntry:
        """
        Hash a video frame and add it to the evidence chain.

        Args:
            frame: BGR numpy array.
            metadata: Additional metadata (stream_id, score, bbox, etc.).

        Returns:
            EvidenceEntry with hash and chain link.
        """
        # Compute frame content hash
        frame_bytes = frame.tobytes()
        content_hash = hashlib.sha256(frame_bytes).hexdigest()

        return self._add_entry(content_hash, 'frame', metadata)

    def hash_file(self, file_path: str,
                  metadata: Optional[Dict] = None) -> EvidenceEntry:
        """
        Hash a file (video clip, image, etc.) and add to chain.

        Args:
            file_path: Path to the evidence file.
            metadata: Additional metadata.

        Returns:
            EvidenceEntry with hash and chain link.
        """
        content_hash = self._compute_file_hash(file_path)
        if metadata is None:
            metadata = {}
        metadata['file_path'] = file_path
        metadata['file_size'] = Path(file_path).stat().st_size if Path(file_path).exists() else 0

        return self._add_entry(content_hash, 'clip', metadata)

    def hash_data(self, data: bytes, evidence_type: str = 'snapshot',
                  metadata: Optional[Dict] = None) -> EvidenceEntry:
        """Hash arbitrary binary data and add to chain."""
        content_hash = hashlib.sha256(data).hexdigest()
        return self._add_entry(content_hash, evidence_type, metadata)

    def _add_entry(self, content_hash: str, evidence_type: str,
                   metadata: Optional[Dict]) -> EvidenceEntry:
        """Add a new entry to the hash chain."""
        with self._lock:
            self._sequence += 1

            # Get previous hash (genesis for first entry)
            previous_hash = (
                self._chain[-1].chain_hash if self._chain
                else self._genesis_hash
            )

            # Compute chain hash: SHA-256(content + previous + metadata + sequence)
            chain_input = (
                content_hash +
                previous_hash +
                json.dumps(metadata or {}, sort_keys=True) +
                str(self._sequence)
            )
            chain_hash = hashlib.sha256(chain_input.encode()).hexdigest()

            entry = EvidenceEntry(
                sequence=self._sequence,
                timestamp=time.time(),
                evidence_hash=content_hash,
                previous_hash=previous_hash,
                chain_hash=chain_hash,
                evidence_type=evidence_type,
                metadata=metadata or {},
            )

            self._chain.append(entry)

            # Persist if configured
            if self._persist_path:
                self._persist_entry(entry)

            return entry

    def verify_chain(self) -> Tuple[bool, List[str]]:
        """
        Verify the integrity of the entire evidence chain.

        Checks:
          1. Each entry's chain_hash is correctly computed
          2. Each entry's previous_hash matches the prior entry's chain_hash
          3. Sequence numbers are monotonically increasing
          4. Timestamps are non-decreasing

        Returns:
            (is_valid, list_of_errors)
        """
        errors = []

        if not self._chain:
            return True, []

        for i, entry in enumerate(self._chain):
            # Check sequence monotonicity
            if i > 0 and entry.sequence <= self._chain[i - 1].sequence:
                errors.append(
                    f"Sequence gap at #{entry.sequence}: "
                    f"expected > {self._chain[i - 1].sequence}"
                )

            # Check timestamp ordering
            if i > 0 and entry.timestamp < self._chain[i - 1].timestamp:
                errors.append(
                    f"Timestamp regression at #{entry.sequence}: "
                    f"{entry.timestamp} < {self._chain[i - 1].timestamp}"
                )

            # Check previous hash linkage
            expected_prev = (
                self._chain[i - 1].chain_hash if i > 0
                else self._genesis_hash
            )
            if entry.previous_hash != expected_prev:
                errors.append(
                    f"Chain break at #{entry.sequence}: "
                    f"previous_hash mismatch"
                )

            # Verify chain hash computation
            chain_input = (
                entry.evidence_hash +
                entry.previous_hash +
                json.dumps(entry.metadata, sort_keys=True) +
                str(entry.sequence)
            )
            expected_chain_hash = hashlib.sha256(chain_input.encode()).hexdigest()
            if entry.chain_hash != expected_chain_hash:
                errors.append(
                    f"Hash tampered at #{entry.sequence}: "
                    f"computed={expected_chain_hash[:16]}, "
                    f"stored={entry.chain_hash[:16]}"
                )

        is_valid = len(errors) == 0
        if is_valid:
            logger.info(f"Evidence chain verified: {len(self._chain)} entries, all valid")
        else:
            logger.error(f"Evidence chain INVALID: {len(errors)} errors found")

        return is_valid, errors

    def export_chain(self) -> List[dict]:
        """Export the full chain as JSON-serializable data."""
        return [entry.to_dict() for entry in self._chain]

    def get_entry(self, sequence: int) -> Optional[EvidenceEntry]:
        """Get a specific entry by sequence number."""
        for entry in self._chain:
            if entry.sequence == sequence:
                return entry
        return None

    @property
    def chain_length(self) -> int:
        return len(self._chain)

    @property
    def latest_hash(self) -> str:
        if self._chain:
            return self._chain[-1].chain_hash
        return self._genesis_hash

    def _persist_entry(self, entry: EvidenceEntry):
        """Append entry to persistent storage."""
        try:
            with open(self._persist_path, 'a') as f:
                f.write(json.dumps(entry.to_dict()) + '\n')
        except Exception as e:
            logger.error(f"Failed to persist evidence entry: {e}")

    def _load_chain(self, path: str):
        """Load chain from persistent storage."""
        try:
            with open(path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        data = json.loads(line)
                        entry = EvidenceEntry(**data)
                        self._chain.append(entry)
                        self._sequence = max(self._sequence, entry.sequence)

            logger.info(f"Loaded {len(self._chain)} entries from {path}")
        except Exception as e:
            logger.error(f"Failed to load evidence chain: {e}")

    @staticmethod
    def _compute_file_hash(path: str, chunk_size: int = 65536) -> str:
        """Compute SHA-256 hash of a file."""
        sha = hashlib.sha256()
        try:
            with open(path, 'rb') as f:
                while True:
                    chunk = f.read(chunk_size)
                    if not chunk:
                        break
                    sha.update(chunk)
            return sha.hexdigest()
        except Exception as e:
            logger.error(f"File hash failed for {path}: {e}")
            return hashlib.sha256(b'ERROR').hexdigest()

    def get_metrics(self) -> dict:
        return {
            'chain_length': len(self._chain),
            'latest_sequence': self._sequence,
            'latest_hash': self.latest_hash[:16],
            'persisted': self._persist_path is not None,
        }
