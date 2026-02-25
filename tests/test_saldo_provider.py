"""Tests for SaldoProvider.

Covers create_checkout, get_payment, and parse_webhook without requiring
a running server or real payment gateway.
"""

from decimal import Decimal

import pytest

from app.providers.saldo import SaldoProvider


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_provider() -> SaldoProvider:
    return SaldoProvider()


# ---------------------------------------------------------------------------
# create_checkout
# ---------------------------------------------------------------------------

class TestSaldoProviderCreateCheckout:
    def test_session_id_starts_with_saldo(self):
        provider = make_provider()
        session = provider.create_checkout(
            amount=Decimal("5000"),
            currency="CLP",
            success_url="https://example.com/success",
            cancel_url="https://example.com/cancel",
        )
        assert session.session_id.startswith("saldo_")

    def test_redirect_url_is_success_url(self):
        provider = make_provider()
        session = provider.create_checkout(
            amount=Decimal("3000"),
            currency="CLP",
            success_url="https://example.com/ok",
            cancel_url="https://example.com/nope",
        )
        assert session.redirect_url == "https://example.com/ok"

    def test_provider_key_is_saldo(self):
        provider = make_provider()
        session = provider.create_checkout(
            amount=Decimal("1000"),
            currency="CLP",
            success_url="https://example.com/ok",
            cancel_url="https://example.com/nope",
        )
        assert session.provider == "saldo"

    def test_amount_and_currency_preserved(self):
        provider = make_provider()
        session = provider.create_checkout(
            amount=Decimal("7500"),
            currency="CLP",
            success_url="https://example.com/ok",
            cancel_url="https://example.com/cancel",
        )
        assert session.amount == Decimal("7500")
        assert session.currency == "CLP"

    def test_transaction_code_in_metadata(self):
        provider = make_provider()
        session = provider.create_checkout(
            amount=Decimal("2000"),
            currency="CLP",
            success_url="https://example.com/ok",
            cancel_url="https://example.com/cancel",
        )
        assert "transaction_code" in session.metadata
        assert len(session.metadata["transaction_code"]) == 8

    def test_saldo_antes_and_despues_computed(self):
        provider = make_provider()
        session = provider.create_checkout(
            amount=Decimal("3000"),
            currency="CLP",
            success_url="https://example.com/ok",
            cancel_url="https://example.com/cancel",
            metadata={"saldo_antes": 10000},
        )
        assert session.metadata["saldo_antes"] == 10000
        assert session.metadata["saldo_despues"] == 7000

    def test_raw_contains_model_property(self):
        provider = make_provider()
        session = provider.create_checkout(
            amount=Decimal("1000"),
            currency="CLP",
            success_url="https://example.com/ok",
            cancel_url="https://example.com/cancel",
            metadata={"model_property": "saldo_cuenta", "apoderado_id": "42"},
        )
        assert session.raw["model_property"] == "saldo_cuenta"
        assert session.raw["apoderado_id"] == "42"

    def test_default_model_property_is_saldo_cuenta(self):
        provider = make_provider()
        session = provider.create_checkout(
            amount=Decimal("500"),
            currency="CLP",
            success_url="https://example.com/ok",
            cancel_url="https://example.com/cancel",
        )
        assert session.raw["model_property"] == "saldo_cuenta"

    def test_transaction_code_in_raw(self):
        provider = make_provider()
        session = provider.create_checkout(
            amount=Decimal("500"),
            currency="CLP",
            success_url="https://example.com/ok",
            cancel_url="https://example.com/cancel",
        )
        assert "transaction_code" in session.raw
        assert session.raw["transaction_code"] == session.metadata["transaction_code"]

    def test_each_call_generates_unique_session_id(self):
        provider = make_provider()
        ids = {
            provider.create_checkout(
                Decimal("100"), "CLP", "https://s", "https://c"
            ).session_id
            for _ in range(10)
        }
        assert len(ids) == 10

    def test_extra_metadata_is_passed_through(self):
        provider = make_provider()
        session = provider.create_checkout(
            amount=Decimal("1000"),
            currency="CLP",
            success_url="https://example.com/ok",
            cancel_url="https://example.com/cancel",
            metadata={"pedido_codigo": "abc-123"},
        )
        assert session.metadata["pedido_codigo"] == "abc-123"


# ---------------------------------------------------------------------------
# get_payment
# ---------------------------------------------------------------------------

class TestSaldoProviderGetPayment:
    def test_always_returns_succeeded(self):
        from merchants.models import PaymentState
        provider = make_provider()
        status = provider.get_payment("saldo_ABCDEF123456")
        assert status.state == PaymentState.SUCCEEDED

    def test_payment_id_preserved(self):
        provider = make_provider()
        status = provider.get_payment("saldo_XYZ987")
        assert status.payment_id == "saldo_XYZ987"

    def test_provider_key_is_saldo(self):
        provider = make_provider()
        status = provider.get_payment("saldo_ABCDEF")
        assert status.provider == "saldo"

    def test_is_final_and_is_success(self):
        provider = make_provider()
        status = provider.get_payment("any_id")
        assert status.is_final is True
        assert status.is_success is True


# ---------------------------------------------------------------------------
# parse_webhook
# ---------------------------------------------------------------------------

class TestSaldoProviderParseWebhook:
    def test_always_returns_succeeded_state(self):
        from merchants.models import PaymentState
        provider = make_provider()
        event = provider.parse_webhook(b'{}', {})
        assert event.state == PaymentState.SUCCEEDED

    def test_event_type_is_payment_saldo(self):
        provider = make_provider()
        event = provider.parse_webhook(b'{}', {})
        assert event.event_type == "payment.saldo"

    def test_provider_key_is_saldo(self):
        provider = make_provider()
        event = provider.parse_webhook(b'{}', {})
        assert event.provider == "saldo"

    def test_fields_extracted_from_payload(self):
        import json
        provider = make_provider()
        payload = json.dumps({
            "event_id": "evt_001",
            "payment_id": "saldo_ABC",
        }).encode()
        event = provider.parse_webhook(payload, {})
        assert event.event_id == "evt_001"
        assert event.payment_id == "saldo_ABC"

    def test_invalid_json_does_not_raise(self):
        provider = make_provider()
        event = provider.parse_webhook(b'not-json', {})
        assert event is not None


# ---------------------------------------------------------------------------
# get_info
# ---------------------------------------------------------------------------

class TestSaldoProviderGetInfo:
    def test_key_is_saldo(self):
        info = make_provider().get_info()
        assert info.key == "saldo"

    def test_name_is_set(self):
        info = make_provider().get_info()
        assert info.name == "Saldo de Cuenta"
