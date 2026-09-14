---
name: factory-run
description: Runs one cycle of the software factory (Planner → human gate on the spec → Builder → Verifier with a correction loop) on a requirement or an approved spec.
disable-model-invocation: true
argument-hint: "<requirement | path of an approved spec>"
---

Run a complete cycle of the FleetBits software factory on `$ARGUMENTS`. Follow the steps in order, without skipping any.

## Permanent repository context

`/home/naej/repos/FleetBits` is **a single git repository** — the FleetBits monorepo. Its four components are top-level directories: `api/` (Python/FastAPI, Alembic, pytest), `ui/` (Python/Flask), `agent/` (shell, systemd, Alloy/Vector), `platform/` (docker-compose, Ansible, scripts). The cross-cutting documents (`README.md`, `GUIDELINES.md`, `FEATURE_ROADMAP.md`, `SECURITY_ROADMAP.md`, `AUDIT-vibecode.md`), the factory (`.claude/`, `ci/`), the specs (`specs/`) and the GitHub workflows (`.github/workflows/`) live at the root.

A single working tree, a single `git status`, a single history: no more `git -C <repository>`, no more branch to synchronise from one repository to another. A cycle that touches both the API and the agent is an ordinary change, testable in one go. The `factory-logs/` logs are ignored by git.

## 1. Input

If `$ARGUMENTS` is the path of an existing file under `specs/` whose status line at the top is exactly `Statut : APPROUVEE`, **go straight to step 3**, taking that file as the approved spec.

Otherwise, treat `$ARGUMENTS` as a **requirement** expressed by the user, and continue at step 2.

## 2. Plan phase — mandatory human gate

1. Launch the `factory-planner` sub-agent (`Agent` tool, `subagent_type: "factory-planner"`) with the requirement `$ARGUMENTS` as input. If the requirement cites a finding from `AUDIT-vibecode.md` or a cross-cutting document, point it out explicitly.
2. When it returns, read the *Questions ouvertes* section of its draft. If it contains at least one question, put them to the user with `AskUserQuestion`, grouping as many questions as possible in a single call and offering, for each of them, the options identified by the Planner.
3. Fold the answers into the draft: each answer makes the corresponding open question disappear and becomes, depending on the case, an acceptance criterion, a line in *Hors-périmètre* or a constraint in *Contexte*. The *Questions ouvertes* section of the written spec must be reduced to "Aucune".
4. Write `specs/SPEC-<slug-of-the-requirement>.md` — a short slug, lowercase, words separated by hyphens, derived from the requirement (e.g. `specs/SPEC-contrat-identite-appareil.md`). The file begins with the title, then, on the second non-empty line, exactly:

   ```
   Statut : PROPOSEE
   ```

   followed by the sections *Contexte*, *Périmètre*, *Critères d'acceptation*, *Hors-périmètre*, *Risques*, *Questions ouvertes* (the spec's section headings stay in French).
5. Present the spec to the user and **ask for explicit approval**. On approval, replace the status line with `Statut : APPROUVEE`. If there are reservations, iterate on the spec (fix, re-present) and only move to the approved status after a clear agreement.
6. **If no interaction is possible (headless execution, `claude -p`), stop immediately with an explicit error**: "A CI cycle requires the path of an already-approved spec under `specs/` carrying `Statut : APPROUVEE`. No spec will be written without a human gate." Write nothing, build nothing.

**Never build without an approved spec.** The user is the Product Owner: no requirement is decided in their place.

## 3. Build phase

Launch the `factory-builder` sub-agent (`Agent` tool, `subagent_type: "factory-builder"`, **fresh context**), passing it:

- the absolute path of the approved spec;
- the list of components touched (`api/`, `ui/`, `agent/`, `platform/`), as the spec names them;
- the instruction to run the build and the tests of each component touched and to hand back only if they pass.

## 4. Verify phase — correction loop, 3 iterations maximum

Keep an iteration counter, initialised to 1.

1. Launch a `factory-verifier` sub-agent (`subagent_type: "factory-verifier"`, **blank context, independent of the Builder's** — a new agent at each iteration, never a resumption of the previous one) with the absolute path of the spec. Retrieve the JSON block at the end of its response.
2. If `verdict` is `APPROVED` **and** `tests_passed` is `true`: exit the loop, the cycle is a success. Go to step 5.
3. Otherwise, relaunch `factory-builder` (fresh context) with the path of the spec **and the complete list of the Verifier's `issues`** — `file`, `severity`, `description` of each one, omitting none and summarising none — and the instruction to fix each issue without regressing on the criteria already satisfied. Increment the counter, then resume at step 1 with a **new** Verifier.
4. After the **3rd** unapproved iteration, **fail explicitly**: publish the remaining issues, the number of iterations consumed and the state of the working tree. **Never approve out of exhaustion**, nor declare the cycle successful because the remaining issues seem minor.
5. **A silent Verifier is not a satisfied Verifier.** If the Builder or the Verifier dies (API error, dropped connection, interrupted agent) or returns unusable output instead of its JSON block, relaunch it **once, identically**. If the second attempt also fails, **fail explicitly**, saying so: "The verifier returned no usable verdict after two attempts; the code produced is not verified." Never treat the absence of a verdict as an approval, never consume an iteration of the counter for the benefit of a dead agent, never move on with a missing verdict. A cycle that ships unverified code because its verifier fell over is worse than a cycle that fails.

## 5. Final report

Produce a structured report containing:

- **Modified files**, obtained by a single call:

  ```bash
  git -C /home/naej/repos/FleetBits status --short
  ```

  Group them by component (`api/`, `ui/`, `agent/`, `platform/`, root) in the report.

- **Test results**: for each component touched, the command run and its exit code (`api/`: `./.venv/bin/python -m pytest`; `ui/`: the same if a `tests/` exists; `agent/`: `./scripts/run-tests.sh`, i.e. `shellcheck` + `bats`; `platform/`: `./scripts/run-tests.sh`, i.e. `docker compose config -q` + `ansible-playbook --syntax-check` + `ansible-lint` + `pytest` + `shellcheck`).
- **Verdict** — the Verifier's final one — and the number of iterations consumed.
- **Suggested next action**: review of the diff by the user (`git -C /home/naej/repos/FleetBits diff`), then commit and branch at their discretion. **Never commit in their place** — the splitting of commits belongs to them.
