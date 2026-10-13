from django.contrib import admin
from .models import ReconciliationResult


@admin.register(ReconciliationResult)
class ReconciliationResultAdmin(admin.ModelAdmin):
    list_display = [
        "branch", "date", "currency", "status", "matched_total", "discrepancy_amount",
        "resolution_status", "reconciled_at",
    ]
    list_filter = ["status", "resolution_status", "branch__business", "branch", "date"]
    date_hierarchy = "date"
    readonly_fields = ["reconciled_at", "resolved_by", "resolved_at", "last_alerted_amount"]
