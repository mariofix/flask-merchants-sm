"""Flask-Admin ModelView for the SQLAlchemy-backed Payment model.

Requires the ``db`` extra::

    pip install "flask-merchants[db]"

Example::

    from flask import Flask
    from flask_sqlalchemy import SQLAlchemy
    from flask_admin import Admin
    from flask_merchants import FlaskMerchants
    from flask_merchants.models import Base, Payment
    from flask_merchants.contrib.sqla import PaymentModelView

    db = SQLAlchemy(model_class=Base)

    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///payments.db"
    app.config["SECRET_KEY"] = "change-me"

    ext = FlaskMerchants(app, db=db)
    db.init_app(app)

    admin = Admin(app, name="My Shop")
    admin.add_view(PaymentModelView(Payment, db.session, ext=ext, name="Payments"))

    with app.app_context():
        db.create_all()
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

try:
    from flask_admin.actions import action
    from flask_admin.contrib.sqla import ModelView
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "flask-admin and flask-sqlalchemy are required for "
        "flask_merchants.contrib.sqla. "
        "Install them with: pip install 'flask-merchants[db]'"
    ) from exc

if TYPE_CHECKING:
    from flask_merchants import FlaskMerchants


_STATE_CHOICES = [
    ("pending", "Pending"),
    ("processing", "Processing"),
    ("succeeded", "Succeeded"),
    ("failed", "Failed"),
    ("cancelled", "Cancelled"),
    ("refunded", "Refunded"),
    ("unknown", "Unknown"),
]


class PaymentModelView(ModelView):
    """Flask-Admin view for the :class:`~flask_merchants.models.Payment` model.

    Provides:
    - Searchable / filterable list of all payment records.
    - Create, view, and edit payment records (all user-editable fields).
    - State validation via ``on_model_change`` as a Flask-Admin-level guard,
      backed by the SQLAlchemy ``@validates`` hook in
      :class:`~flask_merchants.models.PaymentMixin` at the ORM level.
    - Bulk **Refund**, **Cancel**, and **Sync from Provider** actions.

    Args:
        model: The :class:`~flask_merchants.models.Payment` model class.
        session: A SQLAlchemy scoped session (e.g. ``db.session``).
        ext: Optional :class:`~flask_merchants.FlaskMerchants` instance.
            Required only for the *Sync from Provider* action.
        name: Display name shown in the admin navigation bar.
        endpoint: Internal Flask endpoint prefix (must be unique).
        category: Optional admin category/group name.
    """

    # ------------------------------------------------------------------
    # Column configuration
    # ------------------------------------------------------------------
    column_list = [
        "session_id",
        "provider",
        "amount",
        "currency",
        "state",
        "created_at",
        "updated_at",
    ]
    column_searchable_list = ["session_id", "provider"]
    column_filters = ["state", "provider", "currency"]
    column_default_sort = ("created_at", True)

    # Allow creating new payment records from the admin UI.
    can_create = True

    # Fields available when creating a new payment.
    form_create_columns = [
        "session_id",
        "redirect_url",
        "provider",
        "amount",
        "currency",
        "state",
        "metadata_json",
    ]

    # Fields available when editing an existing payment.
    form_edit_columns = [
        "redirect_url",
        "provider",
        "amount",
        "currency",
        "state",
        "metadata_json",
    ]

    form_choices = {"state": _STATE_CHOICES}

    # ------------------------------------------------------------------
    # Init
    # ------------------------------------------------------------------

    def __init__(
        self,
        model,
        session,
        *,
        ext: "FlaskMerchants | None" = None,
        can_create: bool | None = None,
        can_edit: bool | None = None,
        can_delete: bool | None = None,
        **kwargs: Any,
    ) -> None:
        self._ext = ext
        # Allow per-instance overrides of the class-level capability flags so
        # callers can restrict the UI without having to subclass:
        #
        #   PaymentModelView(Payment, db.session, ext=ext, can_create=False)
        if can_create is not None:
            self.can_create = can_create
        if can_edit is not None:
            self.can_edit = can_edit
        if can_delete is not None:
            self.can_delete = can_delete
        super().__init__(model, session, **kwargs)

    # ------------------------------------------------------------------
    # on_model_change hook
    # ------------------------------------------------------------------

    def on_model_change(self, form, model, is_created: bool) -> None:
        """Validate state before committing.

        WTForms rejects unknown choices via ``form_choices`` before this hook
        runs.  ``PaymentMixin.validate_state`` (a SQLAlchemy ``@validates``
        hook) rejects invalid values at the ORM attribute level.  This method
        acts as a third, Flask-Admin-level guard so that any value that
        somehow slips through still raises a :class:`wtforms.ValidationError`
        and surfaces a clean error in the admin UI rather than an unhandled
        exception.
        """
        valid_states = {s for s, _ in _STATE_CHOICES}
        if model.state not in valid_states:
            from wtforms import ValidationError

            raise ValidationError(
                f"Invalid state {model.state!r}. "
                f"Choose one of: {', '.join(sorted(valid_states))}."
            )

    def after_model_change(self, form, model, is_created: bool) -> None:
        """Called after a successful commit.

        Syncs the in-memory store (if the extension is available) so that
        both storage backends stay consistent.
        """
        if self._ext is not None:
            self._ext.update_state(model.session_id, model.state)

    # ------------------------------------------------------------------
    # Bulk actions
    # ------------------------------------------------------------------

    @action("refund", "Refund", "Mark selected payments as refunded?")
    def action_refund(self, ids: list[str]) -> None:
        """Mark the selected payment rows as *refunded*."""
        from flask import flash

        try:
            count = 0
            for pk in ids:
                record = self.get_one(pk)
                if record is not None:
                    record.state = "refunded"
                    if self._ext is not None:
                        self._ext.update_state(record.session_id, "refunded")
                    count += 1
            self.session.commit()
            flash(f"{count} payment(s) marked as refunded.", "success")
        except Exception as exc:  # noqa: BLE001
            self.session.rollback()
            flash(f"Failed to refund payments: {exc}", "danger")

    @action("cancel", "Cancel", "Cancel the selected payments?")
    def action_cancel(self, ids: list[str]) -> None:
        """Mark the selected payment rows as *cancelled*."""
        from flask import flash

        try:
            count = 0
            for pk in ids:
                record = self.get_one(pk)
                if record is not None:
                    record.state = "cancelled"
                    if self._ext is not None:
                        self._ext.update_state(record.session_id, "cancelled")
                    count += 1
            self.session.commit()
            flash(f"{count} payment(s) cancelled.", "success")
        except Exception as exc:  # noqa: BLE001
            self.session.rollback()
            flash(f"Failed to cancel payments: {exc}", "danger")

    @action("sync", "Sync from Provider", "Sync selected payments from the payment provider?")
    def action_sync(self, ids: list[str]) -> None:
        """Fetch live payment status from the provider and update each record."""
        from flask import flash

        if self._ext is None:
            flash("FlaskMerchants extension not configured; cannot sync.", "danger")
            return

        try:
            count = 0
            for pk in ids:
                record = self.get_one(pk)
                if record is None:
                    continue
                try:
                    status = self._ext.client.payments.get(record.session_id)
                    record.state = status.state.value
                    count += 1
                except Exception:  # noqa: BLE001
                    pass
            self.session.commit()
            flash(f"{count} payment(s) synced from provider.", "success")
        except Exception as exc:  # noqa: BLE001
            self.session.rollback()
            flash(f"Failed to sync payments: {exc}", "danger")
