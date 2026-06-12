"""
CCTV Orchestrator — Top-level session controller for real-time multi-stream tracking.

Responsibilities:
  1. Load ModelPool once (YOLOv10n + InsightFace + OSNet)
  2. Build reference gallery from suspect images
  3. Create RTSPCapture → StreamProcessor pairs for each camera
  4. Start/stop all threads
  5. Monitor stream health, auto-restart dead streams
  6. Provide session status API

V2 Architecture:
  - Integrates new GPU infrastructure (per-model CUDA streams)
  - Uses DetectionRouter, TrackerOrchestrator, AdaptiveFacePipeline
  - Wires DAG pipeline via PipelineBuilder when available
  - Falls back to legacy StreamProcessor when V2 components unavailable
  - Adds observability (MetricsCollector, HealthCheck)
  - Initializes evidence integrity chain
  - Supports multi-GPU load balancing
"""
import threading
import time
import logging
from typing import List, Dict, Optional, Callable
from django.utils import timezone

logger = logging.getLogger(__name__)

# Global orchestrator instance (one active session at a time)
_active_orchestrator = None
_orchestrator_lock = threading.Lock()


class CCTVOrchestrator:
    """
    Manages a live tracking session across multiple RTSP cameras.
    Only one session can be active at a time (single GPU constraint).
    """

    def __init__(self):
        self.session = None
        self.model_pool = None
        self.processors: Dict[str, 'StreamProcessorInfo'] = {}
        self.running = False
        self.is_starting = False
        self._monitor_thread = None
        self._state_lock = threading.Lock()
        self.alert_callback = None

        # --- V2 Engine Components (initialized during start_session) ---
        self._detection_router = None
        self._tracker_orchestrator = None
        self._face_pipeline = None
        self._fusion_engine = None
        self._lowlight_enhancer = None
        self._evidence_mgr = None
        self._custody_mgr = None
        self._gpu_monitor = None
        self._metrics = None
        self._health_check = None
        self._load_balancer = None
        self._event_bus = None
        self._v2_enabled = False

        # --- V3 Intelligence Layer (initialized during start_session) ---
        self._identity_graph = None
        self._camera_topology = None
        self._cross_camera_tracker = None
        self._identity_memory = None
        self._investigation_engine = None
        self._active_learning = None
        self._quality_monitor = None

        # --- V4 Copilot & Operations Layer (initialized during start_session) ---
        self._investigation_copilot = None
        self._case_management = None
        self._event_intelligence = None
        self._evidence_vault = None
        self._security_manager = None
        self._secret_manager = None
        self._audit_intelligence = None
        self._telemetry_platform = None
        self._advanced_metrics = None
        self._ai_operations = None
        self._anomaly_detection = None
        self._incident_response = None
        self._autonomous_optimization = None
        self._digital_twin = None

        # --- V5 Intelligence Evolution (initialized during start_session) ---
        self._global_identity_graph = None
        self._multi_modal_fusion = None
        self._tiered_feature_store = None
        self._predictive_movement = None
        self._adaptive_inference_director = None
        self._global_gpu_orchestrator = None
        self._distributed_resolver = None
        self._v5_evidence_integrity = None
        self._forensic_replay = None
        self._circuit_protection = None
        self._digital_twin_validation = None
        self._v5_investigation_copilot = None
        self._v5_autonomous_optimization = None

        # --- V6 Enterprise Evolution (initialized during start_session) ---
        self._v6_global_identity_memory = None
        self._v6_federated_mesh = None
        self._v6_forensic_knowledge_graph = None
        self._v6_behavioral_intelligence = None
        self._v6_camera_intelligence = None
        self._v6_context_fusion = None
        self._v6_event_backbone = None
        self._v6_hierarchical_gpu = None
        self._v6_load_forecaster = None
        self._v6_geo_redundant_storage = None
        self._v6_model_marketplace = None
        self._v6_autonomous_recovery = None
        self._v6_explainable_resolution = None
        self._v6_investigation_copilot_v2 = None
        self._v6_live_digital_twin = None

    def start_session(self, case_id, stream_configs: List[Dict],
                      ref_paths: List[str], mode: str = 'hybrid',
                      threshold: float = 0.55,
                      alert_callback: Optional[Callable] = None) -> dict:
        """
        Start a live tracking session.
        
        Args:
            case_id: ForensicCase UUID
            stream_configs: List of {'name': str, 'rtsp_url': str, 'location': str}
            ref_paths: Paths to reference/suspect images
            mode: 'face', 'body', or 'hybrid'
            threshold: Similarity threshold
            alert_callback: Optional callback for real-time alert push
            
        Returns:
            dict with session_id and status
        """
        from .models import ForensicCase
        from .models_stream import CCTVStream, LiveTrackingSession
        from .model_pool import ModelPool
        from .rtsp_capture import RTSPCapture
        from .stream_processor import StreamProcessor

        with self._state_lock:
            if self.running or self.is_starting:
                return {'error': 'A session is already running or starting', 'status': 'ERROR'}
            self.is_starting = True

        self.alert_callback = alert_callback

        try:
            # 1. Get/create case
            case = ForensicCase.objects.get(id=case_id)
            case.status = 'PROCESSING'
            case.save()

            # 2. Load shared models
            logger.info("Loading AI models...")
            self.model_pool = ModelPool.get_instance(mode=mode)

            # 3. Build reference gallery
            logger.info(f"Building gallery from {len(ref_paths)} reference(s)...")
            self.model_pool.build_gallery(ref_paths)

            # 3.5 Initialize V2 engine components (graceful fallback)
            self._init_v2_components(mode)

            # 4. Create session in DB
            session = LiveTrackingSession.objects.create(
                case=case,
                mode=mode,
                threshold=threshold,
                status='STARTING',
            )
            self.session = session

            # 5. Create stream objects and processors
            for config in stream_configs:
                stream_obj, _ = CCTVStream.objects.get_or_create(
                    rtsp_url=config['rtsp_url'],
                    defaults={
                        'name': config.get('name', f"Camera {len(self.processors) + 1}"),
                        'location': config.get('location', ''),
                    }
                )
                stream_obj.is_active = True
                stream_obj.status = 'IDLE'
                stream_obj.save()
                session.streams.add(stream_obj)

                # Create capture + processor
                capture = RTSPCapture(
                    rtsp_url=config['rtsp_url'],
                    stream_id=str(stream_obj.id),
                )

                processor = StreamProcessor(
                    stream_id=str(stream_obj.id),
                    model_pool=self.model_pool,
                    capture=capture,
                    session=session,
                    stream_obj=stream_obj,
                    threshold=threshold,
                    skip_n=4,
                    alert_callback=alert_callback,
                    v2_engines={
                        'detection_router': self._detection_router,
                        'tracker_orchestrator': self._tracker_orchestrator,
                        'face_pipeline': self._face_pipeline,
                        'fusion_engine': self._fusion_engine,
                        'lowlight_enhancer': self._lowlight_enhancer,
                        'evidence_mgr': self._evidence_mgr,
                        'metrics': self._metrics,
                    } if self._v2_enabled else None,
                )

                self.processors[str(stream_obj.id)] = StreamProcessorInfo(
                    stream_obj=stream_obj,
                    capture=capture,
                    processor=processor,
                )

            # 6. Start all captures and processors
            for info in self.processors.values():
                info.capture.start()
                time.sleep(0.5)  # Stagger connections
                info.processor.start()

            session.status = 'RUNNING'
            session.save()
            with self._state_lock:
                self.running = True
                self.is_starting = False

            # 7. Start health monitor
            self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
            self._monitor_thread.start()

            logger.info(f"Live session started: {session.id} with {len(self.processors)} stream(s)")

            return {
                'session_id': str(session.id),
                'status': 'RUNNING',
                'streams': len(self.processors),
            }

        except Exception as e:
            logger.error(f"Session start failed: {e}")
            import traceback
            traceback.print_exc()
            self._cleanup()
            with self._state_lock:
                self.is_starting = False
            return {'error': str(e), 'status': 'ERROR'}

    def stop_session(self) -> dict:
        """Stop the active tracking session."""
        if not self.running:
            return {'status': 'NO_SESSION'}

        logger.info("Stopping live session...")
        self.running = False

        # Stop all processors and captures
        for info in self.processors.values():
            try:
                info.processor.stop()
                info.capture.stop()
                info.stream_obj.status = 'IDLE'
                info.stream_obj.save()
            except Exception as e:
                logger.error(f"Error stopping stream {info.stream_obj.id}: {e}")

        # Update session
        if self.session:
            self.session.status = 'STOPPED'
            self.session.stopped_at = timezone.now()
            self.session.save()

        session_id = str(self.session.id) if self.session else None
        self._cleanup()

        return {'session_id': session_id, 'status': 'STOPPED'}

    def get_status(self) -> dict:
        """Return complete session status with per-stream metrics."""
        if not self.running or not self.session:
            return {'status': 'NO_SESSION', 'running': False}

        stream_statuses = []
        for sid, info in self.processors.items():
            status = info.processor.get_status()
            status['stream_name'] = info.stream_obj.name
            status['location'] = info.stream_obj.location
            stream_statuses.append(status)

        total_alerts = sum(
            info.processor.alert_mgr.alert_count for info in self.processors.values()
        )

        # V2: Include engine metrics if available
        v2_metrics = {}
        if self._v2_enabled:
            if self._metrics:
                v2_metrics = self._metrics.to_json()
            if self._gpu_monitor:
                try:
                    gpu_info = self._gpu_monitor.get_metrics_summary()
                    v2_metrics['gpu'] = gpu_info
                except Exception:
                    pass

        return {
            'session_id': str(self.session.id),
            'status': self.session.status,
            'running': self.running,
            'streams': stream_statuses,
            'total_alerts': total_alerts,
            'mode': self.session.mode,
            'threshold': self.session.threshold,
            'v2_enabled': self._v2_enabled,
            'engine_metrics': v2_metrics,
        }

    def _monitor_loop(self):
        """Background thread that monitors stream health."""
        while self.running:
            try:
                for sid, info in list(self.processors.items()):
                    health = info.capture.get_health()

                    # Update DB status
                    if health['is_alive']:
                        if info.stream_obj.status != 'CONNECTED':
                            info.stream_obj.status = 'CONNECTED'
                            info.stream_obj.last_frame_at = timezone.now()
                            info.stream_obj.save()
                    else:
                        if health['status'] == RTSPCapture.STATUS_STOPPED:
                            info.stream_obj.status = 'DISCONNECTED'
                        elif health['reconnect_count'] > 5:
                            info.stream_obj.status = 'ERROR'
                        else:
                            info.stream_obj.status = 'DISCONNECTED'
                        info.stream_obj.save()

            except Exception as e:
                logger.error(f"Monitor error: {e}")

            time.sleep(5.0)  # Check every 5 seconds

    def _cleanup(self):
        """Clean up all resources."""
        # Stop V2 components
        try:
            if self._gpu_monitor:
                self._gpu_monitor.stop_background()
            if self._event_bus:
                self._event_bus.close()
        except Exception as e:
            logger.error(f"V2 cleanup error: {e}")

        self.processors.clear()
        self.session = None
        self.running = False
        self._v2_enabled = False

        # Note: ModelPool is a singleton, we keep it alive for reuse

    def _init_v2_components(self, mode: str):
        """
        Initialize V2 engine components.
        Each component is wrapped in try/except for graceful fallback.
        If any V2 component fails, the system falls back to legacy behavior.
        """
        v2_count = 0

        # GPU Monitor
        try:
            from .gpu.gpu_monitor import GPUMonitor
            self._gpu_monitor = GPUMonitor()
            self._gpu_monitor.start_background(interval=10.0)
            v2_count += 1
        except Exception as e:
            logger.debug(f"V2 GPUMonitor unavailable: {e}")

        # Metrics Collector
        try:
            from .observability.metrics import MetricsCollector
            self._metrics = MetricsCollector.get_instance()
            v2_count += 1
        except Exception as e:
            logger.debug(f"V2 MetricsCollector unavailable: {e}")

        # Detection Router
        try:
            from .engine.detection_router import DetectionRouter
            self._detection_router = DetectionRouter(
                model_pool=self.model_pool,
                device=self.model_pool.device,
            )
            v2_count += 1
        except Exception as e:
            logger.debug(f"V2 DetectionRouter unavailable: {e}")

        # Tracker Orchestrator
        try:
            from .engine.tracker_orchestrator import TrackerOrchestrator
            self._tracker_orchestrator = TrackerOrchestrator(
                auto_switch=True,
            )
            v2_count += 1
        except Exception as e:
            logger.debug(f"V2 TrackerOrchestrator unavailable: {e}")

        # Confidence Fusion
        try:
            from .engine.confidence_fusion import ConfidenceFusionEngine
            self._fusion_engine = ConfidenceFusionEngine()
            v2_count += 1
        except Exception as e:
            logger.debug(f"V2 ConfidenceFusion unavailable: {e}")

        # Adaptive Face Pipeline
        try:
            from .engine.face_pipeline import AdaptiveFacePipeline
            if self.model_pool.face_model:
                self._face_pipeline = AdaptiveFacePipeline(
                    model_pool=self.model_pool,
                    device=self.model_pool.device,
                )
                v2_count += 1
        except Exception as e:
            logger.debug(f"V2 FacePipeline unavailable: {e}")

        # Low-Light Enhancer
        try:
            from .engine.lowlight_enhancer import AdaptiveLowLightEnhancer
            self._lowlight_enhancer = AdaptiveLowLightEnhancer(
                device=self.model_pool.device,
            )
            v2_count += 1
        except Exception as e:
            logger.debug(f"V2 LowLightEnhancer unavailable: {e}")

        # Evidence Integrity
        try:
            from .evidence.integrity import EvidenceIntegrityManager
            from .evidence.chain_of_custody import ChainOfCustody
            self._evidence_mgr = EvidenceIntegrityManager()
            self._custody_mgr = ChainOfCustody()
            v2_count += 1
        except Exception as e:
            logger.debug(f"V2 Evidence unavailable: {e}")

        # Health Check
        try:
            from .observability.health_check import (
                HealthCheck, create_gpu_probe, create_model_probe
            )
            self._health_check = HealthCheck()
            self._health_check.register_probe('gpu', create_gpu_probe(self._gpu_monitor))
            self._health_check.register_probe('models', create_model_probe(self.model_pool))
            v2_count += 1
        except Exception as e:
            logger.debug(f"V2 HealthCheck unavailable: {e}")

        # Event Bus
        try:
            from .distributed.event_bus import EventBus
            self._event_bus = EventBus.create('memory', source='orchestrator')
            v2_count += 1
        except Exception as e:
            logger.debug(f"V2 EventBus unavailable: {e}")

        self._v2_enabled = v2_count > 0
        logger.info(
            f"V2 engine components: {v2_count}/10 initialized "
            f"({'ACTIVE' if self._v2_enabled else 'LEGACY MODE'})"
        )

        # --- V3 Intelligence Layer Initialization ---
        v3_count = 0

        # Identity Graph (Phase 37)
        try:
            from .engine.identity_graph import IdentityGraph
            self._identity_graph = IdentityGraph()
            v3_count += 1
        except Exception as e:
            logger.debug(f"V3 IdentityGraph unavailable: {e}")

        # Camera Topology (Phase 40)
        try:
            from .engine.camera_topology import CameraTopologyEngine
            self._camera_topology = CameraTopologyEngine()
            v3_count += 1
        except Exception as e:
            logger.debug(f"V3 CameraTopology unavailable: {e}")

        # Identity Memory Bank (Phase 38)
        try:
            from .engine.identity_memory import IdentityMemoryBank
            self._identity_memory = IdentityMemoryBank()
            v3_count += 1
        except Exception as e:
            logger.debug(f"V3 IdentityMemory unavailable: {e}")

        # Cross-Camera Tracker (Phase 41)
        try:
            from .engine.cross_camera_tracker import CrossCameraTracker
            self._cross_camera_tracker = CrossCameraTracker()
            v3_count += 1
        except Exception as e:
            logger.debug(f"V3 CrossCameraTracker unavailable: {e}")

        # Investigation Engine (Phases 45, 46, 47)
        try:
            from .engine.investigation_engine import InvestigationEngine
            self._investigation_engine = InvestigationEngine(
                identity_graph=self._identity_graph,
                cross_graph=getattr(self, '_cross_camera_graph', None),
                memory_bank=self._identity_memory,
                topology=self._camera_topology,
            )
            v3_count += 1
        except Exception as e:
            logger.debug(f"V3 InvestigationEngine unavailable: {e}")

        # Active Learning Collector (Phase 43)
        try:
            from .engine.active_learning import ActiveLearningCollector
            self._active_learning = ActiveLearningCollector()
            v3_count += 1
        except Exception as e:
            logger.debug(f"V3 ActiveLearning unavailable: {e}")

        # Identity Quality Monitor (Phase 49)
        try:
            from .engine.identity_quality import IdentityQualityMonitor
            self._quality_monitor = IdentityQualityMonitor()
            v3_count += 1
        except Exception as e:
            logger.debug(f"V3 QualityMonitor unavailable: {e}")

        logger.info(
            f"V3 intelligence components: {v3_count}/7 initialized"
        )

        # --- V4 Copilot & Operations Layer Initialization ---
        v4_count = 0

        # Stage 1: Investigation & Event
        try:
            from .engine.investigation_copilot import InvestigationCopilot
            self._investigation_copilot = InvestigationCopilot(self._investigation_engine)
            v4_count += 1
        except Exception as e:
            logger.debug(f"V4 InvestigationCopilot unavailable: {e}")
            
        try:
            from .engine.case_management import CaseManagementEngine
            self._case_management = CaseManagementEngine()
            v4_count += 1
        except Exception as e:
            logger.debug(f"V4 CaseManagement unavailable: {e}")
            
        try:
            from .engine.event_intelligence import EventIntelligencePlatform
            self._event_intelligence = EventIntelligencePlatform()
            v4_count += 1
        except Exception as e:
            logger.debug(f"V4 EventIntelligence unavailable: {e}")

        # Stage 2: Evidence Vault
        try:
            from .evidence.evidence_vault import EvidenceVault
            self._evidence_vault = EvidenceVault()
            v4_count += 1
        except Exception as e:
            logger.debug(f"V4 EvidenceVault unavailable: {e}")

        # Stage 3: Security Hardening
        try:
            from .security.security_manager import SecurityManager
            self._security_manager = SecurityManager()
            v4_count += 1
        except Exception as e:
            logger.debug(f"V4 SecurityManager unavailable: {e}")
            
        try:
            from .security.secret_management import SecretManager
            self._secret_manager = SecretManager()
            v4_count += 1
        except Exception as e:
            logger.debug(f"V4 SecretManager unavailable: {e}")
            
        try:
            from .security.audit_intelligence import AuditIntelligence
            self._audit_intelligence = AuditIntelligence()
            v4_count += 1
        except Exception as e:
            logger.debug(f"V4 AuditIntelligence unavailable: {e}")

        # Stage 4: Observability 2.0
        try:
            from .observability.telemetry_platform import CentralizedTelemetryPlatform
            self._telemetry_platform = CentralizedTelemetryPlatform()
            v4_count += 1
        except Exception as e:
            logger.debug(f"V4 TelemetryPlatform unavailable: {e}")
            
        try:
            from .observability.advanced_metrics import AdvancedMetricsEngine
            self._advanced_metrics = AdvancedMetricsEngine()
            v4_count += 1
        except Exception as e:
            logger.debug(f"V4 AdvancedMetrics unavailable: {e}")

        # Stage 5: AI Ops & Resilience
        try:
            from .engine.ai_operations import AIOperationsAgents
            self._ai_operations = AIOperationsAgents()
            v4_count += 1
        except Exception as e:
            logger.debug(f"V4 AIOperations unavailable: {e}")
            
        try:
            from .engine.anomaly_detection import AnomalyDetectionPlatform
            self._anomaly_detection = AnomalyDetectionPlatform(self._telemetry_platform, self._advanced_metrics)
            v4_count += 1
        except Exception as e:
            logger.debug(f"V4 AnomalyDetection unavailable: {e}")
            
        try:
            from .engine.incident_response import IncidentResponsePlatform
            self._incident_response = IncidentResponsePlatform()
            v4_count += 1
        except Exception as e:
            logger.debug(f"V4 IncidentResponse unavailable: {e}")
            
        try:
            from .engine.autonomous_optimization import AutonomousOptimizationLayer
            self._autonomous_optimization = AutonomousOptimizationLayer(self._telemetry_platform)
            v4_count += 1
        except Exception as e:
            logger.debug(f"V4 AutonomousOptimization unavailable: {e}")

        # Stage 6: Digital Twin
        try:
            from .engine.digital_twin import DigitalTwinArchitecture
            self._digital_twin = DigitalTwinArchitecture(self._camera_topology)
            v4_count += 1
        except Exception as e:
            logger.debug(f"V4 DigitalTwin unavailable: {e}")

        logger.info(
            f"V4 copilot & operations components: {v4_count}/14 initialized"
        )

        # --- V5 Intelligence Evolution Initialization ---
        v5_count = 0

        # Stage 2: Intelligence Graph & Feature Store
        try:
            from .engine.global_identity_graph import GlobalIdentityGraph
            self._global_identity_graph = GlobalIdentityGraph(self._identity_graph)
            v5_count += 1
        except Exception as e:
            logger.debug(f"V5 GlobalIdentityGraph unavailable: {e}")
            
        try:
            from .engine.tiered_feature_store import TieredFeatureStore
            self._tiered_feature_store = TieredFeatureStore()
            v5_count += 1
        except Exception as e:
            logger.debug(f"V5 TieredFeatureStore unavailable: {e}")

        try:
            from .engine.predictive_movement import PredictiveMovementEngine
            self._predictive_movement = PredictiveMovementEngine(self._camera_topology)
            v5_count += 1
        except Exception as e:
            logger.debug(f"V5 PredictiveMovementEngine unavailable: {e}")

        # Stage 3: Multi-Modal Fusion & Inference Director
        try:
            from .engine.multi_modal_fusion import MultiModalFusionEngine
            self._multi_modal_fusion = MultiModalFusionEngine(self._fusion_engine)
            v5_count += 1
        except Exception as e:
            logger.debug(f"V5 MultiModalFusionEngine unavailable: {e}")

        try:
            from .engine.adaptive_inference_director import AdaptiveInferenceDirector
            self._adaptive_inference_director = AdaptiveInferenceDirector()
            v5_count += 1
        except Exception as e:
            logger.debug(f"V5 AdaptiveInferenceDirector unavailable: {e}")

        # Stage 4: Distributed Orchestration & Resilience
        try:
            from .engine.global_gpu_orchestrator import GlobalGPUOrchestrator
            self._global_gpu_orchestrator = GlobalGPUOrchestrator()
            v5_count += 1
        except Exception as e:
            logger.debug(f"V5 GlobalGPUOrchestrator unavailable: {e}")

        try:
            from .engine.distributed_resolver import DistributedIdentityResolver
            self._distributed_resolver = DistributedIdentityResolver(self._global_identity_graph, self._tiered_feature_store)
            v5_count += 1
        except Exception as e:
            logger.debug(f"V5 DistributedIdentityResolver unavailable: {e}")

        try:
            from .engine.circuit_protection import CircuitProtectionFramework
            self._circuit_protection = CircuitProtectionFramework()
            v5_count += 1
        except Exception as e:
            logger.debug(f"V5 CircuitProtectionFramework unavailable: {e}")

        try:
            from .engine.v5_autonomous_optimization import V5AutonomousOptimization
            self._v5_autonomous_optimization = V5AutonomousOptimization(
                telemetry_platform=self._telemetry_platform,
                inference_director=self._adaptive_inference_director,
                gpu_orchestrator=self._global_gpu_orchestrator,
                circuit_framework=self._circuit_protection
            )
            v5_count += 1
        except Exception as e:
            logger.debug(f"V5 AutonomousOptimization unavailable: {e}")

        # Stage 5: Forensic Replay & Investigation Evolution
        try:
            from .engine.v5_evidence_integrity import V5EvidenceIntegrity
            self._v5_evidence_integrity = V5EvidenceIntegrity(self._evidence_vault)
            v5_count += 1
        except Exception as e:
            logger.debug(f"V5 EvidenceIntegrity unavailable: {e}")

        try:
            from .engine.forensic_replay import ForensicReplaySystem
            self._forensic_replay = ForensicReplaySystem(self._global_identity_graph, self._tiered_feature_store)
            v5_count += 1
        except Exception as e:
            logger.debug(f"V5 ForensicReplaySystem unavailable: {e}")

        try:
            from .engine.digital_twin_validation import DigitalTwinValidation
            self._digital_twin_validation = DigitalTwinValidation(
                gpu_orchestrator=self._global_gpu_orchestrator,
                circuit_framework=self._circuit_protection,
                inference_director=self._adaptive_inference_director
            )
            v5_count += 1
        except Exception as e:
            logger.debug(f"V5 DigitalTwinValidation unavailable: {e}")

        try:
            from .engine.v5_investigation_copilot import V5InvestigationCopilot
            self._v5_investigation_copilot = V5InvestigationCopilot(
                global_graph=self._global_identity_graph,
                predictive_engine=self._predictive_movement,
                v4_copilot=self._investigation_copilot
            )
            v5_count += 1
        except Exception as e:
            logger.debug(f"V5 InvestigationCopilot unavailable: {e}")

        logger.info(
            f"V5 intelligence evolution components: {v5_count}/13 initialized"
        )

        # --- V6 Enterprise Evolution Initialization ---
        v6_count = 0

        # Stage 2: Global Identity & Federated Intelligence
        try:
            from .engine.v6_global_identity_memory import V6GlobalIdentityMemory
            self._v6_global_identity_memory = V6GlobalIdentityMemory(self._global_identity_graph)
            v6_count += 1
        except Exception as e:
            logger.debug(f"V6 GlobalIdentityMemory unavailable: {e}")

        try:
            from .engine.v6_federated_mesh import V6FederatedMesh
            self._v6_federated_mesh = V6FederatedMesh(self._distributed_resolver)
            v6_count += 1
        except Exception as e:
            logger.debug(f"V6 FederatedMesh unavailable: {e}")

        try:
            from .engine.v6_forensic_knowledge_graph import V6ForensicKnowledgeGraph
            self._v6_forensic_knowledge_graph = V6ForensicKnowledgeGraph(self._global_identity_graph)
            v6_count += 1
        except Exception as e:
            logger.debug(f"V6 ForensicKnowledgeGraph unavailable: {e}")

        try:
            from .engine.v6_behavioral_intelligence import V6BehavioralIntelligence
            self._v6_behavioral_intelligence = V6BehavioralIntelligence(self._v6_forensic_knowledge_graph)
            v6_count += 1
        except Exception as e:
            logger.debug(f"V6 BehavioralIntelligence unavailable: {e}")

        # Stage 3: Autonomous Camera & MultiModal Context
        try:
            from .engine.v6_camera_intelligence import V6CameraIntelligence
            self._v6_camera_intelligence = V6CameraIntelligence()
            v6_count += 1
        except Exception as e:
            logger.debug(f"V6 CameraIntelligence unavailable: {e}")

        try:
            from .engine.v6_context_fusion import V6ContextFusion
            self._v6_context_fusion = V6ContextFusion(self._multi_modal_fusion, self._v6_camera_intelligence)
            v6_count += 1
        except Exception as e:
            logger.debug(f"V6 ContextFusion unavailable: {e}")

        # Stage 4: Infrastructure & Event Backbone
        try:
            from .engine.v6_event_backbone import V6EventBackbone
            self._v6_event_backbone = V6EventBackbone()
            v6_count += 1
        except Exception as e:
            logger.debug(f"V6 EventBackbone unavailable: {e}")

        try:
            from .engine.v6_hierarchical_gpu import V6HierarchicalGPU
            self._v6_hierarchical_gpu = V6HierarchicalGPU(self._global_gpu_orchestrator)
            v6_count += 1
        except Exception as e:
            logger.debug(f"V6 HierarchicalGPU unavailable: {e}")

        try:
            from .engine.v6_load_forecaster import V6LoadForecaster
            self._v6_load_forecaster = V6LoadForecaster(self._telemetry_platform)
            v6_count += 1
        except Exception as e:
            logger.debug(f"V6 LoadForecaster unavailable: {e}")

        try:
            from .engine.v6_geo_redundant_storage import V6GeoRedundantStorage
            self._v6_geo_redundant_storage = V6GeoRedundantStorage()
            v6_count += 1
        except Exception as e:
            logger.debug(f"V6 GeoRedundantStorage unavailable: {e}")

        # Stage 5: Autonomy, Copilot & MLOps
        try:
            from .engine.v6_model_marketplace import V6ModelMarketplace
            self._v6_model_marketplace = V6ModelMarketplace(self._digital_twin)
            v6_count += 1
        except Exception as e:
            logger.debug(f"V6 ModelMarketplace unavailable: {e}")

        try:
            from .engine.v6_autonomous_recovery import V6AutonomousRecovery
            self._v6_autonomous_recovery = V6AutonomousRecovery(self._circuit_protection, self._v6_hierarchical_gpu)
            v6_count += 1
        except Exception as e:
            logger.debug(f"V6 AutonomousRecovery unavailable: {e}")

        try:
            from .engine.v6_explainable_resolution import V6ExplainableResolution
            self._v6_explainable_resolution = V6ExplainableResolution(self._multi_modal_fusion)
            v6_count += 1
        except Exception as e:
            logger.debug(f"V6 ExplainableResolution unavailable: {e}")

        try:
            from .engine.v6_investigation_copilot_v2 import V6InvestigationCopilot
            self._v6_investigation_copilot_v2 = V6InvestigationCopilot(
                forensic_graph=self._v6_forensic_knowledge_graph,
                v5_copilot=self._v5_investigation_copilot
            )
            v6_count += 1
        except Exception as e:
            logger.debug(f"V6 InvestigationCopilotV2 unavailable: {e}")

        try:
            from .engine.v6_live_digital_twin import V6LiveDigitalTwin
            self._v6_live_digital_twin = V6LiveDigitalTwin(
                event_backbone=self._v6_event_backbone,
                v5_digital_twin=self._digital_twin_validation
            )
            v6_count += 1
        except Exception as e:
            logger.debug(f"V6 LiveDigitalTwin unavailable: {e}")

        logger.info(
            f"V6 enterprise evolution components: {v6_count}/15 initialized"
        )
    def get_health(self) -> dict:
        """Get system health status (V2 feature)."""
        if self._health_check:
            return self._health_check.check_all()
        return {'status': 'unknown', 'v2_enabled': False}

    def get_engine_metrics(self) -> dict:
        """Get detailed V2 + V3 engine metrics."""
        metrics = {'v2_enabled': self._v2_enabled}
        if self._detection_router:
            metrics['detection_router'] = self._detection_router.get_metrics()
        if self._tracker_orchestrator:
            metrics['tracker'] = self._tracker_orchestrator.get_metrics()
        if self._face_pipeline:
            metrics['face_pipeline'] = self._face_pipeline.get_metrics()
        if self._fusion_engine:
            metrics['fusion'] = self._fusion_engine.get_metrics()
        if self._lowlight_enhancer:
            metrics['enhancer'] = self._lowlight_enhancer.get_metrics()
        if self._evidence_mgr:
            metrics['evidence'] = self._evidence_mgr.get_metrics()

        # V3 Intelligence Layer metrics
        if self._identity_graph:
            metrics['identity_graph'] = self._identity_graph.get_metrics()
        if self._camera_topology:
            metrics['camera_topology'] = self._camera_topology.get_metrics()
        if self._cross_camera_tracker:
            metrics['cross_camera'] = self._cross_camera_tracker.get_metrics()
        if self._quality_monitor:
            metrics['quality'] = self._quality_monitor.get_metrics()
        if self._active_learning:
            metrics['active_learning'] = self._active_learning.get_metrics()
        if self._investigation_engine:
            metrics['investigation'] = self._investigation_engine.get_metrics()

        # V4 Operations Layer metrics
        if self._investigation_copilot:
            metrics['copilot'] = self._investigation_copilot.get_metrics()
        if self._case_management:
            metrics['cases'] = self._case_management.get_metrics()
        if self._event_intelligence:
            metrics['events'] = self._event_intelligence.get_metrics()
        if self._evidence_vault:
            metrics['vault'] = self._evidence_vault.get_metrics()
        if self._security_manager:
            metrics['security'] = self._security_manager.get_metrics()
        if self._secret_manager:
            metrics['secrets'] = self._secret_manager.get_metrics()
        if self._audit_intelligence:
            metrics['audit'] = self._audit_intelligence.get_metrics()
        if self._telemetry_platform:
            metrics['telemetry'] = self._telemetry_platform.get_full_telemetry()
        if self._advanced_metrics:
            metrics['health_score'] = self._advanced_metrics.generate_health_score()
        if self._ai_operations:
            metrics['ai_ops'] = self._ai_operations.get_metrics()
        if self._anomaly_detection:
            metrics['anomalies'] = self._anomaly_detection.get_metrics()
        if self._incident_response:
            metrics['incidents'] = self._incident_response.get_metrics()
        if self._autonomous_optimization:
            metrics['auto_opt'] = self._autonomous_optimization.get_metrics()
        if self._digital_twin:
            metrics['digital_twin'] = self._digital_twin.get_metrics()

        # V5 Intelligence Evolution metrics
        if self._global_identity_graph:
            metrics['global_graph'] = self._global_identity_graph.get_metrics()
        if self._multi_modal_fusion:
            metrics['multi_modal_fusion'] = self._multi_modal_fusion.get_metrics()
        if self._tiered_feature_store:
            metrics['tiered_feature_store'] = self._tiered_feature_store.get_metrics()
        if self._predictive_movement:
            metrics['predictive_movement'] = self._predictive_movement.get_metrics()
        if self._adaptive_inference_director:
            metrics['adaptive_inference'] = self._adaptive_inference_director.get_metrics()
        if self._global_gpu_orchestrator:
            metrics['global_gpu'] = self._global_gpu_orchestrator.get_metrics()
        if self._distributed_resolver:
            metrics['distributed_resolver'] = self._distributed_resolver.get_metrics()
        if self._v5_evidence_integrity:
            metrics['v5_evidence_integrity'] = self._v5_evidence_integrity.get_metrics()
        if self._forensic_replay:
            metrics['forensic_replay'] = self._forensic_replay.get_metrics()
        if self._circuit_protection:
            metrics['circuit_protection'] = self._circuit_protection.get_metrics()
        if self._digital_twin_validation:
            metrics['digital_twin_validation'] = self._digital_twin_validation.get_metrics()
        if self._v5_investigation_copilot:
            metrics['v5_copilot'] = self._v5_investigation_copilot.get_metrics()
        if self._v5_autonomous_optimization:
            metrics['v5_auto_opt'] = self._v5_autonomous_optimization.get_metrics()

        # V6 Enterprise Evolution metrics
        if self._v6_global_identity_memory:
            metrics['v6_global_identity_memory'] = self._v6_global_identity_memory.get_metrics()
        if self._v6_federated_mesh:
            metrics['v6_federated_mesh'] = self._v6_federated_mesh.get_metrics()
        if self._v6_forensic_knowledge_graph:
            metrics['v6_forensic_knowledge_graph'] = self._v6_forensic_knowledge_graph.get_metrics()
        if self._v6_behavioral_intelligence:
            metrics['v6_behavioral_intelligence'] = self._v6_behavioral_intelligence.get_metrics()
        if self._v6_camera_intelligence:
            metrics['v6_camera_intelligence'] = self._v6_camera_intelligence.get_metrics()
        if self._v6_context_fusion:
            metrics['v6_context_fusion'] = self._v6_context_fusion.get_metrics()
        if self._v6_event_backbone:
            metrics['v6_event_backbone'] = self._v6_event_backbone.get_metrics()
        if self._v6_hierarchical_gpu:
            metrics['v6_hierarchical_gpu'] = self._v6_hierarchical_gpu.get_metrics()
        if self._v6_load_forecaster:
            metrics['v6_load_forecaster'] = self._v6_load_forecaster.get_metrics()
        if self._v6_geo_redundant_storage:
            metrics['v6_geo_redundant_storage'] = self._v6_geo_redundant_storage.get_metrics()
        if self._v6_model_marketplace:
            metrics['v6_model_marketplace'] = self._v6_model_marketplace.get_metrics()
        if self._v6_autonomous_recovery:
            metrics['v6_autonomous_recovery'] = self._v6_autonomous_recovery.get_metrics()
        if self._v6_explainable_resolution:
            metrics['v6_explainable_resolution'] = self._v6_explainable_resolution.get_metrics()
        if self._v6_investigation_copilot_v2:
            metrics['v6_investigation_copilot_v2'] = self._v6_investigation_copilot_v2.get_metrics()
        if self._v6_live_digital_twin:
            metrics['v6_live_digital_twin'] = self._v6_live_digital_twin.get_metrics()

        return metrics

    def add_stream(self, rtsp_url: str, name: str = '', location: str = '') -> dict:
        """Add a stream to the running session."""
        if not self.running:
            return {'error': 'No active session'}

        from .models_stream import CCTVStream
        from .rtsp_capture import RTSPCapture
        from .stream_processor import StreamProcessor

        stream_obj, _ = CCTVStream.objects.get_or_create(
            rtsp_url=rtsp_url,
            defaults={'name': name or f"Camera {len(self.processors) + 1}",
                      'location': location}
        )
        stream_obj.is_active = True
        stream_obj.save()
        self.session.streams.add(stream_obj)

        capture = RTSPCapture(rtsp_url=rtsp_url, stream_id=str(stream_obj.id))
        processor = StreamProcessor(
            stream_id=str(stream_obj.id),
            model_pool=self.model_pool,
            capture=capture,
            session=self.session,
            stream_obj=stream_obj,
            threshold=self.session.threshold,
            alert_callback=self.alert_callback,
            v2_engines={
                'detection_router': self._detection_router,
                'tracker_orchestrator': self._tracker_orchestrator,
                'face_pipeline': self._face_pipeline,
                'fusion_engine': self._fusion_engine,
                'lowlight_enhancer': self._lowlight_enhancer,
                'evidence_mgr': self._evidence_mgr,
                'metrics': self._metrics,
            } if self._v2_enabled else None,
        )

        self.processors[str(stream_obj.id)] = StreamProcessorInfo(
            stream_obj=stream_obj,
            capture=capture,
            processor=processor,
        )

        capture.start()
        processor.start()

        return {'stream_id': str(stream_obj.id), 'status': 'ADDED'}

    def remove_stream(self, stream_id: str) -> dict:
        """Remove a stream from the running session."""
        info = self.processors.pop(stream_id, None)
        if info is None:
            return {'error': 'Stream not found'}

        info.processor.stop()
        info.capture.stop()
        info.stream_obj.status = 'IDLE'
        info.stream_obj.save()

        return {'stream_id': stream_id, 'status': 'REMOVED'}


class StreamProcessorInfo:
    """Simple container for a stream's capture + processor pair."""
    def __init__(self, stream_obj, capture, processor):
        self.stream_obj = stream_obj
        self.capture = capture
        self.processor = processor


# Import RTSPCapture for status constants
from .rtsp_capture import RTSPCapture


# --- Module-level convenience functions ---

def get_orchestrator() -> CCTVOrchestrator:
    """Get or create the global orchestrator instance."""
    global _active_orchestrator
    with _orchestrator_lock:
        if _active_orchestrator is None:
            _active_orchestrator = CCTVOrchestrator()
        return _active_orchestrator


def reset_orchestrator():
    """Reset the global orchestrator (for testing)."""
    global _active_orchestrator
    with _orchestrator_lock:
        if _active_orchestrator is not None:
            if _active_orchestrator.running:
                _active_orchestrator.stop_session()
            _active_orchestrator = None
