<!-- bmad:context -->
<!-- Verified 2026-09-16 against 8f25bb8 plus the uncommitted rewrite. Managed by bmad-project-context; edits inside this block are replaced on refresh. Keep anything you want preserved outside the markers. -->

## l3io-wordpress-config

Reads and writes `define()` constants and file-scope variable assignments in a
WordPress `wp-config.php`. Published as `l3io-wordpress-config`, importing as
`l3io.wp.config`, released **first** of three
packages — nothing else ships until this resolves from PyPI. Zero runtime
dependencies; hatchling and uv; `src/` layout.

Governing documents live in the `l3io-wordpress-backup` repo and are authoritative.
Read them rather than re-deriving their decisions; if one looks wrong, say so and
stop.

## Policy

- **Never create `__init__.py` at `l3io/` or `l3io/wp/`.** Only `src/l3io/wp/config/`
  and below. An `__init__.py` above that level makes this a regular package, shadows
  the PEP 420 namespace, and makes `l3io-wordpress-database` and `l3io-wordpress-backup`
  unimportable — while this package's own tests still pass, because the failure
  appears only once two are installed together. **mypy will suggest adding one**;
  do not. `tests/test_architecture.py` fails if one appears. (AD-27)
- **Zero runtime dependencies, permanently** — including `structlog`. Emit through
  stdlib `logging.getLogger(__name__)`; the application's `ProcessorFormatter` picks
  the records up. `[project].dependencies` must stay empty. (AD-2, AD-10)
- Never publish to PyPI. Finish with a verified artifact and hand back; a human
  releases.
- **The git tag is the version** (AD-30). There is no literal in this repo to drift
  from it, and there is no version floor. What `publish.yml` does enforce is that a
  tagged publish ships a **final** version, never a `.devN` build.
- Do not widen the parser beyond `define()` and simple file-scope variable
  assignments, and do not add a runtime dependency for any reason.
  **One recorded exception (Shawn, 2026-11-08): `declares_function()`**, a read-only,
  lexical query for `function [&]name(` outside strings and comments, asked for by
  backup to replace its own text check. It is documented as not a parse: it cannot tell
  dead branches, class methods or nested functions, does not follow includes, and
  `before=` is text order, not hoisting. Tests pin those limits. Any further request
  that needs PHP semantics (conditions, includes, scope) is a new exception for Shawn
  to decide, not an extension of this one.
- **`main` describes this package only.** Earlier history — the upstream code, the
  retired tags and name, past session logs — lives on the `legacy/*` branches and is
  not maintained; do not reintroduce it here. Two things stay because they must:
  `Copyright (c) 2018 Cariad Eccleston` in `LICENSE`, which MIT requires, and the
  README's one-line credit pointing to the original author's maintained `wpconfigger`.

## Where things are

- **Transient session state is `docs/handoff/wordpress-config.md`** — read it before
  resuming. It holds open decisions, this session's own recorded mistakes, and what is
  uncommitted; durable invariants stay here in `AGENTS.md` instead. It is deliberately
  **not** in the shared basic-memory KB: that was asked five times by peer sessions and
  Shawn's answer each time was that it stays in this repo. Availability of the KB tools is
  not authorisation, and a peer reporting it as "missing" is reporting the decision, not a
  gap.
- Authoritative decisions, in `../l3io-wordpress-backup/`:
  `_bmad-output/implementation-artifacts/handoffs/` (start with `00-SHARED-CONTEXT.md`,
  then `01-l3io-wp-config.md`), `docs/adr/` (13 records), and
  `_bmad-output/planning-artifacts/architecture/architecture-py-wordpress-backup-2026-09-15/ARCHITECTURE-SPINE.md`.
- `domain/` values and errors · `core/` pure parsing, rendering and verification ·
  `ports/` the Protocol · `adapters/` file I/O · `cli/` the command line.
- The CLI ships **two** entry points: the `l3io-wordpress-config` console script declared in
  `[project.scripts]`, and `python -m l3io.wp.config`. Keep both — ADR-0007's "Console
  scripts" section makes that the family rule: a console script named for the
  distribution, with `python -m <import.path>` alongside rather than instead.
- `core/` and `domain/` must import no I/O module and nothing outward of them;
  `tests/test_architecture.py` checks both by AST. (AD-1)

