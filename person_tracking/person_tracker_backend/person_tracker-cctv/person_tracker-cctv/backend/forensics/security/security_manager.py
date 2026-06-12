"""
Security Manager (Phase 60)
Implements Zero-Trust architecture, RBAC, ABAC, and device trust validation.
"""
import logging
import time
from typing import Dict, Any, List

logger = logging.getLogger(__name__)


class SecurityManager:
    """
    Central enforcer for Zero-Trust policies, role-based, and attribute-based access control.
    """

    def __init__(self):
        self._roles = {
            "ADMIN": ["manage_users", "view_all", "export_evidence", "system_config"],
            "INVESTIGATOR": ["view_all", "export_evidence", "manage_cases"],
            "GUARD": ["view_live", "acknowledge_alerts"]
        }
        self._active_sessions: Dict[str, Dict] = {}
        self._metrics = {
            "auth_success": 0,
            "auth_failures": 0,
            "access_denied": 0,
            "zero_trust_blocks": 0
        }
        logger.info("SecurityManager initialized (Zero-Trust Mode Active)")

    def authenticate(self, user_id: str, token: str, device_context: dict) -> bool:
        """Authenticate user and validate device trust."""
        # Simulated authentication for demo/architecture purposes
        is_valid = bool(user_id and token)
        
        # Device trust validation (Phase 60)
        device_trusted = device_context.get("is_managed", False) or device_context.get("vpn_active", False)
        
        if is_valid and device_trusted:
            self._metrics["auth_success"] += 1
            session_id = f"SESS-{int(time.time())}-{user_id}"
            self._active_sessions[session_id] = {
                "user_id": user_id,
                "role": device_context.get("role", "GUARD"),
                "expires_at": time.time() + 3600, # 1 hour session
                "device": device_context
            }
            return True
            
        self._metrics["auth_failures"] += 1
        if is_valid and not device_trusted:
            self._metrics["zero_trust_blocks"] += 1
            logger.warning(f"Zero-Trust Block: Valid credentials from untrusted device for {user_id}")
            
        return False

    def authorize(self, session_id: str, action: str, resource_tags: List[str] = None) -> bool:
        """RBAC and ABAC authorization check."""
        session = self._active_sessions.get(session_id)
        if not session or session["expires_at"] < time.time():
            self._metrics["access_denied"] += 1
            return False
            
        # RBAC Check
        role = session["role"]
        has_permission = action in self._roles.get(role, [])
        
        if not has_permission:
            self._metrics["access_denied"] += 1
            logger.info(f"RBAC Deny: {session['user_id']} attempted {action}")
            return False
            
        # ABAC Check (Attribute-Based)
        # E.g. INVESTIGATOR can only view certain high-clearance cases if they have clearance
        if resource_tags and "HIGH_CLEARANCE" in resource_tags:
            if not session["device"].get("high_clearance_authorized", False):
                self._metrics["access_denied"] += 1
                logger.info(f"ABAC Deny: {session['user_id']} lacks high clearance attribute.")
                return False
                
        return True
        
    def get_metrics(self) -> dict:
        return dict(self._metrics)
