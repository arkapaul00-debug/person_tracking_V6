"""
Signed Evidence Exporter — Cryptographically Signed Evidence Packages.

Creates tamper-evident evidence export packages containing:
  - Video clips with detection overlays
  - Evidence metadata (timestamps, scores, track IDs)
  - Hash chain verification data
  - Chain of custody audit trail
  - Digital signature for package integrity

Export formats:
  - ZIP package (clips + metadata + chain + signature)
  - JSON report (metadata + chain only, no video)
"""
import hashlib
import json
import time
import logging
import zipfile
import hmac
from pathlib import Path
from typing import Optional, Dict, List, Any
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)

# Signing key — in production, use HSM or KMS-managed keys
_DEFAULT_SIGNING_KEY = b'FORENSIC_EVIDENCE_SIGNING_KEY_v1'


@dataclass
class ExportManifest:
    """Manifest describing the contents of an evidence package."""
    export_id: str
    created_at: float
    created_by: str
    evidence_ids: List[str]
    file_count: int
    total_size_bytes: int
    chain_length: int
    manifest_hash: str = ''
    signature: str = ''


class SignedEvidenceExporter:
    """
    Creates cryptographically signed evidence export packages.

    Usage:
        exporter = SignedEvidenceExporter(
            integrity_mgr=integrity_manager,
            custody_mgr=custody_manager,
        )

        # Export evidence as signed ZIP
        result = exporter.export_zip(
            evidence_ids=['clip_001', 'clip_002'],
            clip_paths=['/clips/clip_001.mp4', '/clips/clip_002.mp4'],
            output_path='/exports/case_42.zip',
            actor='officer:badge_12345',
            case_id='CASE-2024-042',
        )

        # Verify a signed package
        is_valid, errors = exporter.verify_package('/exports/case_42.zip')
    """

    def __init__(self, integrity_mgr=None, custody_mgr=None,
                 signing_key: Optional[bytes] = None):
        """
        Args:
            integrity_mgr: EvidenceIntegrityManager for hash chain data.
            custody_mgr: ChainOfCustody for audit trail data.
            signing_key: HMAC signing key (default for development).
        """
        self.integrity = integrity_mgr
        self.custody = custody_mgr
        self._signing_key = signing_key or _DEFAULT_SIGNING_KEY

        logger.info("SignedEvidenceExporter initialized")

    def export_zip(self,
                   evidence_ids: List[str],
                   clip_paths: List[str],
                   output_path: str,
                   actor: str = 'system',
                   case_id: str = '',
                   metadata: Optional[Dict] = None) -> Dict[str, Any]:
        """
        Export evidence as a signed ZIP package.

        Args:
            evidence_ids: List of evidence identifiers to include.
            clip_paths: Corresponding file paths for video clips.
            output_path: Output ZIP file path.
            actor: Who is performing the export (for custody trail).
            case_id: Associated case identifier.
            metadata: Additional export metadata.

        Returns:
            Export result with manifest and signature info.
        """
        import uuid
        export_id = f"EXP-{uuid.uuid4().hex[:12].upper()}"

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        total_size = 0
        file_count = 0

        try:
            with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                # 1. Add video clips
                for clip_path in clip_paths:
                    if Path(clip_path).exists():
                        arcname = f"clips/{Path(clip_path).name}"
                        zf.write(clip_path, arcname)
                        total_size += Path(clip_path).stat().st_size
                        file_count += 1

                # 2. Add hash chain data
                if self.integrity:
                    chain_data = self.integrity.export_chain()
                    chain_json = json.dumps(chain_data, indent=2)
                    zf.writestr('metadata/hash_chain.json', chain_json)
                    file_count += 1

                # 3. Add custody trail
                if self.custody:
                    trails = {}
                    for eid in evidence_ids:
                        trail = self.custody.get_trail(eid)
                        trails[eid] = [e.to_dict() for e in trail]
                    custody_json = json.dumps(trails, indent=2)
                    zf.writestr('metadata/chain_of_custody.json', custody_json)
                    file_count += 1

                # 4. Add export metadata
                export_meta = {
                    'export_id': export_id,
                    'case_id': case_id,
                    'created_at': time.time(),
                    'created_by': actor,
                    'evidence_ids': evidence_ids,
                    'clip_count': len(clip_paths),
                    'additional': metadata or {},
                }
                zf.writestr(
                    'metadata/export_info.json',
                    json.dumps(export_meta, indent=2)
                )
                file_count += 1

                # 5. Compute manifest hash (hash of all included files)
                manifest_hash = self._compute_archive_hash(zf)

                # 6. Create and sign manifest
                manifest = ExportManifest(
                    export_id=export_id,
                    created_at=time.time(),
                    created_by=actor,
                    evidence_ids=evidence_ids,
                    file_count=file_count,
                    total_size_bytes=total_size,
                    chain_length=self.integrity.chain_length if self.integrity else 0,
                    manifest_hash=manifest_hash,
                )

                # Sign the manifest
                manifest.signature = self._sign(manifest_hash)

                # Add signed manifest to archive
                zf.writestr(
                    'MANIFEST.json',
                    json.dumps(asdict(manifest), indent=2)
                )

            # Record custody event
            if self.custody:
                for eid in evidence_ids:
                    from .chain_of_custody import CustodyAction
                    self.custody.record(
                        action=CustodyAction.EXPORTED,
                        actor=actor,
                        evidence_id=eid,
                        evidence_hash=manifest_hash,
                        details={
                            'export_id': export_id,
                            'output_path': output_path,
                            'case_id': case_id,
                        }
                    )

            logger.info(
                f"Evidence exported: {export_id} → {output_path} "
                f"({file_count} files, {total_size / 1024:.1f} KB)"
            )

            return {
                'success': True,
                'export_id': export_id,
                'output_path': output_path,
                'file_count': file_count,
                'total_size_bytes': total_size,
                'manifest_hash': manifest_hash,
                'signature': manifest.signature[:32] + '...',
            }

        except Exception as e:
            logger.error(f"Evidence export failed: {e}")
            return {
                'success': False,
                'error': str(e),
                'export_id': export_id,
            }

    def export_json_report(self,
                           evidence_ids: List[str],
                           output_path: str,
                           actor: str = 'system',
                           case_id: str = '') -> Dict[str, Any]:
        """
        Export metadata-only JSON report (no video files).
        Lighter alternative for remote transmission.
        """
        report = {
            'case_id': case_id,
            'created_at': time.time(),
            'created_by': actor,
            'evidence_ids': evidence_ids,
        }

        # Add hash chain
        if self.integrity:
            report['hash_chain'] = self.integrity.export_chain()

        # Add custody trails
        if self.custody:
            trails = {}
            for eid in evidence_ids:
                trail = self.custody.get_trail(eid)
                trails[eid] = [e.to_dict() for e in trail]
            report['custody_trails'] = trails

        # Sign report
        report_json = json.dumps(report, sort_keys=True)
        report_hash = hashlib.sha256(report_json.encode()).hexdigest()
        report['signature'] = self._sign(report_hash)
        report['report_hash'] = report_hash

        try:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, 'w') as f:
                json.dump(report, f, indent=2)

            logger.info(f"JSON report exported: {output_path}")
            return {'success': True, 'output_path': output_path}

        except Exception as e:
            logger.error(f"JSON report export failed: {e}")
            return {'success': False, 'error': str(e)}

    def verify_package(self, package_path: str) -> tuple:
        """
        Verify a signed evidence package.

        Returns:
            (is_valid, list_of_errors)
        """
        errors = []

        try:
            with zipfile.ZipFile(package_path, 'r') as zf:
                # Read manifest
                if 'MANIFEST.json' not in zf.namelist():
                    return False, ['Missing MANIFEST.json']

                manifest_data = json.loads(zf.read('MANIFEST.json'))

                # Verify signature
                stored_hash = manifest_data.get('manifest_hash', '')
                stored_sig = manifest_data.get('signature', '')

                expected_sig = self._sign(stored_hash)
                if stored_sig != expected_sig:
                    errors.append('INVALID SIGNATURE — package may have been tampered with')

                # Verify archive hash
                computed_hash = self._compute_archive_hash(zf, exclude='MANIFEST.json')
                if computed_hash != stored_hash:
                    errors.append(
                        f'Archive hash mismatch: '
                        f'expected={stored_hash[:16]}, computed={computed_hash[:16]}'
                    )

                # Verify hash chain integrity
                if 'metadata/hash_chain.json' in zf.namelist():
                    chain_data = json.loads(zf.read('metadata/hash_chain.json'))
                    if self.integrity:
                        # Cross-reference with live chain
                        pass  # Advanced: compare against current chain

        except zipfile.BadZipFile:
            errors.append('Corrupt ZIP file')
        except Exception as e:
            errors.append(f'Verification error: {e}')

        is_valid = len(errors) == 0
        return is_valid, errors

    def _sign(self, data: str) -> str:
        """Compute HMAC-SHA256 signature."""
        return hmac.new(
            self._signing_key,
            data.encode(),
            hashlib.sha256
        ).hexdigest()

    @staticmethod
    def _compute_archive_hash(zf: zipfile.ZipFile,
                               exclude: str = '') -> str:
        """Compute combined hash of all files in the archive."""
        sha = hashlib.sha256()
        for name in sorted(zf.namelist()):
            if name == exclude:
                continue
            sha.update(name.encode())
            sha.update(zf.read(name))
        return sha.hexdigest()
