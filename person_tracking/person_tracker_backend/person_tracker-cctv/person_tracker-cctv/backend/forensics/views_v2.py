"""
V2 API Views — Health, Metrics, and Engine Status endpoints.

These are ADDITIVE endpoints that DO NOT modify any existing views.
All existing API contracts are preserved exactly.
"""
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.http import HttpResponse
from rest_framework.views import APIView
from rest_framework.response import Response

from .cctv_orchestrator import get_orchestrator


class HealthView(APIView):
    """
    GET /api/v2/health/
    System-wide health check for monitoring and Kubernetes probes.
    """
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        orch = get_orchestrator()
        health = orch.get_health()
        status_code = 200 if health.get('status') in ('healthy', 'degraded') else 503
        return Response(health, status=status_code)


class MetricsView(APIView):
    """
    GET /api/v2/metrics/
    Returns all metrics in JSON format for the frontend status panel.
    """
    def get(self, request):
        orch = get_orchestrator()
        metrics = orch.get_engine_metrics()

        # Add session-level stats if running
        if orch.running:
            metrics['session'] = orch.get_status()

        return Response(metrics)


class PrometheusView(APIView):
    """
    GET /api/v2/metrics/prometheus
    Returns metrics in Prometheus text exposition format.
    """
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        try:
            from .observability.metrics import MetricsCollector
            collector = MetricsCollector.get_instance()
            text = collector.to_prometheus()
        except Exception:
            text = '# No metrics available\n'

        return HttpResponse(text, content_type='text/plain; version=0.0.4')


class EngineStatusView(APIView):
    """
    GET /api/v2/engine/
    Detailed V2 engine component status.
    """
    def get(self, request):
        orch = get_orchestrator()
        return Response({
            'v2_enabled': orch._v2_enabled,
            'components': {
                'detection_router': orch._detection_router is not None,
                'tracker_orchestrator': orch._tracker_orchestrator is not None,
                'face_pipeline': orch._face_pipeline is not None,
                'fusion_engine': orch._fusion_engine is not None,
                'lowlight_enhancer': orch._lowlight_enhancer is not None,
                'evidence_mgr': orch._evidence_mgr is not None,
                'custody_mgr': orch._custody_mgr is not None,
                'gpu_monitor': orch._gpu_monitor is not None,
                'metrics': orch._metrics is not None,
                'health_check': orch._health_check is not None,
                'event_bus': orch._event_bus is not None,
            },
            'engine_metrics': orch.get_engine_metrics(),
        })


class EvidenceChainView(APIView):
    """
    GET /api/v2/evidence/chain/
    Returns the evidence integrity hash chain for audit.
    """
    def get(self, request):
        orch = get_orchestrator()
        if orch._evidence_mgr is None:
            return Response({'error': 'Evidence integrity not enabled'}, status=404)

        chain = orch._evidence_mgr.export_chain()
        is_valid, errors = orch._evidence_mgr.verify_chain()

        return Response({
            'chain_length': len(chain),
            'is_valid': is_valid,
            'errors': errors,
            'entries': chain[-50:],  # Last 50 entries
        })


@method_decorator(csrf_exempt, name='dispatch')
class EvidenceExportView(APIView):
    """
    POST /api/v2/evidence/export/
    Export signed evidence package.
    """
    def post(self, request):
        orch = get_orchestrator()
        if orch._evidence_mgr is None or orch._custody_mgr is None:
            return Response({'error': 'Evidence system not enabled'}, status=404)

        try:
            from .evidence.signed_export import SignedEvidenceExporter
            exporter = SignedEvidenceExporter(
                integrity_mgr=orch._evidence_mgr,
                custody_mgr=orch._custody_mgr,
            )

            evidence_ids = request.data.get('evidence_ids', [])
            clip_paths = request.data.get('clip_paths', [])
            output_path = request.data.get('output_path', 'evidence_export.zip')
            case_id = request.data.get('case_id', '')
            actor = request.data.get('actor', 'api_user')

            result = exporter.export_zip(
                evidence_ids=evidence_ids,
                clip_paths=clip_paths,
                output_path=output_path,
                actor=actor,
                case_id=case_id,
            )

            return Response(result)

        except Exception as e:
            return Response({'error': str(e)}, status=500)
