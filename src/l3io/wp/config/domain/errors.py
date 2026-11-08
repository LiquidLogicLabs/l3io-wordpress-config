"""
Package-owned error hierarchy (AD-14).

No stdlib or dependency exception type crosses this package's public boundary.
Failures at a boundary are caught and re-raised as one of these, with
``raise ... from`` preserving the cause. Every error carries structured fields
rather than only a formatted message, and no message contains a credential --
values are identified by key, never quoted back.
"""

from __future__ import annotations

__all__ = [
    "ConfigKeyError",
    "ConfigLookupError",
    "ConfigReadError",
    "ConfigValueError",
    "ConfigWriteError",
    "ReadBackError",
    "WpConfigError",
]


class WpConfigError(Exception):
    """Base for every error this package raises."""


class ConfigReadError(WpConfigError):
    """A ``wp-config.php`` could not be read."""

    def __init__(self, filename: str, reason: str) -> None:
        self.filename = filename
        self.reason = reason
        super().__init__(f"Cannot read {filename!r}: {reason}")


class ConfigWriteError(WpConfigError):
    """A ``wp-config.php`` could not be written, or a constant could not be placed."""

    def __init__(self, filename: str, reason: str, key: str | None = None) -> None:
        self.filename = filename
        self.reason = reason
        self.key = key
        where = f" while setting {key!r}" if key else ""
        super().__init__(f"Cannot write {filename!r}{where}: {reason}")


class ConfigKeyError(WpConfigError):
    """
    A key is not a PHP identifier, so no statement naming it could be written.

    ``key`` is the ``repr()`` of what was passed, since it may not be a ``str``.
    """

    def __init__(self, key: str, reason: str) -> None:
        self.key = key
        self.reason = reason
        super().__init__(f"Cannot use {key} as a key: {reason}")


class ConfigValueError(WpConfigError):
    """A value cannot be rendered as a PHP literal."""

    def __init__(self, key: str, value_type: str, reason: str | None = None) -> None:
        self.key = key
        self.value_type = value_type
        self.reason = reason or "supported types are str, bool, int and float"
        # The value itself is never quoted: it may be a credential.
        super().__init__(
            f"Cannot render a value of type {value_type!r} for key {key!r}; {self.reason}"
        )


class ConfigLookupError(WpConfigError):
    """An environment lookup could not be built or resolved."""

    def __init__(self, name: str, reason: str) -> None:
        self.name = name
        self.reason = reason
        # The variable is named; its value never is -- it may be a credential.
        super().__init__(f"Cannot resolve environment variable {name!r}: {reason}")


class ReadBackError(WpConfigError):
    """
    Read-back verification failed (ADR-0010).

    The write is not committed, so the file on disk is unchanged. ``mismatches``
    names what differed, by key, without quoting any value.
    """

    def __init__(self, filename: str, mismatches: list[str]) -> None:
        self.filename = filename
        self.mismatches = mismatches
        super().__init__(
            f"Read-back verification failed for {filename!r}; "
            f"the file was not modified. Problems: {'; '.join(mismatches)}"
        )
