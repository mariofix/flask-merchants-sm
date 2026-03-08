"""Tests for KhipuProvider.

Covers accepts_notify_url flag, body kwarg, transaction_id via metadata,
and parse_webhook without requiring a running server or real API key.
"""

import json
from decimal import Decimal
from unittest.mock import patch

import pytest

from merchants.models import PaymentState
from merchants.providers.khipu import KhipuProvider


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_provider(subject="Order") -> KhipuProvider:
    return KhipuProvider(api_key="test-api-key", subject=subject)


_FAKE_PAYMENT_RESPONSE = {
    "payment_id": "pay_abc123",
    "payment_url": "https://khipu.com/payment/pay_abc123",
    "simplified_transfer_url": "",
    "transfer_url": "",
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
# parse_webhook
# ---------------------------------------------------------------------------

class TestKhipuProviderParseWebhook:
    def test_parse_json_webhook(self):
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
