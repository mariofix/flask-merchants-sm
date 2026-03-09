"""Tests for KhipuProvider.

Covers accepts_notify_url flag, body kwarg, transaction_id via metadata,
parse_webhook for v3.0 and legacy formats, and signature verification.
"""

import base64
import hashlib
import hmac
import json
from decimal import Decimal
from unittest.mock import patch

import pytest

from merchants.models import PaymentState
from merchants.providers.khipu import KhipuProvider
from merchants.webhooks import WebhookVerificationError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_provider(subject="Order", webhook_secret="") -> KhipuProvider:
    return KhipuProvider(api_key="test-api-key", subject=subject, webhook_secret=webhook_secret)


def _make_khipu_signature(secret: str, timestamp: str, payload: bytes) -> str:
    """Build a valid x-khipu-signature header value."""
    to_hash = f"{timestamp}.".encode() + payload
    digest = hmac.new(secret.encode(), to_hash, hashlib.sha256).digest()
    sig = base64.b64encode(digest).decode()
    return f"t={timestamp},s={sig}"


_FAKE_PAYMENT_RESPONSE = {
    "payment_id": "pay_abc123",
    "payment_url": "https://khipu.com/payment/pay_abc123",
    "simplified_transfer_url": "",
    "transfer_url": "",
}

# Example v3.0 webhook body (matches real Khipu format)
_V3_WEBHOOK_BODY = {
    "payment_id": "ltoyxrpcwx8s",
    "receiver_id": 316621,
    "subject": "Pago SaborMirandiano",
    "amount": "5900.00",
    "discount": "0.00",
    "currency": "CLP",
    "body": "Abono: c14d6d4f-34c8-4659-ac47-15c7ddcfa63b",
    "receipt_url": "https://s3.amazonaws.com/notifications.khipu.com/CPKH-0803262321-ltoyxrpcwx8s.pdf",
    "bank": "DemoBank",
    "bank_id": "Bawdf",
    "payer_name": "Cobrador de desarrollo #316.621",
    "payer_email": "test@example.com",
    "personal_identifier": "12345678-5",
    "bank_account_number": "000000000000123456785",
    "out_of_date_conciliation": False,
    "transaction_id": "c14d6d4f-34c8-4659-ac47-15c7ddcfa63b",
    "responsible_user_email": "admin@example.com",
    "payment_method": "simplified_transfer",
    "conciliation_date": "2026-03-09T02:22:27.266Z",
}


# ---------------------------------------------------------------------------
# Provider metadata
# ---------------------------------------------------------------------------

class TestKhipuProviderAttributes:
    def test_accepts_notify_url_is_true(self):
        provider = make_provider()
        assert provider.accepts_notify_url is True

    def test_key_is_khipu(self):
        provider = make_provider()
        assert provider.key == "khipu"

    def test_subject_is_configurable(self):
        provider = make_provider(subject="Pago SaborMirandiano")
        assert provider._subject == "Pago SaborMirandiano"

    def test_default_subject(self):
        provider = make_provider()
        assert provider._subject == "Order"

    def test_webhook_secret_stored(self):
        provider = make_provider(webhook_secret="my-secret")
        assert provider._webhook_secret == "my-secret"


# ---------------------------------------------------------------------------
# create_checkout
# ---------------------------------------------------------------------------

