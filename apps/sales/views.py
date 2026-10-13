import csv
import io
from decimal import Decimal, InvalidOperation

from django.shortcuts import get_object_or_404
from django.utils.dateparse import parse_date
from rest_framework import generics, permissions, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit import services as audit
from apps.branches import services as branches_services
from apps.branches.models import Branch
from apps.businesses.utils import ensure_can_write, get_request_business
from . import services as sales_services
from .models import DailySalesRecord
from .serializers import DailySalesRecordSerializer

VALID_CURRENCIES = {c for c, _ in DailySalesRecord.CURRENCY_CHOICES}
MAX_INGEST_RECORDS = 400


def _get_branch_for_user(request, branch_pk):
    branch = get_object_or_404(Branch, pk=branch_pk)
    business = get_request_business(request)
    if business is not None and branch.business_id != business.pk:
        raise PermissionDenied("This branch does not belong to your business.")
    return branch


def _parse_row(row: dict):
    """(date, Decimal amount, currency) from a CSV/JSON row, or raises ValueError."""
    date_val = str(row.get("date") or "").strip()
    amount_val = str(row.get("expected_total") or "").strip()
    currency_val = str(row.get("currency") or DailySalesRecord.CURRENCY_KHR).strip().upper()
    if not date_val or not amount_val:
        raise ValueError("Missing date or expected_total")
    try:
        parsed_date = parse_date(date_val)
    except ValueError:
        parsed_date = None
    if parsed_date is None:
        raise ValueError(f"Invalid date {date_val!r} (expected YYYY-MM-DD)")
    try:
        amount = Decimal(amount_val)
    except InvalidOperation:
        raise ValueError(f"Invalid expected_total {amount_val!r}")
    if not amount.is_finite() or amount < 0:
        raise ValueError("expected_total must be a non-negative number")
    if currency_val not in VALID_CURRENCIES:
        raise ValueError(f"Unsupported currency {currency_val!r}")
    return parsed_date, amount, currency_val


def _save_rows(rows, branch, source, user, summary_suffix=""):
    saved, errors = [], []
    for i, row in rows:
        try:
            d, amount, currency = _parse_row(row)
        except ValueError as e:
            errors.append({"row": i, "error": str(e)})
            continue
        record, previous = sales_services.upsert_sales_record(branch, d, currency, amount, source, user)
        if previous != amount:
            audit.record(
                user, branch.business, "sales.create" if previous is None else "sales.update", record,
                summary=f"{branch.name} {d} {currency}: {amount}{summary_suffix}",
                changes={"expected_total": [str(previous) if previous is not None else None, str(amount)],
                         "source": [None, source]},
            )
        saved.append(record.id)
    return saved, errors


class BranchSalesListCreateView(generics.ListCreateAPIView):
    serializer_class = DailySalesRecordSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        branch = _get_branch_for_user(self.request, self.kwargs["branch_pk"])
        return DailySalesRecord.objects.filter(branch=branch).order_by("-date")

    def perform_create(self, serializer):
        ensure_can_write(self.request, "Viewers cannot enter sales.")
        branch = _get_branch_for_user(self.request, self.kwargs["branch_pk"])
        record = serializer.save(branch=branch, created_by=self.request.user)
        audit.record(
            self.request.user, branch.business, "sales.create", record,
            summary=f"{branch.name} {record.date} {record.currency}: {record.expected_total}",
            changes={"expected_total": [None, str(record.expected_total)], "source": [None, record.source]},
        )


class BranchSalesCSVImportView(APIView):
    parser_classes = [MultiPartParser]
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, branch_pk):
        ensure_can_write(request, "Viewers cannot import sales.")
        branch = _get_branch_for_user(request, branch_pk)
        file = request.FILES.get("file")
        if not file:
            return Response({"detail": "No file provided."}, status=status.HTTP_400_BAD_REQUEST)

        # utf-8-sig strips the byte-order mark Excel writes, which would
        # otherwise turn the first header into "﻿date".
        try:
            decoded = file.read().decode("utf-8-sig")
        except UnicodeDecodeError:
            return Response({"detail": "File must be UTF-8 encoded CSV."}, status=status.HTTP_400_BAD_REQUEST)
        reader = csv.DictReader(io.StringIO(decoded))

        created, errors = _save_rows(
            enumerate(reader, start=2), branch, DailySalesRecord.SOURCE_CSV, request.user, " (CSV)"
        )
        return Response({"created": len(created), "errors": errors}, status=status.HTTP_200_OK)


class SalesIngestView(APIView):
    """
    POS / external-system push of daily sales totals, authenticated by a
    per-branch key in the X-Api-Key header (see Settings → Branches).

    Body: {"date": "2026-10-01", "expected_total": "125000", "currency": "KHR"}
       or {"records": [{...}, {...}]}
    Re-sending a date+currency overwrites the earlier total.
    """

    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        branch = branches_services.get_branch_by_ingest_key(request.headers.get("X-Api-Key", ""))
        if branch is None:
            return Response({"detail": "Invalid or missing X-Api-Key."}, status=status.HTTP_401_UNAUTHORIZED)

        data = request.data
        records = data.get("records") if isinstance(data, dict) and "records" in data else [data]
        if not isinstance(records, list) or not all(isinstance(r, dict) for r in records):
            return Response({"detail": "Expected an object or {\"records\": [...]}."}, status=status.HTTP_400_BAD_REQUEST)
        if len(records) > MAX_INGEST_RECORDS:
            return Response({"detail": f"At most {MAX_INGEST_RECORDS} records per request."}, status=status.HTTP_400_BAD_REQUEST)

        saved, errors = _save_rows(
            enumerate(records), branch, DailySalesRecord.SOURCE_API, None, f" (POS key {branch.ingest_key_prefix}…)"
        )
        return Response(
            {"saved": len(saved), "errors": errors},
            status=status.HTTP_200_OK if not errors or saved else status.HTTP_400_BAD_REQUEST,
        )
