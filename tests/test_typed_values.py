"""``get_value()``: a literal, an environment lookup, or an opaque expression -- never a guess.

``get()`` returns an expression as its source text, a ``str`` no caller can tell from a
quoted literal. The official Docker image defines every ``DB_*`` as
``getenv_docker('WORDPRESS_DB_HOST', 'mysql')``, so backup used that text as the host
name. ``get_value()`` says which of the three a value is, and ``EnvLookup.resolve()``
gives what PHP would define, so a caller never parses or evaluates PHP itself.
``tests/test_php_oracle.py`` checks every reading and resolution against PHP 8.4.
"""

import pytest

from l3io.wp.config import (
    MISSING,
    ConfigLookupError,
    EnvLookup,
    Expression,
    WpConfigFile,
    WpConfigString,
)

DOCKER_HOST = "<?php\ndefine( 'DB_HOST', getenv_docker('WORDPRESS_DB_HOST', 'mysql') );\n"


def value(source: str) -> object:
    return WpConfigString(f"<?php\ndefine('X', {source});\n").get_value("X")


# ---- literals ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("'mysql'", "mysql"),
        (r"'it\'s'", "it's"),
        ("''", ""),
        ('"plain"', "plain"),
        ("true", True),
        ("FALSE", False),
        ("0", 0),
        ("-42", -42),
        ("3.5", 3.5),
        ("-.5", -0.5),
        ("1e3", 1000.0),
        ("9223372036854775807", 9223372036854775807),
        ("9223372036854775808", 9223372036854775808.0),
    ],
)
def test_a_literal_is_its_php_value(source, expected):
    got = value(source)
    assert (got, type(got)) == (expected, type(expected))


@pytest.mark.parametrize(
    "source",
    [
        '"has $interpolation"',
        r'"has \n escape"',
        "017",
        "0x1A",
        "1_000",
        "null",
        "inf",
        "WP_HOME",
        "__DIR__ . '/'",
        "!!getenv_docker('WORDPRESS_DEBUG', '')",
        "getenv_docker('A', 'b') . '/x'",
        "getenv('A', true)",
        "getenv_docker('A')",
        "getenv_docker('A', SOME_CONSTANT)",
        'getenv("A")',
    ],
)
def test_anything_else_is_an_expression_with_its_source(source):
    """Octal, hex and interpolation are PHP readings this package does not attempt."""
    assert value(source) == Expression(source=source)


# ---- environment lookups -------------------------------------------------------


def test_the_docker_image_shape_is_an_env_lookup():
    got = WpConfigString(DOCKER_HOST).get_value("DB_HOST")
    assert got == EnvLookup(name="WORDPRESS_DB_HOST", default="mysql", function="getenv_docker")


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("getenv('DB_HOST')", EnvLookup("DB_HOST", None, "getenv")),
        ("getenv( 'DB_HOST' ) ?: 'localhost'", EnvLookup("DB_HOST", "localhost", "getenv")),
        ("GETENV('P') ?: 3306", EnvLookup("P", 3306, "getenv")),
        ("Getenv_Docker( 'A' , '' )", EnvLookup("A", "", "getenv_docker")),
        ("getenv_docker('A', false)", EnvLookup("A", False, "getenv_docker")),
    ],
)
def test_each_env_shape_is_read(source, expected):
    assert value(source) == expected


def test_a_variable_reads_the_same_way():
    content = "<?php\n$table_prefix = getenv_docker('WORDPRESS_TABLE_PREFIX', 'wp_');\n"
    got = WpConfigString(content).get_variable_value("table_prefix")
    assert got == EnvLookup("WORDPRESS_TABLE_PREFIX", "wp_", "getenv_docker")


def test_absent_is_missing():
    config = WpConfigString(DOCKER_HOST)
    assert config.get_value("NOPE") is MISSING
    assert config.get_variable_value("table_prefix") is MISSING
    assert config.get_source("NOPE") is MISSING


def test_get_is_unchanged():
    """Existing callers keep the source text; only get_value() distinguishes."""
    expected = "getenv_docker('WORDPRESS_DB_HOST', 'mysql')"
    assert WpConfigString(DOCKER_HOST).get("DB_HOST") == expected


# ---- source text, verbatim -----------------------------------------------------


def test_get_source_is_the_value_exactly_as_written():
    config = WpConfigString("<?php\ndefine( 'A', 'x' );\n$p = getenv('P') ?: 'wp_';\n")
    assert config.get_source("A") == "'x'"
    assert config.get_variable_source("p") == "getenv('P') ?: 'wp_'"


