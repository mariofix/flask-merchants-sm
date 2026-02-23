"""Tests for flask_merchants.contrib.admin form field help tips and column descriptions."""

import pytest


class TestPaymentViewFormDescriptions:
    """Verify that PaymentView.scaffold_form() attaches help-tip descriptions to fields."""

    def _get_state_form_class(self):
        from flask_merchants.contrib.admin import PaymentView, _PaymentRecord

        # Instantiate with a minimal stub extension
        class _StubExt:
            pass

        # BaseModelView.__init__ requires a Flask app context; bypass by calling
        # scaffold_form directly without going through __init__.
        view = object.__new__(PaymentView)
        view._ext = _StubExt()
        return view.scaffold_form()

    def test_state_field_has_description(self):
        form_class = self._get_state_form_class()
        field = form_class.state
        assert field.kwargs.get("description"), "state field should have a non-empty description"

    def test_state_description_is_string(self):
        form_class = self._get_state_form_class()
        description = form_class.state.kwargs.get("description", "")
        assert isinstance(description, str)
        assert len(description) > 0


class TestPaymentViewColumnDescriptions:
    """Verify that PaymentView declares column_descriptions for all list columns."""

    def test_column_descriptions_defined(self):
        from flask_merchants.contrib.admin import PaymentView

        assert hasattr(PaymentView, "column_descriptions")
        assert isinstance(PaymentView.column_descriptions, dict)

    def test_all_list_columns_have_descriptions(self):
        from flask_merchants.contrib.admin import PaymentView

        for col in PaymentView.column_list:
            assert col in PaymentView.column_descriptions, (
                f"column '{col}' is missing from PaymentView.column_descriptions"
            )

    def test_descriptions_are_non_empty_strings(self):
        from flask_merchants.contrib.admin import PaymentView

        for col, desc in PaymentView.column_descriptions.items():
            assert isinstance(desc, str) and desc, (
                f"description for column '{col}' must be a non-empty string"
            )


class TestProvidersViewColumnDescriptions:
    """Verify that ProvidersView declares column_descriptions for all list columns."""

    def test_column_descriptions_defined(self):
        from flask_merchants.contrib.admin import ProvidersView

        assert hasattr(ProvidersView, "column_descriptions")
        assert isinstance(ProvidersView.column_descriptions, dict)

    def test_all_list_columns_have_descriptions(self):
        from flask_merchants.contrib.admin import ProvidersView

        for col in ProvidersView.column_list:
            assert col in ProvidersView.column_descriptions, (
                f"column '{col}' is missing from ProvidersView.column_descriptions"
            )

    def test_descriptions_are_non_empty_strings(self):
        from flask_merchants.contrib.admin import ProvidersView

        for col, desc in ProvidersView.column_descriptions.items():
            assert isinstance(desc, str) and desc, (
                f"description for column '{col}' must be a non-empty string"
            )
