from django.urls import path, include
from rest_framework.routers import DefaultRouter
# Import from views (since we moved everything to views.py)
from .views import StartAnalysisView, CaseStatusView, index_view, GetSightingsView
from .views_live import (
    StreamManageView, LiveStartView, LiveStopView,
    LiveStatusView, LiveAlertsView,
    LiveStreamAddView, LiveStreamRemoveView,
    LiveSnapshotView, LiveMJPEGView,
)
from .views_v2 import (
    HealthView, MetricsView, PrometheusView,
    EngineStatusView, EvidenceChainView, EvidenceExportView,
)
from .views_frontend import UserViewSet, SystemActivityViewSet

router = DefaultRouter()
router.register(r'users', UserViewSet, basename='users')
router.register(r'activity', SystemActivityViewSet, basename='activity')

urlpatterns = [
    # --- Existing (File-Based Pipeline) ---
    path('api/', include(router.urls)),
    path('', index_view, name='home'),
    path('analyze/', StartAnalysisView.as_view(), name='start_analysis'),
    path('status/<uuid:case_id>/', CaseStatusView.as_view(), name='case_status'),
    path('sightings/<uuid:case_id>/', GetSightingsView.as_view(), name='get_sightings'),

    # --- Live CCTV Tracking ---
    path('api/streams/', StreamManageView.as_view(), name='stream_manage'),
    path('api/live/start/', LiveStartView.as_view(), name='live_start'),
    path('api/live/stop/', LiveStopView.as_view(), name='live_stop'),
    path('api/live/status/', LiveStatusView.as_view(), name='live_status'),
    path('api/live/alerts/<uuid:session_id>/', LiveAlertsView.as_view(), name='live_alerts'),
    path('api/live/stream/add/', LiveStreamAddView.as_view(), name='live_stream_add'),
    path('api/live/stream/remove/', LiveStreamRemoveView.as_view(), name='live_stream_remove'),
    path('api/live/snapshot/<str:stream_id>/', LiveSnapshotView.as_view(), name='live_snapshot'),
    path('api/live/mjpeg/<str:stream_id>/', LiveMJPEGView.as_view(), name='live_mjpeg'),

    # --- V2 Engine APIs (additive, no frontend changes needed) ---
    path('api/v2/health/', HealthView.as_view(), name='v2_health'),
    path('api/v2/metrics/', MetricsView.as_view(), name='v2_metrics'),
    path('api/v2/metrics/prometheus', PrometheusView.as_view(), name='v2_prometheus'),
    path('api/v2/engine/', EngineStatusView.as_view(), name='v2_engine'),
    path('api/v2/evidence/chain/', EvidenceChainView.as_view(), name='v2_evidence_chain'),
    path('api/v2/evidence/export/', EvidenceExportView.as_view(), name='v2_evidence_export'),
]