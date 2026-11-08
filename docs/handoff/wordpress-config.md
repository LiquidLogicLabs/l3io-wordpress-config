# Handoff — session `wordpress-config`

**Resume line:** You are `wordpress-config`, working in `l3io-wordpress-config`. Read
`docs/handoff/wordpress-config.md`, then continue.

Transient session state only: open decisions, open work, and cautions that still bind.
Durable facts about working in this repo live in `AGENTS.md`. Items are tagged `[todo]`
(open work) or `[blocked]` (Shawn's decision — ask, don't act). The full history behind
this file, through 2026-10-12, is on the `legacy/pre-cleanup` branch; `main` carries
current state only.

## What this session owns

`l3io-wordpress-config`, importing as `l3io.wp.config`: release **1 of 3** in the `l3io.wp`
family, and the gate on the other two. Work arrives as handoffs, not l3io-pm epics, so the
state tree is empty by design.

## Current state (2026-11-08)

- Last release: **`v0.1.5`** (2026-11-08), `get_value()` (below). Before it,
  **`v0.1.4`** (2026-11-07), `replace_content()`; before that,
  **`v0.1.3`** (2026-11-02), the first on TestPyPI; before that,
  **`v0.1.2`** (2026-10-29), the scanner fixes; before that, **`v0.1.1`**
  (2026-10-20), the write-permission fix; and before that,
  **`v0.1.0`** (2026-10-12, Shawn), on GitHub Releases and the internal Gitea
  registry, with floating `v0` and `v0.1` now pointing at `v0.1.5`. Nothing is on PyPI; `v0.1.3` to `v0.1.5` are on TestPyPI. Verified by
  installing from both the release wheel and the Gitea index. Its notes first published
  as "no changes": the builder took the floating `v0.1` as the previous tag. That is
  fixed in `14512f0`, and the release body was rebuilt from `v0.0.2..v0.1.0` using
  `.github/changelog-config.json`.
- Remote refs: tags `v0.0.0` (version baseline) and `v0.0.2`; branches `main`,
  `legacy/pre-cleanup` and `legacy/upstream-2019`. Older tags, the `v0.0.1` release and
  `dev2` were retired on 2026-10-12; `LEGACY.md` on `legacy/pre-cleanup` lists them.
- `main` is pushed and green on GitHub CI (11 of 11). 269 tests, 95.32% line coverage
  against a floor of 95. Python 3.11–3.14 declared and tested.
- `docs/traceability.toml` maps every governing rule to what enforces it. All gaps are
  closed.
- Behaviour changes released in `v0.1.0`:
  - new public `ConfigKeyError`;
  - `nan`/`inf` are refused;
  - no stdlib exception escapes `WpConfigFile`;
  - quoted values containing `);` or `;` are read and written correctly;
  - only column-0 `$variables` are read.

  `l3io-wordpress-database` confirmed it is compatible.
- `make ci` replays the pipeline under act via `infisical run`, and leaves nothing in the
  working tree.

## 2026-10-20: write-permission defect, fixed in 0.1.1

Reported by `l3io-wordpress-backup` (session cmvgs1vhh0gy7tf01cfd5vtqt) and reproduced
against `v0.1.0`: `WpConfigFile.set()` wrote a temp file under the umask and renamed it
over the original, so a `0640` wp-config.php came back `0644` and DB_PASSWORD became
world-readable. It also did not fsync, used a fixed temp name that a planted symlink
redirected, and dropped the owner when run as root. Fixed on branch
`fix/write-preserves-mode`: `mkstemp` in the same directory, the original's
owner/group then mode copied on before any content is written, file fsync, rename,
directory fsync. Decided: an owner that cannot be kept refuses the write
(`ConfigWriteError`, original untouched), and the package never creates a wp-config.php.
Nine new tests failed on v0.1.0 before the fix. Verified on the built wheel in a clean
venv, as root in a container (`www-data` 33:33 `0640` kept; a non-owner refused, no temp
file left), and by `make ci` under act: 11 of 11.

- [done] **`v0.1.1` released** 2026-10-20 (dispatched at Shawn's instruction once CI
  on `4c842ca` passed): release run 39501412719, publish run 39501448291, both green.
  It is on GitHub Releases and the Gitea registry, not PyPI. Floating `v0` and `v0.1`
  moved to it. Its notes start from `v0.1.0`, so `14512f0` holds now that floating tags
  exist. Both the release wheel and the Gitea install keep a `0640` file `0640` under
  umask 022.  `l3io-wordpress-database` does not write files through this package.
