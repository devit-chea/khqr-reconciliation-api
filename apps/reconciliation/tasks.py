import logging
from collections import Counter
from datetime import date, datetime, timedelta

from celery import shared_task
from django.utils import timezone

from apps.bakong import services as bakong_services
from apps.branches.models import Branch
from apps.businesses.models import Business
from apps.notifications.telegram import escape_md, send_discrepancy_alert, send_message
from apps.sales import services as sales_services
from .engine import SOURCE_UNATTRIBUTED, Attribution, reconcile_branch_date
from .models import ReconciliationResult

logger = logging.getLogger(__name__)


def _parse_date(target_date: str = None, default_offset_days: int = 0) -> date:
    if target_date:
        return datetime.strptime(target_date, "%Y-%m-%d").date()
    return timezone.localdate() - timedelta(days=default_offset_days)


def _alert_if_new(branch, target_date: date, result: ReconciliationResult):
    """Alert once per discrepancy amount, and only while nobody has picked it up."""
    if result.status != ReconciliationResult.STATUS_DISCREPANCY:
        if result.last_alerted_amount is not None:
            # Back in balance — a future discrepancy should alert again.
            result.last_alerted_amount = None
            result.save(update_fields=["last_alerted_amount"])
        return
    if result.resolution_status != ReconciliationResult.RESOLUTION_OPEN:
        return
    if result.last_alerted_amount == result.discrepancy_amount:
        return
    if send_discrepancy_alert(branch, target_date, result.discrepancy_amount, result.currency):
        result.last_alerted_amount = result.discrepancy_amount
        result.save(update_fields=["last_alerted_amount"])


@shared_task
def run_reconciliation(target_date: str = None, business_id: int = None):
    d = _parse_date(target_date)

    branches = Branch.objects.select_related("business")
    if business_id:
        branches = branches.filter(business_id=business_id)

    attributions = {}
    for branch in branches:
        try:
            attribution = attributions.get(branch.business_id)
            if attribution is None:
                attribution = attributions[branch.business_id] = Attribution(branch.business)
            for result in reconcile_branch_date(branch, d, attribution):
                _alert_if_new(branch, d, result)
        except Exception as exc:
            logger.error("Reconciliation failed for branch %s date %s: %s", branch.pk, d, exc)


def build_digest(business, d: date) -> str:
    branches = list(Branch.objects.filter(business=business))
    results = list(ReconciliationResult.objects.filter(branch__business=business, date=d).select_related("branch"))
    counts = Counter(r.status for r in results)
    open_discrepancies = [
        r for r in results
        if r.status == ReconciliationResult.STATUS_DISCREPANCY
        and r.resolution_status in (ReconciliationResult.RESOLUTION_OPEN, ReconciliationResult.RESOLUTION_INVESTIGATING)
    ]
    with_sales = sales_services.branches_with_sales([b.pk for b in branches], d)
    missing_sales = [b for b in branches if b.pk not in with_sales]
    attribution = Attribution(business, branches)
    unattributed = sum(
        1 for t in bakong_services.get_transactions(business, d)
        if attribution.branch_for(t)[1] == SOURCE_UNATTRIBUTED
    )

    lines = [
        f"📊 *Daily reconciliation — {escape_md(business.name)}*",
        f"*Date:* {d}",
        "",
        f"✅ Matched: {counts[ReconciliationResult.STATUS_MATCHED]}   "
        f"⚠️ Discrepancies: {counts[ReconciliationResult.STATUS_DISCREPANCY]}   "
        f"⏳ Pending: {counts[ReconciliationResult.STATUS_PENDING]}",
    ]
    if open_discrepancies:
        lines += ["", "*Open discrepancies:*"]
        lines += [
            f"• {escape_md(r.branch.name)}: {r.discrepancy_amount:,.2f} {r.currency} ({r.resolution_status})"
            for r in open_discrepancies
        ]
    if missing_sales:
        lines += ["", "*No sales entered:*"]
        lines += [f"• {escape_md(b.name)}" for b in missing_sales]
    if unattributed:
        lines += ["", f"*Unassigned payments:* {unattributed} — assign them on the Transactions page."]
    return "\n".join(lines)


@shared_task
def send_daily_digest(target_date: str = None):
    """Morning summary of yesterday (by default), one Telegram message per business.
    Reconciles first so the numbers include payments polled overnight."""
    d = _parse_date(target_date, default_offset_days=1)
    for business in Business.objects.filter(daily_digest_enabled=True):
        try:
            run_reconciliation(d.isoformat(), business_id=business.pk)
            if not Branch.objects.filter(business=business).exists():
                continue
            send_message(business, build_digest(business, d))
        except Exception as exc:
            logger.error("Daily digest failed for business %s: %s", business.pk, exc)


@shared_task
def remind_missing_sales(target_date: str = None):
    """Evening nudge listing branches that haven't entered today's (by default) sales."""
    d = _parse_date(target_date)
    for business in Business.objects.filter(sales_reminder_enabled=True):
        branches = list(Branch.objects.filter(business=business))
        with_sales = sales_services.branches_with_sales([b.pk for b in branches], d)
        missing = [b for b in branches if b.pk not in with_sales]
        if not missing:
            continue
        message = "\n".join(
            [f"📝 *Sales not entered yet — {escape_md(business.name)}*", f"*Date:* {d}", ""]
            + [f"• {escape_md(b.name)}" for b in missing]
            + ["", "Please enter today's sales so they can be reconciled."]
        )
        send_message(business, message)
