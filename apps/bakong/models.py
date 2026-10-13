from django.conf import settings
from django.db import models
from apps.businesses.models import Business


class BakongTransaction(models.Model):
    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name="bakong_transactions")
    timestamp = models.DateTimeField()
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    currency = models.CharField(max_length=10, default="KHR")
    reference = models.CharField(max_length=500, blank=True)
    # Bakong account the payment landed in — the payload's accountId, or the
    # account we polled when the payload doesn't say. Drives branch attribution.
    account_id = models.CharField(max_length=255, blank=True)
    hash = models.CharField(max_length=500, blank=True, unique=True)
    # Raw API payload kept for audit and manual investigation
    raw_payload = models.JSONField(default=dict)

    # Manual review (Transactions page). A payment assigned to a branch counts
    # for that branch whatever account it landed in; an excluded one (refund,
    # owner transfer, …) counts for no branch at all.
    assigned_branch = models.ForeignKey(
        "branches.Branch", on_delete=models.SET_NULL, null=True, blank=True, related_name="assigned_transactions"
    )
    excluded = models.BooleanField(default=False)
    review_note = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["business", "timestamp"]),
            models.Index(fields=["business", "account_id", "timestamp"]),
        ]

    def __str__(self):
        return f"{self.business} — {self.amount} {self.currency} @ {self.timestamp}"