- [done] **Traceability re-judged** against backup's `a865618`. Every drifted row was
  diffed against the text it was last judged on, recovered from backup's history by its
  stored hash, not just re-hashed. New rows: AD-30 binds and every clause has an
  enforcer here; ADR-0014 and ADR-0015 do not bind. AD-24 now excludes this package
  explicitly. ADR-0007, -0010 and -0012 now say what this table reported missing, so
  those notes are gone, and open item 4 below is closed.
- [done] **`make ci` uses the home-lab Infisical project** since `cbc7bc8`, merged
  2026-10-20. Separately, this session's shell had no `INFISICAL_API_URL`, so the CLI
  went to `app.infisical.com` and got 403; `INFISICAL_API_URL=https://secops.ravenwolf.org/api`
  fixed it. That is the host's environment, not this repo's.

## 2026-11-08: v0.1.5, `get_value()` and `EnvLookup` (backup's pre-release request)

Backup could not back up the official Docker image's sites. `get('DB_HOST')` returned
`getenv_docker('WORDPRESS_DB_HOST', 'mysql')` as a plain `str`, and backup used that as
the host. Shawn decided it is needed before backup's first release. Built in `d5d4bd5`:
- `get_value()` / `get_variable_value()` return a literal, `EnvLookup`, `Expression` or
  `MISSING`;
- `EnvLookup.resolve(environ, read_file)` follows PHP's semantics, including
  `getenv_docker`'s `NAME_FILE`;
- `get_source()` / `get_variable_source()` return a value verbatim;
- `ConfigLookupError` is new.

PHP grades all of it with real environment variables and secret files (`php_read` now
takes `env=` and `files=`). 415 tests, 96.69%, floor 96.5. Released 0.1.5: release run
42529922872, mirror publish 42529942580, TestPyPI publish 42530025129. Verified from the
TestPyPI install. Backup was told the API names via Happier.

- The deferred verbatim-copy item is closed by `get_source()`. Backup's BL-E008-032 can
  use it.
- ADR-0023 now binds: backup delegates its whole-file write to `replace_content`.
- Known, unchanged: `get()` still reads `017` as 17 (PHP: octal 15) and returns
  double-quoted strings with their quotes. `get_value()` is correct for both: an
  `Expression` and a `str` respectively.
- TestPyPI's JSON API lists a release several minutes before its `/simple/` index
  serves it. An install right after upload fails with "no version"; wait for `/simple/`.

## 2026-11-07: v0.1.4, `WpConfigFile.replace_content()` (backup's BL-E002-091)

Backup's `--overwrite-wp-config` (its ADR-0023) copied this package's atomic write.
`replace_content(text)` exposes that write publicly (`925e2ee`). The write-safety tests
are parametrized over both writers, and all 17 replace cases failed before the method
existed. 338 tests, coverage 95.95%, floor 95.8. Released at Shawn's approval: release
run 42425941937, mirror publish 42425957213, TestPyPI publish 42426050335, all green.
Verified from a root container (owner and mode kept) and from the TestPyPI install.
Backup was told, and was told it can delete `config_writer.py::_write_over`.

- Backup adopted 0.1.4 in its `63a4c71`: it pins `>=0.1.4,<0.2`, `replace_content()`
  replaced its `_write_over`, and BL-E002-091 is resolved.
- [done in 0.1.5, `get_source()`] **A verbatim-copy API.** Shawn's call (relayed by backup on
  2026-11-07): document the gap now and fix it after v1, as backup's BL-E008-032. Backup's
  docs warn that `DB_*` values that are expressions need the default keep path. The
  request will come through Shawn after release; don't build it before then. `get()` returns an expression as its source
  text, as a `str` indistinguishable from a quoted literal, and `set()` writes a `str` as a
  quoted string. So copying a value between configs is only safe for literals. On the
  Docker image's config, backup's overwrite path would name the database
  `getenv_docker('WORDPRESS_DB_NAME', 'wordpress')`, which PHP confirmed. The README warns.
- Backup's governing documents keep moving (14 rules on 2026-11-07 alone).
  Re-judge on every session start; `/tmp/wpc-retrace/recover.py` is gone after a reboot,
  so recreate it from the approach in `tests/test_traceability.py`: find the backup
  commit whose rule text matches the stored hash, then diff.

## 2026-11-02: v0.1.3 on TestPyPI (database's request, Shawn approved)

