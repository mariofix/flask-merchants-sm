"""Blinker signals emitted by the merchants SDK.

Subscribers can connect to these signals to react to payment lifecycle
events without coupling to framework-specific hooks.

Example::

    from merchants.signals import checkout_created

    @checkout_created.connect
    def on_checkout(sender, session, **kwargs):
        print(f"Checkout created: {session.session_id}")
"""
from __future__ import annotations

from blinker import Namespace

_signals = Namespace()

#: Sent after a checkout session is successfully created.
#: Sender is the :class:`~merchants.client.PaymentsResource` instance.
#: Extra keyword argument ``session``: the :class:`~merchants.models.CheckoutSession`.
checkout_created = _signals.signal("checkout-created")

#: Sent after a payment status is retrieved from a provider.
#: Sender is the :class:`~merchants.client.PaymentsResource` instance.
#: Extra keyword argument ``status``: the :class:`~merchants.models.PaymentStatus`.
payment_retrieved = _signals.signal("payment-retrieved")

#: Sent after a webhook payload is parsed into a :class:`~merchants.models.WebhookEvent`.
#: Sender is the :func:`~merchants.webhooks.parse_event` function.
#: Extra keyword argument ``event``: the :class:`~merchants.models.WebhookEvent`.
webhook_event_parsed = _signals.signal("webhook-event-parsed")

#: Sent after a provider is registered in the global registry.
#: Sender is the :func:`~merchants.providers.register_provider` function.
#: Extra keyword argument ``provider``: the :class:`~merchants.providers.Provider` instance.
provider_registered = _signals.signal("provider-registered")
