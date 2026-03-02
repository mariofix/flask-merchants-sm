"""Custom Flask-Security username utility for Chilean phone number validation."""

import re

from flask_security.username_util import UsernameUtil


_CHILEAN_PHONE_RE = re.compile(r"^56\d{9}$")

_CHILEAN_PHONE_ERROR = (
    "Ingresa un número telefónico chileno válido: 11 dígitos sin signo +, "
    "comenzando con 56 (ejemplo: 56912345678)."
)


class ChileanPhoneUsernameUtil(UsernameUtil):
    """UsernameUtil that enforces a Chilean phone number in the username field.

    The username must be exactly 11 digits with no plus sign, starting with
    the Chilean country code ``56`` (e.g. ``56912345678``).
    """

    def check_username(self, username: str) -> str | None:
        """Return an error message if *username* is not a valid Chilean phone number.

        Accepts only the format ``56XXXXXXXXX`` — exactly 11 digits, no plus
        sign, starting with the Chilean country code ``56``.

        Returns:
            None if valid, otherwise a human-readable error string.
        """
        if not _CHILEAN_PHONE_RE.match(username):
            return _CHILEAN_PHONE_ERROR
        return None
