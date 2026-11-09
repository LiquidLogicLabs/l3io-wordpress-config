"""PHP 8.4 grades the scanner: what the package reads and writes is what PHP runs.

Read-back re-scans with the scanner's own patterns, so it cannot see the scanner's
bugs. Two shipped that way: salts cut short at the first ``);``, and defines inside
a block comment read as live. Every check here asks PHP instead. The ``php_read``
fixture in ``conftest.py`` skips without docker, or fails under
``L3IO_REQUIRE_PHP_ORACLE=1``.
"""

from __future__ import annotations

import json
import random
from collections.abc import Callable
from typing import Any

from tests.test_real_configs import CASES, EXPECTED, rewrite

from l3io.wp.config import (
    ConfigWriteError,
    EnvLookup,
    Expression,
    MissingType,
    ReadBackError,
    WpConfigString,
)
from l3io.wp.config.core.config_string import render_value
from l3io.wp.config.domain.values import ConfigValue

RANDOM_CASES = 300

# Dense in what has broken this scanner or could: quotes and escapes, the `);` and
# `;` that ended values early, comment markers, PHP's `$` and `?>`, and non-ASCII.
_ALPHABET = "abcXYZ019 _-.:/'\\\"();,#*?<>$@!%&=+[]{}|~`^\té€✓"


def _same(php: Any, ours: ConfigValue) -> bool:
    """Equal, and the same PHP type: `true` is not `1`, and `1` is not `1.0`."""
    return type(php) is type(ours) and php == ours


def _problems(case: str, seen: dict[str, Any]) -> list[str]:
    expected = EXPECTED[case]
    constants: dict[str, Any] = seen["constants"]
    out = [f"{case}: PHP warned: {w}" for w in seen["warnings"]]
    out += [
        f"{case}: {key} is {constants.get(key, '<undefined>')!r} to PHP, {value!r} expected"
        for key, value in expected["values"].items()
        if key not in constants or not _same(constants[key], value)
    ]
    out += [f"{case}: PHP does not define {key}" for key in expected["raw"] if key not in constants]
    out += [
        f"{case}: PHP defines {key}, expected absent"
        for key in expected["absent"]
        if key in constants
    ]
    unread = constants.keys() - expected["values"].keys() - expected["raw"].keys()
    out += [f"{case}: PHP defines {key}, which the package does not read" for key in sorted(unread)]
    if seen["table_prefix"] != expected["table_prefix"]:
        out.append(f"{case}: $table_prefix is {seen['table_prefix']!r} to PHP")
    return out


def test_the_expectations_are_what_php_reads(php_read):
    """expected.json, which the docker-free tests rely on, is PHP's reading, not ours."""
    seen = php_read(CASES)
    assert [p for case in CASES for p in _problems(case, seen[case])] == []


def test_php_reads_every_rewrite_where_the_package_wrote_it(php_read):
    rewrites = {case: rewrite(case) for case in CASES}
    before = php_read(CASES)
    after = php_read({case: content for case, (content, _, _) in rewrites.items()})
    problems: list[str] = []
    for case, (_content, written, prefix) in rewrites.items():
        seen = after[case]
        constants = seen["constants"]
        problems += [f"{case}: PHP warned: {w}" for w in seen["warnings"]]
        problems += [
            f"{case}: wrote {key}={value!r}, PHP reads {constants.get(key, '<undefined>')!r}"
            for key, value in written.items()
            if key not in constants or not _same(constants[key], value)
        ]
        # Literals only: an expression such as `WP_HOME . '/content'` rightly follows
        # a constant that was written.
        problems += [
            f"{case}: {key} changed, and it was not written"
            for key, value in before[case]["constants"].items()
            if key not in written
            and key not in EXPECTED[case]["raw"]
            and constants.get(key) != value
        ]
        if EXPECTED[case]["table_prefix_literal"] and seen["table_prefix"] != prefix:
            problems.append(
                f"{case}: wrote $table_prefix={prefix!r}, PHP reads {seen['table_prefix']!r}"
            )
    assert problems == []