class TestKhipuProviderCreateCheckout:
    def _make_session(self, provider, **kwargs):
        with patch("khipu_tools.Payments.create", return_value=_FAKE_PAYMENT_RESPONSE):
            return provider.create_checkout(
                amount=Decimal("5000"),
                currency="CLP",
                success_url="https://example.com/success",
                cancel_url="https://example.com/cancel",
                **kwargs,
            )

    def test_body_is_sent_when_provided(self):
        provider = make_provider()
        with patch("khipu_tools.Payments.create") as mock_create:
            mock_create.return_value = _FAKE_PAYMENT_RESPONSE
            provider.create_checkout(
                amount=Decimal("5000"),
                currency="CLP",
                success_url="https://example.com/success",
                cancel_url="https://example.com/cancel",
                body="Abono: abc-123",
            )
            call_kwargs = mock_create.call_args[1]
            assert call_kwargs["body"] == "Abono: abc-123"

    def test_body_omitted_when_empty(self):
        provider = make_provider()
        with patch("khipu_tools.Payments.create") as mock_create:
            mock_create.return_value = _FAKE_PAYMENT_RESPONSE
            provider.create_checkout(
                amount=Decimal("5000"),
                currency="CLP",
                success_url="https://example.com/success",
                cancel_url="https://example.com/cancel",
            )
            call_kwargs = mock_create.call_args[1]
            assert "body" not in call_kwargs

    def test_transaction_id_set_from_metadata_order_id(self):
        provider = make_provider()
        with patch("khipu_tools.Payments.create") as mock_create:
            mock_create.return_value = _FAKE_PAYMENT_RESPONSE
            provider.create_checkout(
                amount=Decimal("5000"),
                currency="CLP",
                success_url="https://example.com/success",
                cancel_url="https://example.com/cancel",
                metadata={"order_id": "de19a532-abc"},
            )
            call_kwargs = mock_create.call_args[1]
            assert call_kwargs["transaction_id"] == "de19a532-abc"

    def test_transaction_id_omitted_without_metadata(self):
        provider = make_provider()
        with patch("khipu_tools.Payments.create") as mock_create:
            mock_create.return_value = _FAKE_PAYMENT_RESPONSE
            provider.create_checkout(
                amount=Decimal("5000"),
                currency="CLP",
                success_url="https://example.com/success",
                cancel_url="https://example.com/cancel",
            )
            call_kwargs = mock_create.call_args[1]
            assert "transaction_id" not in call_kwargs

    def test_notify_url_from_kwargs(self):
        provider = make_provider()
        with patch("khipu_tools.Payments.create") as mock_create:
            mock_create.return_value = _FAKE_PAYMENT_RESPONSE
            provider.create_checkout(
                amount=Decimal("5000"),
                currency="CLP",
                success_url="https://example.com/success",
                cancel_url="https://example.com/cancel",
                notify_url="https://example.com/webhook/khipu",
            )
            call_kwargs = mock_create.call_args[1]
            assert call_kwargs["notify_url"] == "https://example.com/webhook/khipu"

    def test_notify_url_fallback_to_instance_default(self):
        provider = KhipuProvider(api_key="test-key", notify_url="https://default.example.com/wh")
        with patch("khipu_tools.Payments.create") as mock_create:
            mock_create.return_value = _FAKE_PAYMENT_RESPONSE
            provider.create_checkout(
                amount=Decimal("5000"),
                currency="CLP",
                success_url="https://example.com/success",
                cancel_url="https://example.com/cancel",
            )
            call_kwargs = mock_create.call_args[1]
            assert call_kwargs["notify_url"] == "https://default.example.com/wh"

    def test_notify_url_omitted_when_empty(self):
        provider = make_provider()
        with patch("khipu_tools.Payments.create") as mock_create:
            mock_create.return_value = _FAKE_PAYMENT_RESPONSE
            provider.create_checkout(
                amount=Decimal("5000"),
                currency="CLP",
                success_url="https://example.com/success",
                cancel_url="https://example.com/cancel",
            )
            call_kwargs = mock_create.call_args[1]
            assert "notify_url" not in call_kwargs

    def test_subject_sent_from_instance(self):
        provider = make_provider(subject="Pago SaborMirandiano")
        with patch("khipu_tools.Payments.create") as mock_create:
            mock_create.return_value = _FAKE_PAYMENT_RESPONSE
            provider.create_checkout(
                amount=Decimal("5000"),
                currency="CLP",
                success_url="https://example.com/success",
                cancel_url="https://example.com/cancel",
            )
            call_kwargs = mock_create.call_args[1]
            assert call_kwargs["subject"] == "Pago SaborMirandiano"

    def test_session_id_from_payment_id(self):
        provider = make_provider()
        session = self._make_session(provider)
        assert session.session_id == "pay_abc123"

    def test_redirect_url_is_payment_url(self):
        provider = make_provider()
        session = self._make_session(provider)
        assert session.redirect_url == "https://khipu.com/payment/pay_abc123"

    def test_provider_key_is_khipu(self):
        provider = make_provider()
        session = self._make_session(provider)
        assert session.provider == "khipu"

    def test_amount_preserved(self):
        provider = make_provider()
        session = self._make_session(provider)
        assert session.amount == Decimal("5000")

    def test_currency_preserved(self):
        provider = make_provider()
        session = self._make_session(provider)
        assert session.currency == "CLP"

    def test_notify_api_version_always_sent(self):
        provider = make_provider()
        with patch("khipu_tools.Payments.create") as mock_create:
            mock_create.return_value = _FAKE_PAYMENT_RESPONSE
            provider.create_checkout(
                amount=Decimal("5000"),
                currency="CLP",
                success_url="https://example.com/success",
                cancel_url="https://example.com/cancel",
            )
            call_kwargs = mock_create.call_args[1]
            assert call_kwargs.get("notify_api_version") == "3.0"


# ---------------------------------------------------------------------------
# parse_webhook — v3.0 format
# ---------------------------------------------------------------------------