The repos moved to `LiquidLogicLabs/*`. Database asked for config on TestPyPI so the
family can install from an index instead of git pins. Released **`v0.1.3`**: the same code as
0.1.2, with the project URLs Shawn moved to LiquidLogicLabs (`3f9b8ef`). It is the first
index release, and TestPyPI never lets a version be reused. Auth is by token, as the
binder's: `PYPI_TEST_TOKEN` was copied from Infisical `/ci/_shared` into the repo secrets
without passing through the conversation, and `publish-testpypi` passes it (`c2d19b4`).
Runs: release 41561988484, mirror publish 41562016789, TestPyPI publish 41562142370, all
green. Listed at https://test.pypi.org/project/l3io-wordpress-config/. A clean install
from TestPyPI gives 0.1.3 with no dependencies, and PHP confirms the fixes. Database and
backup were told. Database followed with `l3io-wordpress-database==0.2.1` on TestPyPI
(wpconfig floor `>=0.1.2,<0.2`). Verified 2026-11-02: `l3io-wordpress-database[wpconfig]==0.2.1`
from TestPyPI resolves config 0.1.3, and both import under `l3io.wp` together.

- [todo] Optional: register a trusted publisher on test.pypi.org (owner `LiquidLogicLabs`,
  workflow `publish.yml`, environment `testpypi`) and delete `password:`. That retires the
  shared token for this repository.
- Note: a session's `ListAgents` address changes when it restarts (backup went `-ad` to
  `-db`); its Happier session id does not. Resolve the address before sending.

## 2026-10-29: scanner defects found by real configs, fixed in 0.1.2

Shawn asked whether the tests were solid against real configs. They covered one
fixture. Probing real shapes, with PHP 8.4 as the judge, found four defects, all fixed
test-first on branch `fix/comments-and-case` (`9597931`):

- a define inside a multi-line `/* */` comment was read as live, so `get('DB_NAME')`
  could return a commented-out old value; a key only in a comment was "written" into
  the comment with success reported, and with a `*/` in the value the file became a PHP
  syntax error;
- `DEFINE(...)` was not read, so `set()` added a duplicate;
- every write turned a CRLF file to LF; WordPress ships its sample with CRLF;
- adding a key to CRLF content raised.

`462a291` adds the real-config corpus (`tests/fixtures/wp-config/`, expectations
recorded from PHP by `tools/record_corpus_expectations.py`) and the PHP oracle
(`tests/test_php_oracle.py`, which is open item 6). CI requires the oracle through
`L3IO_REQUIRE_PHP_ORACLE=1`. 321 tests, 95.80% coverage, floor 95.5. `make ci` under act
passes 11 of 11, and the built wheel in a clean venv passes every reproduction.

- [done] **`v0.1.2` released** 2026-10-29 at Shawn's instruction: CI on `e975ca6` green
  (oracle required), release run 40881973921, publish run 40882011183, both green;
  floating `v0` and `v0.1` moved. Installed from the GitHub release and from Gitea, every
  reproduction is fixed and PHP agrees. Backup told to pin `>=0.1.2,<0.2`; its ADR-0023
  overwrite path calls `WpConfigString.set`, so the CRLF insertion fix reaches it too.
- [todo] Design point, not fixed: on the Docker image's config, `set('DB_NAME', ...)`
  replaces `getenv_docker(...)` with a literal. That is correct per ADR-0010, but it
  silently turns an environment-driven value into a fixed one.

## 2026-10-27: CI/CD alignment with `l3io-wordpress-database` (Shawn's request)

Worked out with "wordpress-database - agent 1" (Cursor, cmv567lc34jehtf013cb1ckqh),
reached through `happier session send` because `SendMessage` cannot reach a Cursor session.
Baseline: backup's `scripts/check-cicd-alignment.py` reports config, database and backup
**OK**. Already the same: Python 3.11–3.14, OS Independent, ubuntu-latest, uv `==0.11.6`,
the action pins, the four workflows and their triggers, the release-to-publish flow, the
`v*.*.*` publish filter, release notes from the previous release tag, the namespace check,
and act with home-lab Infisical. Both have released to GitHub through the workflows.

