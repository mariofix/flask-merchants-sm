import json

from flask import current_app, flash
from flask_admin import AdminIndexView, expose
from flask_admin.actions import action
from flask_admin.contrib.sqla import ModelView
from markupsafe import Markup
from wtforms import ValidationError, fields


class AppAdmin:
    page_size = 20
    can_create = True
    can_edit = True
    can_delete = True
    column_display_pk = True
    save_as = True
    save_as_continue = True
    can_export = True
    can_view_details = True
    can_set_page_size = True


class MerchantsIndex(AdminIndexView):
    @expose("/")
    def index(self):
        return self.render("dashboard.html")


class IntegrationAdmin(AppAdmin, ModelView):
    name = "Integration"
    name_plural = "Integrations"
    column_list = ["slug", "integration_class", "is_active"]

    form_overrides = {"config": fields.TextAreaField}
    form_widget_args = {
        "config": {"rows": 10, "style": "font-family: monospace;"},
    }

    def _integration_class_validator(form, field):
        allowed_integrations = current_app.config.get("MERCHANTS_ALLOWED_INTEGRATIONS", [])

        if not field.data:
            return

        if field.data not in allowed_integrations:
            raise ValidationError(
                f'Integration class "{field.data}" is not allowed. Must be one of: {", ".join(allowed_integrations)}'
            )

    form_args = {"integration_class": {"validators": [_integration_class_validator]}}

    def on_form_prefill(self, form, id):
        if form.config.data:
            form.config.data = json.dumps(form.config.data, indent=2)

    def on_model_change(self, form, model, is_created):
        if isinstance(form.config.data, str):
            try:
                model.config = json.loads(form.config.data)
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid JSON format: {e}")

    column_formatters_detail = {
        "config": lambda view, context, model, name: Markup(
            f'<pre style="white-space: pre-wrap; font-family: monospace;">{json.dumps(model.config, indent=2) if model.config else "{}"}</pre>'
        )
    }

    def is_html_allowed(self, name):
        # Enable safe HTML rendering for specific fields
        return name in ["config"]


class PaymentAdmin(ModelView):
    name = "Payment"
    name_plural = "Payments"

    page_size = 20
    can_create = True
    can_edit = True
    can_delete = True
    column_display_pk = True
    save_as = True
    save_as_continue = True
    can_export = True
    can_view_details = True
    can_set_page_size = True

    column_list = ["merchants_token", "integration_slug", "currency", "amount", "status", "creation"]
    form_overrides = {
        "integration_payload": fields.TextAreaField,
        "integration_response": fields.TextAreaField,
    }
    column_formatters_detail = {
        "integration_payload": lambda view, context, model, name: Markup(
            f'<pre style="white-space: pre-wrap; font-family: monospace;">{json.dumps(model.integration_payload, indent=2) if model.integration_payload else "{}"}</pre>'
        ),
        "integration_response": lambda view, context, model, name: Markup(
            f'<pre style="white-space: pre-wrap; font-family: monospace;">{json.dumps(model.integration_response, indent=2) if model.integration_response else "{}"}</pre>'
        ),
    }
    form_widget_args = {
        "integration_payload": {"rows": 10, "style": "font-family: monospace;"},
        "integration_response": {"rows": 10, "style": "font-family: monospace;"},
    }

    def on_form_prefill(self, form, id):
        if form.integration_payload.data:
            form.integration_payload.data = json.dumps(form.integration_payload.data, indent=2)
        if form.integration_response.data:
            form.integration_response.data = json.dumps(form.integration_response.data, indent=2)

    def is_html_allowed(self, name):
        # Enable safe HTML rendering for specific fields
        return name in ["integration_payload", "integration_response"]

    def on_model_change(self, form, model, is_created):
        if isinstance(form.integration_payload.data, str) and len(form.integration_payload.data) > 0:
            try:
                model.integration_payload = json.loads(form.integration_payload.data)
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid JSON format: {e}")
        if isinstance(form.integration_response.data, str) and len(form.integration_response.data) > 0:
            try:
                model.integration_response = json.loads(form.integration_response.data)
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid JSON format: {e}")

    @action("process", "Process", "Are you sure you want to process the payments?")
    def action_process(self, ids):
        from .core import get_payment_model

        payment_model = get_payment_model(current_app, current_app.extensions["sqlalchemy"])
        payments = payment_model.query.filter(payment_model.id.in_(ids))
        for p in payments.all():
            try:
                flash(f"Payment {p}: {p.process()}", "info")
            except Exception as ex:
                flash(f"Payment {p} Error: {ex}", "error")
