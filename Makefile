# l3io-wordpress-config — local developer entry points.
#
# CI is replayed locally with nektos/act, configured by .actrc plus
# .act.{vars,env,secrets}. The same workflow files run here and on GitHub.
#
# First-time setup:
#   make act-init   copies .act.{vars,env,secrets}.example -> .act.{vars,env,secrets}
#
# `make ci` runs act under `infisical run`, as ADR-0013 specifies and as the
# sibling repositories do. ci.yml itself uses no secrets; the environment is
# needed because ~/.actrc declares them (see ACT_RUNNER below).
#
# Useful targets:
#   make lint         ruff check + format --check
#   make types        mypy --strict
#   make test         pytest
#   make contracts    the architecture gates (AD-27, AD-1, AD-2)
#   make check        lint + types + contracts + test, the whole local gate
#   make audit        uv audit over uv.lock (network; not part of check)
#   make ci           replay the whole CI pipeline locally via act
#   make ci-job JOB=  replay one job, e.g. make ci-job JOB=contracts
#   make ci-dryrun    parse and plan the workflow without running it
#   make build        uv build --no-sources

ACT_FILES := .act.vars .act.env .act.secrets
UV := uv

# ~/.actrc declares secrets as bare `-s NAME`, which act resolves from the
# environment; `infisical run` is what puts them there. act prompts for any
# that are unset OR empty and then fails on a non-interactive terminal, so the
# secrets have to be present even though ci.yml uses none of them. That includes
# GITHUB_TOKEN: an earlier version of this file left it unset on the claim that
# act does not prompt for it, and on 2026-10-12 act 0.2.89 did, failing every
# `make ci-job` outside a TTY.
#
# Do NOT substitute placeholder values. A bogus GITHUB_TOKEN is worse than an
# absent one: act passes it to git as a credential when fetching actions, and
# the fetch fails with "authentication required" instead of proceeding
# anonymously.
#
# Kept identical to l3io-wordpress-database's Makefile. INFISICAL_ENV must be
# prod: `infisical secrets` returns an empty string, exit 0, for any other.
INFISICAL ?= infisical
INFISICAL_PROJECT ?= 7ca0e01b-28f6-4a61-b901-5fe834e1661a
INFISICAL_ENV ?= prod
# This repo's CI leaf in the home-lab project (ADR-0008): /ci/<platform>/<repo>.
INFISICAL_PATH ?= /ci/act/l3io-wordpress-config
ACT_RUNNER ?= $(INFISICAL) run --projectId $(INFISICAL_PROJECT) --env $(INFISICAL_ENV) --path $(INFISICAL_PATH) --
ACT ?= act

