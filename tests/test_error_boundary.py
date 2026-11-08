"""AD-14: only package-owned exceptions cross the public boundary.

The surface is derived from ``l3io.wp.config.__all__``: every public class that
is not itself an error, and every public method on it. Each is driven with
hostile arguments and hostile files, and anything raised must descend from
:class:`WpConfigError`. A ``TypeError``, ``ValueError`` or ``OSError`` reaching a
caller forces them to catch a stdlib type to handle our failure -- which is what
AD-14 exists to prevent.

What this does not prove: that a call which *returns* did the right thing. A
value written without raising can still be wrong; that is the parser tests' job.
"""

from __future__ import annotations

import inspect
import itertools
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from l3io.wp import config
from l3io.wp.config import WpConfigError

SAMPLE = "<?php\ndefine( 'DB_NAME', 'wp' );\ndefine('WP_DEBUG', false);\n$table_prefix = 'wp_';\n"

HOSTILE: list[Any] = [
    None,
    object(),
    1,
    1.5,
    float("nan"),
    b"DB_NAME",
    ["DB_NAME"],
    "",
    "DB_NAME",
    "it's",
    "x\ny",
    "a\0b",
    "\udcff",  # a lone surrogate: valid str, unencodable as UTF-8
    {"WORDPRESS_DB_HOST_FILE": "/nonexistent/secret"},  # an environ that needs read_file
    lambda path: 1 / 0,  # a read_file that raises something arbitrary
]


def _public_classes() -> list[type]:
    found = [
        obj
        for name in config.__all__
        if inspect.isclass(obj := getattr(config, name))
        and not issubclass(obj, BaseException)
        and _public_methods(obj)
    ]
    assert found, "no public classes derived from __all__ -- the boundary check is vacuous"
    return found


def _public_methods(cls: type) -> list[str]:
    return [
        name
        for name, member in inspect.getmembers(cls)
        if not name.startswith("_") and inspect.isfunction(member)
    ]


def leak(call: Callable[..., object], *args: Any) -> str | None:
    """None if ``call(*args)`` returns or raises a package-owned error, else what leaked."""
    try:
        call(*args)
    except WpConfigError:
        return None
    except Exception as exc:  # noqa: BLE001 - the point is to catch what leaks
        return f"{type(exc).__name__}: {exc}"
    return None


# ---- how to build each public class, and the states to build it in ------------


def _string_instances(tmp_path: Path) -> list[Any]:
    return [config.WpConfigString(SAMPLE), config.WpConfigString("<?php\n")]


def _file_instances(tmp_path: Path) -> list[Any]:
    path = tmp_path / "wp-config.php"
    path.write_text(SAMPLE, encoding="utf-8")
    return [config.WpConfigFile(path)]


def _lookup_instances(tmp_path: Path) -> list[Any]:
    # Every hostile environ is refused before use; the getenv_docker one is resolved
    # with each hostile read_file too, since a NAME_FILE path is set in environ.
    return [
        config.EnvLookup("WORDPRESS_DB_HOST", "mysql", "getenv_docker"),
        config.EnvLookup("DB_HOST", "localhost", "getenv"),
        config.EnvLookup("DB_HOST"),
    ]


#: Keyed by class. A public class with no entry fails the test below rather than
#: going unexercised, so this mapping cannot fall behind __all__ silently.
FACTORIES: dict[type, Callable[[Path], list[Any]]] = {
    config.WpConfigString: _string_instances,
    config.WpConfigFile: _file_instances,
    config.EnvLookup: _lookup_instances,
}


def test_every_public_class_has_a_factory() -> None:
    missing = [c.__name__ for c in _public_classes() if c not in FACTORIES]
    assert not missing, f"public classes this boundary test cannot build: {missing}"


@pytest.mark.parametrize("cls", _public_classes(), ids=lambda c: c.__name__)
def test_no_public_method_leaks_a_foreign_exception(cls: type, tmp_path: Path) -> None:
    leaks = []
    for method in _public_methods(cls):
        arity = len(inspect.signature(getattr(cls, method)).parameters) - 1
        for args in itertools.product(HOSTILE, repeat=arity):
            for instance in FACTORIES[cls](tmp_path):
                if problem := leak(getattr(instance, method), *args):
                    leaks.append(f"{cls.__name__}.{method}{args!r}: {problem}")
    assert not leaks, "\n".join(leaks[:20])


@pytest.mark.parametrize("cls", _public_classes(), ids=lambda c: c.__name__)
def test_no_constructor_leaks_a_foreign_exception(cls: type) -> None:
    leaks = [f"{cls.__name__}({arg!r}): {p}" for arg in HOSTILE if (p := leak(cls, arg))]
    assert not leaks, "\n".join(leaks)


def _non_utf8(tmp_path: Path) -> Path:
    path = tmp_path / "latin1.php"
    path.write_bytes(b"<?php\ndefine('DB_NAME', 'caf\xe9');\n")
    return path


@pytest.mark.parametrize(
    "make_path",
    [
        lambda tmp: tmp / "absent.php",
        lambda tmp: tmp,
        _non_utf8,
    ],
    ids=["absent", "a-directory", "not-utf8"],
)
def test_a_hostile_file_raises_a_package_owned_error(
    make_path: Callable[[Path], Path], tmp_path: Path
) -> None:
    assert leak(config.WpConfigFile, make_path(tmp_path)) is None


def test_a_file_that_turns_hostile_after_opening_is_reported_as_ours(tmp_path: Path) -> None:
    path = tmp_path / "wp-config.php"
    path.write_text(SAMPLE, encoding="utf-8")
    opened = config.WpConfigFile(path)
    path.write_bytes(b"<?php\n\xff\n")
    assert leak(opened.verify) is None
    path.unlink()
    assert leak(opened.verify) is None


# ---- planted violations ------------------------------------------------------


def test_the_leak_check_reports_a_foreign_exception() -> None:
    def raises_value_error() -> None:
        msg = "planted"
        raise ValueError(msg)

    assert leak(raises_value_error) == "ValueError: planted"


def test_the_leak_check_accepts_a_package_owned_error() -> None:
    def raises_ours() -> None:
        raise config.ConfigReadError(filename="x", reason="planted")

    assert leak(raises_ours) is None
