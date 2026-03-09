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

---

## L-002: Decisions that require Pi changes need implementation tasks

**Date:** 2026-03-09
**Context:** D-018 (wayvnc replaces RustDesk) — declared but never executed

D-018 was recorded in decisions.md and referenced in status.md, but nobody
actually removed RustDesk from the Pi. It was still running with a weak
password, 3 firewall ports still open. The security specialist discovered
this during a cross-team review -- weeks could have passed with the old
software exposed.

**Root cause:** Decisions (D-NNN) are recorded as policy statements. There
is no automatic mechanism to translate a decision into an implementation
task on the Pi.

**Fix:** Any decision that requires Pi changes must have a corresponding
task (TK-NNN) assigned to the change-manager at the time the decision is
recorded. The PM is responsible for filing this task. The decision is not
"implemented" until the task is done and verified.

**Verification:** After a decision's task is complete, the CM or QE should
confirm the Pi state matches the decision (e.g., `dpkg -l rustdesk` returns
"not installed", firewall rules removed, ports closed).

---

## L-003: Worker verification is not owner verification

**Date:** 2026-03-09
**Context:** TK-040 (USBStreamer 8ch in Reaper) — closed prematurely

A worker verified a fix at the system level (`pw-jack jack_lsp` showed
ports), then killed Reaper before the owner could confirm via VNC that the
8 channels were actually visible in the application GUI. TK-040 was marked
done based on worker testing alone.

**Fix:** Any task requiring owner-visible verification (GUI rendering, audio
output, MIDI response) must NOT be closed until the owner confirms via VNC
or direct observation. Worker testing is necessary but not sufficient.
Workers must leave applications running for owner inspection after applying
fixes. This is now a permanent process rule in tasks.md.
