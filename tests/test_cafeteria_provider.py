"""Tests for CafeteriaProvider.

Covers create_checkout, get_payment, and parse_webhook without requiring
a running server or real payment gateway.
"""

from decimal import Decimal

import pytest

from app.providers.cafeteria import CafeteriaProvider


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_provider() -> CafeteriaProvider:
    return CafeteriaProvider()


# ---------------------------------------------------------------------------
# create_checkout
# ---------------------------------------------------------------------------

class TestCafeteriaProviderCreateCheckout:
    def test_session_id_starts_with_cafe(self):
        provider = make_provider()
        session = provider.create_checkout(
            amount=Decimal("5000"),
            currency="CLP",
            success_url="https://example.com/success",
            cancel_url="https://example.com/cancel",
        )
        assert session.session_id.startswith("cafe_")

    def test_redirect_url_is_success_url(self):
        provider = make_provider()
        session = provider.create_checkout(
            amount=Decimal("3000"),
            currency="CLP",
            success_url="https://example.com/ok",
            cancel_url="https://example.com/nope",
        )
        assert session.redirect_url == "https://example.com/ok"

    def test_provider_key_is_cafeteria(self):
        provider = make_provider()
        session = provider.create_checkout(
            amount=Decimal("1000"),
            currency="CLP",
            success_url="https://example.com/ok",
            cancel_url="https://example.com/nope",
        )
        assert session.provider == "cafeteria"

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

    def test_initial_state_is_processing(self):
        from merchants.models import PaymentState
        provider = make_provider()
        session = provider.create_checkout(
            amount=Decimal("2000"),
            currency="CLP",
            success_url="https://example.com/ok",
            cancel_url="https://example.com/cancel",
        )
        assert session.initial_state == PaymentState.PROCESSING

    def test_display_code_in_metadata(self):
        provider = make_provider()
        session = provider.create_checkout(
            amount=Decimal("1000"),
            currency="CLP",
            success_url="https://example.com/ok",
            cancel_url="https://example.com/cancel",
        )
        assert "display_code" in session.metadata
        assert len(session.metadata["display_code"]) == 6

    def test_custom_codigo_used_as_session_id(self):
        provider = make_provider()
        session = provider.create_checkout(
            amount=Decimal("1000"),
            currency="CLP",
            success_url="https://example.com/ok",
            cancel_url="https://example.com/cancel",
            codigo="cafe_MYCODE12",
        )
        assert session.session_id == "cafe_MYCODE12"

    def test_each_call_generates_unique_session_id(self):
        provider = make_provider()
        ids = {
            provider.create_checkout(
                Decimal("100"), "CLP", "https://s", "https://c"
            ).session_id
            for _ in range(10)
        }
        assert len(ids) == 10

    def test_notify_url_is_accepted_and_ignored(self):
        """notify_url is Khipu-specific; CafeteriaProvider must silently ignore it."""
        provider = make_provider()
        session = provider.create_checkout(
            amount=Decimal("5000"),
            currency="CLP",
            success_url="https://example.com/ok",
            cancel_url="https://example.com/cancel",
            notify_url="https://example.com/webhook/cafeteria",
        )
        assert session.session_id.startswith("cafe_")

    def test_notify_url_with_codigo_accepted(self):
        """Both notify_url and codigo can be passed together without error."""
        provider = make_provider()
        session = provider.create_checkout(
            amount=Decimal("3000"),
            currency="CLP",
            success_url="https://example.com/ok",
            cancel_url="https://example.com/cancel",
            codigo="cafe_TESTCODE",
            notify_url="https://example.com/webhook/cafeteria",
        )
        assert session.session_id == "cafe_TESTCODE"


# ---------------------------------------------------------------------------
# get_payment
# ---------------------------------------------------------------------------

class TestCafeteriaProviderGetPayment:
    def test_always_returns_processing(self):
        from merchants.models import PaymentState
        provider = make_provider()
        status = provider.get_payment("cafe_ABCDEF12")
        assert status.state == PaymentState.PROCESSING

    def test_payment_id_preserved(self):
        provider = make_provider()
        status = provider.get_payment("cafe_XYZ987AB")
        assert status.payment_id == "cafe_XYZ987AB"

    def test_provider_key_is_cafeteria(self):
        provider = make_provider()
        status = provider.get_payment("cafe_ABCDEF12")
        assert status.provider == "cafeteria"


# ---------------------------------------------------------------------------
# parse_webhook
# ---------------------------------------------------------------------------

class TestCafeteriaProviderParseWebhook:
    def test_always_returns_processing_state(self):
        from merchants.models import PaymentState
        provider = make_provider()
        event = provider.parse_webhook(b'{}', {})
        assert event.state == PaymentState.PROCESSING

    def test_event_type_is_payment_cafeteria(self):
        provider = make_provider()
        event = provider.parse_webhook(b'{}', {})
        assert event.event_type == "payment.cafeteria"

    def test_provider_key_is_cafeteria(self):
        provider = make_provider()
        event = provider.parse_webhook(b'{}', {})
        assert event.provider == "cafeteria"

    def test_fields_extracted_from_payload(self):
        import json
        provider = make_provider()
        payload = json.dumps({
            "event_id": "evt_001",
            "payment_id": "cafe_ABC12345",
        }).encode()
        event = provider.parse_webhook(payload, {})
        assert event.event_id == "evt_001"
        assert event.payment_id == "cafe_ABC12345"

    def test_invalid_json_does_not_raise(self):
        provider = make_provider()
        event = provider.parse_webhook(b'not-json', {})
        assert event is not None


# ---------------------------------------------------------------------------
# get_info
# ---------------------------------------------------------------------------

class TestCafeteriaProviderGetInfo:
    def test_key_is_cafeteria(self):
        info = make_provider().get_info()
        assert info.key == "cafeteria"

    def test_name_is_set(self):
        info = make_provider().get_info()
        assert info.name == "Cafetería"
