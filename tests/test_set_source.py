"""``set_source()``: write a value's PHP source verbatim, or refuse it.

``set()`` writes a ``str`` as a quoted literal, so the Docker image's
``getenv_docker('WORDPRESS_DB_HOST', 'mysql')`` copied with ``get``/``set`` became a
database named after that text. ``set_source()`` writes source as source. Since this is
not a PHP parser, it refuses anything that could end the statement, open a comment,
leave PHP or unbalance a bracket, and anything ``get_source()`` would not read back
identically. ``tests/test_php_oracle.py`` has PHP grade copies between real configs.
"""

import pytest

from l3io.wp.config import (
    ConfigKeyError,
    ConfigValueError,
    EnvLookup,
    ReadBackError,
    WpConfigFile,
    WpConfigString,
)

DOCKER = "getenv_docker('WORDPRESS_DB_HOST', 'mysql')"
TARGET = "<?php\ndefine( 'DB_HOST', 'localhost' );\n$table_prefix = 'wp_';\n"


def test_an_existing_define_takes_the_source_verbatim():
    config = WpConfigString(TARGET)
    assert config.set_source("DB_HOST", DOCKER) is True
    assert config.content == f"<?php\ndefine( 'DB_HOST', {DOCKER} );\n$table_prefix = 'wp_';\n"
    assert config.get_source("DB_HOST") == DOCKER
    assert config.get_value("DB_HOST") == EnvLookup("WORDPRESS_DB_HOST", "mysql", "getenv_docker")


def test_an_absent_define_is_added_with_the_source():
    config = WpConfigString(TARGET)
    config.set_source("DB_NAME", "getenv('DB') ?: 'wp'")
    assert config.get_source("DB_NAME") == "getenv('DB') ?: 'wp'"


def test_a_variable_takes_the_source_too():
    config = WpConfigString(TARGET)
    source = "getenv_docker('WORDPRESS_TABLE_PREFIX', 'wp_')"
    assert config.set_variable_source("table_prefix", source) is True
    assert config.get_variable_source("table_prefix") == source
    config.set_variable_source("site_url", "'https://' . $_SERVER['HTTP_HOST']")
    assert config.get_variable_source("site_url") == "'https://' . $_SERVER['HTTP_HOST']"


def test_the_same_source_is_not_rewritten():
    config = WpConfigString(TARGET)
    assert config.set_source("DB_HOST", "'localhost'") is False


def test_copying_get_source_between_configs_is_exact():
    """The case this exists for: carry the target's DB_* into another config."""
    source = WpConfigString(
        f"<?php\ndefine( 'DB_HOST', {DOCKER} );\ndefine('A', __DIR__ . '/x');\n"
    )
    target = WpConfigString(TARGET)
    for key in ("DB_HOST", "A"):
        copied = source.get_source(key)
        assert isinstance(copied, str)
        target.set_source(key, copied)
        assert target.get_source(key) == source.get_source(key)


@pytest.mark.parametrize(
    "source",
    [
        "'a\\'b'",
        '"two words"',
        "'has ); and ; inside'",
        "'a /* not a comment */ b'",
        "'?> stays a string'",
        "[ 'a' => 1, 'b' => [2, 3] ]",
        "!!getenv_docker('WORDPRESS_DEBUG', '')",
        "defined( 'X' ) ? X : ( 1 + 2 )",
        "-1",
        "true",
    ],
)
def test_sound_sources_are_accepted_and_read_back(source):
    config = WpConfigString(TARGET)
    config.set_source("K", source)
    assert config.get_source("K") == source


@pytest.mark.parametrize(
    "source",
    [
        "",
        "   ",
        " 'leading space'",
        "'trailing space' ",
        "'a'\n",
        "'a' . \r'b'",
        "'unterminated",
        '"unterminated',
        "f(1",
        "f(1))",
        "[1, 2",
        "a ]",
        "'a'; drop()",
        "'a') ; define('EVIL', 1",
        "1 ?> <?php 2",
        "1 /* comment */",
        "1 // comment",
        "1 # comment",
        "`id`",
        "<<<EOT\nx\nEOT",
        "<?php 1",
    ],
)
def test_structurally_unsafe_sources_are_refused(source):
    config = WpConfigString(TARGET)
    with pytest.raises(ConfigValueError) as caught:
        config.set_source("DB_HOST", source)
    assert config.content == TARGET, "nothing is written"
    assert caught.value.key == "DB_HOST"
    if source.strip():
        assert source.strip() not in str(caught.value), "a source is never quoted back"


@pytest.mark.parametrize("bad", [None, 1, b"'x'", ["'x'"]])
def test_a_source_that_is_not_text_is_refused(bad):
    with pytest.raises(ConfigValueError):
        WpConfigString(TARGET).set_source("DB_HOST", bad)


def test_a_key_must_be_an_identifier():
    with pytest.raises(ConfigKeyError):
        WpConfigString(TARGET).set_source("not a key", "'x'")


# ---- through the file adapter: the same verified write as set() -----------------


def test_the_file_adapter_writes_and_verifies_the_source(tmp_path):
    path = tmp_path / "wp-config.php"
    path.write_bytes(TARGET.replace("\n", "\r\n").encode())
    config = WpConfigFile(path)
    assert config.set_source("DB_HOST", DOCKER) is True
    assert config.set_variable_source("table_prefix", "getenv('P') ?: 'wp_'") is True
    after = path.read_bytes()
    assert b"define( 'DB_HOST', " + DOCKER.encode() + b" );\r\n" in after
    assert b"$table_prefix = getenv('P') ?: 'wp_';\r\n" in after
    assert WpConfigFile(path).get_source("DB_HOST") == DOCKER


def test_the_file_adapter_refuses_before_touching_the_file(tmp_path):
    path = tmp_path / "wp-config.php"
    path.write_text(TARGET)
    with pytest.raises(ConfigValueError):
        WpConfigFile(path).set_source("DB_HOST", "'a'); evil(")
    assert path.read_text() == TARGET
    assert list(tmp_path.iterdir()) == [path]


def test_a_damaged_file_is_refused_by_read_back(tmp_path):
    path = tmp_path / "wp-config.php"
    path.write_text(TARGET + "define('DB_HOST', 'again');\n")
    with pytest.raises(ReadBackError):
        WpConfigFile(path).set_source("DB_HOST", DOCKER)
