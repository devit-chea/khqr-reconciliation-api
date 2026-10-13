"""
Read surface other apps use to get at sales data, instead of querying
DailySalesRecord directly. Same rationale as apps.bakong.services — this is
the seam a future split would extract along.
"""
from datetime import date as Date
from decimal import Decimal
from typing import Iterable, List, Optional, Set, Tuple

from django.db.models import Sum

from .models import DailySalesRecord


def get_sales_record(branch, target_date: Date, currency: str = DailySalesRecord.CURRENCY_KHR) -> Optional[DailySalesRecord]:
    return DailySalesRecord.objects.filter(branch=branch, date=target_date, currency=currency).first()


def get_sales_records(branch, target_date: Date) -> List[DailySalesRecord]:
    """All of a branch's sales records for a date — one per currency."""
    return list(DailySalesRecord.objects.filter(branch=branch, date=target_date))


def get_totals(branch_ids: Iterable[int], date_from: Date, date_to: Date) -> dict:
    """{(branch_id, currency): expected total} over the date range."""
    rows = (
        DailySalesRecord.objects.filter(branch_id__in=list(branch_ids), date__gte=date_from, date__lte=date_to)
        .values("branch_id", "currency")
        .annotate(total=Sum("expected_total"))
    )
    return {(r["branch_id"], r["currency"]): r["total"] for r in rows}


def branches_with_sales(branch_ids: Iterable[int], target_date: Date) -> Set[int]:
    return set(
        DailySalesRecord.objects.filter(branch_id__in=list(branch_ids), date=target_date)
        .values_list("branch_id", flat=True)
    )


def upsert_sales_record(branch, target_date, currency: str, expected_total: Decimal, source: str, user=None) -> Tuple[DailySalesRecord, Optional[Decimal]]:
    """Creates or overwrites the branch's record for date+currency.
    Returns (record, previous expected_total or None if newly created)."""
    existing = DailySalesRecord.objects.filter(branch=branch, date=target_date, currency=currency).first()
    previous = existing.expected_total if existing else None
    record, _ = DailySalesRecord.objects.update_or_create(
        branch=branch,
        date=target_date,
        currency=currency,
        defaults={"expected_total": expected_total, "source": source, "created_by": user},
    )
    return record, previous
