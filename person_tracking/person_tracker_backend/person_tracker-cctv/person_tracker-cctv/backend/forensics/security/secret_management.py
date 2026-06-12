"""
Secret Management (Phase 61)
Centralized management of API keys, tokens, and certificates.
"""
import uuid
import time
import logging
from typing import Dict, Optional
import threading

logger = logging.getLogger(__name__)


class SecretManager:
    """
    Manages lifecycle of system secrets, API keys, and internal service tokens.
    """

    def __init__(self):
        self._secrets: Dict[str, Dict] = {}
        self._lock = threading.Lock()
        self._metrics = {
            "active_keys": 0,
            "revoked_keys": 0,
            "key_rotations": 0
        }
        logger.info("SecretManager initialized")

    def generate_api_key(self, service_name: str, expiry_days: int = 30) -> str:
        """Generate a new API key for a service."""
        key = f"sk_{service_name}_{uuid.uuid4().hex}"
        with self._lock:
            self._secrets[key] = {
                "service": service_name,
                "created_at": time.time(),
                "expires_at": time.time() + (expiry_days * 86400),
                "status": "ACTIVE"
            }
            self._metrics["active_keys"] += 1
        return key

    def validate_key(self, key: str) -> bool:
        """Check if an API key is valid and not expired."""
        with self._lock:
            secret = self._secrets.get(key)
            if not secret:
                return False
                
            if secret["status"] != "ACTIVE":
                return False
                
            if time.time() > secret["expires_at"]:
                secret["status"] = "EXPIRED"
                self._metrics["active_keys"] -= 1
                return False
                
            return True

    def revoke_key(self, key: str) -> bool:
        """Revoke an API key immediately."""
        with self._lock:
            if key in self._secrets and self._secrets[key]["status"] == "ACTIVE":
                self._secrets[key]["status"] = "REVOKED"
                self._metrics["active_keys"] -= 1
                self._metrics["revoked_keys"] += 1
                return True
        return False
        
    def get_metrics(self) -> dict:
        with self._lock:
            return dict(self._metrics)
