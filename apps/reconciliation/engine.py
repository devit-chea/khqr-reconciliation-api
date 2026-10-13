"""
Matching engine: compares DailySalesRecord vs BakongTransaction for a branch/date
and writes one ReconciliationResult row per currency.

Which branch a transaction belongs to (Attribution.branch_for), in order:
1. Excluded during review (refund, owner transfer, …) → no branch.
2. Manually assigned to a branch during review → that branch.
3. Landed in a branch's Bakong sub-account → that branch.
4. Otherwise it's in the business's unattributed pool. If exactly one branch
   has no sub-account, that branch claims the pool. If several do, the pool
   can't be split automatically: those payments stay unattributed until
   someone assigns them, and the branches without a sub-account stay
   'pending' meanwhile.

A branch with its own sub-account treats "no payments" as zero received. A
branch relying on the pool with nothing attributed is 'pending' (polling may
not have run yet).

Currencies are reconciled separately: KHR sales against KHR transactions, USD
against USD. A currency that has transactions but no sales record still gets
a row, so nothing goes unnoticed.

Tolerance: amounts match within 1 KHR / 0.01 USD rounding.

This module only reaches into sales/bakong/branches through their services
modules (apps.sales.services, apps.bakong.services, apps.branches.services),
not their models directly — reconciliation is the one place that reads
across every other domain, so it's the one place that matters most for
keeping those reads behind a narrow, swappable interface.
"""
from collections import defaultdict
from decimal import Decimal
from datetime import date as Date
from typing import List, Optional, Tuple

from apps.bakong import services as bakong_services
from apps.branches import services as branches_services
from apps.branches.models import Branch
from apps.sales import services as sales_services
from .models import ReconciliationResult

DEFAULT_CURRENCY = "KHR"
TOLERANCES = {"KHR": Decimal("1.00"), "USD": Decimal("0.01")}

SOURCE_EXCLUDED = "excluded"
SOURCE_MANUAL = "manual"
SOURCE_ACCOUNT = "account"
SOURCE_POOL = "pool"
SOURCE_UNATTRIBUTED = "unattributed"

REASON_NO_SALES = "No sales record entered for this date."
REASON_NO_TRANSACTIONS = "No Bakong transactions received yet."


def unassigned_reason(count: int) -> str:
    return (
        f"{count} payment(s) couldn't be matched to a branch automatically because several "
        "branches have no Bakong sub-account. Assign them on the Transactions page, or set a "
        "Bakong account ID on each branch."
    )


class Attribution:
    """Decides which branch each of one business's Bakong transactions belongs to."""

    def __init__(self, business, branches: Optional[List[Branch]] = None):
        branches = branches if branches is not None else branches_services.get_branches(business)
        self.branches = {b.pk: b for b in branches}
        self.by_account = {}
        for b in branches:
            if b.bakong_account_id:
                self.by_account.setdefault(b.bakong_account_id, b.pk)
        without_account = [b.pk for b in branches if not b.bakong_account_id]
        self.pool_branch_id = without_account[0] if len(without_account) == 1 else None

    def branch_for(self, txn) -> Tuple[Optional[int], str]:
        if txn.excluded:
            return None, SOURCE_EXCLUDED
        if txn.assigned_branch_id:
            return txn.assigned_branch_id, SOURCE_MANUAL
        if txn.account_id in self.by_account:
            return self.by_account[txn.account_id], SOURCE_ACCOUNT
        if self.pool_branch_id:
            return self.pool_branch_id, SOURCE_POOL
        return None, SOURCE_UNATTRIBUTED


def get_branch_transactions(branch: Branch, target_date: Date, attribution: Optional[Attribution] = None) -> list:
    """The Bakong transactions attributed to `branch` on `target_date`."""
    attribution = attribution or Attribution(branch.business)
    return [
        t for t in bakong_services.get_transactions(branch.business, target_date)
        if attribution.branch_for(t)[0] == branch.pk
    ]


def _save(branch, target_date, currency, status, matched_total=0, discrepancy=0, detail=""):
    result, _ = ReconciliationResult.objects.update_or_create(
        branch=branch,
        date=target_date,
        currency=currency,
        defaults={
            "status": status,
            "matched_total": matched_total,
            "discrepancy_amount": discrepancy,
            "status_detail": detail,
        },
    )
    return result


def reconcile_branch_date(branch: Branch, target_date: Date, attribution: Optional[Attribution] = None) -> List[ReconciliationResult]:
    attribution = attribution or Attribution(branch.business)
    sales_by_currency = {r.currency: r for r in sales_services.get_sales_records(branch, target_date)}

    txns_by_currency = defaultdict(list)
    unattributed = 0
    for t in bakong_services.get_transactions(branch.business, target_date):
        branch_id, source = attribution.branch_for(t)
        if branch_id == branch.pk:
            txns_by_currency[t.currency].append(t)
        elif source == SOURCE_UNATTRIBUTED:
            unattributed += 1

    pending_reason = ""
    if not branch.bakong_account_id:
        if unattributed:
            pending_reason = unassigned_reason(unattributed)
        elif not txns_by_currency:
            pending_reason = REASON_NO_TRANSACTIONS

    currencies = (set(sales_by_currency) | set(txns_by_currency)) or {DEFAULT_CURRENCY}
    results = []
    for currency in sorted(currencies):
        sales_record = sales_by_currency.get(currency)
        if sales_record is None:
            results.append(_save(branch, target_date, currency, ReconciliationResult.STATUS_PENDING, detail=REASON_NO_SALES))
            continue
        if pending_reason:
            results.append(_save(branch, target_date, currency, ReconciliationResult.STATUS_PENDING, detail=pending_reason))
            continue

        bakong_total = sum((t.amount for t in txns_by_currency[currency]), Decimal("0"))
        discrepancy = abs(sales_record.expected_total - bakong_total)
        tolerance = TOLERANCES.get(currency, TOLERANCES["USD"])
        status = ReconciliationResult.STATUS_MATCHED if discrepancy <= tolerance else ReconciliationResult.STATUS_DISCREPANCY
        results.append(_save(branch, target_date, currency, status, bakong_total, discrepancy))
    return results


def reconcile_business_date(business, target_date: Date) -> List[ReconciliationResult]:
    """Re-runs every branch of a business for one date (e.g. after a manual
    review changes which branch a payment belongs to). No alerts."""
    branches = branches_services.get_branches(business)
    attribution = Attribution(business, branches)
    results = []
    for branch in branches:
        results.extend(reconcile_branch_date(branch, target_date, attribution))
    return results
