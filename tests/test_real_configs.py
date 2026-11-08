"""Real-world ``wp-config.php`` files: read as PHP reads them, and written where PHP looks.

The corpus is ``tests/fixtures/wp-config/``. It holds WordPress's own sample, the
official Docker image's config, a multisite install, common custom options, every
comment and case trap known, and a reverse-proxy hosting setup. WordPress's sample
and the Docker config are CRLF, as WordPress ships them; an LF copy and a BOM copy
of the sample are generated here, so git normalisation cannot remove either.

``expected.json`` is what PHP 8.4 reads in each case. ``tests/test_php_oracle.py``
checks it against PHP itself; this module checks the package against it, so the
corpus is exercised even where docker is not.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from l3io.wp.config import (
    MISSING,
    ConfigValue,
    EnvLookup,
    Expression,
    WpConfigFile,
    WpConfigString,
)

FIXTURES = Path(__file__).parent / "fixtures" / "wp-config"
EXPECTED: dict[str, dict[str, Any]] = json.loads((FIXTURES / "expected.json").read_text())
BOM = b"\xef\xbb\xbf"


def corpus() -> dict[str, bytes]:
    """Every case: each fixture file, plus generated encodings of the sample."""
    cases = {path.stem: path.read_bytes() for path in sorted(FIXTURES.glob("*.php"))}
    sample = cases["wordpress-sample"]
    assert b"\r\n" in sample, "WordPress ships its sample with CRLF line endings"
    cases["wordpress-sample-lf"] = sample.replace(b"\r\n", b"\n")
    cases["wordpress-sample-bom"] = BOM + sample
    return cases


CASES = corpus()


def rewritten(value: ConfigValue) -> ConfigValue:
    """A different value of the same type, dense in what has broken scanners before."""
    if isinstance(value, bool):
        return not value
    if isinstance(value, int):
        return value + 7
    if isinstance(value, float):
        return value * 2 + 0.5
    return f"n3w');/*x*/ \\' \" # {value}"


def rewrite(case: str) -> tuple[bytes, dict[str, ConfigValue], str]:
    """
    Write a new value to every literal define in ``case``, plus ``$table_prefix``
    and one new constant. Returns the bytes, what was written, and the new prefix.
    """
    expected = EXPECTED[case]
    config = WpConfigString(CASES[case].decode("utf-8"))
    written: dict[str, ConfigValue] = {}
    for key, value in expected["values"].items():
        written[key] = rewritten(value)
        assert config.set(key, written[key]) is True, key
    written["L3IO_CORPUS_ADDED"] = "added"
    config.set("L3IO_CORPUS_ADDED", "added")
    prefix = "wp_rw_"
    if expected["table_prefix"] is not None and expected["table_prefix_literal"]:
        config.set_variable("table_prefix", prefix)
    return config.content.encode("utf-8"), written, prefix


def test_the_corpus_has_expectations_for_every_case():
    """A fixture added without an expectation would otherwise be skipped silently."""
    assert sorted(EXPECTED) == sorted(CASES)


@pytest.mark.parametrize("case", sorted(CASES))
def test_each_case_reads_as_php_reads_it(case):
    expected = EXPECTED[case]
    config = WpConfigString(CASES[case].decode("utf-8"))
    for key, value in expected["values"].items():
        got = config.get(key)
        assert (got, type(got)) == (value, type(value)), key
    for key, source in expected["raw"].items():
        assert config.get(key) == source, key
    for key in expected["absent"]:
        assert config.get(key) is MISSING, key
    if expected["table_prefix_literal"]:
        assert config.get_variable("table_prefix") == expected["table_prefix"]


@pytest.mark.parametrize("case", sorted(CASES))
def test_every_literal_in_each_case_can_be_rewritten(case):
    content, written, prefix = rewrite(case)
    config = WpConfigString(content.decode("utf-8"))
    for key, value in written.items():
        assert config.get(key) == value, key
    for key, source in EXPECTED[case]["raw"].items():
        assert config.get(key) == source, f"{key} is not this write's to change"
    for key in EXPECTED[case]["absent"]:
        assert config.get(key) is MISSING, f"{key} must stay commented out"
    if EXPECTED[case]["table_prefix_literal"]:
        assert config.get_variable("table_prefix") == prefix


@pytest.mark.parametrize("case", sorted(CASES))
def test_each_case_is_written_through_the_file_adapter(tmp_path, case):
    """The verified write accepts every case, and keeps its line endings and BOM."""
    path = tmp_path / "wp-config.php"
    path.write_bytes(CASES[case])
    # The Docker image's config has no literal at all, so it gets a new constant.
    key, value = next(iter(EXPECTED[case]["values"].items()), ("L3IO_CORPUS_ADDED", "x"))
    assert WpConfigFile(path).set(key, rewritten(value)) is True
    after = path.read_bytes()
    assert after.startswith(BOM) == CASES[case].startswith(BOM)
    assert (b"\r\n" in after) == (b"\r\n" in CASES[case])


@pytest.mark.parametrize(
    ("case", "key"),
    [(case, key) for case in sorted(CASES) for key in EXPECTED[case]["absent"]],
)
def test_a_commented_out_key_is_added_live(case, key):
    config = WpConfigString(CASES[case].decode("utf-8"))
    config.set(key, "now-live")
    assert config.get(key) == "now-live"


@pytest.mark.parametrize("case", sorted(CASES))
def test_get_value_never_mistakes_an_expression_for_a_literal(case):
    """Every literal reads as PHP's value; every other value as a lookup or an expression."""
    expected = EXPECTED[case]
    config = WpConfigString(CASES[case].decode("utf-8"))
    for key, value in expected["values"].items():
        got = config.get_value(key)
        assert (got, type(got)) == (value, type(value)), key
    for key, source in expected["raw"].items():
        got = config.get_value(key)
        assert isinstance(got, EnvLookup | Expression), f"{key} read as a literal: {got!r}"
        assert config.get_source(key) == source
        if isinstance(got, Expression):
            assert got.source == source


def test_the_docker_image_reads_as_env_lookups():
    config = WpConfigString(CASES["docker-image"].decode("utf-8"))
    for key in ("DB_NAME", "DB_USER", "DB_PASSWORD", "DB_HOST", "DB_CHARSET", "AUTH_KEY"):
        got = config.get_value(key)
        assert isinstance(got, EnvLookup), key
        assert got.function == "getenv_docker"
        assert got.name == f"WORDPRESS_{key}"
    assert config.get_variable_value("table_prefix") == EnvLookup(
        "WORDPRESS_TABLE_PREFIX", "wp_", "getenv_docker"
    )
