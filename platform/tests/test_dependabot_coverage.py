"""Mechanical checks on .github/dependabot.yml.

Dependabot never reports a misconfigured entry: `directory:` is not recursive
and a directory holding no manifest of the declared ecosystem simply produces
no pull request, forever, in silence. That is how the `docker` entry on
`/platform` watched nothing for months while the eleven real base images of
platform/docker/*/ went unwatched.

Two properties are checked here, and both fail loudly:

  * SOUNDNESS — every declared entry points at a directory that really holds a
    manifest of its ecosystem. An entry that watches nothing is a lie.
  * COVERAGE  — every manifest in the tree is watched by some entry. Adding a
    Dockerfile or a requirements.txt without adding its entry fails this suite.

The file lives under platform/tests/ because platform/ is the component that
owns the repository-wide checks and already has a pytest harness; the
properties themselves are about the repository root, not about platform/.
"""

from __future__ import annotations

import pathlib

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
DEPENDABOT_CONFIG = REPO_ROOT / ".github" / "dependabot.yml"

# Directories that hold copies of third-party code or build output. A
# requirements.txt found there describes no dependency of this repository.
EXCLUDED_PARTS = frozenset(
    {
        ".git",
        ".venv",
        ".venv-platform",
        "node_modules",
        "dist",
        "__pycache__",
        "site-packages",
    }
)


def _is_excluded(path: pathlib.Path, root: pathlib.Path = REPO_ROOT) -> bool:
    return any(part in EXCLUDED_PARTS for part in path.relative_to(root).parts)


def _is_dockerfile(name: str) -> bool:
    """Match a Dockerfile name the way dependabot's docker file fetcher does.

    Upstream matches `/dockerfile/i` against the file name: the match is
    case-insensitive and it is not anchored at the start, so `Dockerfile`,
    `DOCKERFILE`, `Dockerfile.container` and `app.dockerfile` are all
    manifests dependabot will read. Anchoring on a capitalised prefix here
    would let a real manifest through unwatched while this suite stayed green.
    """
    return "dockerfile" in name.lower()


def _is_pip_manifest(path: pathlib.Path) -> bool:
    """Match a pip manifest the way dependabot's python file fetcher does.

    Upstream (dependabot-core, `python/lib/dependabot/python/
    shared_file_fetcher.rb`) selects every `.txt` and `.in` file of the
    directory — and of one level of subdirectories — that parses as a
    requirements file. It is neither case-sensitive nor anchored on a
    capitalised prefix.

    Two shapes therefore count, and both were blind spots of the earlier
    `requirements*.txt` glob:
      - a file whose own name carries `requirements` (`dev-requirements.txt`,
        `Requirements.txt`, `requirements-dev.in`);
      - any `.txt`/`.in` inside a directory named `requirements`, whatever the
        file is called (`requirements/base.txt`).

    Letting either through would leave a real manifest unwatched while this
    suite stayed green — the same failure `_is_dockerfile` exists to avoid on
    the docker side.
    """
    if not path.name.lower().endswith((".txt", ".in")):
        return False
    return (
        "requirements" in path.name.lower()
        or path.parent.name.lower() == "requirements"
    )


def _manifests(ecosystem: str, directory: pathlib.Path) -> list[pathlib.Path]:
    """Return the manifests of `ecosystem` held directly by `directory`.

    Not recursive for docker and github-actions, exactly like dependabot's own
    `directory:` resolution. For pip, dependabot also reads one level of
    subdirectories, so this does too.
    """
    if not directory.is_dir():
        return []
    if ecosystem == "pip":
        direct = (p for p in directory.iterdir() if p.is_file())
        nested = (
            p
            for sub in directory.iterdir()
            if sub.is_dir() and not _is_excluded(sub)
            for p in sub.iterdir()
            if p.is_file()
        )
        return sorted(
            p for p in (*direct, *nested) if _is_pip_manifest(p)
        )
    if ecosystem == "docker":
        return sorted(
            p for p in directory.iterdir() if p.is_file() and _is_dockerfile(p.name)
        )
    if ecosystem == "github-actions":
        workflows = directory / ".github" / "workflows"
        if not workflows.is_dir():
            return []
        return sorted(
            p for p in workflows.iterdir() if p.is_file() and p.suffix in {".yml", ".yaml"}
        )
    raise AssertionError(f"unknown ecosystem declared: {ecosystem!r}")