.PHONY: help act-init lint format types test contracts namespace-check check audit ci ci-audit preflight ci-job ci-dryrun ci-dryrun-one ci-list build verify-wheel clean

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
	  | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-14s\033[0m %s\n",$$1,$$2}'

# Bootstrap any .act.* file from its .example counterpart on first use.
$(ACT_FILES): %: %.example
	@if [ ! -f $@ ]; then cp $< $@; echo "Created $@ from $<."; fi

act-init: $(ACT_FILES) ## Bootstrap .act.{vars,env,secrets} from .example versions

# Scoped to src and tests, exactly as ci.yml's static job is. If these two ever
# disagree, `make check` stops predicting CI, which is the only thing it is for.
lint: ## ruff lint + format check
	$(UV) run ruff check src tests tools
	$(UV) run ruff format --check src tests tools

format: ## Apply ruff formatting
	$(UV) run ruff format src tests tools
	$(UV) run ruff check --fix src tests tools

types: ## mypy --strict
	$(UV) run mypy

contracts: ## Architecture contract gates (AD-27, AD-1, AD-2)
	$(UV) run pytest tests/test_architecture.py -q --no-cov

namespace-check: ## AD-27: prove the namespace survives a sibling distribution
	$(UV) run python tools/check_namespace_coexistence.py

test: ## Run the test suite
	$(UV) run pytest -q

check: lint types contracts namespace-check test ## Everything CI's static/contracts/test jobs run

audit: ## Scan uv.lock for known vulnerabilities (needs network; not part of check)
	$(UV) audit --locked --preview-features audit

build: ## Build wheel + sdist
	$(UV) build --no-sources

# Builds its own wheel into a temporary directory and asserts there is exactly
# one, rather than taking the newest from dist/: a wheel chosen by mtime or sort
# order from a shared directory can be a stale one, and the check then passes
# over a defect in the wheel just built.
verify-wheel: ## Build a wheel, install it into a clean environment and import it
	@set -eu; \
	tmp=$$(mktemp -d); trap 'rm -rf "$$tmp"' EXIT; \
	$(UV) build --no-sources --wheel --out-dir "$$tmp" >/dev/null; \
	set -- "$$tmp"/*.whl; \
	[ $$# -eq 1 ] && [ -f "$$1" ] || { echo "expected exactly one wheel, built: $$*"; exit 1; }; \
	$(UV) run --isolated --no-project --with "$$1" \
	  python -c "from l3io.wp import config; print('import ok', sorted(config.__all__))"

# ---- local CI replay -------------------------------------------------------

ci: act-init ## Replay the full CI pipeline locally
	$(ACT_RUNNER) $(ACT) push

ci-audit: act-init ## Replay security-audit.yml under act (make ci runs only ci.yml)
	$(ACT_RUNNER) $(ACT) push -W .github/workflows/security-audit.yml

# The family rule (Shawn, 2026-11-08): before any release, tag or publish, run every
# job act can run, across the full matrix, and name what it cannot. Here:
#   act runs     ci.yml (all 11 jobs, py3.11-3.14, unnarrowed) and security-audit.yml;
#   GitHub-only  release.yml and publish.yml. They need OIDC or index tokens, tags
#                made by GITHUB_TOKEN, and upload-artifact v7, which act's artifact
#                server does not speak. `ci-dryrun` resolves every job and action ref
#                in them, and their clean-install jobs run on GitHub at publish.
# A pass is recorded against the commit, and `make release` refuses without it.
PREFLIGHT_STAMP = $(shell git rev-parse --git-path l3io-preflight)

preflight: ## Everything act can run, for this commit; required by make release
	@set -eu; \
	if [ -n "$$(git status --porcelain --untracked-files=no)" ]; then \
	  echo "tracked files are modified: preflight would not be testing the commit"; exit 1; \
	fi; \
	rm -f "$(PREFLIGHT_STAMP)"; \
	$(MAKE) --no-print-directory check; \
	$(MAKE) --no-print-directory ci; \
	$(MAKE) --no-print-directory ci-audit; \
	$(MAKE) --no-print-directory ci-dryrun; \
	git rev-parse HEAD > "$(PREFLIGHT_STAMP)"; \
	echo "preflight passed for $$(git rev-parse --short HEAD). GitHub-only: release.yml, publish.yml (dry-run resolved)."

ci-job: act-init ## Replay one job: make ci-job JOB=contracts
	@test -n "$(JOB)" || { echo "usage: make ci-job JOB=<job-id>"; exit 2; }
	$(ACT_RUNNER) $(ACT) push -j $(JOB)

ci-list: act-init ## List the jobs act can see
	$(ACT_RUNNER) $(ACT) push --list

# ---------------------------------------------------------------------------
# Validating the workflows act CANNOT execute
#
# `make ci` runs ci.yml for real. publish.yml and release.yml are deliberately
# outside it -- act has no OIDC and ignores job.permissions, so running them
# locally would be misleading at best, and release.yml CREATES TAGS and dispatches
# publishes, which must never happen from a laptop.
#
# A dry run is the middle ground and it is worth more than it looks. act resolves
# every `uses:` ref against the remote before deciding to skip the step, so a
# dryrun fails on an action version that does not exist -- it is what catches
# `changelog-parser@v3.0.14`, a real version of a DIFFERENT action, which no
# amount of YAML validation would have found. It also catches expression syntax
# errors, unknown contexts and missing `needs`.
#
# --dryrun IS LOAD-BEARING, not a nicety. Without it this target cuts real tags
# and fires real publishes. A contract test asserts every workflow named here is
# run with it, so removing it fails `make check` rather than surprising someone.
# ---------------------------------------------------------------------------

ACT_DRYRUN_FLAGS ?= --var-file .act.vars --concurrent-jobs 1 --dryrun

# The legs live in .github/act-dryrun-legs.json, not here, because a pytest
# contract asserts they reach every job in every workflow -- and it can only do
# that if both read the same declaration. Hand-listing them in the recipe would
# put the rule and its check in two places, which is how they drift.
#
# ci.yml is NOT dry-run: `make ci` runs it for real, and act SEGFAULTS dry-running
# it (nil pointer in containerReference.GetHealth) because it declares MySQL
# service containers that a dry run never starts. An act limitation, not a defect
# in the workflow.
ACT_DRYRUN_LEGS := .github/act-dryrun-legs.json

ci-dryrun: ## Dry-run the workflows `make ci` cannot run, resolving every action ref
	@set -eu; \
	test -f $(ACT_DRYRUN_LEGS) || { echo "missing $(ACT_DRYRUN_LEGS)"; exit 1; }; \
	legs=$$(python3 -c "import json;[print(l['workflow'],l['event'],l.get('eventpath','-'),','.join(f'{k}={v}' for k,v in (l.get('inputs') or {}).items()) or '-') for l in json.load(open('$(ACT_DRYRUN_LEGS)'))['legs']]"); \
	test -n "$$legs" || { echo "no legs declared -- this gate would pass vacuously"; exit 1; }; \
	rc=0; n=0; \
	echo "$$legs" | while read -r wf ev epath inputs; do \
	  args=""; \
	  [ "$$epath" = "-" ] || args="$$args -e $$epath"; \
	  if [ "$$inputs" != "-" ]; then \
	    for kv in $$(echo "$$inputs" | tr ',' ' '); do args="$$args --input $$kv"; done; \
	  fi; \
	  printf '%-13s %-18s %-26s ' "$$wf" "$$ev" "$$inputs"; \
	  if $(ACT_RUNNER) $(ACT) $(ACT_DRYRUN_FLAGS) -W ".github/workflows/$$wf" $$ev $$args \
	       >$(CURDIR)/.act-dryrun.log 2>&1; then echo "ok"; else \
	    echo "FAILED"; \
	    grep -iE "couldn.t find remote ref|failed to fetch|^Error:|invalid|unable to" $(CURDIR)/.act-dryrun.log \
	      | head -3 | sed 's/^/                                                       /'; \
	    echo fail >> $(CURDIR)/.act-dryrun.rc; \
	  fi; \
	  rm -f $(CURDIR)/.act-dryrun.log; \
	done; \
	if [ -f $(CURDIR)/.act-dryrun.rc ]; then rm -f $(CURDIR)/.act-dryrun.rc; \
	  echo "one or more legs failed"; exit 1; \
	else echo "all legs dry-run clean; every action ref resolved"; fi

ci-dryrun-one: ## Dry-run one workflow: make ci-dryrun-one WF=release.yml
	@test -n "$(WF)" || { echo "set WF, e.g. make ci-dryrun-one WF=release.yml"; exit 1; }
	@case "$(WF)" in \
	  release.yml) ev="workflow_dispatch --input bump=patch" ;; \
	  publish.yml) ev="workflow_dispatch --input target=mirror" ;; \
	  *)           ev="push" ;; \
	esac; \
	$(ACT_RUNNER) $(ACT) $(ACT_DRYRUN_FLAGS) -W .github/workflows/$(WF) $$ev

clean: ## Remove build and cache artifacts
	rm -rf dist build .artifacts .uv-cache .pytest_cache .mypy_cache .ruff_cache
	find . -name '__pycache__' -prune -exec rm -rf {} +

# ---------------------------------------------------------------------------
# Releasing
#
# These targets do NOT compute a version, build, or publish. They dispatch
# release.yml and stop. The version is derived from the git tag by hatch-vcs
# (AD-30), so anything that worked out a version locally would be a second
# implementation of the one thing that must have exactly one.
#
# `make release patch` and `make release BUMP=patch` are the same command. The
# bare words are no-op targets that exist only so make does not fail on the
# second goal.
# ---------------------------------------------------------------------------

GH ?= gh
RELEASE_WORKFLOW ?= release.yml
RELEASE_BRANCH ?= main
BUMP ?=

_BUMP_WORDS := patch minor major dev
_BUMP_GOAL := $(firstword $(filter $(_BUMP_WORDS),$(MAKECMDGOALS)))
_BUMP := $(if $(BUMP),$(BUMP),$(_BUMP_GOAL))

.PHONY: release release-patch release-minor release-major release-dev $(_BUMP_WORDS)

release: ## Cut a release: make release patch|minor|major|dev
	@set -eu; \
	bump="$(_BUMP)"; \
	if [ -z "$$bump" ]; then \
	  echo "usage: make release patch|minor|major|dev   (or make release BUMP=patch)"; \
	  exit 2; \
	fi; \
	case "$$bump" in patch|minor|major|dev) ;; *) echo "unknown bump '$$bump'"; exit 2 ;; esac; \
	command -v $(GH) >/dev/null || { echo "gh is not installed"; exit 1; }; \
	$(GH) auth status >/dev/null 2>&1 || { echo "gh is not authenticated: run 'gh auth login'"; exit 1; }; \
	branch=$$(git rev-parse --abbrev-ref HEAD); \
	if [ "$$branch" != "$(RELEASE_BRANCH)" ]; then \
	  echo "on '$$branch', not '$(RELEASE_BRANCH)' -- release.yml tags whatever it checks out"; exit 1; \
	fi; \
	if [ -n "$$(git status --porcelain --untracked-files=no)" ]; then \
	  echo "tracked files are modified. That work is NOT in the release, and a dirty"; \
	  echo "tree also makes a local build report a different version than the tag."; \
	  git status --short --untracked-files=no; exit 1; \
	fi; \
	git fetch --quiet origin $(RELEASE_BRANCH); \
	if [ "$$(git rev-parse HEAD)" != "$$(git rev-parse origin/$(RELEASE_BRANCH))" ]; then \
	  echo "HEAD and origin/$(RELEASE_BRANCH) differ -- the workflow releases the PUSHED commit,"; \
	  echo "so push or pull first. Local: $$(git rev-parse --short HEAD)  origin: $$(git rev-parse --short origin/$(RELEASE_BRANCH))"; \
	  exit 1; \
	fi; \
	sha=$$(git rev-parse HEAD); \
	if [ "$$(cat "$(PREFLIGHT_STAMP)" 2>/dev/null)" != "$$sha" ]; then \
	  echo "no local preflight for $$(git rev-parse --short HEAD): run 'make preflight' first"; exit 1; \
	fi; \
	runs=$$($(GH) run list --commit "$$sha" --json name,status,conclusion); \
	if [ "$$(echo "$$runs" | jq length)" -eq 0 ]; then \
	  echo "GitHub has no runs for $$sha yet -- CI must have run and passed"; exit 1; \
	fi; \
	red=$$(echo "$$runs" | jq -r '.[] | select(.status != "completed" or .conclusion != "success") | "\(.name): \(.status)/\(.conclusion)"'); \
	if [ -n "$$red" ]; then echo "CI on GitHub is not green for this commit:"; echo "$$red"; exit 1; fi; \
	latest=$$(git tag -l 'v[0-9]*.[0-9]*.[0-9]*' --sort=-v:refname | head -1); \
	echo "  repo         $$($(GH) repo view --json nameWithOwner -q .nameWithOwner)"; \
	echo "  commit       $$(git rev-parse --short HEAD)"; \
	echo "  latest tag   $${latest:-<none: the first release will be v1.0.0>}"; \
	echo "  bump         $$bump"; \
	if [ "$$bump" = "dev" ]; then \
	  echo "  effect       publishes this commit to the internal mirror as <next patch>.dev<distance>; NO tag, NO GitHub release"; \
	else \
	  echo "  effect       pushes the next $$bump tag, which triggers build, smoke, mirror publish and a GitHub release"; \
	fi; \
	printf "\nType the bump to confirm: "; \
	read -r reply; \
	if [ "$$reply" != "$$bump" ]; then echo "aborted"; exit 1; fi; \
	$(GH) workflow run $(RELEASE_WORKFLOW) --ref $(RELEASE_BRANCH) -f bump="$$bump"; \
	echo; \
	echo "dispatched. Watch it with:  $(GH) run watch \$$($(GH) run list --workflow $(RELEASE_WORKFLOW) --limit 1 --json databaseId -q '.[0].databaseId')"

release-patch: ## Release a patch version (alias for: make release patch)
	@$(MAKE) --no-print-directory release BUMP=patch

release-minor: ## Release a minor version
	@$(MAKE) --no-print-directory release BUMP=minor

release-major: ## Release a major version
	@$(MAKE) --no-print-directory release BUMP=major

release-dev: ## Publish a dev build of this commit to the mirror (no tag)
	@$(MAKE) --no-print-directory release BUMP=dev

# Reached only as the second goal of `make release <word>`. On its own it is a
# typo for the real target, so say so rather than silently succeeding.
$(_BUMP_WORDS):
	@case " $(MAKECMDGOALS) " in \
	  *" release "*) : ;; \
	  *) echo "make: '$@' is not a target. Did you mean 'make release $@'?"; exit 2 ;; \
	esac