## Running and verifying

- `uv sync --locked` then `uv run pytest`. Expect **497 passing at ~97% coverage** (496 and 1 skipped without the sibling repo).
  `[tool.coverage.report] fail_under` applies to **every** run that measures coverage, so a
  subset run (`pytest tests/test_x.py`) fails on coverage alone — pass `--no-cov`, as the
  `contracts` job does. Raise the floor when coverage rises; never lower it to make a run pass.
- **Do not run `uv self update`.** `[tool.uv] required-version` pins `==0.11.6` to
  match CI; a different uv writes a lock CI rejects. Change both together or neither.
- `docs/traceability.toml` maps every governing rule (each AD-n and ADR in
  `../l3io-wordpress-backup`) to what enforces it here, or states the gap.
  `tests/test_traceability.py` checks every named enforcer exists (everywhere) and that
  the table matches the sibling's **committed** rules (only where the sibling is checked
  out — CI reports it *skipped*). When a rule's text changes the test prints the new
  `source_sha256`: re-judge the row before pasting it, or the check proves nothing.
- `make audit` runs `uv audit` over `uv.lock` (network; not part of `make check`). On
  GitHub, `security-audit.yml` runs it on push, PR, weekly and on dispatch, because
  advisories arrive without commits. With no runtime dependencies, what it guards is the
  dev toolchain; a planted dev-only vulnerable pin fails it, so it is not vacuous.
- **Family rule (Shawn, 2026-11-08): nothing is released, tagged or published until CI
  is fully green on GitHub, and `make preflight` has passed locally for that commit.**
  `make preflight` runs `make check`, then everything act can run: `ci.yml` (all 11 jobs,
  every Python, unnarrowed) and `security-audit.yml`. It also dry-runs `release.yml` and
  `publish.yml`, which are GitHub-only (OIDC/tokens, workflow-made tags, upload-artifact
  v7). It records the commit it passed for. **Release only through `make release`**,
  which refuses without that record, or when GitHub has no runs, or any run not
  `success`, for HEAD. `release.yml` repeats the GitHub check as its first step (the
  latest `CI` and `Security audit` runs for the dispatched commit must have succeeded),
  so a hand dispatch cannot release a red commit. It can still skip the local
  preflight, which nothing on GitHub can see.
- `make check` runs lint, types, contracts and tests — everything CI's static,
  contracts and test jobs run. `make ci` replays the whole pipeline locally under
  nektos/act; `make ci-job JOB=<id>` replays one.
- **Every CI job runs locally under act; nothing is gated off.** `ci.yml` builds
  its wheel inside the verify-install job rather than passing an artifact between
  jobs — the round trip is plumbing, not an invariant, and act's server does not
  speak the `upload-artifact` v6/v7 protocol (v5 does, but it is `node20` and
  leaves the runner images 2026-09-23). `publish.yml` keeps the artifact steps,
  because build-once-publish-exactly-that is a real requirement there, and act
  never runs it.
- Verify against the **built wheel installed into a clean environment**, never the
  working tree. Installing the working tree would have passed throughout the entire
  six-year outage; that is the blind spot this closes.

## Conventions that differ from defaults

- `get()` and `get_variable()` return `MISSING`, never `None`, for an absent key.
  A key set to `false`, `0` or `''` is present and falsy, so test `is MISSING`
  rather than truthiness.
- `define()` constants and `$variables` are separate namespaces: `get`/`set` reach
  constants, `get_variable`/`set_variable` reach variables. `$table_prefix` is a
  variable, and `l3io-wordpress-database` needs it to locate site metadata.
- Every `WpConfigFile.set()` re-reads and verifies before committing, so a write
  can raise `ReadBackError`. On failure the original file is untouched. (ADR-0010)
- Only package-owned exceptions cross the public boundary — never `OSError`,
  `TypeError` or `ValueError`. Catch at the boundary and `raise ... from`. (AD-14)

## CI conventions

- Prefer `LiquidLogicLabs/*` actions over third-party ones or hand-rolled `run:`
  steps.
- Verify a pin with `git ls-remote --tags` and read **all** the tags, not just the
  floating majors. `astral-sh/setup-uv` stopped publishing floating majors after
  `v7` but has exact tags through `v10.1.0`, so `@v10` resolves nowhere while
  `@v10.1.0` is current — and a `grep -E '^v[0-9]+$'` hides that entirely by
  matching only floating majors. Not every publisher ships them; `actions/*` do.