def _all_manifests(
    ecosystem: str, root: pathlib.Path = REPO_ROOT
) -> list[pathlib.Path]:
    """Every manifest of `ecosystem` anywhere in the tree, excluded paths aside.

    `root` is a parameter so the discovery itself can be exercised against a
    throw-away tree — see test_docker_discovery_is_case_insensitive below.
    """
    if ecosystem == "pip":
        # Same reason as the docker branch below: an anchored, case-sensitive
        # glob would miss a manifest dependabot reads.
        found = (p for p in root.rglob("*") if _is_pip_manifest(p))
    elif ecosystem == "docker":
        # rglob("Dockerfile*") would be both case-sensitive and anchored on the
        # prefix; dependabot's file fetcher is neither. Walk the tree and let
        # _is_dockerfile decide, so `app.dockerfile` and `DOCKERFILE` are found.
        found = (p for p in root.rglob("*") if _is_dockerfile(p.name))
    else:
        raise AssertionError(f"coverage is not defined for {ecosystem!r}")
    return sorted(p for p in found if p.is_file() and not _is_excluded(p, root))


@pytest.fixture(scope="module")
def updates() -> list[dict]:
    config = yaml.safe_load(DEPENDABOT_CONFIG.read_text(encoding="utf-8"))
    assert config["version"] == 2, "dependabot config must declare version 2"
    entries = config["updates"]
    assert entries, "dependabot config declares no update entry"
    return entries


def test_every_entry_watches_a_real_manifest(updates: list[dict]) -> None:
    """No entry may point at a directory holding no manifest of its ecosystem."""
    empty = []
    for entry in updates:
        ecosystem = entry["package-ecosystem"]
        declared = entry["directory"]
        assert declared.startswith("/"), (
            f"{ecosystem} {declared}: directory must be repository-absolute"
        )
        directory = REPO_ROOT / declared.lstrip("/")
        assert directory.is_dir(), f"{ecosystem} {declared}: no such directory"
        if not _manifests(ecosystem, directory):
            empty.append(f"{ecosystem} {declared}")

    assert not empty, (
        "dependabot entries pointing at a directory that holds no manifest of "
        "their ecosystem — they watch nothing and will never open a pull "
        "request:\n  " + "\n  ".join(empty)
    )


def test_no_duplicate_entry(updates: list[dict]) -> None:
    """Two entries on the same ecosystem and directory would double every PR."""
    seen = [(e["package-ecosystem"], e["directory"]) for e in updates]
    duplicates = sorted({pair for pair in seen if seen.count(pair) > 1})
    assert not duplicates, f"duplicate dependabot entries: {duplicates}"


@pytest.mark.parametrize("ecosystem", ["pip", "docker"])
def test_every_manifest_in_the_tree_is_watched(
    updates: list[dict], ecosystem: str
) -> None:
    """No manifest may be left unwatched by every entry."""
    watched: set[pathlib.Path] = set()
    for entry in updates:
        if entry["package-ecosystem"] != ecosystem:
            continue
        directory = REPO_ROOT / entry["directory"].lstrip("/")
        watched.update(_manifests(ecosystem, directory))

    unwatched = [
        str(p.relative_to(REPO_ROOT)) for p in _all_manifests(ecosystem) if p not in watched
    ]
    assert not unwatched, (
        f"{ecosystem} manifests watched by no dependabot entry — their pinned "
        f"versions will never be updated:\n  " + "\n  ".join(unwatched)
    )


def test_github_actions_entry_covers_the_workflows(updates: list[dict]) -> None:
    """Workflows only ever run from the repository root, so "/" must be watched."""
    directories = {
        e["directory"] for e in updates if e["package-ecosystem"] == "github-actions"
    }
    assert "/" in directories, (
        "no github-actions entry on '/': the workflows under .github/workflows/ "
        "would be watched by nobody"
    )


def test_no_entry_caps_the_number_of_open_pull_requests(updates: list[dict]) -> None:
    """A reached cap silently withholds the next update.

    Dependabot defaults `open-pull-requests-limit` to 5. Once five are open it
    stops opening more and says so nowhere, which turns a backlog into an
    invisible freeze. Volume is controlled by `groups:`, never by a cap.
    """
    too_low = [
        f"{e['package-ecosystem']} {e['directory']}: "
        f"{e.get('open-pull-requests-limit', 5)}"
        for e in updates
        if e.get("open-pull-requests-limit", 5) < 50
    ]
    assert not too_low, (
        "dependabot entries that would stop opening pull requests once their "
        "cap is reached:\n  " + "\n  ".join(too_low)
    )


def test_github_actions_majors_are_not_grouped_with_minors(updates: list[dict]) -> None:
    """Majors must land alone: they are behaviour changes, read one at a time."""
    for entry in updates:
        if entry["package-ecosystem"] != "github-actions":
            continue
        groups = entry.get("groups") or {}
        assert groups, "the github-actions entry declares no group"
        for name, group in groups.items():
            update_types = group.get("update-types")
            assert update_types, (
                f"github-actions group {name!r} declares no update-types, so it "
                "would swallow major bumps too"
            )
            assert "major" not in update_types, (
                f"github-actions group {name!r} groups major bumps with the rest"
            )


def test_pip_is_grouped_per_component_across_all_update_types(
    updates: list[dict],
) -> None:
    """api/requirements.txt pins a coupled set that cannot move apart.

    Its header names the set: fastapi, starlette,
    prometheus-fastapi-instrumentator, python-multipart and pytest. A pull
    request moving one of them alone fails the api/ suite, so every level of
    every package of a component travels in one group.
    """
    for entry in updates:
        if entry["package-ecosystem"] != "pip":
            continue
        directory = entry["directory"]
        groups = entry.get("groups") or {}
        assert len(groups) == 1, (
            f"pip {directory}: expected exactly one group for the component, "
            f"found {sorted(groups)}"
        )
        (name, group), = groups.items()
        assert group.get("patterns") == ["*"], (
            f"pip group {name!r} does not cover every package of the component"
        )
        assert set(group.get("update-types") or []) == {"major", "minor", "patch"}, (
            f"pip group {name!r} leaves an update level out of the component "
            "group, so a coupled pin could move on its own"
        )


@pytest.mark.parametrize(
    "name",
    [
        "Dockerfile",
        "DOCKERFILE",
        "dockerfile",
        "Dockerfile.container",
        "app.dockerfile",
        "SERVICE.Dockerfile",
    ],
)
def test_docker_discovery_is_case_insensitive(
    tmp_path: pathlib.Path, name: str
) -> None:
    """Discovery must match /dockerfile/i, the way dependabot's fetcher does.

    This is a regression guard on a real defect: discovery used to be
    `rglob("Dockerfile*")` and `"Dockerfile" in p.name`, which are
    case-sensitive and prefix-anchored. A file named `app.dockerfile` is a
    manifest dependabot reads, yet the coverage check above stayed green while
    no entry watched it. Both the per-directory resolution and the whole-tree
    discovery are exercised, because the defect lived in both.
    """
    service = tmp_path / "svc"
    service.mkdir()
    manifest = service / name
    manifest.write_text("FROM python:3.12-slim\n", encoding="utf-8")

    assert _manifests("docker", service) == [manifest], (
        f"{name} is not resolved as a docker manifest of its own directory"
    )
    assert _all_manifests("docker", tmp_path) == [manifest], (
        f"{name} is not discovered by the whole-tree docker scan"
    )


def test_docker_discovery_ignores_what_is_not_a_dockerfile(
    tmp_path: pathlib.Path,
) -> None:
    """The looser match must not start claiming unrelated files."""
    service = tmp_path / "svc"
    service.mkdir()
    for name in ("README.md", "docker-compose.yml", "docker.md", "requirements.txt"):
        (service / name).write_text("", encoding="utf-8")

    assert _manifests("docker", service) == []
    assert _all_manifests("docker", tmp_path) == []
