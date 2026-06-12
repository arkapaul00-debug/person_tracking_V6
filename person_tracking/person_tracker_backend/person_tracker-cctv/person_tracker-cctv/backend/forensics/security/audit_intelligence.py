"""
Audit Intelligence (Phase 62)
Centralized audit platform for all user, system, and security actions.
"""
import time
import logging
import threading
from typing import Dict, List, Any

logger = logging.getLogger(__name__)


class AuditIntelligence:
    """
    Centralized, immutable logging for all critical system actions.
    """

    def __init__(self):
        self._audit_log: List[Dict] = []
        self._lock = threading.Lock()
        self._metrics = {
            "total_audit_events": 0,
            "security_events": 0,
            "admin_events": 0
        }
        logger.info("AuditIntelligence initialized")

    def log_action(self, category: str, action: str, actor: str, target: str, details: Dict[str, Any] = None):
        """
        Log an action into the audit trail.
        Categories: SECURITY, ADMIN, SYSTEM, USER
        """
        entry = {
            "timestamp": time.time(),
            "category": category.upper(),
            "action": action.upper(),
            "actor": actor,
            "target": target,
            "details": details or {}
        }
        
        with self._lock:
            self._audit_log.append(entry)
            self._metrics["total_audit_events"] += 1
            
            if category.upper() == "SECURITY":
                self._metrics["security_events"] += 1
            elif category.upper() == "ADMIN":
                self._metrics["admin_events"] += 1
                
    def get_audit_trail(self, category: str = None, limit: int = 100) -> List[Dict]:
        """Retrieve recent audit logs, optionally filtered by category."""
        with self._lock:
            if category:
                cat_upper = category.upper()
                filtered = [log for log in self._audit_log if log["category"] == cat_upper]
                return filtered[-limit:]
            return self._audit_log[-limit:]

    def get_metrics(self) -> dict:
        with self._lock:
            return dict(self._metrics)
