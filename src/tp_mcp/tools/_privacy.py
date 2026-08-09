"""Shared conservative checks for source-controlled response text."""

import re

_URI = re.compile(r"\b[A-Za-z][A-Za-z0-9+.-]{1,31}://", re.IGNORECASE)
_EMAIL = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
_ABSOLUTE_PATH = re.compile(
    r"(?:[A-Za-z]:[\\/]|\\\\[^\\/\s]+[\\/]|//[^/\s]+/|"
    r"(?:^|[\s=:;,()])/(?!/)\S+)",
    re.IGNORECASE,
)
_CREDENTIAL_MARKER = re.compile(
    r"(?:authorization|bearer|cookie|credential|password|secret|token)",
    re.IGNORECASE,
)


def is_sensitive_text(value: str) -> bool:
    """Return whether source text could expose a path, URL, or credential."""
    return (
        any(ord(character) < 32 or ord(character) == 127 for character in value)
        or _URI.search(value) is not None
        or _EMAIL.search(value) is not None
        or _ABSOLUTE_PATH.search(value) is not None
        or _CREDENTIAL_MARKER.search(value) is not None
    )
