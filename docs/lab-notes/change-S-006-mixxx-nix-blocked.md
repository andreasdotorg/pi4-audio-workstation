# CHANGE Session S-006: TK-139 Nix Mixxx 2.5.4 CPU Test (BLOCKED)

**Evidence basis: CONTEMPORANEOUS**

TW received command-level CC from CM in real time during session execution.

---

**Date:** 2026-03-12, ~22:30 CET
**Operator:** worker-mixxx-nix (via CM CHANGE session S-006)
**Host:** mugge (Raspberry Pi 4B, Debian 13 Trixie, kernel 6.12.62+rpt-rpi-v8-rt)
**Safety precondition:** Owner confirmed PA is OFF prior to session grant.
**Scope:** TK-139 Nix-built Mixxx 2.5.4 CPU comparison test. Process
start/stop only, no config changes.

---

## Outcome: BLOCKED

TK-139 could not proceed. Nix is not installed on the Pi, and no Mixxx 2.5.4
closure has been transferred to the Pi's Nix store. No state changes were made.

## Procedure

### Step 1: Check Nix Installation

```bash
$ nix --version
```

Result: Nix not installed.

### Step 2: Check Running Mixxx

```bash
$ pgrep -a mixxx
```

Result: Mixxx 2.5.0 (apt-installed) running as PID 1622.

### Step 3: Check Nix Store for Mixxx

```bash
$ ls -d /nix/store/*-mixxx-*
```

Result: No `/nix/store` directory or Mixxx entries.

## Prerequisites Not Met

Per `docs/lab-notes/nix-mixxx-deployment.md`, TK-139 requires:

1. Nix installed on Pi (`sh <(curl -L https://nixos.org/nix/install) --daemon`) -- **NOT MET**
2. Mixxx 2.5.4 closure transferred to Pi (`nix copy --to ssh://...`) -- **NOT MET**

These are Steps 2 and 3 of the Nix Mixxx deployment procedure. They must be
completed before TK-139 can be reattempted.

## Validation Summary

| Check | Expected | Actual | Result |
|-------|----------|--------|--------|
| Nix installed | Yes | No | BLOCKED |
| Mixxx 2.5.4 in Nix store | Yes | No | BLOCKED |
| State changes | None | None | PASS (no mutations) |

## Notes

- Mixxx 2.5.0 (apt) is running and available as the baseline for comparison
  once TK-139 prerequisites are met.
- The Nix installation and closure transfer are prep steps that should be done
  in a separate DEPLOY session before reattempting TK-139.
