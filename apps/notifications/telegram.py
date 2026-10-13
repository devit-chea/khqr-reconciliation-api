import logging
from datetime import date
from decimal import Decimal

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


def escape_md(text) -> str:
    """Escapes Telegram legacy-Markdown control characters in user-supplied text
    (branch/business names), which would otherwise break parsing."""
    text = str(text)
    for ch in ("\\", "_", "*", "`", "["):
        text = text.replace(ch, "\\" + ch)
    return text


def send_message(business, message: str) -> bool:
    """Sends a Markdown message to the business's chat. Returns True if delivered."""
    # Prefer the business's own bot/chat; fall back to the server-wide settings so
    # deployments that haven't configured per-business alerting yet keep working.
    token = business.get_telegram_bot_token() or settings.TELEGRAM_BOT_TOKEN
    chat_id = business.telegram_chat_id or settings.TELEGRAM_CHAT_ID
    if not token or not chat_id:
        logger.warning("Telegram not configured for business %s; skipping message.", business)
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        resp = requests.post(
            url,
            json={"chat_id": chat_id, "text": message, "parse_mode": "Markdown"},
            timeout=10,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.error("Failed to send Telegram message: %s", exc)
        return False
    return True


def send_discrepancy_alert(branch, target_date: date, discrepancy_amount: Decimal, currency: str = "KHR") -> bool:
    """Returns True if the alert was delivered."""
    message = (
        f"⚠️ *Reconciliation Discrepancy*\n\n"
        f"*Branch:* {escape_md(branch.name)}\n"
        f"*Business:* {escape_md(branch.business.name)}\n"
        f"*Date:* {target_date}\n"
        f"*Discrepancy:* {discrepancy_amount:,.2f} {currency}\n\n"
        f"Please review the reconciliation dashboard."
    )
    return send_message(branch.business, message)
