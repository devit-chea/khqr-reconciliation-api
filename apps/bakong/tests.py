from unittest import mock

from cryptography.fernet import Fernet
from django.test import TestCase, override_settings

from apps.branches.models import Branch
from apps.businesses.models import Business
from .client import BakongAPIError, BakongClient
from .models import BakongTransaction
from .tasks import poll_bakong_transactions, poll_business_transactions


def raw(hash_, amount="100", account_id=None, currency="KHR"):
    payload = {"hash": hash_, "amount": amount, "currency": currency, "transactionDate": "2026-10-01T10:00:00+07:00"}
    if account_id:
        payload["accountId"] = account_id
    return payload


class ParseTests(TestCase):
    def test_numeric_currency_codes_are_normalised(self):
        self.assertEqual(BakongClient.parse_transaction(raw("a", currency="840"))["currency"], "USD")
        self.assertEqual(BakongClient.parse_transaction(raw("a", currency="khr"))["currency"], "KHR")


@override_settings(ENCRYPTION_KEY=Fernet.generate_key().decode())
@mock.patch("apps.reconciliation.tasks.run_reconciliation.delay")
@mock.patch("apps.bakong.tasks.BakongClient.get_transactions")
class PollTests(TestCase):
    def setUp(self):
        self.business = Business.objects.create(name="Biz", bakong_account_id="biz@nbc")
        self.business.set_bakong_token("tok")
        self.business.save()
        Branch.objects.create(business=self.business, name="A", bakong_account_id="a@nbc")
        Branch.objects.create(business=self.business, name="B")

    def test_polls_business_and_branch_accounts(self, get_txns, reconcile):
        get_txns.side_effect = lambda acct, *_: {
            "biz@nbc": [raw("t1")],
            "a@nbc": [raw("t2")],
        }[acct]

        poll_business_transactions(self.business.pk)

        polled = [c.args[0] for c in get_txns.call_args_list]
        self.assertEqual(polled, ["biz@nbc", "a@nbc"])
        self.assertEqual(
            dict(BakongTransaction.objects.values_list("hash", "account_id")),
            {"t1": "biz@nbc", "t2": "a@nbc"},
        )
        reconcile.assert_called_once()
        self.assertEqual(reconcile.call_args.kwargs["business_id"], self.business.pk)

    def test_payload_account_id_wins_over_polled_account(self, get_txns, reconcile):
        get_txns.side_effect = lambda acct, *_: [raw("t1", account_id="a@nbc")] if acct == "biz@nbc" else []
        poll_business_transactions(self.business.pk)
        self.assertEqual(BakongTransaction.objects.get().account_id, "a@nbc")

    def test_duplicates_are_ignored(self, get_txns, reconcile):
        get_txns.return_value = [raw("t1")]
        poll_business_transactions(self.business.pk)
        poll_business_transactions(self.business.pk)
        self.assertEqual(BakongTransaction.objects.count(), 1)

    def test_api_error_retries_without_reconciling(self, get_txns, reconcile):
        get_txns.side_effect = BakongAPIError("down")
        with mock.patch.object(poll_business_transactions, "retry", side_effect=RuntimeError("retry")) as retry:
            with self.assertRaises(RuntimeError):
                poll_business_transactions(self.business.pk)
        retry.assert_called_once()
        reconcile.assert_not_called()

    def test_fan_out_queues_one_task_per_business(self, get_txns, reconcile):
        other = Business.objects.create(name="Other")
        with mock.patch.object(poll_business_transactions, "delay") as delay:
            poll_bakong_transactions()
        self.assertEqual(sorted(c.args[0] for c in delay.call_args_list), sorted([self.business.pk, other.pk]))
