"""Paystack client: start a payment, confirm it, and check webhook signatures.

Only the secret key (environment variable PAYSTACK_SECRET_KEY) is needed. Amounts are sent in the
currency's smallest unit (pesewas for GHS). Every payment is confirmed by asking Paystack directly
(`verify`) before it is recorded — a browser redirect or webhook alone is never trusted.
"""
import hashlib
import hmac
import json
import urllib.error
import urllib.request
from decimal import Decimal

from flask import current_app


CHECKOUT_ORIGIN = "https://checkout.paystack.com"   # where Paystack's payment pages live


class PaystackError(Exception):
    pass


def configured():
    return bool(current_app.config.get("PAYSTACK_SECRET_KEY"))


def _call(method, path, payload=None):
    key = current_app.config.get("PAYSTACK_SECRET_KEY")
    if not key:
        raise PaystackError("Online payments are not set up.")
    url = current_app.config.get("PAYSTACK_API_BASE", "https://api.paystack.co").rstrip("/") + path
    if not url.startswith("https://"):
        raise PaystackError("The Paystack address must start with https://.")
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {key}", "Content-Type": "application/json", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        try:
            msg = json.loads(exc.read().decode()).get("message")
        except Exception:  # noqa: BLE001 - the provider's error body is optional
            msg = None
        raise PaystackError(msg or f"Paystack answered {exc.code}.") from exc
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise PaystackError("Could not reach Paystack. Please try again in a moment.") from exc
    if not body.get("status"):
        raise PaystackError(body.get("message") or "Paystack refused the request.")
    return body.get("data") or {}


def to_subunit(amount):
    return int((Decimal(amount) * 100).to_integral_value())


def initialize(email, amount, currency, reference, callback_url, metadata):
    data = _call("POST", "/transaction/initialize", {
        "email": email, "amount": to_subunit(amount), "currency": currency, "reference": reference,
        "callback_url": callback_url, "metadata": metadata})
    if not data.get("authorization_url"):
        raise PaystackError("Paystack did not return a payment page.")
    if not data["authorization_url"].startswith(CHECKOUT_ORIGIN + "/"):
        raise PaystackError("Paystack returned an unexpected payment address.")
    return data["authorization_url"]


def verify(reference):
    """{'status': 'success'|..., 'amount': subunits, 'currency': 'GHS', 'channel': 'card'|'mobile_money', ...}"""
    return _call("GET", f"/transaction/verify/{urllib.request.quote(reference, safe='')}")


def signature_ok(raw_body, signature):
    key = current_app.config.get("PAYSTACK_SECRET_KEY")
    if not key or not signature:
        return False
    expected = hmac.new(key.encode(), raw_body, hashlib.sha512).hexdigest()
    return hmac.compare_digest(expected, signature)
