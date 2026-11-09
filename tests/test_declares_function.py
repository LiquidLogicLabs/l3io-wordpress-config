"""``declares_function()``: a lexical answer to "does this config declare that function?".

Backup's ``--overwrite-wp-config`` carries ``getenv_docker(...)`` values into an
Archive's config, which only works if that config declares ``getenv_docker()``. Its own
check matched a line starting ``function getenv_docker(``, which accepted one inside a
comment or string and refused ``function &getenv_docker(``. This query uses the
scanner's string and comment awareness. It is lexical, not a PHP parse: the last
section pins what it cannot know, so the README's limits are tested, not asserted.
``tests/test_php_oracle.py`` checks it against PHP's own ``function_exists()``.
"""

import pytest
from tests.test_real_configs import CASES

from l3io.wp.config import ConfigKeyError, WpConfigFile, WpConfigString

BODY = "($e, $d) { return getenv($e) ?: $d; }"
USE = "define( 'DB_HOST', getenv_docker('WORDPRESS_DB_HOST', 'mysql') );\n"


def config(*lines: str) -> WpConfigString:
    return WpConfigString("<?php\n" + "".join(lines))


def test_the_docker_images_config_declares_it():
    docker = WpConfigString(CASES["docker-image"].decode())
    assert docker.declares_function("getenv_docker") is True
    assert docker.declares_function("getenv_docker", before="DB_HOST") is True


def test_wordpress_s_own_sample_does_not():
    assert (
        WpConfigString(CASES["wordpress-sample"].decode()).declares_function("getenv_docker")
        is False
    )


@pytest.mark.parametrize(
    "declaration",
    [
        f"function getenv_docker{BODY}\n",
        f"function &getenv_docker{BODY}\n",
        f"function & getenv_docker {BODY}\n",
        f"FUNCTION GetEnv_Docker{BODY}\n",
        f"if (!function_exists('getenv_docker')) {{\n\tfunction getenv_docker{BODY}\n}}\n",
        f"/* note */ function getenv_docker{BODY}\n",
    ],
)
def test_a_declaration_in_code_is_found(declaration):
    assert config(declaration, USE).declares_function("getenv_docker") is True


@pytest.mark.parametrize(
    "decoy",
    [
        f"// function getenv_docker{BODY}\n",
        f"# function getenv_docker{BODY}\n",
        f"/*\nfunction getenv_docker{BODY}\n*/\n",
        f"$doc = 'function getenv_docker{BODY}';\n",
        f'$doc = "function getenv_docker{BODY}";\n',
        "if (function_exists('getenv_docker')) { }\n",
        f"function getenv_docker_v2{BODY}\n",
        f"function my_getenv_docker{BODY}\n",
        "$x = getenv_docker('A', 'b');\n",
    ],
)
def test_a_mention_that_is_not_a_declaration_is_not_found(decoy):
    assert config(decoy, USE).declares_function("getenv_docker") is False


def test_before_compares_with_the_live_define():
    after = config(USE, f"function getenv_docker{BODY}\n")
    assert after.declares_function("getenv_docker") is True
    assert after.declares_function("getenv_docker", before="DB_HOST") is False
    first = config(f"function getenv_docker{BODY}\n", USE)
    assert first.declares_function("getenv_docker", before="DB_HOST") is True


def test_before_ignores_a_commented_out_define():
    content = config(
        "/* define( 'DB_HOST', getenv_docker('X', 'y') ); */\n",
        f"function getenv_docker{BODY}\n",
        USE,
    )
    assert content.declares_function("getenv_docker", before="DB_HOST") is True


def test_before_an_absent_key_is_false():
    assert (
        config(f"function getenv_docker{BODY}\n").declares_function("getenv_docker", before="NOPE")
        is False
    )


@pytest.mark.parametrize("bad", ["", "get env", "1abc", "a-b", None, 3])
def test_a_name_must_be_an_identifier(bad):
    with pytest.raises(ConfigKeyError):
        config(USE).declares_function(bad)


def test_the_file_adapter_answers_the_same(tmp_path):
    path = tmp_path / "wp-config.php"
    path.write_bytes(CASES["docker-image"])
    assert WpConfigFile(path).declares_function("getenv_docker", before="DB_NAME") is True


# ---- what a lexical query cannot know: the README's limits, pinned ---------------


@pytest.mark.parametrize(
    "declaration",
    [
        f"if (false) {{ function getenv_docker{BODY} }}\n",
        f"class Helper {{ function getenv_docker{BODY} }}\n",
        f"function outer() {{ function getenv_docker{BODY} }}\n",
    ],
    ids=["dead-branch", "class-method", "nested-in-a-function"],
)
def test_limit_a_declaration_php_never_makes_is_still_found(declaration):
    """True here, though PHP never declares the function: it is not a parse."""
    assert config(declaration, USE).declares_function("getenv_docker") is True


def test_limit_an_included_file_is_not_followed():
    content = config("require __DIR__ . '/helpers.php';\n", USE)
    assert content.declares_function("getenv_docker") is False


def test_limit_before_is_text_order_not_php_hoisting():
    """PHP hoists an unconditional top-level function; `before` does not."""
    hoisted = config(USE, f"function getenv_docker{BODY}\n")
    assert hoisted.declares_function("getenv_docker", before="DB_HOST") is False
