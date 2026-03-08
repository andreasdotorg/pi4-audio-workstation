# Lessons Learned — Pi4 Audio Workstation

Project-specific process lessons. For global lessons, see
`~/mobile/gabriela-bogk/team-protocol/lessons-learned.md`.

---

## L-001: sshd drop-in files use first-match-wins, not last-match-wins

**Date:** 2026-03-08
**Context:** US-000a security hardening — SSH password auth disable

sshd config processing differs from systemd unit drop-ins:

- **systemd unit drop-ins:** processed in lexical order, **last value wins**
  (higher-numbered files override lower-numbered ones)
- **sshd drop-ins (`/etc/ssh/sshd_config.d/`):** processed in lexical order,
  **first value wins** (lower-numbered files take priority, later duplicates
  are silently ignored)

A `99-hardening.conf` setting `PasswordAuthentication no` was silently ignored
because `50-cloud-init.conf` already set `PasswordAuthentication yes` and was
read first. The fix: use a prefix lower than the file you need to override
(e.g., `40-`), or remove the conflicting file.

**Always verify sshd changes with `sudo sshd -T | grep <directive>` after
reload.** The `-T` flag shows the effective configuration after all drop-ins
are merged.