def _random_text(rng: random.Random) -> str:
    return "".join(rng.choice(_ALPHABET) for _ in range(rng.randint(0, 40)))


def test_random_writes_land_as_php_reads_them(php_read):
    """Whenever ``set()`` returns, PHP reads exactly what was written.

    300 configs, from WordPress's sample in both line endings. A write the package
    refuses is allowed; a write it accepts and PHP reads differently is the defect.
    Seeded, so a failure reproduces.
    """
    rng = random.Random(20261029)  # noqa: S311 - test data, seeded to reproduce, not secrets
    bases = [CASES["wordpress-sample"].decode(), CASES["wordpress-sample-lf"].decode()]
    cases: dict[str, bytes] = {}
    intended: dict[str, tuple[dict[str, ConfigValue], str]] = {}
    for n in range(RANDOM_CASES):
        config = WpConfigString(bases[n % 2])
        values: dict[str, ConfigValue] = {
            "DB_PASSWORD": _random_text(rng),
            "AUTH_KEY": _random_text(rng),
            "WP_DEBUG": rng.random() < 0.5,
            "WP_POST_REVISIONS": rng.randint(-(2**63), 2**63 - 1),
            "WP_REDIS_TIMEOUT": rng.uniform(-1e6, 1e6),
            "L3IO_RANDOM": _random_text(rng),
        }
        prefix = _random_text(rng)
        try:
            for key, value in values.items():
                config.set(key, value)
            config.set_variable("table_prefix", prefix)
        except (ConfigWriteError, ReadBackError):  # pragma: no cover - none today
            continue
        cases[f"r{n:03d}"] = config.content.encode()
        intended[f"r{n:03d}"] = (values, prefix)
    assert len(cases) == RANDOM_CASES, "every random write was accepted"

    seen = php_read(cases)
    problems = [
        f"{name}: wrote {key}={value!r}, "
        f"PHP reads {seen[name]['constants'].get(key, '<undefined>')!r}"
        for name, (values, _) in intended.items()
        for key, value in values.items()
        if not _same(seen[name]["constants"].get(key), value)
    ]
    problems += [
        f"{name}: wrote $table_prefix={prefix!r}, PHP reads {seen[name]['table_prefix']!r}"
        for name, (_, prefix) in intended.items()
        if seen[name]["table_prefix"] != prefix
    ]
    problems += [f"{name}: PHP warned: {w}" for name in cases for w in seen[name]["warnings"]]
    assert problems == [], f"{len(problems)} disagreements, first: {problems[:5]}"


# ---- get_value() and EnvLookup.resolve(), graded by PHP ------------------------

_DOCKER_HELPER = (
    CASES["docker-image"]
    .decode()
    .replace("\r\n", "\n")  # the fixture is CRLF, as the image ships it
    .split("if (!function_exists('getenv_docker')) {", 1)[1]
    .split("\n}\n", 1)[0]
)
#: The official image's own getenv_docker(), copied from the fixture, not rewritten.
DOCKER_HELPER = "if (!function_exists('getenv_docker')) {" + _DOCKER_HELPER + "\n}\n"

_LITERAL_SOURCES = [
    "'plain'",
    r"'it\'s'",
    r"'back\\slash'",
    r"'a\nb'",
    "''",
    '"dq"',
    '""',
    "true",
    "TRUE",
    "false",
    "0",
    "-0",
    "+7",
    "42",
    "-42",
    "017",
    "0x1A",
    "1_000",
    "9223372036854775807",
    "9223372036854775808",
    "-9223372036854775808",
    "3.5",
    "-.5",
    "1.",
    "1e3",
    "2E-2",
    "0.0",
    "null",
    '"has $x"',
]


