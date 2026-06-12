"""
Circuit Protection Framework (V5 Upgrade 10)
Platform-wide resilience layer with circuit breakers, bulkhead isolation,
and recovery orchestration to prevent cascading failures.
"""
import time
import logging
import threading
from typing import Dict, Any, Callable, Optional
from enum import Enum

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    CLOSED = "CLOSED"         # Normal operation
    OPEN = "OPEN"             # Failures detected, calls blocked
    HALF_OPEN = "HALF_OPEN"   # Probing with limited calls


class CircuitBreaker:
    """
    Individual circuit breaker for a single service/component.
    """

    def __init__(self, name: str, failure_threshold: int = 5,
                 cooldown_sec: float = 30.0):
        self.name = name
        self.failure_threshold = failure_threshold
        self.cooldown_sec = cooldown_sec

        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time = 0.0
        self.last_state_change = time.time()

    def can_execute(self) -> bool:
        """Check if a call should be allowed through this circuit."""
        if self.state == CircuitState.CLOSED:
            return True
        elif self.state == CircuitState.OPEN:
            if time.time() - self.last_state_change > self.cooldown_sec:
                self.state = CircuitState.HALF_OPEN
                self.last_state_change = time.time()
                logger.info(f"Circuit '{self.name}': OPEN → HALF_OPEN (probing)")
                return True  # Allow one probe call
            return False
        elif self.state == CircuitState.HALF_OPEN:
            return True  # Allow probe calls
        return False

    def record_success(self):
        """Record a successful call."""
        if self.state == CircuitState.HALF_OPEN:
            self.state = CircuitState.CLOSED
            self.failure_count = 0
            self.last_state_change = time.time()
            logger.info(f"Circuit '{self.name}': HALF_OPEN → CLOSED (recovered)")
        self.success_count += 1

    def record_failure(self):
        """Record a failed call."""
        self.failure_count += 1
        self.last_failure_time = time.time()

        if self.state == CircuitState.HALF_OPEN:
            # Probe failed, go back to OPEN
            self.state = CircuitState.OPEN
            self.last_state_change = time.time()
            logger.critical(f"Circuit '{self.name}': HALF_OPEN → OPEN (probe failed)")
        elif (self.state == CircuitState.CLOSED
              and self.failure_count >= self.failure_threshold):
            self.state = CircuitState.OPEN
            self.last_state_change = time.time()
            logger.critical(
                f"Circuit '{self.name}': CLOSED → OPEN "
                f"({self.failure_count} failures)"
            )

    def get_state(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "state": self.state.value,
            "failure_count": self.failure_count,
            "success_count": self.success_count,
        }


class CircuitProtectionFramework:
    """
    Manages circuit breakers for all critical subsystems.
    Provides a unified resilience layer across the entire platform.
    """

    DEFAULT_CIRCUITS = {
        "detection_pipeline": {"failure_threshold": 5, "cooldown_sec": 30},
        "reid_pipeline": {"failure_threshold": 3, "cooldown_sec": 20},
        "identity_graph": {"failure_threshold": 3, "cooldown_sec": 60},
        "evidence_vault": {"failure_threshold": 2, "cooldown_sec": 45},
        "websocket_broadcast": {"failure_threshold": 10, "cooldown_sec": 15},
        "feature_store": {"failure_threshold": 3, "cooldown_sec": 30},
        "gpu_orchestrator": {"failure_threshold": 2, "cooldown_sec": 60},
    }

    def __init__(self):
        self._lock = threading.RLock()
        self._circuits: Dict[str, CircuitBreaker] = {}

        # Initialize default circuits
        for name, config in self.DEFAULT_CIRCUITS.items():
            self._circuits[name] = CircuitBreaker(name, **config)

        self._metrics = {
            "total_circuits": len(self._circuits),
            "open_circuits": 0,
            "total_trips": 0,
            "total_recoveries": 0,
        }

        logger.info(
            f"V5 CircuitProtectionFramework initialized "
            f"({len(self._circuits)} circuits)"
        )

    def execute_protected(self, circuit_name: str,
                          func: Callable, *args, **kwargs) -> Any:
        """
        Execute a function with circuit breaker protection.
        If the circuit is OPEN, returns None immediately instead of calling func.
        """
        with self._lock:
            cb = self._circuits.get(circuit_name)
            if not cb:
                # Unknown circuit — execute unprotected
                return func(*args, **kwargs)

            if not cb.can_execute():
                self._metrics["open_circuits"] = sum(
                    1 for c in self._circuits.values()
                    if c.state == CircuitState.OPEN
                )
                return None  # Circuit is OPEN — block the call

        # Execute outside the lock
        try:
            result = func(*args, **kwargs)
            with self._lock:
                prev_state = cb.state
                cb.record_success()
                if prev_state == CircuitState.HALF_OPEN and cb.state == CircuitState.CLOSED:
                    self._metrics["total_recoveries"] += 1
            return result
        except Exception as e:
            with self._lock:
                prev_state = cb.state
                cb.record_failure()
                if cb.state == CircuitState.OPEN and prev_state != CircuitState.OPEN:
                    self._metrics["total_trips"] += 1
                self._metrics["open_circuits"] = sum(
                    1 for c in self._circuits.values()
                    if c.state == CircuitState.OPEN
                )
            logger.error(f"Circuit '{circuit_name}' recorded failure: {e}")
            return None

    def get_circuit_states(self) -> Dict[str, Dict[str, Any]]:
        """Get the state of all circuits."""
        with self._lock:
            return {name: cb.get_state() for name, cb in self._circuits.items()}

    def get_metrics(self) -> dict:
        with self._lock:
            return dict(self._metrics)