class TestKhipuProviderParseWebhookV3:
    """Tests for Khipu v3.0 webhook parsing (JSON with conciliation_date)."""

    def test_v3_conciliated_payment_maps_to_succeeded(self):
        provider = make_provider()
        payload = json.dumps(_V3_WEBHOOK_BODY).encode()
        event = provider.parse_webhook(payload, {})
        assert event.state == PaymentState.SUCCEEDED

    def test_v3_event_type_is_conciliated(self):
        provider = make_provider()
        payload = json.dumps(_V3_WEBHOOK_BODY).encode()
        event = provider.parse_webhook(payload, {})
        assert event.event_type == "payment.conciliated"

    def test_v3_payment_id_extracted(self):
        provider = make_provider()
        payload = json.dumps(_V3_WEBHOOK_BODY).encode()
        event = provider.parse_webhook(payload, {})
        assert event.payment_id == "ltoyxrpcwx8s"

    def test_v3_raw_contains_full_body(self):
        provider = make_provider()
        payload = json.dumps(_V3_WEBHOOK_BODY).encode()
        event = provider.parse_webhook(payload, {})
        assert event.raw["transaction_id"] == "c14d6d4f-34c8-4659-ac47-15c7ddcfa63b"
        assert event.raw["amount"] == "5900.00"
        assert event.raw["payer_email"] == "test@example.com"

    def test_v3_provider_is_khipu(self):
        provider = make_provider()
        payload = json.dumps(_V3_WEBHOOK_BODY).encode()
        event = provider.parse_webhook(payload, {})
        assert event.provider == "khipu"

    def test_v3_without_conciliation_date_maps_to_unknown(self):
        body = {k: v for k, v in _V3_WEBHOOK_BODY.items() if k != "conciliation_date"}
        provider = make_provider()
        payload = json.dumps(body).encode()
        event = provider.parse_webhook(payload, {})
        assert event.state == PaymentState.UNKNOWN
        assert event.event_type == "payment.notification"


# ---------------------------------------------------------------------------
# parse_webhook — signature verification
# ---------------------------------------------------------------------------

class TestKhipuProviderWebhookSignature:
    """Tests for x-khipu-signature verification in parse_webhook."""

    def test_valid_signature_passes(self):
        secret = "1a4cbbbeb8bdb7e1d73572b9cc43ce4ce18f79d9"
        provider = make_provider(webhook_secret=secret)
        payload = json.dumps(_V3_WEBHOOK_BODY).encode()
        timestamp = "1773022948436"
        sig = _make_khipu_signature(secret, timestamp, payload)
        headers = {"X-Khipu-Signature": sig}

        event = provider.parse_webhook(payload, headers)
        assert event.state == PaymentState.SUCCEEDED

    def test_invalid_signature_raises(self):
        secret = "1a4cbbbeb8bdb7e1d73572b9cc43ce4ce18f79d9"
        provider = make_provider(webhook_secret=secret)
        payload = json.dumps(_V3_WEBHOOK_BODY).encode()
        headers = {"X-Khipu-Signature": "t=1773022948436,s=INVALID_BASE64_SIGNATURE=="}

        with pytest.raises(WebhookVerificationError):
            provider.parse_webhook(payload, headers)

    def test_missing_signature_header_raises_when_secret_configured(self):
        provider = make_provider(webhook_secret="some-secret")
        payload = json.dumps(_V3_WEBHOOK_BODY).encode()

        with pytest.raises(WebhookVerificationError, match="header is missing"):
            provider.parse_webhook(payload, {})

    def test_no_secret_skips_verification(self):
        provider = make_provider(webhook_secret="")
        payload = json.dumps(_V3_WEBHOOK_BODY).encode()
        headers = {"X-Khipu-Signature": "t=123,s=anything"}
        # Should not raise even with bogus signature
        event = provider.parse_webhook(payload, headers)
        assert event.payment_id == "ltoyxrpcwx8s"

    def test_signature_with_lowercase_header(self):
        secret = "test-secret-key"
        provider = make_provider(webhook_secret=secret)
        payload = json.dumps(_V3_WEBHOOK_BODY).encode()
        timestamp = "1773022948436"
        sig = _make_khipu_signature(secret, timestamp, payload)
        headers = {"x-khipu-signature": sig}

        event = provider.parse_webhook(payload, headers)
        assert event.state == PaymentState.SUCCEEDED


# ---------------------------------------------------------------------------
# parse_webhook — legacy format (backward compat)
# ---------------------------------------------------------------------------

class TestKhipuProviderParseWebhookLegacy:
    """Tests for backward-compatible parsing of legacy webhook formats."""

    def test_parse_json_webhook_with_payment_status(self):
        provider = make_provider()
        payload = json.dumps({"payment_id": "pay_xyz", "payment_status": "done"}).encode()
        event = provider.parse_webhook(payload, {})
        assert event.payment_id == "pay_xyz"
        assert event.provider == "khipu"

    def test_parse_urlencoded_webhook(self):
        provider = make_provider()
        payload = b"payment_id=pay_xyz&payment_status=done"
        event = provider.parse_webhook(payload, {})
        assert event.payment_id == "pay_xyz"
        assert event.state == PaymentState.SUCCEEDED

    def test_done_maps_to_succeeded(self):
        provider = make_provider()
        payload = json.dumps({"payment_id": "p1", "payment_status": "done"}).encode()
        event = provider.parse_webhook(payload, {})
        assert event.state == PaymentState.SUCCEEDED

    def test_pending_maps_to_pending(self):
        provider = make_provider()
        payload = json.dumps({"payment_id": "p1", "payment_status": "pending"}).encode()
        event = provider.parse_webhook(payload, {})
        assert event.state == PaymentState.PENDING