def test_every_literal_reading_is_phps(php_read):
    """When get_value() says a value is a literal, it is the value PHP defines."""
    body = "".join(f"define('L{i}', {src});\n" for i, src in enumerate(_LITERAL_SOURCES))
    content = f"<?php\n$x = 'X';\n{body}"
    seen = php_read({"literals": content.encode()})["literals"]
    config = WpConfigString(content)
    problems = []
    for i, src in enumerate(_LITERAL_SOURCES):
        ours = config.get_value(f"L{i}")
        if isinstance(ours, Expression | EnvLookup | MissingType):
            continue
        php = seen["constants"].get(f"L{i}")
        if not _same(php, ours):
            problems.append(f"{src}: we read {ours!r}, PHP defines {php!r}")
    assert problems == []
    readings = [config.get_value(f"L{i}") for i in range(len(_LITERAL_SOURCES))]
    assert sum(isinstance(r, Expression) for r in readings) <= 6, "the test reads literals"


def _env_state(rng: random.Random, name: str) -> tuple[dict[str, str], dict[str, bytes]]:
    """A random environment for ``name``: unset, empty, '0', a value, and/or a secret file."""
    env: dict[str, str] = {}
    files: dict[str, bytes] = {}
    choice = rng.choice(["unset", "empty", "zero", "value"])
    if choice != "unset":
        env[name] = {"empty": "", "zero": "0", "value": f"v-{rng.randint(0, 999)}"}[choice]
    file_choice = rng.choice(["none", "none", "empty", "zero", "file"])
    if file_choice in ("empty", "zero"):
        env[f"{name}_FILE"] = "" if file_choice == "empty" else "0"
    elif file_choice == "file":
        ending = rng.choice(["", "\n", "\r\n"])
        files[f"secret_{name}"] = f"from-file-{rng.randint(0, 999)}{ending}".encode()
    return env, files


def test_env_lookups_resolve_as_php_resolves_them(php_read):
    """resolve() gives what PHP defines, for every lookup shape and environment state."""
    rng = random.Random(20261108)  # noqa: S311 - test data, seeded to reproduce
    shapes: list[Callable[[str], str]] = [
        lambda n: f"getenv_docker('{n}', 'fallback')",
        lambda n: f"getenv_docker('{n}', '')",
        lambda n: f"getenv('{n}')",
        lambda n: f"getenv('{n}') ?: 'fallback'",
        lambda n: f"GETENV( '{n}' ) ?: 5",
    ]
    cases: dict[str, bytes] = {}
    env: dict[str, dict[str, str]] = {}
    files: dict[str, dict[str, bytes]] = {}
    expected: dict[str, list[tuple[str, EnvLookup, dict[str, str], dict[str, bytes]]]] = {}
    for n in range(40):
        case = f"e{n:02d}"
        body, case_env, case_files, keys = "", {}, {}, []
        for k, shape in enumerate(shapes):
            name = f"L3IO_E{n}_{k}"
            var_env, var_files = _env_state(rng, name)
            for fname in var_files:
                var_env[f"{name}_FILE"] = f"/w/{case}/{fname}"
            case_env.update(var_env)
            case_files.update(var_files)
            body += f"define('K{k}', {shape(name)});\n"
            keys.append((f"K{k}", var_env, var_files))
        content = f"<?php\n{DOCKER_HELPER}{body}"
        cases[case] = content.encode()
        env[case], files[case] = case_env, case_files
        config = WpConfigString(content)
        expected[case] = []
        for key, var_env, var_files in keys:
            lookup = config.get_value(key)
            assert isinstance(lookup, EnvLookup), (key, lookup)
            expected[case].append((key, lookup, var_env, var_files))

    seen = php_read(cases, env=env, files=files)
    problems = []
    for case, entries in expected.items():
        for key, lookup, var_env, var_files in entries:
            by_path = {f"/w/{case}/{f}": data.decode() for f, data in var_files.items()}
            ours = lookup.resolve(var_env, by_path.__getitem__)
            php = seen[case]["constants"].get(key)
            if not _same(php, ours):
                problems.append(f"{case} {key} {lookup} env={var_env}: ours {ours!r}, PHP {php!r}")
    assert problems == [], f"{len(problems)} disagreements, first: {problems[:5]}"


