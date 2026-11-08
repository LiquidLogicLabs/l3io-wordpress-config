"""
Read and write ``define()`` constants in ``wp-config.php`` content.

Pure: string in, string out. No I/O, and nothing here imports ``ports``,
``adapters`` or ``cli`` (AD-1).

This is a reader and writer for the ``define()`` subset of PHP that WordPress
itself writes. It is **not** a PHP parser; ADR-0010 records its documented
limits and the read-back verification that guards them.
"""

from __future__ import annotations

import bisect
import math
import re
from dataclasses import dataclass
from logging import getLogger
from typing import Literal

from l3io.wp.config.domain.errors import ConfigKeyError, ConfigValueError, ConfigWriteError
from l3io.wp.config.domain.values import (
    MISSING,
    ConfigValue,
    EnvFunction,
    EnvLookup,
    Expression,
    MissingType,
)

__all__ = [
    "Constant",
    "Kind",
    "WpConfigString",
    "read_value",
    "render_define",
    "render_statement",
    "render_value",
    "render_variable",
    "scan",
]

#: The two shapes `wp-config.php` carries. Connection settings are `define()`
#: constants; the table prefix is a variable assignment. Both are read and
#: written; nothing else in PHP is (ADR-0010).
Kind = Literal["define", "variable"]

_log = getLogger(__name__)

# A quoted PHP string, consumed whole, so nothing inside it can end a value.
_QUOTED = r"'(?:[^'\\\n]|\\.)*'|\"(?:[^\"\\\n]|\\.)*\""

# A value: quoted strings as atomic tokens, anything else one character at a
# time, never a newline and never a bare quote. Non-greedy, so it stops at the
# first terminator OUTSIDE a string. It used to be `.*?`, which stopped at the
# first `);` anywhere: WordPress's salt generator emits both characters, and
# 7.5% of salt sets were cut short and corrupted on write, with read-back passing
# because it re-scans with this same pattern. tests/test_value_spans.py.
_VALUE = rf"(?:{_QUOTED}|[^'\"\n])*?"

# Anchored at line start so a commented-out `// define(...)` never matches; that
# anchor is load-bearing. Leading whitespace is allowed:
# WP-CLI writes WP_DEBUG indented inside an `if ( ! defined(...) )` block.
# `define` in any case: PHP function names are case-insensitive, so `DEFINE(...)`
# is a definition, and missing it made `set()` add a second one.
_DEFINE_RE = re.compile(
    rf"^[ \t]*(?i:define)\s*\(\s*'(?P<key>(?:[^'\\]|\\.)*)'\s*,\s*(?P<value>{_VALUE})\s*\)\s*;",
    re.MULTILINE,
)

# Anchored at column 0, which approximates file scope: an assignment indented
# inside a function body is not matched. It used to allow leading whitespace,
# so an indented `$table_prefix` above the file-scope one was the one read.
_VARIABLE_RE = re.compile(
    rf"^\$(?P<key>[A-Za-z_]\w*)\s*=\s*(?P<value>{_VALUE})\s*;",
    re.MULTILINE,
)

# What PHP does not execute, in the order PHP's lexer meets it: a quoted string
# (so `/*` inside a salt is data), a block comment (to its first `*/`, or the end
# of the file if unterminated, and quotes inside it mean nothing), and a line
# comment, which the line-start anchors above already make invisible but which
# must still be consumed so a `/*` inside one opens nothing. `#[` is a PHP 8
# attribute, not a comment. Heredoc and nowdoc are not recognised (ADR-0010).
_NON_CODE_RE = re.compile(
    r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"|/\*.*?(?:\*/|\Z)|(?://|#(?!\[))[^\n]*",
    re.DOTALL,
)

#: Each shape and the pattern that finds it. Annotated so the Literal survives.
_PATTERNS: tuple[tuple[Kind, re.Pattern[str]], ...] = (
    ("define", _DEFINE_RE),
    ("variable", _VARIABLE_RE),
)

_INT_RE = re.compile(r"^[+-]?\d+$")

# What both a define() name and a variable name must be, so a written statement is
# always valid PHP. define() itself accepts any string, but nothing WordPress
# reads is named otherwise, and an unescapable quote or space in a key is a
# syntax error that takes the site down.
_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_PHP_OPEN = "<?php\n"
# The opening tag and the line ending after it. A constant is inserted after the
# first one, ending in that same newline: WordPress's own sample uses CRLF.
_PHP_OPEN_RE = re.compile(r"<\?php(\r?\n)")


@dataclass(frozen=True)
class Constant:
    """One ``define()`` occurrence found in the content."""

    kind: Kind
    """Which shape this is: a ``define()`` constant or a variable assignment."""
    key: str
    """The constant name, or the variable name without its ``$``."""
    raw_value: str
    """The value exactly as it appears in the source, unparsed."""
    start: int
    """Offset of the first character of ``raw_value``."""
    end: int
    """Offset one past the last character of ``raw_value``."""
    text: str
    """The whole matched ``define(...);`` as it appears in the source."""


