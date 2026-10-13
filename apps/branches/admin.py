from django.contrib import admin
from .models import Branch


@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = ["name", "business", "location", "bakong_account_id"]
    list_filter = ["business"]
    search_fields = ["name", "location"]
