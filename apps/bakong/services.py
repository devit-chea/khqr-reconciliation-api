"""
Read surface other apps use to get at Bakong data, instead of querying
BakongTransaction directly. How account attribution is stored is this app's
own implementation detail — callers ask "what did this business/account see
on this date", they don't filter the fields themselves.

This is also the seam a future split would extract along: if bakong
ingestion ever moves to its own service, everything in this module becomes
the client for that service's API instead of a local queryset.
"""
from datetime import date as Date
from decimal import Decimal
from typing import Iterable, Optional

from django.db.models import QuerySet
from django.utils import timezone

from .models import BakongTransaction


def get_transactions(
    business,
    target_date: Date,
    account_id: str = "",
    exclude_account_ids: Optional[Iterable[str]] = None,
) -> QuerySet:
    """
    Bakong transactions for `business` on `target_date`.
    - account_id: if set, only transactions attributed to that sub-account.
    - exclude_account_ids: if account_id is not set, exclude transactions
      attributed to any of these sub-accounts (used to find the pool of
      transactions not yet claimed by a known branch sub-account).
    """
    qs = BakongTransaction.objects.filter(business=business, timestamp__date=target_date)
    if account_id:
        return qs.filter(account_id=account_id)
    exclude_account_ids = [a for a in exclude_account_ids or [] if a]
    if exclude_account_ids:
        qs = qs.exclude(account_id__in=exclude_account_ids)
    return qs


def get_total(
    business,
    target_date: Date,
    account_id: str = "",
    exclude_account_ids: Optional[Iterable[str]] = None,
) -> Decimal:
    qs = get_transactions(business, target_date, account_id, exclude_account_ids)
    return sum((t.amount for t in qs), Decimal("0"))


def get_transactions_between(business, date_from: Date, date_to: Date) -> QuerySet:
    return BakongTransaction.objects.filter(
        business=business, timestamp__date__gte=date_from, timestamp__date__lte=date_to
    ).select_related("reviewed_by")


def get_transaction(pk) -> Optional[BakongTransaction]:
    return BakongTransaction.objects.select_related("business", "reviewed_by").filter(pk=pk).first()


def local_date(txn: BakongTransaction) -> Date:
    return timezone.localtime(txn.timestamp).date()


def review_transaction(txn: BakongTransaction, user, **changes) -> dict:
    """
    Applies manual review fields (assigned_branch, excluded, review_note) and
    stamps who did it. Returns {field: [old, new]} for what actually changed.
    """
    before = {k: getattr(txn, k) for k in changes}
    for k, v in changes.items():
        setattr(txn, k, v)
    changed = {k: [before[k], v] for k, v in changes.items() if before[k] != v}
    if changed:
        txn.reviewed_by = user if getattr(user, "is_authenticated", False) else None
        txn.reviewed_at = timezone.now()
        txn.save(update_fields=[*changes, "reviewed_by", "reviewed_at"])
    return changed
