from django.contrib import admin
from .models import DailySalesRecord


@admin.register(DailySalesRecord)
class DailySalesRecordAdmin(admin.ModelAdmin):
    list_display = ["branch", "date", "expected_total", "currency", "source", "created_by"]
    list_filter = ["branch__business", "branch", "source", "date"]
    date_hierarchy = "date"
