from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from apps.branches.models import Branch
from apps.businesses.models import Business, UserProfile
from .models import DailySalesRecord


class SalesApiTests(TestCase):
    def setUp(self):
        self.business = Business.objects.create(name="Biz")
        self.branch = Branch.objects.create(business=self.business, name="Main")
        User = get_user_model()
        self.manager = User.objects.create_user("manager", password="x")
        UserProfile.objects.create(user=self.manager, business=self.business, role=UserProfile.ROLE_MANAGER)
        self.viewer = User.objects.create_user("viewer", password="x")
        UserProfile.objects.create(user=self.viewer, business=self.business, role=UserProfile.ROLE_VIEWER)
        self.client = APIClient()
        self.import_url = f"/api/v1/branches/{self.branch.pk}/sales/import/"
        self.list_url = f"/api/v1/branches/{self.branch.pk}/sales/"

    def upload(self, content: bytes):
        return self.client.post(self.import_url, {"file": SimpleUploadedFile("s.csv", content)}, format="multipart")

    def test_csv_with_excel_bom_imports(self):
        self.client.force_authenticate(self.manager)
        resp = self.upload("﻿date,expected_total\r\n2026-10-01,12000\r\n".encode("utf-8"))
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data, {"created": 1, "errors": []})
        record = DailySalesRecord.objects.get()
        self.assertEqual((record.expected_total, record.currency), (Decimal("12000"), "KHR"))

    def test_csv_currency_column(self):
        self.client.force_authenticate(self.manager)
        resp = self.upload(b"date,expected_total,currency\n2026-10-01,12000,KHR\n2026-10-01,15.5,usd\n2026-10-01,1,EUR\n")
        self.assertEqual(resp.data["created"], 2)
        self.assertEqual(resp.data["errors"][0]["row"], 4)
        self.assertEqual(DailySalesRecord.objects.filter(currency="USD").get().expected_total, Decimal("15.5"))

    def test_non_utf8_csv_is_rejected(self):
        self.client.force_authenticate(self.manager)
        resp = self.upload(b"date,expected_total\n\xff\xfe\n")
        self.assertEqual(resp.status_code, 400)

    def test_viewer_cannot_import_or_create(self):
        self.client.force_authenticate(self.viewer)
        self.assertEqual(self.upload(b"date,expected_total\n2026-10-01,1\n").status_code, 403)
        resp = self.client.post(self.list_url, {"branch": self.branch.pk, "date": "2026-10-01", "expected_total": "1"}, format="json")
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(DailySalesRecord.objects.exists())

    def test_manual_entry_per_currency(self):
        self.client.force_authenticate(self.manager)
        for currency in ("KHR", "USD"):
            resp = self.client.post(
                self.list_url,
                {"branch": self.branch.pk, "date": "2026-10-01", "expected_total": "10", "currency": currency},
                format="json",
            )
            self.assertEqual(resp.status_code, 201, resp.data)
        # Currency is optional and defaults to KHR — and is unique per day.
        resp = self.client.post(self.list_url, {"branch": self.branch.pk, "date": "2026-10-01", "expected_total": "10"}, format="json")
        self.assertEqual(resp.status_code, 400)
