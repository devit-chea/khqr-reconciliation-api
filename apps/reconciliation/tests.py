from datetime import date, datetime
from decimal import Decimal
from unittest import mock
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.bakong.models import BakongTransaction
from apps.branches.models import Branch
from apps.businesses.models import Business, UserProfile
from apps.sales.models import DailySalesRecord
from .engine import REASON_NO_SALES, REASON_NO_TRANSACTIONS, REASON_SHARED_POOL, reconcile_branch_date
from .models import ReconciliationResult
from .tasks import run_reconciliation

TZ = ZoneInfo("Asia/Phnom_Penh")
DAY = date(2026, 10, 1)


class Fixtures:
    def setUp(self):
        self.business = Business.objects.create(name="Biz", bakong_account_id="biz@nbc")
        self._n = 0

    def branch(self, name="Main", account_id=""):
        return Branch.objects.create(business=self.business, name=name, bakong_account_id=account_id)

    def sale(self, branch, amount, currency="KHR", day=DAY):
        return DailySalesRecord.objects.create(branch=branch, date=day, expected_total=Decimal(amount), currency=currency)

    def txn(self, amount, account_id="biz@nbc", currency="KHR", day=DAY, business=None):
        self._n += 1
        return BakongTransaction.objects.create(
            business=business or self.business,
            account_id=account_id,
            timestamp=datetime(day.year, day.month, day.day, 12, 0, tzinfo=TZ),
            amount=Decimal(amount),
            currency=currency,
            hash=f"h{self._n}",
        )


class EngineTests(Fixtures, TestCase):
    def test_matched_with_sub_account(self):
        b = self.branch(account_id="b1@nbc")
        self.sale(b, "10000")
        self.txn("6000", "b1@nbc")
        self.txn("4000", "b1@nbc")
        self.txn("99999", "other@nbc")

        [r] = reconcile_branch_date(b, DAY)
        self.assertEqual(r.status, ReconciliationResult.STATUS_MATCHED)
        self.assertEqual(r.matched_total, Decimal("10000"))

    def test_discrepancy_outside_tolerance(self):
        b = self.branch(account_id="b1@nbc")
        self.sale(b, "10000")
        self.txn("9000", "b1@nbc")

        [r] = reconcile_branch_date(b, DAY)
        self.assertEqual(r.status, ReconciliationResult.STATUS_DISCREPANCY)
        self.assertEqual(r.discrepancy_amount, Decimal("1000"))

    def test_sub_account_with_no_transactions_is_a_discrepancy(self):
        b = self.branch(account_id="b1@nbc")
        self.sale(b, "500")

        [r] = reconcile_branch_date(b, DAY)
        self.assertEqual(r.status, ReconciliationResult.STATUS_DISCREPANCY)

    def test_currencies_are_reconciled_separately(self):
        b = self.branch(account_id="b1@nbc")
        self.sale(b, "40000", "KHR")
        self.sale(b, "10", "USD")
        self.txn("40000", "b1@nbc", "KHR")
        self.txn("10", "b1@nbc", "USD")

        results = {r.currency: r for r in reconcile_branch_date(b, DAY)}
        self.assertEqual(set(results), {"KHR", "USD"})
        self.assertEqual(results["KHR"].status, ReconciliationResult.STATUS_MATCHED)
        self.assertEqual(results["USD"].status, ReconciliationResult.STATUS_MATCHED)

    def test_usd_tolerance_is_one_cent(self):
        b = self.branch(account_id="b1@nbc")
        self.sale(b, "10.00", "USD")
        self.txn("9.50", "b1@nbc", "USD")

        [r] = reconcile_branch_date(b, DAY)
        self.assertEqual(r.status, ReconciliationResult.STATUS_DISCREPANCY)

    def test_transactions_without_sales_record_are_pending(self):
        b = self.branch(account_id="b1@nbc")
        self.sale(b, "1000", "KHR")
        self.txn("1000", "b1@nbc", "KHR")
        self.txn("5", "b1@nbc", "USD")

        results = {r.currency: r for r in reconcile_branch_date(b, DAY)}
        self.assertEqual(results["USD"].status, ReconciliationResult.STATUS_PENDING)
        self.assertEqual(results["USD"].status_detail, REASON_NO_SALES)

    def test_no_sales_record_is_pending(self):
        b = self.branch(account_id="b1@nbc")
        [r] = reconcile_branch_date(b, DAY)
        self.assertEqual(r.status, ReconciliationResult.STATUS_PENDING)
        self.assertEqual(r.status_detail, REASON_NO_SALES)

    def test_single_unassigned_branch_claims_pool(self):
        assigned = self.branch("A", "a@nbc")
        pool = self.branch("Pool")
        self.sale(pool, "3000")
        self.txn("1000", "a@nbc")
        self.txn("3000", "biz@nbc")

        [r] = reconcile_branch_date(pool, DAY)
        self.assertEqual(r.status, ReconciliationResult.STATUS_MATCHED)
        self.assertEqual(r.matched_total, Decimal("3000"))

    def test_empty_pool_is_pending(self):
        pool = self.branch("Pool")
        self.sale(pool, "3000")

        [r] = reconcile_branch_date(pool, DAY)
        self.assertEqual(r.status, ReconciliationResult.STATUS_PENDING)
        self.assertEqual(r.status_detail, REASON_NO_TRANSACTIONS)

    def test_two_unassigned_branches_do_not_both_claim_pool(self):
        b1 = self.branch("One")
        b2 = self.branch("Two")
        self.sale(b1, "3000")
        self.sale(b2, "3000")
        self.txn("3000", "biz@nbc")

        for b in (b1, b2):
            [r] = reconcile_branch_date(b, DAY)
            self.assertEqual(r.status, ReconciliationResult.STATUS_PENDING)
            self.assertEqual(r.status_detail, REASON_SHARED_POOL)

    def test_rerun_preserves_resolution(self):
        b = self.branch(account_id="b1@nbc")
        self.sale(b, "10000")
        [r] = reconcile_branch_date(b, DAY)
        r.resolution_status = ReconciliationResult.RESOLUTION_RESOLVED
        r.resolution_note = "cash"
        r.save()

        [r] = reconcile_branch_date(b, DAY)
        self.assertEqual(r.resolution_status, ReconciliationResult.RESOLUTION_RESOLVED)
        self.assertEqual(r.resolution_note, "cash")


