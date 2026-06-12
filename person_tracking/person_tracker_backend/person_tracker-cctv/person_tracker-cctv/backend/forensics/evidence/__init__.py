"""
Evidence Integrity Package — Forensic-Grade Evidence Chain Management.

Provides tamper-proof evidence handling with:
  - SHA-256 cryptographic frame/clip hashing
  - Blockchain-style hash chain linking
  - Chain of custody audit trail
  - Signed evidence export with verification
"""
from .integrity import EvidenceIntegrityManager
from .chain_of_custody import ChainOfCustody
from .signed_export import SignedEvidenceExporter

__all__ = [
    'EvidenceIntegrityManager',
    'ChainOfCustody',
    'SignedEvidenceExporter',
]
