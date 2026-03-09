"""Tests for verify_khipu_signature in merchants.webhooks.

Validates the Khipu v3.0 x-khipu-signature HMAC-SHA256 verification
using the reference example from Khipu's official documentation.
"""

import base64
import hashlib
import hmac

import pytest

from merchants.webhooks import WebhookVerificationError, verify_khipu_signature


# Reference values from Khipu documentation
_KHIPU_DOC_SECRET = "1a4cbbbeb8bdb7e1d73572b9cc43ce4ce18f79d9"

_KHIPU_DOC_PAYLOAD = (
    b'{"payment_id":"zfxnocsow6mz","receiver_id":990939,"subject":"TEST_COBRO",'
    b'"amount":"1000.0000","discount":"0.0000","currency":"CLP",'
    b'"receipt_url":"https:\\/\\/s3.amazonaws.com\\/staging.notifications.khipu.com'
    b'\\/CPKH-1804240956-zfxnocsow6mz.pdf","bank":"DemoBank","bank_id":"Bawdf",'
    b'"payer_name":"Cobrador de desarrollo #990.939","payer_email":"test@khipu.com",'
    b'"personal_identifier":"44.444.444-4","bank_account_number":"000000000000444444444",'
    b'"out_of_date_conciliation":false,'
    b'"transaction_id":"15f836bd-e8a7-4d12-b2f1-56403012b555",'
    b'"responsible_user_email":"test@khipu.com",'
    b'"payment_method":"simplified_transfer",'
    b'"conciliation_date":"2024-04-18T13:56:54.859Z"}'
)

_KHIPU_DOC_TIMESTAMP = "1711965600393"
_KHIPU_DOC_SIGNATURE = "GYzpjnXlTKQ+BJY7pZJmrM6DZgWMSJdtOr/dleBKTdg="
_KHIPU_DOC_HEADER = f"t={_KHIPU_DOC_TIMESTAMP},s={_KHIPU_DOC_SIGNATURE}"


class TestVerifyKhipuSignatureDocExample:
    """Verify against the exact example from Khipu's official docs."""

    def test_doc_example_passes(self):
        ts = verify_khipu_signature(
            _KHIPU_DOC_PAYLOAD, _KHIPU_DOC_SECRET, _KHIPU_DOC_HEADER
        )
        assert ts == _KHIPU_DOC_TIMESTAMP

    def test_doc_example_wrong_secret_fails(self):
        with pytest.raises(WebhookVerificationError):
            verify_khipu_signature(
                _KHIPU_DOC_PAYLOAD, "wrong-secret", _KHIPU_DOC_HEADER
            )

    def test_doc_example_tampered_payload_fails(self):
        tampered = _KHIPU_DOC_PAYLOAD + b" "
        with pytest.raises(WebhookVerificationError):
            verify_khipu_signature(tampered, _KHIPU_DOC_SECRET, _KHIPU_DOC_HEADER)


class TestVerifyKhipuSignatureEdgeCases:
    def test_malformed_header_missing_s(self):
        with pytest.raises(WebhookVerificationError, match="missing t= or s="):
            verify_khipu_signature(b"body", "secret", "t=123")

    def test_malformed_header_missing_t(self):
        with pytest.raises(WebhookVerificationError, match="missing t= or s="):
            verify_khipu_signature(b"body", "secret", "s=abc123")

    def test_empty_header(self):
        with pytest.raises(WebhookVerificationError, match="missing t= or s="):
            verify_khipu_signature(b"body", "secret", "")

    def test_returns_timestamp(self):
        secret = "test-secret"
        payload = b'{"test": true}'
        timestamp = "9999999999999"
        to_hash = f"{timestamp}.".encode() + payload
        digest = hmac.new(secret.encode(), to_hash, hashlib.sha256).digest()
        sig_b64 = base64.b64encode(digest).decode()
        header = f"t={timestamp},s={sig_b64}"

        result = verify_khipu_signature(payload, secret, header)
        assert result == timestamp

    def test_bytes_secret_also_works(self):
        secret_bytes = b"test-secret"
        payload = b'{"test": true}'
        timestamp = "1234567890"
        to_hash = f"{timestamp}.".encode() + payload
        digest = hmac.new(secret_bytes, to_hash, hashlib.sha256).digest()
        sig_b64 = base64.b64encode(digest).decode()
        header = f"t={timestamp},s={sig_b64}"

        result = verify_khipu_signature(payload, secret_bytes, header)
        assert result == timestamp
