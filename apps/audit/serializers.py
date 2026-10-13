from rest_framework import serializers
from .models import AuditLogEntry


class AuditLogEntrySerializer(serializers.ModelSerializer):
    actor_username = serializers.CharField(source="actor.username", read_only=True, default=None)

    class Meta:
        model = AuditLogEntry
        fields = ["id", "created_at", "actor", "actor_username", "action", "object_type", "object_id", "summary", "changes"]