def test_the_docker_image_resolves_as_php_resolves_it(php_read):
    """The official image's own config, with its WORDPRESS_* environment, end to end."""
    content = CASES["docker-image"]
    config = WpConfigString(content.decode())
    environ = {
        "WORDPRESS_DB_HOST": "db:3306",
        "WORDPRESS_DB_USER": "wp",
        "WORDPRESS_DB_NAME": "",
        "WORDPRESS_TABLE_PREFIX": "site_",
        "WORDPRESS_DB_PASSWORD_FILE": "/w/docker/db_password",
    }
    secret = b"s3cr3t'\"\n"
    seen = php_read(
        {"docker": content}, env={"docker": environ}, files={"docker": {"db_password": secret}}
    )["docker"]
    read = {"/w/docker/db_password": secret.decode()}.__getitem__
    problems = []
    for key, php in seen["constants"].items():
        ours = config.get_value(key)
        if isinstance(ours, EnvLookup):
            resolved = ours.resolve(environ, read)
            if not _same(php, resolved):
                problems.append(f"{key}: ours {resolved!r}, PHP {php!r}")
        elif not isinstance(ours, Expression):
            problems.append(f"{key}: read as a literal, {ours!r}")
    prefix = config.get_variable_value("table_prefix")
    assert isinstance(prefix, EnvLookup)
    assert prefix.resolve(environ, read) == seen["table_prefix"] == "site_"
    assert problems == []
    assert seen["constants"]["DB_PASSWORD"] == "s3cr3t'\""
    assert isinstance(config.get_value("WP_DEBUG"), Expression)


# ---- set_source(), graded by PHP ------------------------------------------------

_DOCKER_ENV = {
    "WORDPRESS_DB_HOST": "db:3306",
    "WORDPRESS_DB_USER": "wp",
    "WORDPRESS_TABLE_PREFIX": "site_",
    "WORDPRESS_DEBUG": "1",
}


def test_restoring_every_value_from_its_source_is_exact(php_read):
    """Overwrite every key with junk, then restore it with set_source(get_source()).

    PHP must read the original back.
    """
    restored: dict[str, bytes] = {}
    for case, data in CASES.items():
        original = WpConfigString(data.decode())
        config = WpConfigString(data.decode())
        keys = [*EXPECTED[case]["values"], *EXPECTED[case]["raw"]]
        for key in keys:
            config.set(key, "junk")
        for key in keys:
            source = original.get_source(key)
            assert isinstance(source, str)
            config.set_source(key, source)
        prefix = original.get_variable_source("table_prefix")
        if isinstance(prefix, str):
            config.set_variable("table_prefix", "junk_")
            config.set_variable_source("table_prefix", prefix)
        assert config.content == original.content, f"{case}: not byte-identical"
        restored[f"{case}--restored"] = config.content.encode()
    env = dict.fromkeys([*CASES, *restored], _DOCKER_ENV)
    seen = php_read({**CASES, **restored}, env=env)

    def reading(name: str, directory: str) -> str:
        # __DIR__ differs per case directory; nothing else may.
        return json.dumps(seen[name], sort_keys=True).replace(f"/w/{directory}/", "/w/CASE/")

    problems = [
        f"{case}: PHP reads the restored config differently"
        for case in CASES
        if reading(case, case) != reading(f"{case}--restored", f"{case}--restored")
    ]
    problems += [f"{c}: PHP warned: {w}" for c in restored for w in seen[c]["warnings"]]
    assert problems == []


