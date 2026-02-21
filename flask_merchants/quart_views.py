"""Async blueprint for Quart applications.

This module mirrors :mod:`flask_merchants.views` but uses ``async def``
view functions and awaits Quart's coroutine-based request helpers
(``await request.get_json()``, ``await request.get_data()``,
``await request.form``).

It is selected automatically by :meth:`~flask_merchants.FlaskMerchants.init_app`
when the application is a :class:`quart.Quart` instance.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import merchants

if TYPE_CHECKING:
    from flask_merchants import FlaskMerchants


def create_async_blueprint(ext: "FlaskMerchants"):
    """Return a Quart Blueprint pre-configured with the extension instance."""
    try:
        from quart import Blueprint, jsonify, redirect, request, url_for
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "quart is required for flask_merchants.quart_views. "
            "Install it with: pip install 'flask-merchants[quart]'"
        ) from exc

    bp = Blueprint("merchants", __name__, template_folder="templates")

    # ------------------------------------------------------------------
    # Checkout – initiate a payment
    # ------------------------------------------------------------------

    @bp.route("/checkout", methods=["GET", "POST"])
    async def checkout():
        """Create a hosted-checkout session and redirect the user."""
        json_data = await request.get_json(silent=True)
        if json_data is not None:
            data = json_data
        else:
            data = await request.form

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
        except merchants.UserError as exc_:
            return jsonify({"error": str(exc_)}), 400

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

        if json_data is not None:
            return jsonify(
                {
                    "session_id": session.session_id,
                    "redirect_url": session.redirect_url,
                }
            )
        return redirect(session.redirect_url)

    # ------------------------------------------------------------------
    # Providers – list available payment providers
    # ------------------------------------------------------------------

    @bp.route("/providers", methods=["GET"])
    async def providers():
        """Return the list of registered payment provider keys."""
        return jsonify({"providers": ext.list_providers()})

    # ------------------------------------------------------------------
    # Success / cancel landing pages
    # ------------------------------------------------------------------

    @bp.route("/success")
    async def success():
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
    async def cancel():
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
    async def payment_status(payment_id: str):
        """Return the live payment status from the provider."""
        try:
            status = ext.client.payments.get(payment_id)
        except merchants.UserError as exc_:
            return jsonify({"error": str(exc_)}), 400

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
    async def webhook():
        """Receive and process incoming provider webhook events."""
        from quart import current_app

        secret: str | None = current_app.config.get("MERCHANTS_WEBHOOK_SECRET")
        payload: bytes = await request.get_data()
        headers: dict[str, str] = dict(request.headers)

        if secret:
            signature = headers.get("X-Merchants-Signature", "")
            try:
                merchants.verify_signature(
                    payload=payload,
                    secret=secret,
                    signature=signature,
                )
            except merchants.WebhookVerificationError:
                return jsonify({"error": "invalid signature"}), 400

        try:
            event = ext.client._provider.parse_webhook(payload, headers)
        except Exception:  # noqa: BLE001
            return jsonify({"error": "malformed payload"}), 400

        ext.update_state(event.payment_id, event.state.value)

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