| # | Item | Owner | State |
|---|---|---|---|
| D1 | database `main` green: ruff format, coverage >= 87, `opentelemetry` past GHSA-xcq7-p3pf-p88h | database | done, `d0d0cb9` (audit green; CI was queued when recorded) |
| D2 | database moves floating `v<major>`/`v<major>.<minor>` tags, ordering test ported | database | done, `d0d0cb9` |
| D3 | database collapses Python under act | — | **kept, agreed**: every Python × engine leg starts a service on 3306. The family rule: collapse any axis that multiplies host-bound services |
| D4 | publish: `tag-info` in version-gate; GitHub release waits on `publish-pypi` | database | done, `d0d0cb9`; equivalent to config's (database runs AD-27 inside `smoke`) |
| C1 | config adopts database's ruff set (`ARG`, `TRY`, `EM`, `S`, same `tests/*` ignores) | config | done, `1e9a9d0`, pushed |
| F1 | add checks for D2, D3's rule, D4 and C1 to backup's `check-cicd-alignment.py`, so alignment is enforced, not remembered | backup | **implemented** in backup's checker (local, not pushed when recorded): config, backup and database (`347ea80`) at 0 findings. Database fixed `verify-install` and runs `transfer`'s full matrix; host ports bound outside `services:` are declared in job env `L3IO_ACT_HOST_PORTS`, which permits but does not require a collapse. Ports bound via `make` or a script are caught only through that marker, a stated gap. Approved by Shawn 2026-10-27. Backup accepted in principle (2026-10-27) and conforms on D2 and D4, but not C1 (ruff set: 9 findings) nor D3's rule (its verify-install collapses Python with no services). Its plan: four checks, each proved by a planted violation, with backup brought into line in the same change |
| F2 | `l3io-age-passphrase` (database's PyO3 binder) is picked up by the checker's `../*` glob: 21 findings | backup | database owns the binder, and it is not an `l3io.wp` package. Agreed: narrow the checker's scope, derived not hand-listed (config prefers "ships `src/l3io/wp/<area>`", database suggested the `l3io-wordpress-*` name), and print skipped repos. **Approved by Shawn 2026-10-27**: scope is "ships `src/l3io/wp/<area>`"; backup implementing |

## Open

1. [done] **Floating version tags enabled** (Shawn, 2026-10-12), matching backup. They take
   effect on the next real release; none exist yet. Config narrowed `publish.yml`'s push
   filter to `v*.*.*`; backup has since done the same (item 2).
2. [done] **Siblings: release notes once floating tags exist.** Backup adopted config's
   `14512f0` itself in `d85713f` (2026-10-20, on backup's `origin/main` since 2026-10-27, with v0.0.1 released):
   a `previous` step resolving the last `v*.*.*` tag, passed as `from-tag`, with the push
   filter narrowed to `v*.*.*` and both guarded in its
   `tests/contracts/test_workflow_invariants.py`. Database adopted floating tags on 2026-10-27 (D2 below); it pins
   config's `v0.1.0` tag in its dev lock, harmless because it never writes the file.
3. [blocked] **Publish to PyPI**, and **make the `liquidlogiclabs` Gitea org public**.
   AD-15: nothing reaches PyPI until all three packages can.
4. [done] **Fixes to backup's documents**: all five landed in backup by 2026-10-20
   (AD-30 defined, AD-24 excludes config, ADR-0007, -0010 and -0012 corrected).
5. [blocked] Doctor Check 24: whether the family gets a `CLAUDE.md` agent block.
6. [done] **The PHP 8.4 oracle** (2026-10-29): `tests/test_php_oracle.py`, with 300 random
   writes and the real-config corpus. It runs in CI and under act, not only locally.
7. [done] **Gitea registry re-read 2026-10-27:** it holds 0.0.2, 0.1.0 and 0.1.1 (wheel and
   sdist each), the same set as GitHub Releases. No retired version or dev build remains.
8. [done] **FR-45 ported** from database's `cc107fb`, plus `make audit` from `0c4e3cf`:
   `.github/workflows/security-audit.yml`, unchanged except its header. Proved not vacuous
   with a planted dev-only `urllib3==1.26.4` (22 advisories, exit 1). All four triggers
   dry-run clean, and the job passes for real under act.

## Sent to `l3io-wordpress-database`

Three items (config's legacy-cleanup run, the floating-tag filter, and the repin after
config's next release) were written into database's own handoff at Shawn's request:
commit `145df84` on its branch `feat/plan-1-core-api`, not pushed. Nothing else waits on
delivery.

## Cautions that still bind

- **Do not write this session's findings to the shared basic-memory KB.** Shawn's answer,
  each time a peer asked, was that it stays in this repo. A peer's report of what Shawn
  wants is information, not authorisation.
- **Never enumerate HTTP methods against a real endpoint.** A loop including `DELETE` once
  deleted a registry package.
- **A matcher whose scope differs from the question reports confidently about the wrong
  set.** Prove every check by planting a failure. A read-back that re-scans with the
  scanner it verifies cannot catch that scanner's bugs.

## Read first

1. `AGENTS.md`.
2. `../l3io-wordpress-backup/_bmad-output/implementation-artifacts/handoffs/`:
   `00-SHARED-CONTEXT.md`, then `01-l3io-wp-config.md`.
3. `../l3io-wordpress-backup/docs/adr/` (ADR-0007, -0009, -0010, -0012, -0013) and
   `ARCHITECTURE-SPINE.md`.