def test_the_file_adapter_offers_the_same_reads(tmp_path):
    path = tmp_path / "wp-config.php"
    path.write_text(DOCKER_HOST)
    config = WpConfigFile(path)
    assert config.get_value("DB_HOST") == EnvLookup("WORDPRESS_DB_HOST", "mysql", "getenv_docker")
    assert config.get_source("DB_HOST") == "getenv_docker('WORDPRESS_DB_HOST', 'mysql')"
    assert config.get_variable_value("table_prefix") is MISSING
    assert config.get_variable_source("table_prefix") is MISSING


# ---- resolve(): what PHP would define ------------------------------------------

DOCKER = EnvLookup("WORDPRESS_DB_HOST", "mysql", "getenv_docker")


def _no_reads(path):
    msg = f"read {path}"
    raise AssertionError(msg)


@pytest.mark.parametrize(
    ("environ", "expected"),
    [
        ({}, "mysql"),
        ({"WORDPRESS_DB_HOST": "db:3306"}, "db:3306"),
        ({"WORDPRESS_DB_HOST": ""}, ""),
        ({"WORDPRESS_DB_HOST": "0"}, "0"),
        ({"WORDPRESS_DB_HOST": "db", "WORDPRESS_DB_HOST_FILE": ""}, "db"),
        ({"WORDPRESS_DB_HOST": "db", "WORDPRESS_DB_HOST_FILE": "0"}, "db"),
    ],
)
def test_getenv_docker_uses_the_variable_even_when_empty(environ, expected):
    """`!== false`: a set variable wins, even ''. A `_FILE` of '' or '0' is falsy."""
    assert DOCKER.resolve(environ, _no_reads) == expected


def test_getenv_docker_prefers_the_file_and_strips_its_line_ending():
    environ = {"WORDPRESS_DB_HOST": "ignored", "WORDPRESS_DB_HOST_FILE": "/run/secrets/h"}
    reads = []

    def read(path):
        reads.append(path)
        return "db.internal\r\n\n"

    assert DOCKER.resolve(environ, read) == "db.internal"
    assert reads == ["/run/secrets/h"]


@pytest.mark.parametrize(
    ("lookup", "environ", "expected"),
    [
        (EnvLookup("H", None, "getenv"), {}, False),
        (EnvLookup("H", None, "getenv"), {"H": ""}, ""),
        (EnvLookup("H", "localhost", "getenv"), {}, "localhost"),
        (EnvLookup("H", "localhost", "getenv"), {"H": ""}, "localhost"),
        (EnvLookup("H", "localhost", "getenv"), {"H": "0"}, "localhost"),
        (EnvLookup("H", "localhost", "getenv"), {"H": "db"}, "db"),
        (EnvLookup("H", "localhost", "getenv"), {"H_FILE": "/x"}, "localhost"),
    ],
)
def test_getenv_follows_php(lookup, environ, expected):
    """`?:` falls back on any falsy string, '' and '0' included; plain getenv gives false."""
    assert lookup.resolve(environ, _no_reads) == expected


def test_a_file_lookup_without_a_reader_is_refused():
    with pytest.raises(ConfigLookupError) as caught:
        DOCKER.resolve({"WORDPRESS_DB_HOST_FILE": "/run/secrets/h"})
    assert caught.value.name == "WORDPRESS_DB_HOST"


def test_a_failing_reader_is_a_package_error_and_names_no_secret():
    def broken(path):
        raise OSError(2, "No such file or directory")

    with pytest.raises(ConfigLookupError) as caught:
        DOCKER.resolve({"WORDPRESS_DB_HOST_FILE": "/run/secrets/h"}, broken)
    assert isinstance(caught.value.__cause__, OSError)
    assert "WORDPRESS_DB_HOST_FILE" in str(caught.value)


def test_a_reader_returning_bytes_is_refused():
    with pytest.raises(ConfigLookupError):
        DOCKER.resolve({"WORDPRESS_DB_HOST_FILE": "/s"}, lambda path: b"db\n")  # type: ignore[arg-type,return-value]


@pytest.mark.parametrize("environ", [None, ["A"], "A=1"])
def test_an_environ_that_is_not_a_mapping_is_refused(environ):
    with pytest.raises(ConfigLookupError):
        DOCKER.resolve(environ)


@pytest.mark.parametrize(
    "args",
    [
        (None, None, "getenv"),
        ("", None, "getenv"),
        ("A", None, "putenv"),
        ("A", object(), "getenv"),
    ],
)
def test_an_env_lookup_cannot_be_built_wrong(args):
    with pytest.raises(ConfigLookupError):
        EnvLookup(*args)
