import csv
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import permissions, status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit import services as audit
from apps.bakong import services as bakong_services
from apps.branches.models import Branch
from apps.businesses.models import Business
from apps.businesses.utils import ensure_can_write, get_request_business
from apps.sales import services as sales_services
from .engine import Attribution, reconcile_business_date
from .models import ReconciliationResult
from .serializers import (
    BakongTransactionReviewSerializer,
    DiscrepancyDetailSerializer,
    ReconciliationResolveSerializer,
    ReconciliationResultSerializer,
    transaction_row,
)

MAX_REPORT_DAYS = 366


def _date_param(params, name, default=None):
    value = params.get(name)
    if not value:
        return default
    try:
        parsed = parse_date(value)
    except ValueError:
        parsed = None
    if parsed is None:
        raise ValidationError({name: "Must be YYYY-MM-DD."})
    return parsed


def _scoped_results(request):
    """ReconciliationResults the caller may see, narrowed by query params:
    business (superusers), branch, date, date_from, date_to, currency, status,
    unresolved=1 (hide resolved/ignored)."""
    business = get_request_business(request)
    params = request.query_params
    qs = ReconciliationResult.objects.select_related("branch__business", "resolved_by")

    if business is not None:
        qs = qs.filter(branch__business=business)
    elif params.get("business"):
        # Superuser: allow optional ?business= filter
        qs = qs.filter(branch__business_id=params["business"])

    if params.get("date"):
        qs = qs.filter(date=_date_param(params, "date"))
    date_from = _date_param(params, "date_from")
    date_to = _date_param(params, "date_to")
    if date_from:
        qs = qs.filter(date__gte=date_from)
    if date_to:
        qs = qs.filter(date__lte=date_to)
    if params.get("branch"):
        qs = qs.filter(branch_id=params["branch"])
    if params.get("currency"):
        qs = qs.filter(currency=params["currency"].upper())
    if params.get("status"):
        qs = qs.filter(status=params["status"])
    if params.get("unresolved") in ("1", "true"):
        qs = qs.exclude(resolution_status__in=[
            ReconciliationResult.RESOLUTION_RESOLVED, ReconciliationResult.RESOLUTION_IGNORED,
        ])
    return qs.order_by("-date", "branch__name", "currency")


def _check_owns(request, business_id):
    business = get_request_business(request)
    if business is not None and business_id != business.pk:
        raise PermissionDenied("This record does not belong to your business.")


class ReconciliationListView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        qs = _scoped_results(request)
        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        return paginator.get_paginated_response(ReconciliationResultSerializer(page, many=True).data)


class ReconciliationExportView(APIView):
    """CSV of the same rows the list endpoint returns (all pages)."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        rows = ReconciliationResultSerializer(_scoped_results(request), many=True).data
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="reconciliation.csv"'
        response.write("﻿")  # BOM so Excel opens it as UTF-8 (Khmer branch names)
        columns = [
            "date", "business_name", "branch_name", "currency", "expected_total", "matched_total",
            "discrepancy_amount", "status", "status_detail", "resolution_status", "resolution_note",
            "resolved_by_username",
        ]
        writer = csv.writer(response)
        writer.writerow(columns)
        for row in rows:
            writer.writerow([row.get(c) if row.get(c) is not None else "" for c in columns])
        return response


class ReconciliationSummaryView(APIView):
    """Per branch+currency totals over a date range (default: last 30 days)."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        params = request.query_params
        today = timezone.localdate()
        date_to = _date_param(params, "date_to", today)
        date_from = _date_param(params, "date_from", date_to - timedelta(days=29))
        if date_from > date_to:
            raise ValidationError({"date_from": "Must be on or before date_to."})
        if (date_to - date_from).days >= MAX_REPORT_DAYS:
            raise ValidationError({"date_from": f"Range can be at most {MAX_REPORT_DAYS} days."})

        qs = _scoped_results(request).filter(date__gte=date_from, date__lte=date_to)
        groups = defaultdict(lambda: {
            "days": 0, "matched": 0, "discrepancy": 0, "pending": 0, "open_discrepancies": 0,
            "bakong_total": Decimal("0"), "discrepancy_total": Decimal("0"),
        })
        names = {}
        for r in qs:
            key = (r.branch_id, r.currency)
            names[r.branch_id] = (r.branch.name, r.branch.business.name)
            g = groups[key]
            g["days"] += 1
            g[r.status] += 1
            g["bakong_total"] += r.matched_total
            g["discrepancy_total"] += r.discrepancy_amount
            if r.status == ReconciliationResult.STATUS_DISCREPANCY and r.resolution_status in (
                ReconciliationResult.RESOLUTION_OPEN, ReconciliationResult.RESOLUTION_INVESTIGATING,
            ):
                g["open_discrepancies"] += 1

        expected = sales_services.get_totals({b for b, _ in groups}, date_from, date_to)
        rows = []
        for (branch_id, currency), g in sorted(groups.items(), key=lambda kv: (names[kv[0][0]], kv[0][1])):
            rows.append({
                "branch": branch_id,
                "branch_name": names[branch_id][0],
                "business_name": names[branch_id][1],
                "currency": currency,
                **g,
                "expected_total": str(expected.get((branch_id, currency), Decimal("0"))),
                "bakong_total": str(g["bakong_total"]),
                "discrepancy_total": str(g["discrepancy_total"]),
            })
        return Response({"date_from": date_from, "date_to": date_to, "rows": rows})


class ReconciliationDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        result = get_object_or_404(
            ReconciliationResult.objects.select_related("branch__business"), pk=pk
        )
        _check_owns(request, result.branch.business_id)
        serializer = DiscrepancyDetailSerializer({"reconciliation": result}, context={"request": request})
        return Response(serializer.data)


class ReconciliationResolveView(APIView):
    """Lets staff record what happened to a discrepancy — open/investigating/resolved/
    ignored plus a note — without touching `status`, which stays owned by the engine."""

    permission_classes = [permissions.IsAuthenticated]

    def patch(self, request, pk):
        result = get_object_or_404(
            ReconciliationResult.objects.select_related("branch__business"), pk=pk
        )
        _check_owns(request, result.branch.business_id)
        ensure_can_write(request, "Viewers cannot update reconciliation resolution.")

        before = {"resolution_status": result.resolution_status, "resolution_note": result.resolution_note}
        serializer = ReconciliationResolveSerializer(
            result, data=request.data, partial=True, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        instance = serializer.save()
        changes = audit.diff(before, {k: getattr(instance, k) for k in before})
        if changes:
            audit.record(
                request.user, result.branch.business, "reconciliation.resolve", instance,
                summary=f"{result.branch.name} {result.date} {result.currency}: {instance.resolution_status}",
                changes=changes,
            )
        return Response(ReconciliationResultSerializer(instance).data)


class TriggerReconciliationView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        business = get_request_business(request)
        ensure_can_write(request, "Viewers cannot trigger reconciliation.")

        date_param = request.data.get("date") or None
        if date_param:
            try:
                valid = parse_date(date_param) is not None
            except ValueError:
                valid = False
            if not valid:
                return Response({"detail": "date must be YYYY-MM-DD."}, status=status.HTTP_400_BAD_REQUEST)

        # Business users only ever re-run their own branches; superusers may
        # target one business or (by omitting it) all of them.
        business_id = business.pk if business is not None else request.data.get("business") or None

        from .tasks import run_reconciliation
        run_reconciliation.delay(target_date=date_param, business_id=business_id)
        return Response({"detail": "Reconciliation task queued."})


class TransactionListView(APIView):
    """
    Bakong transactions for one day with the branch each is attributed to and
    why (manual / account / pool / unattributed / excluded).
    Params: date (default yesterday), branch, attribution, business (superusers).
    """

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        params = request.query_params
        d = _date_param(params, "date", timezone.localdate() - timedelta(days=1))
        business = get_request_business(request)
        if business is not None:
            businesses = [business]
        else:
            businesses = Business.objects.all()
            if params.get("business"):
                businesses = businesses.filter(pk=params["business"])

        rows = []
        for biz in businesses:
            branches = list(Branch.objects.filter(business=biz))
            attribution = Attribution(biz, branches)
            for txn in bakong_services.get_transactions_between(biz, d, d).order_by("timestamp"):
                rows.append(transaction_row(txn, attribution))

        if params.get("branch"):
            rows = [r for r in rows if str(r["branch"]) == params["branch"]]
        if params.get("attribution"):
            rows = [r for r in rows if r["attribution"] == params["attribution"]]
        return Response({"date": d, "results": rows})


class TransactionReviewView(APIView):
    """Assign a payment to a branch, exclude it, or annotate it — then re-run
    that day's reconciliation for the business so totals reflect it at once."""

    permission_classes = [permissions.IsAuthenticated]

    def patch(self, request, pk):
        txn = bakong_services.get_transaction(pk)
        if txn is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        _check_owns(request, txn.business_id)
        ensure_can_write(request, "Viewers cannot review transactions.")

        serializer = BakongTransactionReviewSerializer(data=request.data, context={"business": txn.business})
        serializer.is_valid(raise_exception=True)

        changes = bakong_services.review_transaction(txn, request.user, **serializer.validated_data)
        if changes:
            audit.record(
                request.user, txn.business, "transaction.review", txn,
                summary=f"{txn.amount} {txn.currency} @ {timezone.localtime(txn.timestamp):%Y-%m-%d %H:%M}",
                changes=audit.diff({k: v[0] for k, v in changes.items()}, {k: v[1] for k, v in changes.items()}),
            )
            reconcile_business_date(txn.business, bakong_services.local_date(txn))

        attribution = Attribution(txn.business)
        return Response(transaction_row(txn, attribution))
