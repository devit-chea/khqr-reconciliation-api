import hashlib
import secrets

from django.db import models
from django.utils import timezone
from apps.businesses.models import Business

INGEST_KEY_PREFIX = "khqr_"


def hash_ingest_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


class Branch(models.Model):
    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name="branches")
    name = models.CharField(max_length=255)
    location = models.CharField(max_length=500, blank=True)
    # Optional: branch-level Bakong account ID if the business uses sub-accounts per branch
    bakong_account_id = models.CharField(max_length=255, blank=True)
    # POS ingestion key: only the hash is stored; the key is shown once.
    ingest_key_hash = models.CharField(max_length=64, blank=True, db_index=True)
    ingest_key_prefix = models.CharField(max_length=16, blank=True)
    ingest_key_created_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.business.name} — {self.name}"

    def rotate_ingest_key(self) -> str:
        """Issues a new POS key (invalidating the old one) and returns it."""
        key = INGEST_KEY_PREFIX + secrets.token_urlsafe(32)
        self.ingest_key_hash = hash_ingest_key(key)
        self.ingest_key_prefix = key[:12]
        self.ingest_key_created_at = timezone.now()
        self.save(update_fields=["ingest_key_hash", "ingest_key_prefix", "ingest_key_created_at"])
        return key

    def revoke_ingest_key(self):
        self.ingest_key_hash = ""
        self.ingest_key_prefix = ""
        self.ingest_key_created_at = None
        self.save(update_fields=["ingest_key_hash", "ingest_key_prefix", "ingest_key_created_at"])