@mock.patch("apps.reconciliation.tasks.send_discrepancy_alert", return_value=True)
class AlertTests(Fixtures, TestCase):
    def setUp(self):
        super().setUp()
        self.b = self.branch(account_id="b1@nbc")
        self.sale(self.b, "10000")
        self.txn("9000", "b1@nbc")

    def test_alerts_once_per_amount(self, send):
        run_reconciliation(DAY.isoformat())
        run_reconciliation(DAY.isoformat())
        self.assertEqual(send.call_count, 1)
        send.assert_called_with(self.b, DAY, Decimal("1000.00"), "KHR")

    def test_realerts_when_amount_changes(self, send):
        run_reconciliation(DAY.isoformat())
        self.txn("500", "b1@nbc")
        run_reconciliation(DAY.isoformat())
        self.assertEqual(send.call_count, 2)

    def test_no_alert_once_resolved_or_investigating(self, send):
        run_reconciliation(DAY.isoformat())
        ReconciliationResult.objects.update(resolution_status=ReconciliationResult.RESOLUTION_INVESTIGATING)
        self.txn("500", "b1@nbc")
        run_reconciliation(DAY.isoformat())
        self.assertEqual(send.call_count, 1)

    def test_failed_delivery_retries_next_run(self, send):
        send.return_value = False
        run_reconciliation(DAY.isoformat())
        send.return_value = True
        run_reconciliation(DAY.isoformat())
        self.assertEqual(send.call_count, 2)

    def test_business_filter(self, send):
        other = Business.objects.create(name="Other")
        ob = Branch.objects.create(business=other, name="X", bakong_account_id="x@nbc")
        DailySalesRecord.objects.create(branch=ob, date=DAY, expected_total=Decimal("1"))

        run_reconciliation(DAY.isoformat(), business_id=other.pk)
        self.assertFalse(ReconciliationResult.objects.filter(branch=self.b).exists())
        self.assertTrue(ReconciliationResult.objects.filter(branch=ob).exists())


class ApiTests(Fixtures, TestCase):
    def setUp(self):
        super().setUp()
        User = get_user_model()
        self.manager = User.objects.create_user("manager", password="x")
        UserProfile.objects.create(user=self.manager, business=self.business, role=UserProfile.ROLE_MANAGER)
        self.viewer = User.objects.create_user("viewer", password="x")
        UserProfile.objects.create(user=self.viewer, business=self.business, role=UserProfile.ROLE_VIEWER)
        self.client = APIClient()

    @mock.patch("apps.reconciliation.tasks.run_reconciliation.delay")
    def test_trigger_is_scoped_to_callers_business(self, delay):
        self.client.force_authenticate(self.manager)
        resp = self.client.post("/api/v1/reconciliation/trigger/", {"date": "2026-10-01"}, format="json")
        self.assertEqual(resp.status_code, 200)
        delay.assert_called_once_with(target_date="2026-10-01", business_id=self.business.pk)

    @mock.patch("apps.reconciliation.tasks.run_reconciliation.delay")
    def test_trigger_rejects_bad_date(self, delay):
        self.client.force_authenticate(self.manager)
        for bad in ("yesterday", "2026-13-45"):
            resp = self.client.post("/api/v1/reconciliation/trigger/", {"date": bad}, format="json")
            self.assertEqual(resp.status_code, 400)
        delay.assert_not_called()

    def test_viewer_cannot_trigger(self):
        self.client.force_authenticate(self.viewer)
        resp = self.client.post("/api/v1/reconciliation/trigger/", {}, format="json")
        self.assertEqual(resp.status_code, 403)

    def test_detail_lists_only_branch_transactions_in_result_currency(self):
        b = self.branch(account_id="b1@nbc")
        self.sale(b, "1000")
        mine = self.txn("1000", "b1@nbc")
        self.txn("7", "b1@nbc", "USD")
        self.txn("555", "other@nbc")
        result = next(r for r in reconcile_branch_date(b, DAY) if r.currency == "KHR")

        self.client.force_authenticate(self.manager)
        resp = self.client.get(f"/api/v1/reconciliation/{result.pk}/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual([t["id"] for t in resp.data["bakong_transactions"]], [mine.pk])
        self.assertEqual(resp.data["reconciliation"]["currency"], "KHR")
