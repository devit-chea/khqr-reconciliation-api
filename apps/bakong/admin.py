from django.contrib import admin
from .models import BakongTransaction


@admin.register(BakongTransaction)
class BakongTransactionAdmin(admin.ModelAdmin):
    list_display = ["business", "account_id", "timestamp", "amount", "currency", "reference", "hash"]
    list_filter = ["business", "currency"]
    search_fields = ["reference", "hash", "account_id"]
    date_hierarchy = "timestamp"
    readonly_fields = ["raw_payload", "created_at"]
