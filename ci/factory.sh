#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# ci/factory.sh — exécution headless d'un cycle de l'usine logicielle FleetBits.
#
# Usage :
#   ./ci/factory.sh specs/SPEC-mon-besoin.md
#   ./ci/factory.sh --yolo specs/SPEC-mon-besoin.md
#
# La spec doit exister et porter « Statut : APPROUVEE » : un cycle headless ne
# rédige jamais de spec, la gate humaine de /factory-run n'est pas contournable.
#
# Sortie JSON : factory-logs/factory-<horodatage>.json
# Exit code   : celui de `claude`.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

usage() {
  cat >&2 <<'EOF'
Usage : ci/factory.sh [--yolo] <chemin-de-la-spec-approuvee>

  <chemin-de-la-spec-approuvee>  Fichier sous specs/ portant « Statut : APPROUVEE ».
  --yolo                         Remplace la liste blanche d'outils par
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
      echo "ci/factory.sh : option inconnue « $1 »." >&2
      usage
      exit 2
      ;;
    *)
      if [ -n "$SPEC" ]; then
        echo "ci/factory.sh : un seul chemin de spec est attendu (déjà reçu « $SPEC »)." >&2
        exit 2
      fi
      SPEC="$1"
      shift
      ;;
  esac
done

if [ -z "$SPEC" ]; then
  echo "ci/factory.sh : le chemin d'une spec approuvée est obligatoire." >&2
  usage
  exit 2
fi

case "$SPEC" in
  /*) SPEC_ABS="$SPEC" ;;
  *)  SPEC_ABS="$ROOT_DIR/$SPEC" ;;
esac

if [ ! -f "$SPEC_ABS" ]; then
  echo "ci/factory.sh : spec introuvable : $SPEC_ABS" >&2
  exit 2
fi

if ! grep -q 'Statut : APPROUVEE' "$SPEC_ABS"; then
  echo "ci/factory.sh : « $SPEC_ABS » ne porte pas « Statut : APPROUVEE »." >&2
  echo "                Un cycle CI exige une spec déjà approuvée par l'utilisateur." >&2
  echo "                Lancer d'abord, en session interactive : /factory-run \"<votre besoin>\"" >&2
  exit 2
fi

if ! command -v claude >/dev/null 2>&1; then
  echo "ci/factory.sh : la commande « claude » est introuvable dans le PATH." >&2
  exit 127
fi

# Liste blanche d'outils : outils de base de l'usine, git sur les quatre dépôts,
# et les commandes réellement utilisées par la stack FleetBits
# (python3/venv pour -api et -ui, docker pour shellcheck, bats, ansible-lint,
# compose, et bash -n pour les scripts de -agent et -platform).
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

echo "ci/factory.sh : spec      = $SPEC_ABS"
echo "ci/factory.sh : journal   = $LOG_FILE"
echo "ci/factory.sh : mode      = $([ "$YOLO" -eq 1 ] && echo 'YOLO (permissions ignorées)' || echo 'acceptEdits + liste blanche')"

set +e
(cd "$ROOT_DIR" && claude "${CLAUDE_ARGS[@]}") | tee "$LOG_FILE"
EXIT_CODE=${PIPESTATUS[0]}
set -e

echo "ci/factory.sh : exit code claude = $EXIT_CODE"
exit "$EXIT_CODE"
