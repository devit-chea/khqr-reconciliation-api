from django.conf import settings
from django.db import models
from apps.businesses.models import Business


class AuditLogEntry(models.Model):
    """Append-only record of who changed what. Never stores secrets — callers
    pass field names, not values, for credential changes."""

    business = models.ForeignKey(Business, on_delete=models.CASCADE, null=True, blank=True, related_name="audit_entries")
    # Null for system/API-key actions (e.g. POS ingestion).
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    action = models.CharField(max_length=50)
    object_type = models.CharField(max_length=50)
    object_id = models.CharField(max_length=50)
    summary = models.CharField(max_length=500, blank=True)
    changes = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["object_type", "object_id"]),
            models.Index(fields=["business", "created_at"]),
        ]

    def __str__(self):
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.action} {self.object_type}#{self.object_id}"
