"""
Project-level views that don't belong to any one domain app — currently just
the health check an orchestrator (Docker healthcheck, load balancer, future
k8s readiness/liveness probe) polls to decide if this process is servable.

Deliberately a plain Django view, not a DRF APIView: infra probes shouldn't
need a JWT, and it sits outside /api/v1/ so it never moves when the API
version does.
"""
import redis
from django.conf import settings
from django.db import connections
from django.db.utils import OperationalError
from django.http import JsonResponse


def health_check(request):
    checks = {}
    healthy = True

    try:
        connections["default"].cursor().execute("SELECT 1")
        checks["database"] = "ok"
    except OperationalError:
        checks["database"] = "unreachable"
        healthy = False

    try:
        redis.Redis.from_url(settings.CELERY_BROKER_URL, socket_connect_timeout=2).ping()
        checks["broker"] = "ok"
    except Exception:
        checks["broker"] = "unreachable"
        healthy = False

    return JsonResponse(
        {"status": "ok" if healthy else "degraded", "checks": checks},
        status=200 if healthy else 503,
    )