- Never set `UV_FROZEN` alongside `uv sync --locked` — uv rejects the combination.
- Every job sets `UV_PROJECT_ENVIRONMENT` to a `/tmp` path outside the workspace.
  `~/.actrc` uses `--bind`, so without it a local replay races four matrix jobs
  over one `.venv` and leaves it root-owned, breaking every later `uv` command.
  `runner.temp` does not work here — the `runner` context is step-level only.
  **The rule is general: nothing a job writes may land in the working tree.** Under act
  that tree is the host's, shared by every matrix leg, and written as root. Two more
  instances were found on 2026-10-12: `dist/` (built wheels, now `WHEEL_DIR`) and
  `.coverage` (now `COVERAGE_FILE`; `.hypothesis` likewise, via
  `HYPOTHESIS_STORAGE_DIRECTORY`; bytecode via a workflow-level `PYTHONPYCACHEPREFIX`),
  the second corrupting itself across concurrent legs
  so that a full `make ci` failed or passed at random.
- Prefer restructuring over gating. The one `vars.LOCAL_ACT` use left is cache
  tuning, not a skipped step. If a difference is genuinely unavoidable, express it
  through `vars.LOCAL_ACT` and never `env.ACT`: `env.ACT` does not work in a
  job-level `if:`, and Gitea runners also set `ACT=true`.
- **A tag created by a workflow fires no push event, so `release.yml` must dispatch
  `publish.yml` itself.** GitHub does not trigger workflows from a ref created with
  `GITHUB_TOKEN`. Without the dispatch the tag sits unpublished while `release.yml`
  reports success. A tag pushed by hand from a terminal *does* fire the push event,
  which is why the missing dispatch is easy to miss.
