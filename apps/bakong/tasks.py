import logging
from datetime import date, timedelta

from celery import shared_task
from django.utils import timezone

from apps.branches import services as branches_services
from apps.businesses.models import Business
from .client import BakongClient, BakongAPIError
from .models import BakongTransaction

logger = logging.getLogger(__name__)


@shared_task
def poll_bakong_transactions(business_id: int = None):
    """
    Fans out one poll task per business (or just `business_id`), so one
    business's API failure retries on its own instead of blocking the rest.
    """
    qs = Business.objects.all()
    if business_id:
        qs = qs.filter(pk=business_id)
    for pk in qs.values_list("pk", flat=True):
        poll_business_transactions.delay(pk)


def _store_transaction(business, polled_account_id: str, raw: dict) -> bool:
    parsed = BakongClient.parse_transaction(raw)
    txn_hash = parsed.get("hash")
    if not txn_hash:
        return False
    _, created = BakongTransaction.objects.get_or_create(
        hash=txn_hash,
        defaults={
            "business": business,
            "account_id": parsed["account_id"] or polled_account_id,
            "timestamp": parsed["timestamp"],
            "amount": parsed["amount"],
            "currency": parsed["currency"],
            "reference": parsed["reference"],
            "raw_payload": parsed["raw_payload"],
        },
    )
    return created


MAX_BACKFILL_DAYS = 31


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def poll_business_transactions(self, business_id: int, date_from: str = None, date_to: str = None):
    """
    Polls Bakong for the business account and every branch sub-account,
    stores new transactions, then reconciles each polled day before today
    (yesterday, by default). date_from/date_to (YYYY-MM-DD) backfill a range.
    """
    business = Business.objects.filter(pk=business_id).first()
    if business is None:
        return

    token = business.get_bakong_token()
    if not token:
        logger.info("Business %s has no Bakong token, skipping.", business.pk)
        return

    account_ids = list(dict.fromkeys(
        a for a in [business.bakong_account_id, *branches_services.get_account_ids(business)] if a
    ))
    if not account_ids:
        logger.info("Business %s has no Bakong account IDs, skipping.", business.pk)
        return

    today = timezone.localdate()
    from_date = date.fromisoformat(date_from) if date_from else today - timedelta(days=1)
    to_date = date.fromisoformat(date_to) if date_to else today

    client = BakongClient(token)
    saved = 0
    try:
        for account_id in account_ids:
            for raw in client.get_transactions(account_id, from_date, to_date):
                saved += _store_transaction(business, account_id, raw)
    except BakongAPIError as exc:
        logger.error("Bakong poll failed for business %s: %s", business.pk, exc)
        Business.objects.filter(pk=business.pk).update(
            bakong_last_error=str(exc)[:1000], bakong_last_error_at=timezone.now()
        )
        raise self.retry(exc=exc)

    Business.objects.filter(pk=business.pk).update(
        bakong_last_polled_at=timezone.now(), bakong_last_error="", bakong_last_error_at=None
    )
    logger.info("Business %s: saved %d new Bakong transactions.", business.pk, saved)

    # Today is still in progress — it gets reconciled once it's "yesterday".
    from apps.reconciliation.tasks import run_reconciliation
    d = from_date
    while d <= min(to_date, today - timedelta(days=1)):
        run_reconciliation.delay(target_date=d.isoformat(), business_id=business.pk)
        d += timedelta(days=1)
