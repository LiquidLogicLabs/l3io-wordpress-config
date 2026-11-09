"""
Read-back verification over rendered text (ADR-0010).

Pure. The comparison is on the rendered ``define()`` text, never on values
round-tripped through ``get()``: the parser deliberately does not round-trip
every literal, so a value comparison reports a mismatch for correct input -- an
all-digit password being the ordinary case.
"""

from __future__ import annotations

from collections import Counter

from l3io.wp.config.core.config_string import Constant, Kind, SourceText, render_value, scan
from l3io.wp.config.domain.values import ConfigValue

__all__ = ["verify_write"]


def verify_write(
    *,
    before: str,
    actual: str,
    written: dict[tuple[Kind, str], ConfigValue | SourceText],
) -> list[str]:
    """
    Check ``actual`` against ``before`` for the writes in ``written``.

    Asserts all three of ADR-0010's properties and returns a list of
    human-readable problems, empty when the write is sound. Values are never
    quoted into a problem string -- one of them may be a credential.

    Args:
        before: Content as it was prior to the write.
        actual: Content as read back afterwards.
        written: What the write intended to set, keyed by ``(kind, key)`` so a
            ``define()`` and a variable of the same name stay distinct.
    """
    problems: list[str] = []
    after_list = scan(actual)
    after: dict[tuple[Kind, str], Constant] = {}
    for constant in after_list:
        after.setdefault((constant.kind, constant.key), constant)

    # 1. No key appears twice. A duplicate means the pattern matched one
    #    occurrence while WordPress would use the other.
    for (kind, key), count in Counter((c.kind, c.key) for c in after_list).items():
        if count > 1:
            problems.append(f"{key!r} ({kind}) appears {count} times")

    # 2. Every constant we wrote carries the value text we intended.
    #
    #    The comparison is on the VALUE text, not the whole statement. A write
    #    replaces only the value span and preserves the file's own formatting, and
    #    WordPress's own sample spaces its statements as `define( 'X', 'y' );`.
    #    Comparing whole statements against a canonical rendering would reject
    #    correct writes to almost every real wp-config.php.
    for (kind, key), value in written.items():
        intended = value.text if isinstance(value, SourceText) else render_value(key, value)
        found = after.get((kind, key))
        if found is None:
            problems.append(f"{key!r} ({kind}) is absent after writing it")
        elif found.raw_value != intended:
            problems.append(f"{key!r} ({kind}) did not round-trip to what was intended")

    # 3. Every constant we did NOT write is byte-identical. A greedy match or a
    #    bad insertion can damage a neighbour, which checking only our own keys
    #    would miss entirely.
    untouched = {(c.kind, c.key): c for c in scan(before) if (c.kind, c.key) not in written}
    for (kind, key), original in untouched.items():
        found = after.get((kind, key))
        if found is None:
            problems.append(f"{key!r} ({kind}) disappeared, and was not written")
        elif found.text != original.text:
            problems.append(f"{key!r} ({kind}) was altered, and was not written")

    return problems