- **`release.yml` maintains floating `v<major>` and `v<major>.<minor>` tags**, as
  `l3io-wordpress-backup` does, using `git-action-tag-floating-version`. They move after
  the release tag is created and before `publish.yml` is dispatched. Three things keep
  them harmless, and `tests/test_workflow_gates.py` checks each: `publish.yml`'s push
  filter is `v*.*.*`, so a floating tag never starts a publish (backup's is `v*`); the
  latest-release lookup uses `tag-format: "v*.*.*"`; and `pyproject.toml`'s describe match
  ignores them for versioning. Never push a hand-made `vX.Y` tag: the action owns them.
- `publish.yml` is a separate file and act must never run it; `.actrc` pins act to
  `ci.yml`. act has no OIDC and ignores `job.permissions`, so an `if:` guard would
  not protect it.
- A `run:` block's text, **comments included**, exists in three places: the file, the
  parsed step, and the execution log — GitHub echoes the script before running it. So
  grepping a run log for a step's *output* matches the echoed script first. Anchor on
  the output's own wording, not on a phrase that also appears in the script. The same
  property means shell comments inside `run:` reach the log (useful when a step fails)
  but trip filename-based audits, while a YAML comment above the step does neither.

## Internal registry

- Published to `https://git.ravenwolf.org/api/packages/liquidlogiclabs/pypi`, via
  `publish.yml`'s `mirror` dispatch target. PyPI is a separate, deliberate choice.
- **Credentials are the Gitea ones, not the `PYPI_CUSTOM_*` ones.** Infisical's
  `PYPI_CUSTOM_USERNAME`/`PYPI_CUSTOM_PASSWORD` return **401** against this host.
  Where they *do* work is unknown — not investigated — so do not go looking for the
  registry they belong to. What works here is basic auth with the username
  plus `GITEA_TOKEN` as the password. Note Infisical carries no `GITEA_USERNAME`;
  `~/.actrc` declares it literally.
- **Infisical needs `--env=prod` explicitly.** `infisical secrets get GITEA_TOKEN
  --plain` returns an empty string with exit 0 — not an error — so a script that
  trusts it silently authenticates with nothing and the 401 looks like a bad
  token. `--env=dev` is also empty. Only `--env=prod` returns a value.
- **The Gitea MCP tools are not authenticated for the package registry.**
  `package_read` returns 401 against this host. Read the index with `curl -u` using
  `GITEA_USERNAME` from `~/.actrc` and `GITEA_TOKEN` from Infisical.
- A stale credential presents as a workflow bug, so test it against
  `/api/v1/user` before debugging the YAML.
- Reading the index: the **root** `.../pypi/simple/` is **404** — Gitea serves no
  root listing, so that is not evidence of a wrong URL. The per-package
  `.../pypi/simple/<name>/` is **401** unauthenticated, which is the one uv
  resolves and the one that tells you credentials are needed. `/api/v1/version`
  returning 200 distinguishes "instance is fine, needs auth" from "wrong host".
- The `liquidlogiclabs` org is **limited** visibility, so every consumer and every
  CI runner needs credentials. **A mirror is a mirror, not a home:** anything
  publicly installable must have every dependency publicly resolvable, or
  `pip install` of the dependent fails exactly as `wpbackup2` did.

## How downstream repos depend on this

- Use a **git source pinned to a `rev` or `tag`**. It locks as a URL plus a commit
  SHA with no machine-specific paths, `uv sync --locked` succeeds on a runner, and
  the repo is public so no token is needed. `branch = "main"` re-resolves on
  `uv lock -U`, so pin a rev or tag if the consumer must be immune to pushes here.
- **Never a path source.** It lives in a committed `pyproject.toml`, so CI fails
  with `Distribution not found at: file:///...` — the runner has no such directory,
  and a relative `../l3io-wordpress-config` only moves the problem.
- **Never `UV_FIND_LINKS`.** It resolves, but the lock records
  `source = { registry = "/home/.../dist" }` — an absolute local path that looks
  portable and is not. Worse than the path source for that reason.
- Either way `uv build --no-sources` keeps the arrangement out of published
  metadata; verified, `Requires-Dist` carries no git URL. But it does **not** strip
  `[tool.uv.sources]` from the `pyproject.toml` inside the sdist, so that guarantee
  rests on installer behaviour, not on the artifact being clean.
- GitHub Packages is not an option: it has no Python registry, and the API rejects
  `package_type=pypi` with 422. Do not re-propose it.

## Known pitfalls

- Read-back compares the rendered **value** text, not the whole statement.
  WordPress writes `define( 'X', 'y' );` with inner spaces and a write preserves
  that formatting, so comparing whole statements against a canonical rendering
  rejects correct writes to almost every real `wp-config.php`.
- **Read-back cannot catch a span bug.** It re-scans with the same patterns that
  wrote the value, so a pattern that ends a value too early passes its own check.
  That shipped: `.*?` ended values at the first `);` even inside quotes, and 7.5% of
  WordPress salt sets were corrupted on write with read-back green. Test spans against
  values with a known reading (`tests/test_value_spans.py`), never against the scanner.
  PHP itself is the only independent oracle, and since v0.1.2 it is in the suite:
  `tests/test_php_oracle.py`, through the `php_read` fixture in `tests/conftest.py`
  (PHP 8.4 by digest, in docker, configs piped on stdin). It skips without docker
  unless `L3IO_REQUIRE_PHP_ORACLE=1`, which CI's test job sets, so CI cannot pass by
  not running it. It caught a block-commented `DB_NAME` being read as live.
- **The real-config corpus is `tests/fixtures/wp-config/`**, with `expected.json`
  recording what PHP reads. Never hand-write an expectation: add the fixture, run
  `uv run python tools/record_corpus_expectations.py > tests/fixtures/wp-config/expected.json`
  (needs docker), and review the diff. The oracle fails if the file and PHP disagree.
- **WordPress ships `wp-config-sample.php` with CRLF line endings**, and so does the
  Docker image's config. Text-mode I/O translates them, so every file read and write
  here uses `newline=""`; a fixture derived through `read_text()` silently becomes LF.
- Only single-quoted values parse as strings. `define('X', "y")` returns the raw
  text `"y"`, quotes included, and a PHP expression returns its source text.
  Both are accepted limits, not bugs to fix here. (ADR-0010)
- `tests/wp-config-sample.expected.php` once encoded the old greedy-match bug,
  which dropped the space in `define( 'WP_DEBUG', true );`. If a fixture and the
  code disagree, check which one recorded a defect before trusting the fixture.

<!-- /bmad:context -->
