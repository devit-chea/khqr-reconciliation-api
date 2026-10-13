from django.contrib import admin
from .models import AuditLogEntry


@admin.register(AuditLogEntry)
class AuditLogEntryAdmin(admin.ModelAdmin):
    list_display = ["created_at", "business", "actor", "action", "object_type", "object_id", "summary"]
    list_filter = ["business", "action", "object_type"]
    search_fields = ["summary", "object_id"]

    def has_change_permission(self, request, obj=None):
        return False