def _block_comments(content: str) -> tuple[list[int], list[int]]:
    """Start and end offsets of every ``/* ... */`` comment, in source order."""
    starts: list[int] = []
    ends: list[int] = []
    for m in _NON_CODE_RE.finditer(content):
        if m.group().startswith("/*"):
            starts.append(m.start())
            ends.append(m.end())
    return starts, ends


def scan(content: str) -> list[Constant]:
    """
    Every ``define()`` and file-scope variable assignment, in source order.

    A statement inside a block comment is not one: PHP never runs it. Line
    comments need no filter here, because both patterns are anchored at the start
    of a line.
    """
    starts, ends = _block_comments(content)

    def commented(offset: int) -> bool:
        i = bisect.bisect_right(starts, offset) - 1
        return i >= 0 and offset < ends[i]

    found = [
        Constant(
            kind=kind,
            key=m.group("key"),
            raw_value=m.group("value"),
            start=m.start("value"),
            end=m.end("value"),
            text=m.group(0),
        )
        for kind, pattern in _PATTERNS
        for m in pattern.finditer(content)
        if not commented(m.start("key"))
    ]
    found.sort(key=lambda c: c.start)
    return found


def parse_value(raw: str) -> ConfigValue:
    """
    The Python value for a PHP literal, preserving the literal's own type.

    Quoted stays ``str``; unquoted ``true``/``false`` become ``bool``; unquoted
    integers become ``int``; unquoted decimals become ``float``; anything else is
    returned as raw source text (ADR-0010).
    """
    text = raw.strip()

    if len(text) >= 2 and text.startswith("'") and text.endswith("'"):
        return text[1:-1].replace("\\'", "'").replace("\\\\", "\\")

    lowered = text.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False

    if _INT_RE.match(text):
        return int(text)

    try:
        return float(text)
    except ValueError:
        return text


# What get_value() recognises, and nothing more. A literal is a single-quoted string,
# a double-quoted one with nothing PHP would interpolate or unescape, true/false, or a
# decimal number; octal (017), hex, `1_000`, null and constants are left as
# expressions rather than guessed at.
_SINGLE = r"'(?:[^'\\]|\\.)*'"
_LITERAL = rf"""{_SINGLE}|"[^"\\$]*"|(?i:true|false)|[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?"""
_LITERAL_RE = re.compile(_LITERAL)
_DECIMAL_INT_RE = re.compile(r"[+-]?(?:0|[1-9]\d*)")
_LEADING_ZERO_RE = re.compile(r"[+-]?0\d")
_PHP_INT_MAX = 2**63 - 1
_GETENV_DOCKER_RE = re.compile(
    rf"(?i:getenv_docker)\s*\(\s*(?P<name>{_SINGLE})\s*,\s*(?P<default>{_LITERAL})\s*\)"
)
_GETENV_RE = re.compile(
    rf"(?i:getenv)\s*\(\s*(?P<name>{_SINGLE})\s*\)(?:\s*\?:\s*(?P<default>{_LITERAL}))?"
)


def _literal(text: str) -> ConfigValue | None:
    """The PHP value of a literal ``text``, or ``None`` if it is not one this reads."""
    if not _LITERAL_RE.fullmatch(text):
        return None
    if text[0] in "'\"":
        return text[1:-1] if text[0] == '"' else parse_value(text)
    lowered = text.lower()
    if lowered in ("true", "false"):
        return lowered == "true"
    if _LEADING_ZERO_RE.match(text) and not text.lstrip("+-").startswith(("0.", "0e", "0E")):
        return None  # 017 is octal to PHP
    if _DECIMAL_INT_RE.fullmatch(text):
        number = int(text)
        # PHP reads an integer literal past PHP_INT_MAX as a float.
        return float(number) if abs(number) > _PHP_INT_MAX else number
    return float(text)


def read_value(raw: str) -> ConfigValue | EnvLookup | Expression:
    """
    What a value is: a literal's PHP value, an environment lookup, or an expression.

    Never evaluates anything. A shape this does not recognise exactly is an
    :class:`Expression`, so a caller can refuse it rather than act on a guess.
    """
    text = raw.strip()
    literal = _literal(text)
    if literal is not None:
        return literal
    shapes: tuple[tuple[EnvFunction, re.Pattern[str]], ...] = (
        ("getenv_docker", _GETENV_DOCKER_RE),
        ("getenv", _GETENV_RE),
    )
    for function, pattern in shapes:
        m = pattern.fullmatch(text)
        if m is None:
            continue
        name = parse_value(m.group("name"))
        default = None if m.group("default") is None else _literal(m.group("default"))
        if isinstance(name, str) and name:
            return EnvLookup(name=name, default=default, function=function)
    return Expression(source=text)


def render_value(key: str, value: ConfigValue) -> str:
    """The PHP literal for ``value``. Raises :class:`ConfigValueError` otherwise."""
    # bool before int: bool is a subclass of int.
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        # repr() gives `nan` and `inf`, which PHP 8 reads as undefined constants:
        # a fatal error. Read-back cannot catch it -- `nan` round-trips.
        if not math.isfinite(value):
            raise ConfigValueError(
                key=key, value_type="float", reason="there is no PHP literal for a non-finite float"
            )
        return repr(value)
    if isinstance(value, str):
        escaped = value.replace("\\", "\\\\").replace("'", "\\'")
        return f"'{escaped}'"
    raise ConfigValueError(key=key, value_type=type(value).__name__)


