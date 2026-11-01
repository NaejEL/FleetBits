## Summary

- What does this PR change?
- Why is this change needed?

## Security checklist

Required — verify before requesting review.

**Dependency update pull requests** (opened by the bot) are exempt from this
checklist job, which is skipped for that author. Nothing in CI verifies these
items on its own: a human reviewer reads the diff and the release notes before
merging. There is no automated substitute for that reading.

- [ ] I reviewed authorization scope impact (tenant/site boundaries)
- [ ] I reviewed authentication/session/token impact
- [ ] I reviewed secret handling (no secrets committed, no insecure defaults)
- [ ] I reviewed input validation and query injection risk
- [ ] I reviewed telemetry/package/reverse-proxy exposure impact (if applicable)
- [ ] I added or updated automated tests for security-relevant behavior
- [ ] I verified CI security jobs are passing (dependency, secret, vuln scans)

## Rollout / rollback notes

- Rollout plan:
- Rollback plan:
