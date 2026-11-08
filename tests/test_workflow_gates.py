"""Workflow conditions that a governing rule depends on.

* **AD-15** -- PyPI publication is never triggered by a tag: it burns a filename
  permanently, so it must be a decision rather than a side effect. Every job that
  runs ``pypa/gh-action-pypi-publish`` must therefore be reachable only from
  ``workflow_dispatch``. TestPyPI burns filenames the same way, so it is held to
  the same rule rather than exempted.
* **ADR-0013** -- gate on ``vars.LOCAL_ACT``, never ``env.ACT``: Gitea runners also
  set ``ACT=true``, and ``env.ACT`` does not work in a job-level ``if:``.

Both read the PARSED workflow, so a comment explaining the rule -- ci.yml carries
one naming ``env.ACT`` -- is not mistaken for a use of it. Scope is every file in
``.github/workflows/``, never a list of names.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml

WORKFLOWS = Path(__file__).resolve().parent.parent / ".github" / "workflows"
PUBLISH_ACTION = "pypa/gh-action-pypi-publish"
DISPATCH_ONLY = "github.event_name == 'workflow_dispatch'"
ENV_ACT_RE = re.compile(r"\benv\.ACT\b")


def _workflows() -> list[Path]:
    found = sorted([*WORKFLOWS.glob("*.yml"), *WORKFLOWS.glob("*.yaml")])
    assert found, f"no workflows under {WORKFLOWS} -- an empty scope skips, not fails"
    return found


def _load(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def publish_gate_problem(job: dict[str, Any]) -> str | None:
    """None if ``job`` can run only from workflow_dispatch, else why not."""
    condition = " ".join(str(job.get("if", "")).split())
    if not condition:
        return "has no if: -- it runs on every trigger the workflow declares"
    if "||" in condition:
        return f"if: contains '||', so dispatch is one route among several: {condition}"
    conjuncts = [
        c.strip().removeprefix("${{").removesuffix("}}").strip() for c in condition.split("&&")
    ]
    if DISPATCH_ONLY not in conjuncts:
        return f"if: does not require {DISPATCH_ONLY}: {condition}"
    return None


def publishing_jobs(workflow: dict[str, Any]) -> Iterator[tuple[str, dict[str, Any]]]:
    for job_id, job in (workflow.get("jobs") or {}).items():
        if any(str(s.get("uses", "")).startswith(PUBLISH_ACTION) for s in job.get("steps", [])):
            yield job_id, job


def env_act_uses(node: Any, where: str = "") -> list[str]:
    """Every parsed string (key or value) that names env.ACT, with its path."""
    if isinstance(node, dict):
        return [
            hit
            for key, value in node.items()
            for hit in env_act_uses(str(key), f"{where}/{key}")
            + env_act_uses(value, f"{where}/{key}")
        ]
    if isinstance(node, list):
        return [hit for i, item in enumerate(node) for hit in env_act_uses(item, f"{where}[{i}]")]
    if isinstance(node, str) and ENV_ACT_RE.search(node):
        return [f"{where}: {node.strip()[:80]}"]
    return []


def test_some_job_publishes() -> None:
    """Otherwise the gate test below passes over an empty set."""
    assert any(True for path in _workflows() for _ in publishing_jobs(_load(path)))


@pytest.mark.parametrize("path", _workflows(), ids=lambda p: p.name)
def test_every_publishing_job_runs_only_from_dispatch(path: Path) -> None:
    """AD-15: a tag, a push or a release event can never reach a PyPI upload."""
    problems = [
        f"{path.name}::{job_id} {problem}"
        for job_id, job in publishing_jobs(_load(path))
        if (problem := publish_gate_problem(job))
    ]
    assert not problems, "\n".join(problems)


@pytest.mark.parametrize("path", _workflows(), ids=lambda p: p.name)
def test_no_workflow_gates_on_env_act(path: Path) -> None:
    """ADR-0013: vars.LOCAL_ACT, never env.ACT."""
    hits = env_act_uses(_load(path))
    assert not hits, "\n".join(hits)


# ---- planted violations ------------------------------------------------------


@pytest.mark.parametrize(
    ("condition", "fragment"),
    [
        (None, "has no if:"),
        ("startsWith(github.ref, 'refs/tags/')", "does not require"),
        ("github.event_name == 'workflow_dispatch' || github.event_name == 'push'", "'||'"),
        ("github.event_name != 'workflow_dispatch'", "does not require"),
    ],
)
def test_the_publish_gate_rejects_a_reachable_job(condition: str | None, fragment: str) -> None:
    job = {} if condition is None else {"if": condition}
    assert fragment in (publish_gate_problem(job) or "")


@pytest.mark.parametrize(
    "condition",
    [
        "github.event_name == 'workflow_dispatch' && inputs.target == 'pypi'",
        "${{ github.event_name == 'workflow_dispatch' }}",
        ">-\n  github.event_name == 'workflow_dispatch'\n  && inputs.target == 'pypi'",
    ],
)
def test_the_publish_gate_accepts_a_dispatch_only_job(condition: str) -> None:
    assert publish_gate_problem({"if": condition.removeprefix(">-\n")}) is None


def test_a_publish_step_under_any_ref_is_found() -> None:
    workflow = {"jobs": {"j": {"steps": [{"uses": f"{PUBLISH_ACTION}@v1.12.4"}]}}}
    assert [job_id for job_id, _ in publishing_jobs(workflow)] == ["j"]


def test_env_act_is_found_wherever_it_is_parsed() -> None:
    workflow = yaml.safe_load(
        "# a comment naming env.ACT is not a use\n"
        "jobs:\n"
        "  a:\n"
        "    if: ${{ !env.ACT }}\n"
        "    steps:\n"
        "      - run: echo ${{ env.ACT }}\n"
        "      - if: vars.LOCAL_ACT\n"
    )
    hits = env_act_uses(workflow)
    assert len(hits) == 2, hits
    assert not env_act_uses({"if": "vars.LOCAL_ACT"})


# ---- floating version tags ----------------------------------------------------
#
# release.yml maintains floating `v<major>` and `v<major>.<minor>` tags. They must
# never start a publish, never be read as the latest release, and must move only
# once the real tag exists and before publish.yml is handed it.

FLOATING = ["v0", "v0.0", "v1", "v1.2"]
RELEASES = ["v0.0.2", "v0.1.0", "v1.2.3"]


def tag_triggers(workflow: dict[Any, Any]) -> list[str]:
    # PyYAML (YAML 1.1) parses the key `on` as the boolean True.
    on = workflow.get("on", workflow.get(True)) or {}
    return list(((on.get("push") or {}) if isinstance(on, dict) else {}).get("tags", []))


def starts_a_run(tag: str, patterns: list[str]) -> bool:
    """GitHub's tag filter: the last matching pattern wins, `!` negates."""
    from fnmatch import fnmatchcase

    hit = False
    for pattern in patterns:
        negated = pattern.startswith("!")
        if fnmatchcase(tag, pattern.removeprefix("!")):
            hit = not negated
    return hit


@pytest.mark.parametrize("path", _workflows(), ids=lambda p: p.name)
def test_no_floating_tag_starts_a_workflow(path: Path) -> None:
    patterns = tag_triggers(_load(path))
    started = [t for t in FLOATING if starts_a_run(t, patterns)]
    assert not started, f"{path.name} runs on floating tag(s) {started}: {patterns}"


def test_a_release_tag_still_starts_publish() -> None:
    patterns = tag_triggers(_load(WORKFLOWS / "publish.yml"))
    assert patterns, "publish.yml has no tag trigger -- the check above is vacuous"
    assert all(starts_a_run(t, patterns) for t in RELEASES), patterns
    assert not starts_a_run("v0.0.0", patterns), "v0.0.0 is the baseline, never a release"


def _release_steps() -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    for job in (_load(WORKFLOWS / "release.yml").get("jobs") or {}).values():
        steps += job.get("steps", [])
    return steps


def _index(steps: list[dict[str, Any]], action: str) -> int:
    found = [i for i, s in enumerate(steps) if str(s.get("uses", "")).startswith(action)]
    assert found, f"release.yml has no step using {action}"
    return found[-1]


def test_floating_tags_move_after_the_release_tag_and_before_the_dispatch() -> None:
    steps = _release_steps()
    created = _index(steps, "LiquidLogicLabs/git-action-tag-create-update")
    floated = _index(steps, "LiquidLogicLabs/git-action-tag-floating-version")
    dispatched = _index(steps, "LiquidLogicLabs/git-action-trigger-workflow")
    assert created < floated < dispatched


