"""Shared column configuration for Flask-Admin payment views.

This module is intentionally standalone: it does not import from
``flask_merchants`` or from the host application so it can be safely
re-used or vendored into any Flask-Admin integration that manages
payment records.
"""

from __future__ import annotations

from markupsafe import Markup

#: Ordered list of (value, label) pairs for the payment lifecycle state field.
_STATE_CHOICES = [
    ("pending", "Pending"),
    ("processing", "Processing"),
    ("succeeded", "Succeeded"),
    ("failed", "Failed"),
    ("cancelled", "Cancelled"),
    ("refunded", "Refunded"),
    ("unknown", "Unknown"),
]

#: Bootstrap badge class per state value (unmapped states fall back to ``"secondary"``).
_STATE_BADGE_CLASSES = {
    "succeeded": "success",
    "failed": "danger",
    "cancelled": "dark",
    "refunded": "warning",
    "processing": "info",
}


def _fmt_state(v, c, m, n):
    """Render a payment state as a Bootstrap badge."""
    val = v._get_field_value(m, n)
    val = val if val is not None else ""
    return Markup(
        '<span class="badge badge-{cls}">{val}</span>'.format(
            cls=_STATE_BADGE_CLASSES.get(val, "secondary"),
            val=val,
        )
    )


def _fmt_merchants_id(v, c, m, n):
    """Render a merchants ID in a ``<small>`` tag."""
    val = v._get_field_value(m, n)
    return Markup("<small>{}</small>".format(val if val is not None else ""))


class PaymentViewMixin:
    """Shared display configuration for Flask-Admin payment views.

    Mix into any :class:`~flask_admin.model.BaseModelView` subclass
    (including :class:`~flask_admin.contrib.sqla.ModelView`) to apply a
    consistent set of column labels, descriptions, and formatters for
    payment records without duplicating configuration across backends::

        from flask_admin.model import BaseModelView
        from flask_merchants.contrib.base import PaymentViewMixin

        class MyPaymentView(PaymentViewMixin, BaseModelView):
            ...

    Subclasses are free to override any attribute; this mixin only provides
    the sensible defaults for the core payment columns.  SQLAlchemy-backed
    views typically extend :attr:`column_list` and :attr:`column_labels` with
    timestamp columns, for example.
    """

    #: Core columns displayed in the list view.
    column_list = ["merchants_id", "transaction_id", "provider", "amount", "currency", "state"]

    #: Human-readable column header labels.
    column_labels = {
        "merchants_id": "Merchants ID",
        "transaction_id": "Transaction ID",
        "provider": "Provider",
        "amount": "Amount",
        "currency": "Currency",
        "state": "State",
    }

    #: Tooltip help text shown next to each column header.
    column_descriptions = {
        "merchants_id": "Internal payment identifier (UUID4).",
        "transaction_id": "Identifier assigned by the payment provider.",
        "provider": "The payment gateway that processed this transaction.",
        "amount": "Payment amount in the smallest currency unit (e.g. cents).",
        "currency": "ISO-4217 currency code (e.g. USD, EUR, CLP).",
        "state": "Current processing state of the payment.",
    }

    #: Custom cell renderers: state as a Bootstrap badge, merchants_id in ``<small>``.
    column_formatters = {
        "state": _fmt_state,
        "merchants_id": _fmt_merchants_id,
    }

    #: Choices list exposed to templates / ``scaffold_form`` implementations.
    state_choices = _STATE_CHOICES

    #: WTForms field choices for the ``state`` form field.
    form_choices = {"state": _STATE_CHOICES}
