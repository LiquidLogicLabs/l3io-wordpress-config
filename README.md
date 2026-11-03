# l3io-wordpress-config

Read and write `define()` constants and `$variable` assignments in a WordPress
`wp-config.php` file.

```python
from l3io.wp.config import MISSING, WpConfigFile

config = WpConfigFile("/www/wp-config.php")

config.get("DB_NAME")                  # 'my_blog'
config.get("WP_DEBUG")                 # False  -- present and falsy
config.get("NOT_THERE") is MISSING     # True   -- absent
config.get_variable("table_prefix")    # 'wp_'  -- a $variable, not a define()

config.set("DB_NAME", "my_blog")       # written, read back, and verified
```

## What this is, and what it is not

This is a reader and writer for the **`define()` subset of PHP that WordPress
itself writes**, plus simple file-scope `$variable` assignments. **It is not a
PHP parser and must not be relied on as one.**

Its scope is deliberately bounded, and the boundaries are these:

- Only **single-quoted** string values are parsed as strings. `define('X', "y")`
  returns the raw text `"y"`, quotes included.
- A value must sit on **one line**. A statement spanning lines is not matched.
- `define()` statements must start at the beginning of a line (leading
  whitespace aside), and `$variable` assignments at column 0, which approximates
  file scope: one indented inside a function body is not read. This is what
  makes a commented-out `// define('X', 'y');` correctly invisible.
- Anything inside a `/* ... */` block comment is not read and never written, as
  PHP never runs it. `define` is matched in any case (`DEFINE(...)` is the same
  call to PHP). Heredoc and nowdoc strings are not recognised.
- Quoted strings are read whole, so a `)`, `;` or quote inside one never ends
  the value. WordPress's own salts contain `);` in about one site in thirteen.
- A value that is a **PHP expression** or references another constant is
  returned as its raw source text, not evaluated.
- Adding a constant inserts after the **first** `<?php` opening tag, ending in the
  file's own line ending. A file with no `<?php` followed by a newline cannot have
  one inserted, and raises `ConfigWriteError`.
- Line endings and a UTF-8 BOM are kept as they are: WordPress ships its own
  sample with CRLF, and a write changes the one value, not every line.
- A key written by `set()` or `set_variable()` must be a **PHP identifier**
  (`[A-Za-z_][A-Za-z0-9_]*`); anything else raises `ConfigKeyError` before the
  content is touched.
- `nan`, `inf` and `-inf` have no PHP literal and raise `ConfigValueError`. Written
  as `repr()` gives them, PHP 8 would read them as undefined constants and fail on
  every page load — and read-back cannot catch that, because they round-trip.

The tests read and write a corpus of real configs (WordPress's own sample, the
official Docker image's, multisite, common custom options, commented-out blocks,
and a reverse-proxy setup), and **PHP 8.4 grades them**: what the package reads
and writes is checked against what PHP itself runs, including 300 random writes.

Because those limits are real, **every write is verified**. `WpConfigFile.set()`
writes to a temporary file, reads it back, and checks three things before
committing: the constant written carries the value intended, every constant
*not* written is byte-identical, and no key appears twice. On any mismatch it
raises `ReadBackError` and **the original file is left untouched**.

The write is atomic and keeps who can read the file, which holds `DB_PASSWORD`.
The temporary file has an unpredictable name and is opened exclusively, so nothing
already in the site directory is written through. It takes the original's mode,
owner and group before any content reaches it, and it is synced to disk before it
is renamed over the original, as is the directory after. If the owner cannot be
kept — a writer that is neither root nor the file's owner — the write raises
`ConfigWriteError` and changes nothing, rather than handing the file to the writer.
`WpConfigFile` never creates a `wp-config.php`: a file removed since it was read
raises `ConfigWriteError`.

## Install

```shell
pip install l3io-wordpress-config
```

Requires Python 3.11 or newer. It has **no runtime dependencies**, permanently.

## Absent is not falsy

`get()` and `get_variable()` return the `MISSING` sentinel for a key that is not
defined. A key defined as `false`, `0` or `''` is *present* and falsy. Both are
falsy in a boolean test, so compare identity:

```python
if config.get("WP_DEBUG") is MISSING:
    ...   # not defined at all
```

Values keep the type of the PHP literal: quoted stays `str` (so `'3306'` is the
string `"3306"`, not a number), unquoted `true`/`false` become `bool`, unquoted
integers become `int`, unquoted decimals become `float`.

## Errors

Every failure is a package-owned exception under `WpConfigError`; no `OSError`,
`TypeError` or `ValueError` crosses the public boundary.

| Exception | Raised when |
|---|---|
| `ConfigReadError` | the file cannot be read |
| `ConfigWriteError` | the file cannot be written, or a constant cannot be placed |
| `ConfigKeyError` | a key to write is not a PHP identifier |
| `ConfigValueError` | a value cannot be rendered as a PHP literal |
| `ReadBackError` | verification failed; the file is unchanged |

## Command line

```shell
l3io-wordpress-config --filename /www/wp-config.php --key DB_NAME --value my_blog
l3io-wordpress-config --filename /www/wp-config.php --key DB_NAME
```

Also runnable as `python -m l3io.wp.config`. Exit codes are part of the
interface: `0` success, `1` the key is not defined, `2` the operation failed.
A key defined as `false`, `0` or `''` prints its value and exits `0` — that is
what distinguishes it from a key that is absent.

Flags: `--filename`, `--key`, `--value`, `--set-true`, `--set-false`,
`--log-level`.

## Development

```shell
uv sync --locked
make check      # lint, types, architecture contracts, tests
make ci         # replay the whole CI pipeline locally with nektos/act
```

`uv` is pinned by `[tool.uv] required-version` so the lockfile and CI cannot
drift apart. Do not run `uv self update` without changing that pin and CI
together.

## Credits

Originally derived from [`cariad/py-wpconfigr`](https://github.com/cariad/py-wpconfigr)
by Cariad Eccleston (MIT; see `LICENSE`), whose maintained package is now
[`wpconfigger`](https://pypi.org/project/wpconfigger/). Earlier history is kept on
the `legacy/*` branches and is not maintained.

## Releases

Release notes are built from the commit log at release time and published on the
[GitHub releases page](https://github.com/LiquidLogicLabs/l3io-wordpress-config/releases) — there
is no changelog file to keep in sync, and this section deliberately does not
duplicate one.
