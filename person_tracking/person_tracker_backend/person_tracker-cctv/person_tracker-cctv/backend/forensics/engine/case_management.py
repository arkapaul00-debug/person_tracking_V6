"""
Case Management Engine (Phase 52)
Case-centric investigation workflows.

Capabilities:
- Case creation and assignment
- Evidence attachment
- Timeline generation
- Suspect and event linking
- Full audit trails

Usage:
    manager = CaseManagementEngine()
    case = manager.create_case("Theft in Lobby", "investigator_01")
    manager.attach_evidence(case.id, evidence_id, "investigator_01")
"""
import uuid
import time
import logging
from typing import Dict, List, Any, Optional
import threading

logger = logging.getLogger(__name__)


class CaseManagementEngine:
    """
    Manages active investigations, grouping evidence, suspects, and timelines
    into unified 'Cases'. Backed by an in-memory dictionary for now,
    designed to be serialized to a database.
    """

    def __init__(self):
        self._cases: Dict[str, Dict] = {}
        self._audit_log: List[Dict] = []
        self._lock = threading.Lock()
        logger.info("CaseManagementEngine initialized")

    def create_case(self, title: str, created_by: str, description: str = "") -> str:
        """Create a new investigation case."""
        case_id = f"CASE-{uuid.uuid4().hex[:8].upper()}"
        now = time.time()
        
        case = {
            "case_id": case_id,
            "title": title,
            "description": description,
            "status": "OPEN",
            "created_by": created_by,
            "created_at": now,
            "updated_at": now,
            "assigned_to": created_by,
            "evidence": [],
            "suspects": [],
            "events": []
        }
        
        with self._lock:
            self._cases[case_id] = case
            self._log_audit(case_id, "CASE_CREATED", created_by, {"title": title})
            
        return case_id

    def attach_evidence(self, case_id: str, evidence_id: str, user: str, metadata: dict = None) -> bool:
        """Attach an existing piece of evidence to a case."""
        with self._lock:
            if case_id not in self._cases:
                return False
            
            attachment = {
                "evidence_id": evidence_id,
                "attached_by": user,
                "attached_at": time.time(),
                "metadata": metadata or {}
            }
            self._cases[case_id]["evidence"].append(attachment)
            self._cases[case_id]["updated_at"] = time.time()
            self._log_audit(case_id, "EVIDENCE_ATTACHED", user, {"evidence_id": evidence_id})
            return True

    def link_suspect(self, case_id: str, identity_id: str, user: str, role: str = "SUSPECT") -> bool:
        """Link a tracked identity to a case."""
        with self._lock:
            if case_id not in self._cases:
                return False
                
            link = {
                "identity_id": identity_id,
                "role": role,
                "linked_by": user,
                "linked_at": time.time()
            }
            self._cases[case_id]["suspects"].append(link)
            self._cases[case_id]["updated_at"] = time.time()
            self._log_audit(case_id, "SUSPECT_LINKED", user, {"identity_id": identity_id, "role": role})
            return True

    def update_status(self, case_id: str, status: str, user: str) -> bool:
        """Update case status (OPEN, CLOSED, ARCHIVED)."""
        with self._lock:
            if case_id not in self._cases:
                return False
            old_status = self._cases[case_id]["status"]
            self._cases[case_id]["status"] = status
            self._cases[case_id]["updated_at"] = time.time()
            self._log_audit(case_id, "STATUS_CHANGED", user, {"from": old_status, "to": status})
            return True

    def get_case(self, case_id: str) -> Optional[Dict]:
        """Retrieve full case details."""
        with self._lock:
            return self._cases.get(case_id)

    def _log_audit(self, case_id: str, action: str, user: str, details: dict):
        """Internal audit logging for all case actions."""
        self._audit_log.append({
            "case_id": case_id,
            "action": action,
            "user": user,
            "timestamp": time.time(),
            "details": details
        })

    def get_metrics(self) -> dict:
        with self._lock:
            active_cases = sum(1 for c in self._cases.values() if c["status"] == "OPEN")
            return {
                "total_cases": len(self._cases),
                "active_cases": active_cases,
                "total_audit_events": len(self._audit_log)
            }
