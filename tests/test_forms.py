"""Tests for Chilean phone number validation in app/forms.py."""

import pytest

from app.forms import ChileanPhoneUsernameUtil, _CHILEAN_PHONE_ERROR


class TestChileanPhoneUsernameUtil:
    """Unit tests for ChileanPhoneUsernameUtil.check_username."""

    def setup_method(self):
        self.util = ChileanPhoneUsernameUtil.__new__(ChileanPhoneUsernameUtil)

    # --- valid numbers ---

    def test_valid_mobile_number(self):
        assert self.util.check_username("56912345678") is None

    def test_valid_landline_number(self):
        assert self.util.check_username("56212345678") is None

    # --- invalid numbers ---

    def test_rejects_plus_sign_prefix(self):
        assert self.util.check_username("+56912345678") == _CHILEAN_PHONE_ERROR

    def test_rejects_too_short(self):
        assert self.util.check_username("5691234567") == _CHILEAN_PHONE_ERROR

    def test_rejects_too_long(self):
        assert self.util.check_username("569123456789") == _CHILEAN_PHONE_ERROR

    def test_rejects_wrong_country_code(self):
        assert self.util.check_username("12345678901") == _CHILEAN_PHONE_ERROR

    def test_rejects_non_digits(self):
        assert self.util.check_username("5691234567a") == _CHILEAN_PHONE_ERROR

    def test_rejects_empty_string(self):
        assert self.util.check_username("") == _CHILEAN_PHONE_ERROR

    def test_rejects_spaces(self):
        assert self.util.check_username("569 1234 5678") == _CHILEAN_PHONE_ERROR
