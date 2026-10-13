from django.db import models
from django.contrib.auth import get_user_model
from apps.branches.models import Branch

User = get_user_model()


class DailySalesRecord(models.Model):
    SOURCE_MANUAL = "manual"
    SOURCE_CSV = "csv"
    SOURCE_API = "api"
    SOURCE_CHOICES = [(SOURCE_MANUAL, "Manual"), (SOURCE_CSV, "CSV Upload"), (SOURCE_API, "POS / API")]

    CURRENCY_KHR = "KHR"
    CURRENCY_USD = "USD"
    CURRENCY_CHOICES = [(CURRENCY_KHR, "KHR"), (CURRENCY_USD, "USD")]

    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name="sales_records")
    date = models.DateField()
    expected_total = models.DecimalField(max_digits=14, decimal_places=2)
    currency = models.CharField(max_length=10, choices=CURRENCY_CHOICES, default=CURRENCY_KHR)
    source = models.CharField(max_length=10, choices=SOURCE_CHOICES, default=SOURCE_MANUAL)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("branch", "date", "currency")]
        ordering = ["-date"]

    def __str__(self):
        return f"{self.branch} — {self.date} — {self.expected_total} {self.currency}"