def test_the_latest_release_lookup_ignores_floating_tags() -> None:
    steps = _release_steps()
    lookup = steps[_index(steps, "LiquidLogicLabs/git-action-tag-info")]
    assert lookup.get("with", {}).get("tag-format") == "v*.*.*"


def test_the_tag_filter_check_reads_negation_and_order() -> None:
    assert starts_a_run("v0.0.2", ["v*", "!v0.0.0"])
    assert not starts_a_run("v0.0.0", ["v*", "!v0.0.0"])
    assert starts_a_run("v0", ["v*"]), "a bare v* filter does start a run on a floating tag"
    assert not starts_a_run("v0", ["v*.*.*"])


def _publish_release_steps() -> list[dict[str, Any]]:
    job = (_load(WORKFLOWS / "publish.yml").get("jobs") or {}).get("release") or {}
    steps: list[dict[str, Any]] = job.get("steps", [])
    assert steps, "publish.yml has no release job -- the check below is vacuous"
    return steps


def test_release_notes_never_start_from_a_floating_tag() -> None:
    """v0.1.0 shipped with "no changes": auto-detection took the floating v0.1.

    The notes builder must be told its lower bound, and that bound must come from a
    step that only matches three-component tags.
    """
    steps = _publish_release_steps()
    builder = steps[_index(steps, "LiquidLogicLabs/git-action-release-changelog-builder")]
    from_tag = str(builder.get("with", {}).get("from-tag", ""))
    assert "steps.previous.outputs.tag" in from_tag, f"from-tag is {from_tag!r}"
    previous = next((s for s in steps if s.get("id") == "previous"), None)
    assert previous is not None, "no step with id 'previous' computes the lower bound"
    assert "--match 'v[0-9]*.[0-9]*.[0-9]*'" in str(previous.get("run", ""))
    assert steps.index(previous) < steps.index(builder)


# ---- release.yml refuses a commit whose CI is not green (family rule, 2026-11-08) ----

CI_GATE = "CI must be green on the commit being released"


def _gate() -> tuple[int, dict[str, Any]]:
    steps = _release_steps()
    found = [(i, s) for i, s in enumerate(steps) if s.get("name") == CI_GATE]
    assert len(found) == 1, f"release.yml needs exactly one step named {CI_GATE!r}"
    return found[0]


def test_the_ci_gate_runs_before_anything_is_tagged_or_dispatched() -> None:
    """`make release` checks too, but a hand dispatch of release.yml skips make."""
    steps = _release_steps()
    gate, step = _gate()
    acts = [
        i
        for i, s in enumerate(steps)
        if str(s.get("uses", "")).startswith(
            (
                "LiquidLogicLabs/git-action-tag-create-update",
                "LiquidLogicLabs/git-action-tag-floating-version",
                "LiquidLogicLabs/git-action-trigger-workflow",
            )
        )
    ]
    assert acts, "release.yml tags or dispatches nothing -- the check is vacuous"
    assert gate < min(acts)
    assert "if" not in step, "a dev publish is a publish too: the gate applies to every bump"


def test_the_ci_gate_checks_the_released_commit_and_both_workflows() -> None:
    _, step = _gate()
    script = str(step.get("run", ""))
    assert "GITHUB_SHA" in script, "the commit tagged is the one dispatched"
    for workflow in ("CI", "Security audit"):
        assert f'"{workflow}"' in script, f"the gate must require {workflow}"
