#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# ci/factory.sh — headless execution of one FleetBits software factory cycle.
#
# Usage:
#   ./ci/factory.sh specs/SPEC-my-requirement.md
#   ./ci/factory.sh --yolo specs/SPEC-my-requirement.md
#
# The spec must exist and carry "Statut : APPROUVEE": a headless cycle never
# writes a spec, the human gate of /factory-run cannot be bypassed.
#
# JSON output : factory-logs/factory-<timestamp>.json
# Exit code   : that of `claude`.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

usage() {
  cat >&2 <<'EOF'
Usage: ci/factory.sh [--yolo] <path-of-the-approved-spec>

  <path-of-the-approved-spec>  File under specs/ carrying "Statut : APPROUVEE".
  --yolo                       Replaces the tool allowlist with
                               --dangerously-skip-permissions.
EOF
}

YOLO=0
SPEC=""

while [ $# -gt 0 ]; do
  case "$1" in
    --yolo)
      YOLO=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    -*)
      echo "ci/factory.sh: unknown option \"$1\"." >&2
      usage
      exit 2
      ;;
    *)
      if [ -n "$SPEC" ]; then
        echo "ci/factory.sh: a single spec path is expected (already received \"$SPEC\")." >&2
        exit 2
      fi
      SPEC="$1"
      shift
      ;;
  esac
done

if [ -z "$SPEC" ]; then
  echo "ci/factory.sh: the path of an approved spec is mandatory." >&2
  usage
  exit 2
fi

case "$SPEC" in
  /*) SPEC_ABS="$SPEC" ;;
  *)  SPEC_ABS="$ROOT_DIR/$SPEC" ;;
esac

if [ ! -f "$SPEC_ABS" ]; then
  echo "ci/factory.sh: spec not found: $SPEC_ABS" >&2
  exit 2
fi

if ! grep -q 'Statut : APPROUVEE' "$SPEC_ABS"; then
  echo "ci/factory.sh: \"$SPEC_ABS\" does not carry \"Statut : APPROUVEE\"." >&2
  echo "               A CI cycle requires a spec already approved by the user." >&2
  echo "               Run first, in an interactive session: /factory-run \"<your requirement>\"" >&2
  exit 2
fi

if ! command -v claude >/dev/null 2>&1; then
  echo "ci/factory.sh: the \"claude\" command was not found in the PATH." >&2
  exit 127
fi

# Tool allowlist: the factory's basic tools, git on the monorepo,
# and the commands actually used by the FleetBits stack
# (python3/venv for api/ and ui/, docker for shellcheck, bats, ansible-lint,
# compose, and bash -n for the -agent and -platform scripts).
ALLOWED_TOOLS='Read,Glob,Grep,Write,Edit,Bash(git *),Bash(python3 *),Bash(pip *),Bash(pytest *),Bash(ruff *),Bash(bandit *),Bash(alembic *),Bash(docker *),Bash(bash -n *),Bash(shellcheck *),Bash(ansible-lint *),Bash(ansible-playbook *)'

LOG_DIR="$ROOT_DIR/factory-logs"
mkdir -p "$LOG_DIR"
STAMP="$(date +%Y%m%d-%H%M%S)"
LOG_FILE="$LOG_DIR/factory-$STAMP.json"

CLAUDE_ARGS=(
  -p "/factory-run '$SPEC_ABS'"
  --output-format json
  --max-turns 100
)

if [ "$YOLO" -eq 1 ]; then
  CLAUDE_ARGS+=(--dangerously-skip-permissions)
else
  CLAUDE_ARGS+=(--permission-mode acceptEdits --allowedTools "$ALLOWED_TOOLS")
fi

echo "ci/factory.sh: spec      = $SPEC_ABS"
echo "ci/factory.sh: log       = $LOG_FILE"
echo "ci/factory.sh: mode      = $([ "$YOLO" -eq 1 ] && echo 'YOLO (permissions ignored)' || echo 'acceptEdits + allowlist')"

set +e
(cd "$ROOT_DIR" && claude "${CLAUDE_ARGS[@]}") | tee "$LOG_FILE"
EXIT_CODE=${PIPESTATUS[0]}
set -e

echo "ci/factory.sh: claude exit code = $EXIT_CODE"
exit "$EXIT_CODE"
