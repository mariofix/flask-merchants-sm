"""Blueprint with checkout, webhook, success and cancel routes."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

import merchants
from flask import Blueprint, jsonify, redirect, request, url_for

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from flask_merchants import FlaskMerchants


def create_blueprint(ext: "FlaskMerchants") -> Blueprint:
    """Return a Blueprint pre-configured with the extension instance."""

    bp = Blueprint("merchants", __name__, template_folder="templates")

    # ------------------------------------------------------------------
    # Checkout - initiate a payment
    # ------------------------------------------------------------------

    @bp.route("/checkout", methods=["GET", "POST"])
    def checkout():
        """Create a hosted-checkout session and redirect the user.

        Accepts JSON body **or** form fields:

        * ``amount`` - decimal string (e.g. ``"19.99"``)
        * ``currency`` - ISO-4217 code (e.g. ``"USD"``)
        * ``metadata`` - optional JSON object / form JSON string
        * ``provider`` - optional provider key string (e.g. ``"dummy"``).
          Defaults to the first registered provider.
        """
        data = request.get_json(silent=True) or request.form

        amount = data.get("amount", "1.00")
        currency = data.get("currency", "USD")
        raw_meta = data.get("metadata")
        if isinstance(raw_meta, str):
            try:
                metadata = json.loads(raw_meta)
            except (ValueError, TypeError):
                metadata = {}
        elif isinstance(raw_meta, dict):
            metadata = raw_meta
        else:
            metadata = {}

        provider_key = data.get("provider") or None

        try:
            client = ext.get_client(provider_key)
        except KeyError:
            return jsonify({"error": f"Unknown provider: {provider_key!r}"}), 400

        success_url = url_for("merchants.success", _external=True)
        cancel_url = url_for("merchants.cancel", _external=True)

        try:
            session = client.payments.create_checkout(
                amount=amount,
                currency=currency,
                success_url=success_url,
                cancel_url=cancel_url,
                metadata=metadata,
            )
        except merchants.UserError as exc:
            return jsonify({"error": str(exc)}), 400

        req_payload = {
            "amount": amount,
            "currency": currency,
            "success_url": success_url,
            "cancel_url": cancel_url,
            "metadata": metadata,
        }
        if provider_key:
            req_payload["provider"] = provider_key
        ext.save_session(session, request_payload=req_payload)

        if request.is_json:
            return jsonify(
                {
                    "transaction_id": session.session_id,
                    "redirect_url": session.redirect_url,
                }
            )
        return redirect(session.redirect_url)

    # ------------------------------------------------------------------
    # Providers - list available payment providers
    # ------------------------------------------------------------------

    @bp.route("/providers", methods=["GET"])
    def providers():
        """Return the list of registered payment provider keys."""
        return jsonify({"providers": ext.list_providers()})

    # ------------------------------------------------------------------
    # Success / cancel landing pages
    # ------------------------------------------------------------------

    @bp.route("/success")
    def success():
        """Landing page after a successful payment."""
        payment_id = request.args.get("payment_id", "")
        stored = ext.get_session(payment_id) if payment_id else None
        return jsonify(
            {
                "status": "success",
                "payment_id": payment_id or None,
                "stored": stored,
            }
        )

    @bp.route("/cancel")
    def cancel():
        """Landing page after a cancelled payment."""
        payment_id = request.args.get("payment_id", "")
        stored = ext.get_session(payment_id) if payment_id else None
        return jsonify(
            {
                "status": "cancelled",
                "payment_id": payment_id or None,
                "stored": stored,
            }
        )

    # ------------------------------------------------------------------
    # Payment status
    # ------------------------------------------------------------------

    @bp.route("/status/<payment_id>")
    def payment_status(payment_id: str):
        """Return the live payment status from the provider."""
        try:
            status = ext.client.payments.get(payment_id)
        except merchants.UserError as exc:
            return jsonify({"error": str(exc)}), 400

        ext.update_state(payment_id, status.state.value)

        return jsonify(
            {
                "payment_id": status.payment_id,
                "state": status.state.value,
                "provider": status.provider,
                "is_final": status.is_final,
                "is_success": status.is_success,
            }
        )

    # ------------------------------------------------------------------
    # Webhook
    # ------------------------------------------------------------------

    @bp.route("/webhook", methods=["POST"])
    def webhook():
        """Receive and process incoming provider webhook events."""
        logger.debug("views.py: webhook called")
        payload: bytes = request.get_data()
        headers: dict[str, str] = dict(request.headers)

        try:
            event = ext.client._provider.parse_webhook(payload, headers)
        except Exception:  # noqa: BLE001
            return jsonify({"error": "malformed payload"}), 400

        ext.update_state(event.payment_id, event.state.value)
        ext._dispatch_webhook_event(event)

        return jsonify(
            {
                "received": True,
                "event_id": event.event_id,
                "event_type": event.event_type,
                "payment_id": event.payment_id,
                "state": event.state.value,
            }
        )

    # CSRF exemption for both webhook views is handled by FlaskMerchants.init_app
    # which calls csrf_ext.exempt() on these view functions after blueprint
    # registration. Setting an attribute here would have no effect on Flask-WTF.

    @bp.route("/webhook/<provider>", methods=["POST"])
    def webhook_provider(provider: str):
        """Receive and process webhook events for a specific *provider*.

        The URL ``/merchants/webhook/<provider>`` (e.g.
        ``/merchants/webhook/khipu``) is the standard webhook endpoint for all
        registered payment providers.  Pass this URL as ``notify_url`` when
        creating a checkout session so that the provider knows where to send
        payment notifications.

        The URL can be computed at runtime with::

            flask_merchants.get_webhook_url("khipu")

        This requires ``MERCHANTS_WEBHOOK_BASE_URL`` to be set in the app config.
        """
        logger.debug("views.py: webhook_provider called with provider=%r", provider)
        try:
            client = ext.get_client(provider)
        except KeyError:
            return jsonify({"error": f"Unknown provider: {provider!r}"}), 404

        payload: bytes = request.get_data()
        headers: dict[str, str] = dict(request.headers)

        logger.info(
            "webhook_received: provider=%r remote_addr=%r content_type=%r headers=%r body=%r",
            provider,
            request.remote_addr,
            request.content_type,
            headers,
            payload,
        )

        try:
            event = client._provider.parse_webhook(payload, headers)
        except Exception:  # noqa: BLE001
            return jsonify({"error": "malformed payload"}), 400

        if event.payment_id:
            ext.update_state(event.payment_id, event.state.value)

        ext._dispatch_webhook_event(event)

        return jsonify(
            {
                "received": True,
                "event_id": event.event_id,
                "event_type": event.event_type,
                "payment_id": event.payment_id,
                "state": event.state.value,
            }
        )

    return bp
