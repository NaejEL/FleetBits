#!/usr/bin/env bash
# apply-branch-protection.sh
#
# Applies branch protection rules and required status checks to main branch
# across all 4 FleetBits repos. Closes SEC-P0-03, SEC-P0-04, SEC-P0-05.
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
# FleetBits-api — full security baseline + regression stack
# ─────────────────────────────────────────────────────────────────────────────
apply_protection "FleetBits-api" \
  "dependency-review" \
  "secret-scan" \
  "python-sast-and-deps" \
  "filesystem-vuln-scan" \
  "security-regression-stack" \
  "pr-security-checklist"

# ─────────────────────────────────────────────────────────────────────────────
# FleetBits-ui — security baseline (no Python regression stack)
# ─────────────────────────────────────────────────────────────────────────────
apply_protection "FleetBits-ui" \
  "dependency-review" \
  "secret-scan" \
  "python-sast-and-deps" \
  "filesystem-vuln-scan" \
  "pr-security-checklist"

# ─────────────────────────────────────────────────────────────────────────────
# FleetBits-platform — security baseline (infra / YAML repo)
# ─────────────────────────────────────────────────────────────────────────────
apply_protection "FleetBits-platform" \
  "dependency-review" \
  "secret-scan" \
  "filesystem-vuln-scan" \
  "pr-security-checklist"

# ─────────────────────────────────────────────────────────────────────────────
# FleetBits-agent — security baseline (shell/Alloy repo)
# ─────────────────────────────────────────────────────────────────────────────
apply_protection "FleetBits-agent" \
  "dependency-review" \
  "secret-scan" \
  "filesystem-vuln-scan" \
  "pr-security-checklist"

echo ""
echo "════════════════════════════════════════════════════════"
echo " Branch protection applied to all 4 FleetBits repos."
echo " Run once per repo to verify:"
echo "   gh api /repos/${OWNER}/FleetBits-api/branches/main/protection | jq '.required_status_checks'"
echo "════════════════════════════════════════════════════════"
