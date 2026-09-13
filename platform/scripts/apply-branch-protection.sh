#!/usr/bin/env bash
# apply-branch-protection.sh
#
# Applies branch protection rules and required status checks to the main branch
# of the FleetBits monorepo. Closes SEC-P0-03, SEC-P0-04, SEC-P0-05.
#
# Prerequisites:
#   - GitHub CLI installed: https://cli.github.com/
#   - Authenticated: gh auth login (needs admin:repo scope)
#   - GITHUB_OWNER set to your GitHub username/org
#
# Usage:
#   GITHUB_OWNER=your-username bash apply-branch-protection.sh

set -euo pipefail

OWNER="${GITHUB_OWNER:?Error: GITHUB_OWNER env var must be set}"

if ! command -v jq >/dev/null 2>&1; then
  echo "ERROR: jq is required but not installed" >&2
  exit 1
fi

# ─────────────────────────────────────────────────────────────────────────────
# Helper: apply branch protection via GitHub REST API
# ─────────────────────────────────────────────────────────────────────────────

apply_protection() {
  local repo="$1"
  shift
  local required_checks=("$@")

  echo ""
  echo "══════════════════════════════════════════════════════"
  echo " Protecting: ${OWNER}/${repo}  →  branch: main"
  echo "══════════════════════════════════════════════════════"

  # Build required status checks JSON array
  local checks_json
  checks_json=$(printf '%s\n' "${required_checks[@]}" | jq -R '{"context":.}' | jq -s '.')

  gh api \
    --method PUT \
    -H "Accept: application/vnd.github+json" \
    "/repos/${OWNER}/${repo}/branches/main/protection" \
    --input - <<EOF
{
  "required_status_checks": {
    "strict": true,
    "checks": ${checks_json}
  },
  "enforce_admins": true,
  "required_pull_request_reviews": {
    "dismiss_stale_reviews": true,
    "require_code_owner_reviews": true,
    "required_approving_review_count": 1
  },
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "block_creations": false,
  "required_conversation_resolution": true
}
EOF

  echo "  ✅ Protected: ${repo}/main"
  echo "  Required checks: ${required_checks[*]}"
}

# ─────────────────────────────────────────────────────────────────────────────
# FleetBits — the monorepo. The required checks are the jobs of
# .github/workflows/security-baseline.yml plus the PR checklist. All of them run
# on every pull request, unconditionally: a required check that carries a
# `paths:` filter never reports on a PR outside its scope and blocks the merge
# for ever, which is why the path-filtered suites (api-tests, agent-tests,
# platform-tests, security-regression-stack) are deliberately NOT required here.
# ─────────────────────────────────────────────────────────────────────────────
apply_protection "FleetBits" \
  "dependency-review" \
  "secret-scan" \
  "api-sast-and-deps" \
  "ui-sast-and-deps" \
  "filesystem-vuln-scan" \
  "pr-security-checklist"

echo ""
echo "════════════════════════════════════════════════════════"
echo " Branch protection applied to the FleetBits monorepo."
echo " Verify with:"
echo "   gh api /repos/${OWNER}/FleetBits/branches/main/protection | jq '.required_status_checks'"
echo "════════════════════════════════════════════════════════"
