from django.db import models
from django.conf import settings
from django.contrib.auth import get_user_model
from cryptography.fernet import Fernet
import base64


def _fernet():
    key = settings.ENCRYPTION_KEY
    if not key:
        raise RuntimeError("ENCRYPTION_KEY not configured")
    if isinstance(key, str):
        key = key.encode()
    return Fernet(key)


class Business(models.Model):
    name = models.CharField(max_length=255)
    # Bakong Open API token stored encrypted
    _bakong_token = models.TextField(blank=True, db_column="bakong_token")
    bakong_account_id = models.CharField(max_length=255, blank=True)
    # Per-business Telegram alerting. Falls back to the global TELEGRAM_BOT_TOKEN /
    # TELEGRAM_CHAT_ID settings when unset, so existing single-business deployments
    # keep working without configuring anything here.
    _telegram_bot_token = models.TextField(blank=True, db_column="telegram_bot_token")
    telegram_chat_id = models.CharField(max_length=255, blank=True)
    daily_digest_enabled = models.BooleanField(default=True)
    sales_reminder_enabled = models.BooleanField(default=True)
    # Bakong sync health, written by the poll task and shown in Settings.
    bakong_last_polled_at = models.DateTimeField(null=True, blank=True)
    bakong_last_error = models.TextField(blank=True)
    bakong_last_error_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "businesses"

    def __str__(self):
        return self.name

    def set_bakong_token(self, token: str):
        if not token:
            self._bakong_token = ""
            return
        self._bakong_token = _fernet().encrypt(token.encode()).decode()

    def get_bakong_token(self) -> str:
        if not self._bakong_token:
            return ""
        return _fernet().decrypt(self._bakong_token.encode()).decode()

    def set_telegram_bot_token(self, token: str):
        if not token:
            self._telegram_bot_token = ""
            return
        self._telegram_bot_token = _fernet().encrypt(token.encode()).decode()

    def get_telegram_bot_token(self) -> str:
        if not self._telegram_bot_token:
            return ""
        return _fernet().decrypt(self._telegram_bot_token.encode()).decode()


class UserProfile(models.Model):
    ROLE_OWNER = "owner"
    ROLE_MANAGER = "manager"
    ROLE_VIEWER = "viewer"
    ROLE_CHOICES = [
        (ROLE_OWNER, "Owner"),
        (ROLE_MANAGER, "Manager"),
        (ROLE_VIEWER, "Viewer"),
    ]

    user = models.OneToOneField(
        get_user_model(), on_delete=models.CASCADE, related_name="profile"
    )
    business = models.ForeignKey(
        Business, on_delete=models.CASCADE, related_name="profiles"
    )
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default=ROLE_VIEWER)

    def __str__(self):
        return f"{self.user.username} @ {self.business.name} ({self.role})"
