from rest_framework import generics, permissions

from apps.businesses.utils import get_request_business
from .models import AuditLogEntry
from .serializers import AuditLogEntrySerializer


class AuditLogListView(generics.ListAPIView):
    serializer_class = AuditLogEntrySerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        business = get_request_business(self.request)
        qs = AuditLogEntry.objects.select_related("actor")
        params = self.request.query_params
        if business is not None:
            qs = qs.filter(business=business)
        elif params.get("business"):
            qs = qs.filter(business_id=params["business"])
        if params.get("object_type"):
            qs = qs.filter(object_type=params["object_type"])
        if params.get("object_id"):
            qs = qs.filter(object_id=params["object_id"])
        return qs
