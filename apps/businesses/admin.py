from django.contrib import admin
from .models import Business, UserProfile


@admin.register(Business)
class BusinessAdmin(admin.ModelAdmin):
    list_display = ["name", "bakong_account_id", "has_credentials", "has_telegram_config", "created_at"]
    readonly_fields = ["created_at", "updated_at"]

    def has_credentials(self, obj):
        return bool(obj._bakong_token)
    has_credentials.boolean = True

    def has_telegram_config(self, obj):
        return bool(obj._telegram_bot_token and obj.telegram_chat_id)
    has_telegram_config.boolean = True


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ["user", "business", "role"]
    list_filter = ["business", "role"]
    search_fields = ["user__username", "user__email"]
    raw_id_fields = ["user"]