def render_define(key: str, value: ConfigValue) -> str:
    """The whole ``define(...);`` statement for ``key``."""
    return f"define('{key}', {render_value(key, value)});"


def render_variable(key: str, value: ConfigValue) -> str:
    """The whole ``$key = ...;`` assignment."""
    return f"${key} = {render_value(key, value)};"


def render_statement(kind: Kind, key: str, value: ConfigValue) -> str:
    """The whole statement for ``key``, in whichever shape ``kind`` names."""
    if kind == "define":
        return render_define(key, value)
    return render_variable(key, value)


class WpConfigString:
    """
    Read and write ``define()`` constants in ``wp-config.php`` content.

    Args:
        content: The string content of a ``wp-config.php`` file.
    """

    def __init__(self, content: str) -> None:
        self._content = content

    @property
    def content(self) -> str:
        """The current content, including any changes made by :meth:`set`."""
        return self._content

    def get(self, key: str) -> ConfigValue | MissingType:
        """
        The value of the ``define()`` constant ``key``, or :data:`MISSING`.

        A key defined as ``false``, ``0`` or ``''`` is present and falsy, so test
        ``result is MISSING`` rather than truthiness.
        """
        return self._get("define", key)

    def set(self, key: str, value: ConfigValue) -> bool:
        """
        Set the ``define()`` constant ``key``, adding it if absent.

        Returns ``True`` if the content changed. Raises :class:`ConfigValueError`
        for an unrenderable value -- identically whether the key exists or not.
        """
        return self._set("define", key, value)

    def get_variable(self, key: str) -> ConfigValue | MissingType:
        """
        The value of the file-scope variable ``key`` (named without its ``$``).

        ``$table_prefix`` is the one WordPress requires; a non-default prefix
        means site metadata is not in ``wp_options`` (ADR-0010, handoff 5b).
        """
        return self._get("variable", key)

    def set_variable(self, key: str, value: ConfigValue) -> bool:
        """Set the file-scope variable ``key`` (named without its ``$``)."""
        return self._set("variable", key, value)

    def get_value(self, key: str) -> ConfigValue | EnvLookup | Expression | MissingType:
        """
        The ``define()`` constant ``key``: a literal, an :class:`EnvLookup`, an
        :class:`Expression`, or :data:`MISSING`.

        Unlike :meth:`get`, an expression is never returned as a ``str`` that could be
        mistaken for a literal.
        """
        return self._read("define", key)

    def get_variable_value(self, key: str) -> ConfigValue | EnvLookup | Expression | MissingType:
        """The file-scope variable ``key``, read as :meth:`get_value` reads a constant."""
        return self._read("variable", key)

    def get_source(self, key: str) -> str | MissingType:
        """The value of the ``define()`` constant ``key`` exactly as written, or :data:`MISSING`."""
        return self._raw("define", key)

    def get_variable_source(self, key: str) -> str | MissingType:
        """The value of the file-scope variable ``key`` exactly as written, or :data:`MISSING`."""
        return self._raw("variable", key)

    def _raw(self, kind: Kind, key: str) -> str | MissingType:
        for constant in scan(self._content):
            if constant.kind == kind and constant.key == key:
                return constant.raw_value
        return MISSING

    def _read(self, kind: Kind, key: str) -> ConfigValue | EnvLookup | Expression | MissingType:
        raw = self._raw(kind, key)
        return raw if isinstance(raw, MissingType) else read_value(raw)

    def _get(self, kind: Kind, key: str) -> ConfigValue | MissingType:
        for constant in scan(self._content):
            if constant.kind == kind and constant.key == key:
                return parse_value(constant.raw_value)
        return MISSING

    def _set(self, kind: Kind, key: str, value: ConfigValue) -> bool:
        if not (isinstance(key, str) and _IDENTIFIER_RE.fullmatch(key)):
            raise ConfigKeyError(
                key=repr(key), reason="not a PHP identifier ([A-Za-z_][A-Za-z0-9_]*)"
            )
        # Render first, so an unrenderable value fails the same way on both paths.
        rendered = render_value(key, value)

        for constant in scan(self._content):
            if constant.kind != kind or constant.key != key:
                continue
            if constant.raw_value == rendered:
                _log.debug("%r is already up to date.", key)
                return False
            self._content = (
                self._content[: constant.start] + rendered + self._content[constant.end :]
            )
            _log.debug("%r updated.", key)
            return True

        opening = _PHP_OPEN_RE.search(self._content)
        if opening is None:
            raise ConfigWriteError(
                filename="<string>",
                reason=f"no {_PHP_OPEN!r} opening tag to insert after",
                key=key,
            )

        statement = render_statement(kind, key, value)
        # After the FIRST opening tag only: a file carrying two `<?php` markers
        # must not receive two copies of the statement.
        at = opening.end()
        self._content = self._content[:at] + statement + opening.group(1) + self._content[at:]
        _log.debug("%r added.", key)
        return True
