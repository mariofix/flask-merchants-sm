"""Tests for the webhook notification feature in FlaskMerchants.

Covers enable_webhook_notifications, the built-in notification handler,
and the Celery task for sending webhook emails.
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

from flask_merchants import FlaskMerchants
from merchants.models import PaymentState, WebhookEvent
from merchants.providers.dummy import DummyProvider


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def flask_app():
    """Minimal Flask app with FlaskMerchants extension for testing."""
    app = Flask(__name__)
    app.config.update(
        TESTING=True,
        SECRET_KEY="test-secret",
        MERCHANTS_URL_PREFIX="/merchants",
        MERCHANTS_WEBHOOK_BASE_URL="https://example.com",
    )
    ext = FlaskMerchants()
    ext.init_app(app, providers=[DummyProvider()])
    return app, ext


@pytest.fixture()
def webhook_event():
    """A sample webhook event."""
    return WebhookEvent(
        event_id="evt_123",
        event_type="payment.succeeded",
        payment_id="pay_456",
        state=PaymentState.SUCCEEDED,
        provider="dummy",
        raw={"status": "paid"},
    )


# ---------------------------------------------------------------------------
# enable_webhook_notifications
# ---------------------------------------------------------------------------

class TestEnableWebhookNotifications:
    def test_registers_handler(self, flask_app):
        _app, ext = flask_app
        initial_count = len(ext._webhook_handlers)
        ext.enable_webhook_notifications(
            admin_emails_fn=lambda: ["admin@test.cl"],
        )
        assert len(ext._webhook_handlers) == initial_count + 1

    def test_stores_admin_emails_fn(self, flask_app):
        _app, ext = flask_app
        fn = lambda: ["a@b.com"]
        ext.enable_webhook_notifications(admin_emails_fn=fn)
        assert ext._webhook_notify_admin_emails_fn is fn

    def test_stores_send_fn(self, flask_app):
        _app, ext = flask_app
        send = MagicMock()
        ext.enable_webhook_notifications(
            admin_emails_fn=lambda: ["a@b.com"],
            send_fn=send,
        )
        assert ext._webhook_notify_send_fn is send


# ---------------------------------------------------------------------------
# Webhook notification handler
# ---------------------------------------------------------------------------

class TestWebhookNotificationHandler:
    def test_calls_send_fn_with_webhook_info(self, flask_app, webhook_event):
        app, ext = flask_app
        send_fn = MagicMock()
        ext.enable_webhook_notifications(
            admin_emails_fn=lambda: ["admin@test.cl"],
            send_fn=send_fn,
        )
        with app.test_request_context(
            "/merchants/webhook/dummy",
            method="POST",
            data=json.dumps({"status": "paid"}),
            content_type="application/json",
        ):
            ext._webhook_notification_handler(webhook_event)

        send_fn.assert_called_once()
        info = send_fn.call_args[0][0]
        assert info["provider"] == "dummy"
        assert info["transaction"] == "pay_456"
        assert "admin@test.cl" in info["to"]
        assert "Content-Type" in info["headers_json"]
        assert "paid" in info["body_json"]

    def test_email_subject_contains_provider_and_transaction(self, flask_app, webhook_event):
        app, ext = flask_app
        send_fn = MagicMock()
        ext.enable_webhook_notifications(
            admin_emails_fn=lambda: ["admin@test.cl"],
            send_fn=send_fn,
        )
        with app.test_request_context(
            "/merchants/webhook/dummy",
            method="POST",
            data=json.dumps({"status": "paid"}),
            content_type="application/json",
        ):
            ext._webhook_notification_handler(webhook_event)

        info = send_fn.call_args[0][0]
        assert "dummy" in info["subject"]
        assert "pay_456" in info["subject"]

    def test_skips_when_no_admin_emails(self, flask_app, webhook_event):
        app, ext = flask_app
        send_fn = MagicMock()
        ext.enable_webhook_notifications(
            admin_emails_fn=lambda: [],
            send_fn=send_fn,
        )
        with app.test_request_context(
            "/merchants/webhook/dummy",
            method="POST",
            data="{}",
            content_type="application/json",
        ):
            ext._webhook_notification_handler(webhook_event)

        send_fn.assert_not_called()

    def test_handles_non_json_body(self, flask_app, webhook_event):
        app, ext = flask_app
        send_fn = MagicMock()
        ext.enable_webhook_notifications(
            admin_emails_fn=lambda: ["admin@test.cl"],
            send_fn=send_fn,
        )
        with app.test_request_context(
            "/merchants/webhook/dummy",
            method="POST",
            data="payment_id=pay_456&status=done",
            content_type="application/x-www-form-urlencoded",
        ):
            ext._webhook_notification_handler(webhook_event)

        info = send_fn.call_args[0][0]
        assert "payment_id=pay_456" in info["body_json"]

    def test_body_text_format(self, flask_app, webhook_event):
        app, ext = flask_app
        send_fn = MagicMock()
        ext.enable_webhook_notifications(
            admin_emails_fn=lambda: ["admin@test.cl"],
            send_fn=send_fn,
        )
        with app.test_request_context(
            "/merchants/webhook/dummy",
            method="POST",
            data=json.dumps({"status": "paid"}),
            content_type="application/json",
        ):
            ext._webhook_notification_handler(webhook_event)

        info = send_fn.call_args[0][0]
        body = info["body"]
        assert body.startswith("provider: dummy\n")
        assert "transaction: pay_456\n" in body
        assert "headers:\n" in body
        assert "body:\n" in body

    def test_event_without_payment_id(self, flask_app):
        app, ext = flask_app
        send_fn = MagicMock()
        ext.enable_webhook_notifications(
            admin_emails_fn=lambda: ["admin@test.cl"],
            send_fn=send_fn,
        )
        event = WebhookEvent(
            event_id="evt_789",
            event_type="payment.unknown",
            payment_id=None,
            state=PaymentState.UNKNOWN,
            provider="dummy",
        )
        with app.test_request_context(
            "/merchants/webhook/dummy",
            method="POST",
            data="{}",
            content_type="application/json",
        ):
            ext._webhook_notification_handler(event)

        info = send_fn.call_args[0][0]
        assert info["transaction"] == ""
        assert "no-id" in info["subject"]

    def test_uses_default_send_when_no_send_fn(self, flask_app, webhook_event):
        app, ext = flask_app
        ext.enable_webhook_notifications(
            admin_emails_fn=lambda: ["admin@test.cl"],
        )
        with app.test_request_context(
            "/merchants/webhook/dummy",
            method="POST",
            data=json.dumps({"status": "paid"}),
            content_type="application/json",
        ):
            with patch.object(
                FlaskMerchants,
                "_send_webhook_notification_default",
            ) as mock_default:
                ext._webhook_notification_handler(webhook_event)
                mock_default.assert_called_once()


# ---------------------------------------------------------------------------
# Integration: dispatch triggers notification
# ---------------------------------------------------------------------------

class TestDispatchTriggersNotification:
    def test_dispatch_invokes_notification_handler(self, flask_app, webhook_event):
        app, ext = flask_app
        send_fn = MagicMock()
        ext.enable_webhook_notifications(
            admin_emails_fn=lambda: ["admin@test.cl"],
            send_fn=send_fn,
        )
        with app.test_request_context(
            "/merchants/webhook/dummy",
            method="POST",
            data=json.dumps({"status": "paid"}),
            content_type="application/json",
        ):
            ext._dispatch_webhook_event(webhook_event)

        send_fn.assert_called_once()

    def test_notification_does_not_block_other_handlers(self, flask_app, webhook_event):
        app, ext = flask_app
        other_handler = MagicMock()
        ext.add_webhook_handler(other_handler)

        def failing_admin_emails_fn():
            raise RuntimeError("fail")

        ext.enable_webhook_notifications(
            admin_emails_fn=failing_admin_emails_fn,
            send_fn=MagicMock(),
        )
        with app.test_request_context(
            "/merchants/webhook/dummy",
            method="POST",
            data="{}",
            content_type="application/json",
        ):
            ext._dispatch_webhook_event(webhook_event)

        other_handler.assert_called_once_with(webhook_event)
