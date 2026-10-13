from django.utils import timezone
from rest_framework import serializers
from .models import ReconciliationResult
from apps.bakong import services as bakong_services
from apps.sales import services as sales_services
from apps.audit import services as audit_services
from apps.audit.serializers import AuditLogEntrySerializer
from apps.branches.models import Branch
from .engine import Attribution


class ReconciliationResultSerializer(serializers.ModelSerializer):
    branch_name = serializers.CharField(source="branch.name", read_only=True)
    business_name = serializers.CharField(source="branch.business.name", read_only=True)
    expected_total = serializers.SerializerMethodField()
    resolved_by_username = serializers.CharField(source="resolved_by.username", read_only=True, default=None)

    class Meta:
        model = ReconciliationResult
        fields = [
            "id", "branch", "branch_name", "business_name", "date", "currency",
            "expected_total", "matched_total", "discrepancy_amount", "status", "status_detail", "reconciled_at",
            "resolution_status", "resolution_note", "resolved_by", "resolved_by_username", "resolved_at",
        ]

    def get_expected_total(self, obj):
        record = sales_services.get_sales_record(obj.branch, obj.date, obj.currency)
        return str(record.expected_total) if record else None


class ReconciliationResolveSerializer(serializers.ModelSerializer):
    """Handles the manual resolution workflow — kept separate from
    ReconciliationResultSerializer since it's a narrower, write-focused shape
    (only resolution_status/resolution_note are settable) and stamps
    resolved_by/resolved_at as a side effect rather than accepting them as input."""

    class Meta:
        model = ReconciliationResult
        fields = ["resolution_status", "resolution_note"]

    def update(self, instance, validated_data):
        request = self.context.get("request")
        if "resolution_status" in validated_data:
            instance.resolution_status = validated_data["resolution_status"]
        if "resolution_note" in validated_data:
            instance.resolution_note = validated_data["resolution_note"]

        if instance.resolution_status in (
            ReconciliationResult.RESOLUTION_RESOLVED,
            ReconciliationResult.RESOLUTION_IGNORED,
        ):
            instance.resolved_by = getattr(request, "user", None)
            instance.resolved_at = timezone.now()
        else:
            # Reopening (open/investigating) clears the prior resolution stamp.
            instance.resolved_by = None
            instance.resolved_at = None

        instance.save()
        return instance


def transaction_row(txn, attribution: Attribution) -> dict:
    """A Bakong transaction plus the branch it's attributed to and why."""
    branch_id, source = attribution.branch_for(txn)
    branch = attribution.branches.get(branch_id)
    return {
        "id": txn.id,
        "timestamp": txn.timestamp,
        "amount": str(txn.amount),
        "currency": txn.currency,
        "reference": txn.reference,
        "account_id": txn.account_id,
        "branch": branch_id,
        "branch_name": branch.name if branch else None,
        "attribution": source,
        "assigned_branch": txn.assigned_branch_id,
        "excluded": txn.excluded,
        "review_note": txn.review_note,
        "reviewed_by_username": txn.reviewed_by.username if txn.reviewed_by_id else None,
        "reviewed_at": txn.reviewed_at,
    }


class BakongTransactionReviewSerializer(serializers.Serializer):
    """Manual review input. assigned_branch=null hands the payment back to
    automatic attribution; it must belong to the transaction's business."""

    assigned_branch = serializers.PrimaryKeyRelatedField(queryset=Branch.objects.all(), allow_null=True, required=False)
    excluded = serializers.BooleanField(required=False)
    review_note = serializers.CharField(allow_blank=True, required=False, max_length=2000)

    def validate_assigned_branch(self, branch):
        if branch is not None and branch.business_id != self.context["business"].pk:
            raise serializers.ValidationError("Branch belongs to a different business.")
        return branch


class DiscrepancyDetailSerializer(serializers.Serializer):
    reconciliation = ReconciliationResultSerializer()
    sales_record = serializers.SerializerMethodField()
    bakong_transactions = serializers.SerializerMethodField()
    history = serializers.SerializerMethodField()

    def get_sales_record(self, obj):
        result = obj["reconciliation"]
        record = sales_services.get_sales_record(result.branch, result.date, result.currency)
        if not record:
            return None
        return {"id": record.id, "expected_total": str(record.expected_total),
                "currency": record.currency, "source": record.source}

    def get_bakong_transactions(self, obj):
        result = obj["reconciliation"]
        # Same attribution the engine used, so non-excluded rows add up to
        # matched_total. Excluded payments in this branch's own account are
        # listed too so they can be un-excluded.
        attribution = Attribution(result.branch.business)
        rows = []
        for t in bakong_services.get_transactions(result.branch.business, result.date).filter(currency=result.currency):
            branch_id, source = attribution.branch_for(t)
            own_excluded = t.excluded and (
                t.assigned_branch_id == result.branch_id
                or (not t.assigned_branch_id and t.account_id and t.account_id == result.branch.bakong_account_id)
            )
            if branch_id == result.branch_id or own_excluded:
                rows.append(transaction_row(t, attribution))
        return rows

    def get_history(self, obj):
        result = obj["reconciliation"]
        objects = [("reconciliationresult", result.pk)]
        record = sales_services.get_sales_record(result.branch, result.date, result.currency)
        if record:
            objects.append(("dailysalesrecord", record.pk))
        objects += [("bakongtransaction", t["id"]) for t in self.get_bakong_transactions(obj)]
        return AuditLogEntrySerializer(audit_services.entries_for(objects)[:100], many=True).data