def test_docker_sources_carried_into_another_config_resolve_as_in_the_original(php_read):
    """Backup's --overwrite-wp-config: the target's DB_* carried into the Archive's config."""
    target = WpConfigString(CASES["docker-image"].decode())
    archived = WpConfigString(CASES["wordpress-sample-lf"].decode())
    for key in ("DB_NAME", "DB_USER", "DB_PASSWORD", "DB_HOST"):
        source = target.get_source(key)
        assert isinstance(source, str)
        archived.set_source(key, source)
    # The archived config must define getenv_docker for those calls; a real one from
    # the same image does. This adds the image's own helper, unchanged.
    carried = archived.content.replace("<?php\n", "<?php\n" + DOCKER_HELPER, 1)
    seen = php_read(
        {"target": CASES["docker-image"], "carried": carried.encode()},
        env={"target": _DOCKER_ENV, "carried": _DOCKER_ENV},
    )
    for key in ("DB_NAME", "DB_USER", "DB_PASSWORD", "DB_HOST"):
        assert seen["carried"]["constants"][key] == seen["target"]["constants"][key], key
    assert seen["carried"]["constants"]["DB_HOST"] == "db:3306"
    assert seen["carried"]["warnings"] == []


def _expression(rng: random.Random, depth: int = 0) -> str:
    """A random valid PHP expression in the shapes real configs use."""
    atoms: list[Callable[[], str]] = [
        lambda: render_value("K", _random_text(rng)),
        lambda: str(rng.randint(-1000, 1000)),
        lambda: rng.choice(["true", "false"]),
        lambda: f"(getenv('L3IO_X{rng.randint(0, 3)}') ?: {render_value('K', _random_text(rng))})",
        lambda: "$_SERVER['HTTP_HOST']",
        lambda: "PHP_INT_SIZE",
    ]
    if depth >= 2:
        return rng.choice(atoms)()
    shapes: list[Callable[[], str]] = [
        lambda: rng.choice(atoms)(),
        lambda: f"{_expression(rng, depth + 1)} . {_expression(rng, depth + 1)}",
        lambda: f"!!{_expression(rng, depth + 1)}",
        lambda: (
            f"( {_expression(rng, depth + 1)} ? {_expression(rng, depth + 1)}"
            f" : {_expression(rng, depth + 1)} )"
        ),
    ]
    return rng.choice(shapes)()


def _top_expression(rng: random.Random) -> str:
    """An expression, or an array of them: arrays appear only at the top, as in real configs."""
    if rng.random() < 0.15:
        return f"[ {_expression(rng, 1)}, 'k' => {_expression(rng, 1)} ]"
    return _expression(rng)


def test_random_expressions_copied_by_set_source_mean_the_same_to_php(php_read):
    rng = random.Random(20261108)  # noqa: S311 - test data, seeded to reproduce
    exprs = [_top_expression(rng) for _ in range(200)]
    original = "<?php\n" + "".join(f"define('E{i}', {e});\n" for i, e in enumerate(exprs))
    copy = WpConfigString(CASES["wordpress-sample-lf"].decode())
    for i, e in enumerate(exprs):
        assert copy.set_source(f"E{i}", e) is True
        assert copy.get_source(f"E{i}") == e
    env = {"L3IO_X0": "zero", "L3IO_X1": "", "L3IO_X2": "0"}
    seen = php_read(
        {"original": original.encode(), "copy": copy.content.encode()},
        env={"original": env, "copy": env},
    )
    assert seen["copy"]["warnings"] == []
    problems = [
        f"E{i} = {e}: original {seen['original']['constants'].get(f'E{i}')!r}, "
        f"copy {seen['copy']['constants'].get(f'E{i}')!r}"
        for i, e in enumerate(exprs)
        if seen["original"]["constants"].get(f"E{i}") != seen["copy"]["constants"].get(f"E{i}")
    ]
    assert problems == [], f"{len(problems)} disagreements, first: {problems[:3]}"
