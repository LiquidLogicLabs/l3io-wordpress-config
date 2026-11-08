"""Value types for PHP constants, and the sentinel for an absent key."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Final, Literal, TypeAlias

from l3io.wp.config.domain.errors import ConfigLookupError

__all__ = [
    "MISSING",
    "ConfigValue",
    "EnvFunction",
    "EnvLookup",
    "Expression",
    "MissingType",
]

#: A PHP constant value as this package represents it.
#:
#: ``str`` covers quoted strings and any literal the parser does not recognise,
#: which it returns as raw source text (see ADR-0010).
ConfigValue: TypeAlias = "str | bool | int | float"


class MissingType:
    """The type of :data:`MISSING`. Not instantiable by callers."""

    _instance: MissingType | None = None

    def __new__(cls) -> MissingType:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "MISSING"

    def __bool__(self) -> Literal[False]:
        return False


#: Returned by ``get()`` when a key is absent.
#:
#: A key whose value is ``false``, ``0`` or ``''`` is present and falsy; an absent
#: key is ``MISSING``. Both are falsy, so test identity -- ``if value is MISSING``
#: -- never truthiness.
MISSING: Final[MissingType] = MissingType()


#: The two lookup functions recognised. ``getenv_docker`` is the official ``wordpress``
#: image's helper, defined in its own wp-config.php; ``getenv`` is PHP's.
EnvFunction: TypeAlias = Literal["getenv_docker", "getenv"]


def _php_truthy(text: str) -> bool:
    """PHP's truth for a string: everything but ``''`` and ``'0'``."""
    return text not in ("", "0")


@dataclass(frozen=True)
class EnvLookup:
    """
    A value read from the environment at runtime, as WordPress's configs commonly do.

    Exactly two shapes are recognised, each with a literal variable name:

    * ``getenv_docker('NAME', <literal>)``, the official Docker image's helper;
    * ``getenv('NAME')``, optionally followed by ``?: <literal>``.

    Anything more elaborate is an :class:`Expression`. Use :meth:`resolve` rather than
    reading the environment directly: the three shapes fall back in different ways.
    """

    name: str
    """The environment variable, as written in the config."""
    default: ConfigValue | None = None
    """The literal fallback, or ``None`` for a bare ``getenv('NAME')``."""
    function: EnvFunction = "getenv"
    """Which lookup the config calls; it decides how :meth:`resolve` falls back."""

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise ConfigLookupError(name=repr(self.name), reason="the name must be a non-empty str")
        if self.function not in ("getenv_docker", "getenv"):
            raise ConfigLookupError(name=self.name, reason=f"unknown function {self.function!r}")
        if self.function == "getenv_docker" and self.default is None:
            raise ConfigLookupError(name=self.name, reason="getenv_docker always has a default")
        if self.default is not None and not isinstance(self.default, str | bool | int | float):
            raise ConfigLookupError(
                name=self.name, reason=f"a default cannot be a {type(self.default).__name__}"
            )

    def resolve(
        self,
        environ: Mapping[str, str],
        read_file: Callable[[str], str] | None = None,
    ) -> ConfigValue:
        """
        The value PHP would define, given ``environ``.

        * ``getenv_docker``: when ``NAME_FILE`` is set and truthy to PHP, the file it
          names, with trailing ``\\r``/``\\n`` stripped -- Docker secrets. Otherwise
          ``NAME`` if it is set at all, even to ``''``. Otherwise the default.
        * ``getenv`` with a default (``?:``): ``NAME`` if set and truthy to PHP -- so
          ``''`` and ``'0'`` fall back too. Otherwise the default.
        * bare ``getenv``: ``NAME`` if set, else ``False``, which is what PHP defines.

        Args:
            environ: The environment the site runs with, such as ``os.environ``.
            read_file: Reads a ``NAME_FILE`` path as text. Needed only when one is set;
                for example ``lambda p: Path(p).read_text(encoding="utf-8")``.

        Raises:
            ConfigLookupError: ``environ`` is not a mapping, or a ``NAME_FILE`` is set
                and there is no ``read_file``, or reading it failed.
        """
        if not isinstance(environ, Mapping):
            raise ConfigLookupError(name=self.name, reason="environ must be a mapping")
        if read_file is not None and not callable(read_file):
            raise ConfigLookupError(name=self.name, reason="read_file must be callable")
        value = environ.get(self.name)

        if self.function == "getenv_docker":
            path = environ.get(f"{self.name}_FILE")
            if isinstance(path, str) and _php_truthy(path):
                return self._read(path, read_file)
            if value is not None:
                return value
            return self.default if self.default is not None else ""  # pragma: no cover

        if self.default is None:
            return False if value is None else value
        return value if value is not None and _php_truthy(value) else self.default

    def _read(self, path: str, read_file: Callable[[str], str] | None) -> str:
        source = f"{self.name}_FILE"
        if read_file is None:
            raise ConfigLookupError(
                name=self.name, reason=f"{source} is set; pass read_file to read it"
            )
        try:
            text = read_file(path)
        except Exception as exc:  # noqa: BLE001 - the caller's reader; AD-14 wraps whatever it raises
            raise ConfigLookupError(
                name=self.name,
                reason=f"reading the file {source} names failed: {type(exc).__name__}",
            ) from exc
        if not isinstance(text, str):
            raise ConfigLookupError(
                name=self.name, reason=f"read_file returned {type(text).__name__}, not str"
            )
        return text.rstrip("\r\n")


@dataclass(frozen=True)
class Expression:
    """A value that is PHP code this package does not evaluate, kept as its source text."""

    source: str
    """The value exactly as written, such as ``__DIR__ . '/'``."""
