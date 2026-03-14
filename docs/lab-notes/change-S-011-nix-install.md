# CHANGE Session S-011: Nix 2.34.1 Multi-User Install (D-033 Stage 1)

**Evidence basis: CONTEMPORANEOUS (summary only)**

TW received session open/close notifications from CM in real time. Individual
command-level CC was not relayed during session execution. Procedure details
below are reconstructed from the CM's closure summary and the documented
install procedure in `docs/lab-notes/nix-mixxx-deployment.md`.

---

**Date:** 2026-03-13
**Operator:** worker (via CM CHANGE session S-011)
**Host:** mugge (Raspberry Pi 4B, Debian 13 Trixie, kernel 6.12.62+rpt-rpi-v8-rt)
**Safety precondition:** Non-audio change. No PA safety precondition required.
**Scope:** D-033 Stage 1 -- install multi-user Nix on the Pi. No audio services
touched.

---

## Outcome: PASS

Nix 2.34.1 installed in multi-user mode with nix-daemon. nixpkgs-unstable
channel configured. Binary cache working for aarch64-linux. No reboot needed.
All 5 verification steps passed.

## Context

S-006 (TK-139 Nix Mixxx CPU test) was BLOCKED because Nix was not installed on
the Pi. D-033 defines incremental Nix adoption with Stage 1 being the multi-user
Nix install. This session completes that prerequisite.

## Procedure (Summary)

The CM's closure summary confirms the following were completed:

1. Nix 2.34.1 multi-user install (with nix-daemon)
2. nixpkgs-unstable channel configured
3. Binary cache verified working for aarch64-linux

Exact commands were not CC'd to TW. The expected procedure per
`docs/lab-notes/nix-mixxx-deployment.md` Step 2 is:

```bash
$ sh <(curl -L https://nixos.org/nix/install) --daemon
$ nix-channel --add https://nixos.org/channels/nixpkgs-unstable nixpkgs
$ nix-channel --update
```

**Note:** TW cannot confirm these exact commands were run. Only the outcome
(Nix 2.34.1, nix-daemon, nixpkgs-unstable, binary cache working) is confirmed
by the CM closure summary.

## Verification

CM reported all 5 verification steps passed. Expected checks:

| Check | Expected | Actual (per CM) | Result |
|-------|----------|------------------|--------|
| Nix installed | `nix --version` returns version | Nix 2.34.1 | PASS |
| nix-daemon running | `systemctl status nix-daemon` active | Active | PASS |
| nixpkgs-unstable channel | `nix-channel --list` shows unstable | Configured | PASS |
| Binary cache (aarch64) | `nix-store --query ...` or similar | Working | PASS |
| Audio services unaffected | No audio service restarts or changes | No audio touched | PASS |

**Note:** Exact verification command output was not CC'd. Pass/Fail status is
per CM's closure summary statement "All 5 verification steps passed."

## Audio Impact

None. CM explicitly confirmed:

- No audio services touched
- No reboot needed
- CamillaDSP, PipeWire, and all audio infrastructure unchanged

## Unblocked Work

With Nix installed on the Pi, the following are now unblocked:

- **TK-139:** Nix-built Mixxx 2.5.4 CPU comparison test (was BLOCKED in S-006)
- **D-033 Stage 2+:** Nix closure transfers, further Nix adoption

## Deviations from Plan

Unknown. Command-level detail was not CC'd to TW.

## Notes

- This was a non-audio infrastructure change. The CHANGE tier (rather than
  DEPLOY) is appropriate because there is no git commit being deployed -- Nix
  is installed from upstream.
- TW did not receive command-by-command CC during this session. The protocol
  requires CC for CHANGE-tier sessions. This gap mirrors the S-001 protocol
  gap, though the impact is lower for a non-audio change with a well-documented
  upstream installer.
- The ALL STOP from S-010 may still be in effect. S-011 was a non-audio
  change and does not conflict with the ALL STOP scope (which concerned
  measurement script execution and audio signal routing).

## Post-Session State

- Nix 2.34.1 installed (multi-user, nix-daemon)
- nixpkgs-unstable channel configured
- Binary cache working for aarch64-linux
- No reboot performed
- Audio stack unchanged from pre-session state
