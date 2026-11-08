"""The capability a wp-config source offers, independent of where it is stored."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from l3io.wp.config.domain.values import ConfigValue, EnvLookup, Expression, MissingType

__all__ = ["WpConfigSource"]


@runtime_checkable
class WpConfigSource(Protocol):
    """
    Read and write ``define()`` constants, wherever they live.

    Satisfied by both the pure core and the file adapter, so a caller can depend
    on the capability rather than on which of the two it was handed.
    """

    @property
    def content(self) -> str: ...

    def get(self, key: str) -> ConfigValue | MissingType: ...

    def get_value(self, key: str) -> ConfigValue | EnvLookup | Expression | MissingType: ...

    def get_variable_value(
        self, key: str
    ) -> ConfigValue | EnvLookup | Expression | MissingType: ...

    def get_source(self, key: str) -> str | MissingType: ...

    def get_variable_source(self, key: str) -> str | MissingType: ...

    def set(self, key: str, value: ConfigValue) -> bool: ...

    def get_variable(self, key: str) -> ConfigValue | MissingType: ...

    def set_variable(self, key: str, value: ConfigValue) -> bool: ...
