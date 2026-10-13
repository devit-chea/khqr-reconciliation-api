from django.conf import settings
from django.db import models
from apps.branches.models import Branch


class ReconciliationResult(models.Model):
    STATUS_PENDING = "pending"
    STATUS_MATCHED = "matched"
    STATUS_DISCREPANCY = "discrepancy"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_MATCHED, "Matched"),
        (STATUS_DISCREPANCY, "Discrepancy"),
    ]

    RESOLUTION_OPEN = "open"
    RESOLUTION_INVESTIGATING = "investigating"
    RESOLUTION_RESOLVED = "resolved"
    RESOLUTION_IGNORED = "ignored"
    RESOLUTION_CHOICES = [
        (RESOLUTION_OPEN, "Open"),
        (RESOLUTION_INVESTIGATING, "Investigating"),
        (RESOLUTION_RESOLVED, "Resolved"),
        (RESOLUTION_IGNORED, "Ignored"),
    ]

    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name="reconciliation_results")
    date = models.DateField()
    currency = models.CharField(max_length=10, default="KHR")
    matched_total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    discrepancy_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default=STATUS_PENDING)
    # Human-readable reason when status is pending (e.g. no sales entered yet).
    status_detail = models.CharField(max_length=255, blank=True)
    reconciled_at = models.DateTimeField(auto_now=True)

    # Manual resolution workflow. Independent of `status`, which the engine recomputes
    # on every reconciliation run — reconcile_branch_date() only ever writes
    # matched_total/discrepancy_amount/status/status_detail, so these fields survive re-runs.
    resolution_status = models.CharField(max_length=15, choices=RESOLUTION_CHOICES, default=RESOLUTION_OPEN)
    resolution_note = models.TextField(blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="resolved_reconciliations",
    )
    resolved_at = models.DateTimeField(null=True, blank=True)

    # Discrepancy amount we last sent a Telegram alert for, so re-runs don't
    # re-alert the same discrepancy. Owned by tasks.run_reconciliation.
    last_alerted_amount = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)

    class Meta:
        unique_together = [("branch", "date", "currency")]
        ordering = ["-date"]

    def __str__(self):
        return f"{self.branch} — {self.date} — {self.currency} — {self.status}"
