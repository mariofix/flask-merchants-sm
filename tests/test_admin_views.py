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


class TestKhipuProviderAttributes:
    """Verify KhipuProvider exposes _base_url and _auth for ProvidersView display."""

    def test_base_url_is_set(self):
        import khipu_tools
        from merchants.providers.khipu import KhipuProvider

        provider = KhipuProvider(api_key="test-key-123")
        assert provider._base_url == khipu_tools.DEFAULT_API_BASE

    def test_base_url_is_non_empty_string(self):
        from merchants.providers.khipu import KhipuProvider

        provider = KhipuProvider(api_key="test-key-123")
        assert isinstance(provider._base_url, str)
        assert provider._base_url

    def test_auth_is_api_key_auth(self):
        from merchants.auth import ApiKeyAuth
        from merchants.providers.khipu import KhipuProvider

        provider = KhipuProvider(api_key="test-key-123")
        assert isinstance(provider._auth, ApiKeyAuth)

    def test_auth_header_is_x_api_key(self):
        from merchants.providers.khipu import KhipuProvider

        provider = KhipuProvider(api_key="test-key-123")
        assert provider._auth._header == "x-api-key"

    def test_auth_key_matches(self):
        from merchants.providers.khipu import KhipuProvider

        provider = KhipuProvider(api_key="my-secret-key")
        assert provider._auth._api_key == "my-secret-key"


class TestProvidersViewBuildList:
    """Verify _build_providers_list returns correct base_url and auth_type for KhipuProvider."""

    def _make_view_with_khipu(self, api_key="test-key"):
        """Return a ProvidersView instance backed by a stub extension with KhipuProvider.

        Temporarily registers the KhipuProvider in the merchants global registry
        and restores any previous state when done (used as a context manager).
        """
        import contextlib
        import merchants
        from merchants.providers import _REGISTRY
        from merchants.providers.khipu import KhipuProvider
        from flask_merchants.contrib.admin import ProvidersView

        provider = KhipuProvider(api_key=api_key)
        previous = _REGISTRY.pop("khipu", None)
        _REGISTRY["khipu"] = provider

        class _StubExt:
            def get_client(self, key):
                return merchants.Client(provider=key)

            def all_sessions(self):
                return []

        view = object.__new__(ProvidersView)
        view._ext = _StubExt()

        @contextlib.contextmanager
        def _ctx():
            try:
                yield view
            finally:
                _REGISTRY.pop("khipu", None)
                if previous is not None:
                    _REGISTRY["khipu"] = previous

        return _ctx()

    def test_khipu_base_url_not_na(self):
        import khipu_tools
        with self._make_view_with_khipu() as view:
            rows = view._build_providers_list()
            khipu_row = next((r for r in rows if r["key"] == "khipu"), None)
            assert khipu_row is not None
            assert khipu_row["base_url"] != "N/A"
            assert khipu_row["base_url"] == khipu_tools.DEFAULT_API_BASE

    def test_khipu_auth_type_not_none(self):
        with self._make_view_with_khipu() as view:
            rows = view._build_providers_list()
            khipu_row = next((r for r in rows if r["key"] == "khipu"), None)
            assert khipu_row is not None
            assert khipu_row["auth_type"] != "None"
            assert khipu_row["auth_type"] == "ApiKeyAuth"

    def test_khipu_auth_header_is_x_api_key(self):
        with self._make_view_with_khipu() as view:
            rows = view._build_providers_list()
            khipu_row = next((r for r in rows if r["key"] == "khipu"), None)
            assert khipu_row is not None
            assert khipu_row["auth_header"] == "x-api-key"
