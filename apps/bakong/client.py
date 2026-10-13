"""
Bakong Open API client.

Open questions (flagged per brief):
- Whether the API returns enough metadata to auto-match a payment to a specific branch,
  or whether branch-level sub-accounts (bakong_account_id on Branch) are needed.
- Rate limits: the polling interval in Celery Beat should be tuned once known.
"""
import logging
from datetime import date
from decimal import Decimal

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class BakongAPIError(Exception):
    pass


# KHQR payloads may carry ISO 4217 numeric codes instead of letters.
_CURRENCY_CODES = {"116": "KHR", "840": "USD"}


def normalize_currency(value) -> str:
    code = str(value or "KHR").strip().upper()
    return _CURRENCY_CODES.get(code, code)


class BakongClient:
    def __init__(self, token: str):
        self.base_url = settings.BAKONG_API_BASE_URL.rstrip("/")
        self.token = token
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {token}"})

    def _get(self, path: str, params: dict = None) -> dict:
        url = f"{self.base_url}{path}"
        try:
            resp = self.session.get(url, params=params, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            raise BakongAPIError(f"Bakong API request failed: {exc}") from exc

    def get_transactions(self, account_id: str, from_date: date, to_date: date) -> list[dict]:
        """
        Fetch transactions for a given account and date range.
        Returns a list of raw transaction dicts from the API.

        Note: adjust the path/params to match the actual Bakong Open API spec.
        """
        data = self._get(
            "/v1/transactions",
            params={
                "accountId": account_id,
                "fromDate": from_date.isoformat(),
                "toDate": to_date.isoformat(),
            },
        )
        return data.get("data", data) if isinstance(data, dict) else data

    @staticmethod
    def parse_transaction(raw: dict) -> dict:
        """
        Normalise a raw Bakong transaction payload into our internal schema.
        Field names are illustrative — map to the actual API response fields.
        """
        return {
            "timestamp": raw.get("transactionDate") or raw.get("timestamp"),
            "amount": Decimal(str(raw.get("amount", 0))),
            "currency": normalize_currency(raw.get("currency")),
            "account_id": str(raw.get("accountId") or ""),
            "reference": raw.get("reference", ""),
            "hash": raw.get("hash") or raw.get("transactionId", ""),
            "raw_payload": raw,
        }
