"""
Engine Package — Core AI Inference Engine Components.

Provides intelligent model routing, adaptive tracker selection,
quality-aware confidence fusion, and model lifecycle management.

V2 Components:
    - DetectionRouter: YOLOv11 primary + RT-DETR fallback with scene-aware routing
    - TrackerOrchestrator: ByteTrack/BoT-SORT/StrongSORT adaptive switching
    - AdaptiveFacePipeline: Quality-routed face recognition
    - ReIDPipeline: Multi-modal body re-identification
    - AntiSpoofGate: Trigger-based anti-spoofing
    - AdaptiveLowLightEnhancer: RetinexFormer conditional enhancement
    - ModelRegistry: Dynamic model loading and versioning
    - ConfidenceFusionEngine: Quality-aware multi-modal score fusion
    - RiskEngine: Behavioral anomaly scoring and prioritization
    - CrossCameraGraph: Cross-camera identity linking and trail tracking

V3 Intelligence Layer:
    - IdentityGraph: Global persistent identity graph (JSONB-backed)
    - CameraTopologyEngine: Camera adjacency learning and transition prediction
    - CrossCameraTracker: Seamless identity handoff across cameras
    - IdentityMemoryBank: Rolling historical embedding store for long-term ReID
    - InvestigationEngine: Timeline reconstruction and NLP query support
    - ActiveLearningCollector: Automated hard-example collection for retraining
    - IdentityQualityMonitor: Real-time tracking quality metrics and alerts
"""
