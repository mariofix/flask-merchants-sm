"""Flask-Admin views for managing payments stored by flask-merchants.

Install the optional dependency before using this module::

    pip install "flask-merchants[admin]"

Example – manual registration::

    from flask import Flask
    from flask_admin import Admin
    from flask_merchants import FlaskMerchants
    from flask_merchants.contrib.admin import PaymentView, ProvidersView

    app = Flask(__name__)
    ext = FlaskMerchants(app)

    admin = Admin(app, name="My Shop")
    admin.add_view(PaymentView(ext, name="Payments", endpoint="payments"))
    admin.add_view(ProvidersView(ext, name="Providers", endpoint="providers"))

Example – automatic registration (pass ``admin=`` to FlaskMerchants)::

    from flask import Flask
    from flask_admin import Admin
    from flask_merchants import FlaskMerchants

    app = Flask(__name__)
    admin = Admin(app, name="My Shop")
    ext = FlaskMerchants(app, admin=admin)
    # PaymentView and ProvidersView are automatically added under category="Merchants"
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

try:
    from flask_admin.actions import action
    from flask_admin.model import BaseModelView
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "flask-admin is required for flask_merchants.contrib.admin. "
        "Install it with: pip install 'flask-merchants[admin]'"
    ) from exc

if TYPE_CHECKING:
    from flask_merchants import FlaskMerchants


def _mask_secret(value: str) -> str:
    """Return *value* with all but the first 5 and last 1 characters masked.

    Short values (6 characters or fewer) are replaced entirely with ``"***"``
    to avoid leaking meaningful content through the masking pattern.

    Examples::

        _mask_secret("sk_test_1234567890")  # -> "sk_te…0"
        _mask_secret("short")               # -> "***"
    """
    if len(value) <= 6:
        return "***"
    return value[:5] + "…" + value[-1]


def _get_auth_info(auth) -> dict[str, str]:
    """Extract and mask auth details from an :class:`~merchants.auth.AuthStrategy`.

    Returns a dict with ``type``, ``header``, and ``masked_value`` keys.
    When *auth* is ``None`` an empty/unauthenticated descriptor is returned.
    """
    if auth is None:
        return {"type": "None", "header": "—", "masked_value": "—"}

    auth_type = type(auth).__name__
    # ApiKeyAuth stores the key in _api_key; TokenAuth in _token
    raw = getattr(auth, "_api_key", None) or getattr(auth, "_token", None) or ""
    header = getattr(auth, "_header", "—")
    return {
        "type": auth_type,
        "header": str(header),
        "masked_value": _mask_secret(raw) if raw else "—",
    }


_STATE_CHOICES = [
    ("pending", "Pending"),
    ("processing", "Processing"),
    ("succeeded", "Succeeded"),
    ("failed", "Failed"),
    ("cancelled", "Cancelled"),
    ("refunded", "Refunded"),
    ("unknown", "Unknown"),
]


class _PaymentRecord:
    """Placeholder model class used as the ``model`` argument for :class:`PaymentView`."""


class PaymentView(BaseModelView):
    """Flask-Admin view that lists all stored payments and allows managing them.

    Extends :class:`~flask_admin.model.BaseModelView` so the list page gains
    built-in search, column sorting, pagination, and actions consistent with
    other model-backed views in the admin.

    Provides:
    - List of all stored payment sessions with search and sorting.
    - Edit state via modal popup (one payment at a time).
    - Bulk Refund, Cancel, and Sync actions via the "With selected" action dropdown.

    Args:
        ext: Initialised :class:`~flask_merchants.FlaskMerchants` extension instance.
        name: Display name shown in the admin navigation bar.
        endpoint: Internal Flask endpoint prefix (must be unique).
        category: Optional admin category/group name.
    """

    # Disable create/delete; enable modal edit for state changes.
    can_create = False
    can_delete = False
    can_edit = True
    edit_modal = True

    # Column configuration
    column_list = ["session_id", "provider", "amount", "currency", "state"]
    column_searchable_list = ["session_id", "provider", "state"]
    column_sortable_list = ["provider", "amount", "currency", "state"]
    column_labels = {
        "session_id": "Payment ID",
        "provider": "Provider",
        "amount": "Amount",
        "currency": "Currency",
        "state": "State",
    }

    # Custom list template – extends admin/model/list.html for consistent UI.
    list_template = "flask_merchants/admin/payments_list.html"

    # State choices exposed to templates via ``admin_view.state_choices``.
    state_choices = _STATE_CHOICES

    def __init__(
        self,
        ext: "FlaskMerchants",
        name: str = "Payments",
        endpoint: str = "payments",
        category: str | None = None,
        **kwargs: Any,
    ) -> None:
        self._ext = ext
        super().__init__(
            model=_PaymentRecord,
            name=name,
            endpoint=endpoint,
            category=category,
            **kwargs,
        )

    # ------------------------------------------------------------------
    # Required BaseModelView abstract methods
    # ------------------------------------------------------------------

    def scaffold_list_columns(self) -> list[str]:
        return ["session_id", "provider", "amount", "currency", "state"]

    def scaffold_sortable_columns(self) -> dict[str, str]:
        return {
            "provider": "provider",
            "amount": "amount",
            "currency": "currency",
            "state": "state",
        }

    def scaffold_form(self):
        from wtforms import Form as WTForm, SelectField

        choices = _STATE_CHOICES

        class StateForm(WTForm):
            state = SelectField("State", choices=choices)

        return StateForm

    def scaffold_list_form(self, widget=None, validators=None):
        from wtforms import Form as WTForm

        return WTForm

    def init_search(self) -> bool:
        return bool(self.column_searchable_list)

    def get_pk_value(self, model) -> str | None:
        if isinstance(model, dict):
            return model.get("session_id")
        return getattr(model, "session_id", None)

    def get_list(self, page, sort_field, sort_desc, search, filters, page_size=None):
        payments = self._ext.all_sessions()

        if search:
            search_lower = search.lower()
            payments = [
                p
                for p in payments
                if search_lower in str(p.get("session_id", "")).lower()
                or search_lower in str(p.get("provider", "")).lower()
                or search_lower in str(p.get("state", "")).lower()
            ]

        if sort_field:
            payments = sorted(
                payments,
                key=lambda p: str(p.get(sort_field, "")),
                reverse=bool(sort_desc),
            )

        count = len(payments)

        if page_size is None:
            page_size = self.page_size
        if page is not None and page_size:
            payments = payments[page * page_size : (page + 1) * page_size]

        return count, payments

    def get_one(self, id: str):
        return self._ext.get_session(id)

    def create_model(self, form):
        return False

    def update_model(self, form, model) -> bool:
        """Update payment state from the modal edit form."""
        from flask import flash

        payment_id = self.get_pk_value(model)
        new_state = form.state.data
        if self._ext.update_state(payment_id, new_state):
            flash(f"Payment {payment_id} updated to '{new_state}'.", "success")
            return True
        flash(f"Payment {payment_id} not found.", "danger")
        return False

    def delete_model(self, model):
        return False

    def get_empty_list_message(self) -> str:
        return "No payments recorded yet."

    # ------------------------------------------------------------------
    # Bulk actions – shown in the "With selected" dropdown
    # ------------------------------------------------------------------

    @action(
        "refund",
        "Refund",
        "Are you sure you want to mark the selected payments as refunded?",
    )
    def action_refund(self, ids: list[str]) -> None:
        """Mark selected payments as refunded."""
        from flask import flash

        count = sum(1 for pid in ids if self._ext.refund_session(pid))
        flash(f"{count} payment(s) marked as refunded.", "success")

    @action(
        "cancel",
        "Cancel",
        "Are you sure you want to cancel the selected payments?",
    )
    def action_cancel(self, ids: list[str]) -> None:
        """Cancel selected payments."""
        from flask import flash

        count = sum(1 for pid in ids if self._ext.cancel_session(pid))
        flash(f"{count} payment(s) cancelled.", "success")

    @action(
        "sync",
        "Sync from Provider",
        "Fetch live status from the provider for the selected payments?",
    )
    def action_sync(self, ids: list[str]) -> None:
        """Sync selected payments from their provider."""
        from flask import flash

        count = 0
        for pid in ids:
            if self._ext.sync_from_provider(pid) is not None:
                count += 1
        flash(f"{count} payment(s) synced from provider.", "success")


class _ProviderRecord:
    """Placeholder model class used as the ``model`` argument for :class:`ProvidersView`."""


class ProvidersView(BaseModelView):
    """Flask-Admin view that lists all payment providers registered with the application.

    Extends :class:`~flask_admin.model.BaseModelView` so the list page gains
    built-in search, column sorting, and pagination consistent with other
    model-backed views in the admin.

    Args:
        ext: Initialised :class:`~flask_merchants.FlaskMerchants` extension instance.
        name: Display name shown in the admin navigation bar.
        endpoint: Internal Flask endpoint prefix (must be unique).
        category: Optional admin category/group name.
    """

    # Providers are read-only in the admin.
    can_create = False
    can_edit = False
    can_delete = False

    # Column configuration
    column_list = [
        "key",
        "base_url",
        "auth_type",
        "auth_header",
        "auth_masked_value",
        "transport",
        "payment_count",
    ]
    column_searchable_list = ["key", "base_url", "auth_type"]
    column_sortable_list = ["key", "payment_count"]
    column_labels = {
        "key": "Provider Key",
        "base_url": "Base URL",
        "auth_type": "Auth Type",
        "auth_header": "Auth Header",
        "auth_masked_value": "Auth Value",
        "transport": "Transport",
        "payment_count": "Payments",
    }

    # Custom list template – extends admin/model/list.html for consistent UI.
    list_template = "flask_merchants/admin/providers_list.html"

    def __init__(
        self,
        ext: "FlaskMerchants",
        name: str = "Providers",
        endpoint: str = "providers",
        category: str | None = None,
        **kwargs: Any,
    ) -> None:
        self._ext = ext
        super().__init__(
            model=_ProviderRecord,
            name=name,
            endpoint=endpoint,
            category=category,
            **kwargs,
        )

    # ------------------------------------------------------------------
    # Required BaseModelView abstract methods
    # ------------------------------------------------------------------

    def scaffold_list_columns(self) -> list[str]:
        return [
            "key",
            "base_url",
            "auth_type",
            "auth_header",
            "auth_masked_value",
            "transport",
            "payment_count",
        ]

    def scaffold_sortable_columns(self) -> dict[str, str]:
        return {"key": "key", "payment_count": "payment_count"}

    def scaffold_form(self):
        from wtforms import Form as WTForm

        return WTForm

    def scaffold_list_form(self, widget=None, validators=None):
        from wtforms import Form as WTForm

        return WTForm

    def init_search(self) -> bool:
        return bool(self.column_searchable_list)

    def get_pk_value(self, model) -> str | None:
        if isinstance(model, dict):
            return model.get("key")
        return getattr(model, "key", None)

    def _build_providers_list(self) -> list[dict]:
        """Build the enriched list of provider dicts from the merchants SDK."""
        import merchants as merchants_sdk

        provider_keys = merchants_sdk.list_providers()

        all_payments = self._ext.all_sessions()
        payment_counts: dict[str, int] = {}
        for p in all_payments:
            pkey = p.get("provider", "")
            payment_counts[pkey] = payment_counts.get(pkey, 0) + 1

        providers = []
        for key in provider_keys:
            try:
                client = self._ext.get_client(key)
                base_url = (
                    getattr(client._provider, "_base_url", "")
                    or getattr(client, "_base_url", "N/A")
                    or "N/A"
                )
                auth_info = _get_auth_info(client._auth)
                transport = type(client._transport).__name__
            except Exception:  # noqa: BLE001
                base_url = "N/A"
                auth_info = _get_auth_info(None)
                transport = "N/A"

            providers.append(
                {
                    "key": key,
                    "base_url": base_url,
                    "auth_type": auth_info["type"],
                    "auth_header": auth_info["header"],
                    "auth_masked_value": auth_info["masked_value"],
                    "transport": transport,
                    "payment_count": payment_counts.get(key, 0),
                }
            )

        return providers

    def get_list(self, page, sort_field, sort_desc, search, filters, page_size=None):
        providers = self._build_providers_list()

        if search:
            search_lower = search.lower()
            providers = [
                p
                for p in providers
                if search_lower in str(p.get("key", "")).lower()
                or search_lower in str(p.get("base_url", "")).lower()
                or search_lower in str(p.get("auth_type", "")).lower()
            ]

        if sort_field:
            providers = sorted(
                providers,
                key=lambda p: str(p.get(sort_field, "")),
                reverse=bool(sort_desc),
            )

        count = len(providers)

        if page_size is None:
            page_size = self.page_size
        if page is not None and page_size:
            providers = providers[page * page_size : (page + 1) * page_size]

        return count, providers

    def get_one(self, id: str):
        return next(
            (p for p in self._build_providers_list() if p.get("key") == id), None
        )

    def create_model(self, form):
        return False

    def update_model(self, form, model):
        return False

    def delete_model(self, model):
        return False

    def get_empty_list_message(self) -> str:
        return "No providers registered."


def register_admin_views(admin, ext: "FlaskMerchants", *, payment_name: str = "Payments", provider_name: str = "Providers") -> None:
    """Register the standard Merchants admin views into *admin*.

    This registers :class:`PaymentView` and :class:`ProvidersView` under
    ``category="Merchants"``.  It is called automatically when you pass
    ``admin=`` to :class:`~flask_merchants.FlaskMerchants`::

        admin = Admin(app, name="My Shop")
        ext = FlaskMerchants(app, admin=admin)

    You can also call it manually if you need finer control::

        register_admin_views(admin, ext)

    When called via ``FlaskMerchants.init_app``, the *payment_name* and
    *provider_name* values are read from ``app.config`` using
    ``MERCHANTS_PAYMENT_VIEW_NAME`` and ``MERCHANTS_PROVIDER_VIEW_NAME``
    respectively.

    Args:
        admin: A :class:`flask_admin.Admin` instance.
        ext: An initialised :class:`~flask_merchants.FlaskMerchants` instance.
        payment_name: Display name for the Payments menu item.
        provider_name: Display name for the Providers menu item.
    """
    admin.add_view(
        PaymentView(
            ext,
            name=payment_name,
            endpoint="merchants_payments",
            category="Merchants",
        )
    )
    admin.add_view(
        ProvidersView(
            ext,
            name=provider_name,
            endpoint="merchants_providers",
            category="Merchants",
        )
    )
