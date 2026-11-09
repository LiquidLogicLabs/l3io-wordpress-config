"""
The PHP oracle: PHP 8.4 itself reading ``wp-config.php`` files, in a container.

The scanner's read-back verification re-scans with the scanner's own patterns, so it
cannot catch the scanner's bugs. That shipped twice: salts cut short at the first
``);``, and defines inside block comments read as live. PHP is the only grader that
shares none of the scanner's code.

Skipped when docker is unavailable, unless ``L3IO_REQUIRE_PHP_ORACLE=1``, which turns
the skip into a failure, so a runner that is meant to have docker cannot pass by
silently not running the oracle.
"""

from __future__ import annotations

import io
import json
import os
import shlex
import shutil
import subprocess
import tarfile
from collections.abc import Callable
from typing import Any

import pytest

#: PHP 8.4.27, pinned by digest: a moving tag would let the oracle change under
#: the tests that rely on it.
PHP_IMAGE = "php@sha256:9cf851bc2c1b37c3e59dfd677a3c3e56d485af5a47c93f629424bb039eafcb69"

# Includes the config at file scope, so `$table_prefix` is visible, and reports
# every user constant, the prefix, any output, and every warning or notice. A
# redefined constant is a warning, which is how a duplicate define shows up.
_DUMP = r"""<?php
$__l3io_warnings = [];
set_error_handler(function ($no, $msg) use (&$__l3io_warnings) {
    $__l3io_warnings[] = $msg;
    return true;
});
$_SERVER['HTTP_HOST'] = 'example.com';
ob_start();
include $argv[1];
$__l3io_output = ob_get_clean();
restore_error_handler();
echo json_encode([
    'constants' => (object) (get_defined_constants(true)['user'] ?? []),
    'table_prefix' => $table_prefix ?? null,
    'functions' => get_defined_functions()['user'],
    'output' => $__l3io_output,
    'warnings' => $__l3io_warnings,
], JSON_PRESERVE_ZERO_FRACTION | JSON_INVALID_UTF8_SUBSTITUTE);
"""

# One container for every case; each case is its own PHP process, because a config
# defines functions and constants that a second include in the same process would
# collide with. The empty wp-settings.php satisfies the config's final require.
_LOOP = (
    "mkdir /w && cd /w && tar -x && for d in */; do "
    'printf "%s\\t" "${d%/}"; '
    # Each case's environment, if it has one, in a subshell so it ends with the case.
    '( [ -f "${d}.env" ] && . "./${d}.env"; '
    'php -d display_errors=stdout -d error_reporting=-1 _dump.php "/w/${d}wp-config.php" )'
    " | tr -d '\\n'; echo; done"
)

#: ``php_read(cases, env=None, files=None)``. ``env`` gives a case its environment;
#: ``files`` adds files beside its config, at ``/w/<case>/<name>`` in the container.
PhpRead = Callable[..., dict[str, dict[str, Any]]]


def _docker_works() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        probe = subprocess.run(
            ["docker", "info", "--format", "{{.ServerVersion}}"],  # noqa: S607 - docker from PATH
            capture_output=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return probe.returncode == 0


def _archive(
    cases: dict[str, bytes],
    env: dict[str, dict[str, str]] | None = None,
    files: dict[str, dict[str, bytes]] | None = None,
) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:

        def add(name: str, data: bytes) -> None:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))

        add("_dump.php", _DUMP.encode())
        for case, content in cases.items():
            add(f"{case}/wp-config.php", content)
            add(f"{case}/wp-settings.php", b"<?php\n")
            exports = "".join(
                f"export {name}={shlex.quote(value)}\n"
                for name, value in (env or {}).get(case, {}).items()
            )
            if exports:
                add(f"{case}/.env", exports.encode())
            for name, data in (files or {}).get(case, {}).items():
                add(f"{case}/{name}", data)
    return buffer.getvalue()


@pytest.fixture(scope="session")
def php_read() -> PhpRead:
    """Read each ``{case name: wp-config.php bytes}`` with PHP; return what PHP saw."""
    if not _docker_works():
        if os.environ.get("L3IO_REQUIRE_PHP_ORACLE") == "1":
            pytest.fail("L3IO_REQUIRE_PHP_ORACLE=1, but docker is not usable here")
        pytest.skip("the PHP oracle needs docker")

    def read(
        cases: dict[str, bytes],
        env: dict[str, dict[str, str]] | None = None,
        files: dict[str, dict[str, bytes]] | None = None,
    ) -> dict[str, dict[str, Any]]:
        bad = [name for name in cases if not name or "/" in name or name.startswith(".")]
        if bad:
            msg = f"case names must be plain directory names: {bad}"
            raise ValueError(msg)
        done = subprocess.run(  # noqa: S603 - fixed argv; the configs arrive on stdin
            ["docker", "run", "--rm", "-i", "--network", "none", PHP_IMAGE, "sh", "-c", _LOOP],  # noqa: S607
            input=_archive(cases, env, files),
            capture_output=True,
            timeout=600,
            check=False,
        )
        if done.returncode != 0:
            msg = f"the PHP container failed ({done.returncode}): {done.stderr.decode()[-2000:]}"
            raise AssertionError(msg)
        seen: dict[str, dict[str, Any]] = {}
        for line in done.stdout.decode("utf-8", "replace").splitlines():
            name, _, report = line.partition("\t")
            try:
                seen[name] = json.loads(report)
            except json.JSONDecodeError:
                msg = f"PHP could not read case {name!r}: {report[:2000]}"
                raise AssertionError(msg) from None
        missing = sorted(cases.keys() - seen.keys())
        if missing:
            msg = f"PHP reported nothing for {missing}"
            raise AssertionError(msg)
        return seen

    return read
