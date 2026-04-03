# Test Infrastructure Architecture

4-Backend Modular Test Framework for the Pi 4 Audio Workstation Web UI.

**Status:** APPROVED (Architect + QE + AD consensus, owner answers incorporated)
**Date:** 2026-04-03
**Authors:** Architect (lead), QE (test classification, fixture design), AD (safety constraints, tier challenge)

---

## 1. Principles

**P-1: Mark the exceptions, not the majority.**
Most tests run on mock. Only tests requiring real infrastructure get markers (`needs_pw`, `needs_usb_audio`, `needs_acoustic`). Unmarked tests run everywhere.

**P-2: Mock tests are UI smoke tests with a synthetic backend.**
`PI_AUDIO_MOCK=1` replaces production code entirely (L-QE-002 proof). Mock tests verify UI rendering, HTTP routing, form validation — not backend correctness. Calling them "integration tests" is misleading.

**P-3: The test proves what it claims to prove — nothing more.**
A test passing on mock does not prove the feature works on real PipeWire. A test passing on loopback does not prove room correction works. Test names and assertions must be honest about their verification scope.

**P-4: Safety constraints are unconditional.**
Signal-gen cap (-20 dBFS) and gain write validation (D-009: mult <= 1.0) apply on ALL non-mock tiers. Defense-in-depth does not branch on tier.

**P-5: Human attestation gates physical safety.**
The software cannot verify physical setup (speakers disconnected, loopback patched). CLI flags (`--loopback-confirmed`, `--owner-confirmed`) transfer physical-safety responsibility to the operator.

**P-6: Loopback verifies signal path, not acoustic outcome.**
Pi-loopback tests validate filter application (correct coefficients on correct channels), gain staging, and USB audio timing. They do NOT validate room correction effectiveness, acoustic time alignment, or thermal protection under real load.

---

## 2. Architecture: Two-Axis Model

Tests are classified along two independent axes:

### Backend Axis (what runs behind the web UI)

| Tier | Backend | Hardware | Automated? | Gate |
|------|---------|----------|------------|------|
| **mock** | `PI_AUDIO_MOCK=1` synthetic data | None | Yes (CI) | None |
| **local-demo** | Real PipeWire + WirePlumber + services (null sink) | None | Yes (CI) | None |
| **pi-loopback** | Real PipeWire + real USB audio (ADA8200 out->in patch cables) | USBStreamer + ADA8200 | Yes (unattended) | `--loopback-confirmed` |
| **pi-full** | Real PipeWire + real USB audio + speakers + UMIK-1 | Full rig | No (owner present) | `--owner-confirmed` per test |

### Runner Axis (how tests exercise the system)

| Runner | Tool | What it tests |
|--------|------|---------------|
| **API-only** | httpx/requests | REST endpoints, JSON contracts, state mutations |
| **Browser** | Playwright | UI rendering, interaction, WebSocket updates |
| **Audio-pipeline** | signal-gen + pw-record + numpy | Signal path integrity, gain staging, latency |

**Not all combinations are valid.** Browser tests on mock are valuable (UI smoke). Audio-pipeline tests on mock are meaningless. The marker system encodes which combinations are valid.

---

## 3. Directory Structure

```
src/web-ui/tests/
  conftest.py                  -- markers, tier-skip logic, shared fixtures (NO env mutation)
  unit/
    conftest.py                -- PI_AUDIO_MOCK=1, SessionConfig patch, TestClient fixture
    test_calibration.py        -- (22 files moved from tests/ root)
    test_filter_routes.py
    test_graph_routes.py
    ...
  integration/
    conftest.py                -- mock_server subprocess, Playwright fixtures, destructive skip
    test_navigation.py         -- (20 files, unchanged)
    test_full_user_journey.py
    ...
  e2e/
    conftest.py                -- _wait_for_stack, backend detection, safety fixtures, real_page
    test_config_real.py        -- (existing)
    test_audio_flow.py         -- (NEW: ported from bash checks 2-5,8-9)
    test_filter_deploy_real.py -- (NEW: reload-pw cycle, QE-recommended)
    test_loopback_measurement.py -- (NEW: pi-loopback tier, Phase 3)
```

### Conftest Layering

| File | Owns | Must NOT |
|------|------|----------|
| `tests/conftest.py` | Marker registration, `pytest_collection_modifyitems` tier-skip, shared fixtures (`local_demo_url`, `base_url`, `_probe_server`) | Set `PI_AUDIO_MOCK`, import `app.*`, mutate environment |
| `tests/unit/conftest.py` | `PI_AUDIO_MOCK=1`, `SessionConfig.__init__` patch, `client` fixture (TestClient) | Define markers or tier-skip logic |
| `tests/integration/conftest.py` | `mock_server` (uvicorn subprocess), Playwright `page`/`frozen_page`, destructive skip hook | Start real PipeWire or external services |
| `tests/e2e/conftest.py` | `_wait_for_stack`, `backend_type` fixture, `real_page` (Playwright against real backend), safety fixtures | Set mock mode, start mock server |

**Hook chaining:** Both root and integration `pytest_collection_modifyitems` hooks are additive (only add skip markers). Order is irrelevant — no `tryfirst`/`trylast` needed.

**Environment isolation:** Root conftest never sets `PI_AUDIO_MOCK`. Unit tests get mock=1 from `unit/conftest.py`. Integration tests get mock via `mock_server` subprocess. E2E tests connect to an externally-started stack. Running `pytest tests/` will not contaminate tiers.

---

## 4. Marker Taxonomy

### Tier markers (hierarchical)

```
needs_acoustic > needs_usb_audio > needs_pw > unmarked
```

| Marker | Meaning | Skipped when |
|--------|---------|-------------|
| (unmarked) | Runs on all tiers | Never |
| `needs_pw` | Requires real PipeWire | No PW detected (`pw-cli info` fails) |
| `needs_usb_audio` | Requires real USB audio device | No USBStreamer detected |
| `needs_acoustic` | Requires speakers + UMIK-1 + owner | `--owner-confirmed` not passed |

### Orthogonal markers

| Marker | Meaning | Gate |
|--------|---------|------|
| `destructive` | Modifies system state (destroys nodes, changes quantum) | `--destructive` CLI flag |
| `audio_producing` | Sends audio through speakers | `--owner-confirmed` CLI flag |
| `slow` | Takes >10s | No gate (informational) |

### pytest selection by tier

```bash
# CI: mock only
pytest tests/unit/ tests/integration/

# Local-demo: real PipeWire, no hardware
pytest tests/e2e/ -m "not needs_usb_audio"

# Pi-loopback: real USB audio, no speakers
pytest tests/e2e/ -m "not needs_acoustic" --loopback-confirmed

# Pi-full: everything, owner present
pytest tests/e2e/ --owner-confirmed --destructive
```

### Auto-skip logic (root conftest)

```python
def pytest_collection_modifyitems(config, items):
    pw_available = _check_pw_available()
    usb_audio_available = _check_usb_audio()
    owner_confirmed = config.getoption("--owner-confirmed", default=False)

    for item in items:
        if "needs_pw" in item.keywords and not pw_available:
            item.add_marker(pytest.mark.skip(reason="No PipeWire available"))
        if "needs_usb_audio" in item.keywords and not usb_audio_available:
            item.add_marker(pytest.mark.skip(reason="No USB audio device"))
        if "needs_acoustic" in item.keywords and not owner_confirmed:
            item.add_marker(pytest.mark.skip(reason="Requires --owner-confirmed"))
```

---

## 5. Safety Constraints

### Constraint Matrix

| Constraint | mock | local-demo | pi-loopback | pi-full |
|---|---|---|---|---|
| `--owner-confirmed` | n/a | n/a | n/a | REQUIRED per-test |
| `--loopback-confirmed` | n/a | n/a | REQUIRED per-session | n/a |
| signal-gen -20 dBFS pre-check (S-2) | n/a | YES | YES | YES |
| D-009 gain write validation (S-3) | n/a | YES | YES | YES |
| No PW restart (S-4) | n/a | WARN | GATE (`--loopback-confirmed`) | GATE (`--owner-confirmed`) |
| Safe teardown (S-5) | n/a | YES | YES | YES |

### S-1: Human gate for audio-producing tests

```python
@pytest.fixture(autouse=True, scope="session")
def _check_audio_gate(request):
    if request.config.getoption("--owner-confirmed", default=False):
        return  # Owner attested safety
    # Skip any test marked audio_producing
    # (handled by pytest_collection_modifyitems)
```

### S-2: Signal-gen safety pre-check

```python
@pytest.fixture(autouse=True, scope="session")
def _check_signal_gen_level(backend_type):
    if backend_type == "mock":
        return
    resp = httpx.get(f"{SIGNAL_GEN_URL}/status")
    status = resp.json()
    assert status["max_level_dbfs"] <= -20.0, \
        f"ABORT: signal-gen level {status['max_level_dbfs']} dBFS exceeds -20 dBFS cap"
```

### S-3: Gain write validation (D-009)

```python
@pytest.fixture
def safe_gain_writer(base_url):
    def write_gain(channel: str, mult: float):
        assert mult <= 1.0, f"D-009 violation: mult={mult} > 1.0"
        assert mult >= 0.0, f"Invalid gain: mult={mult} < 0.0"
        return httpx.post(f"{base_url}/api/v1/config/gain",
                          json={"channel": channel, "mult": mult})
    return write_gain
```

### S-4: No PW restart

Tests must NOT restart PipeWire on any real backend. On pi-loopback and pi-full, PW restart risks USBStreamer transients. Tests needing clean PW state must use `@pytest.mark.destructive` gated behind the appropriate CLI flag.

### S-5: Safe teardown with validated restore

```python
@pytest.fixture
def gain_restore(safe_gain_writer, base_url):
    """Capture gain state before test, restore after."""
    original = httpx.get(f"{base_url}/api/v1/config").json()["gains"]
    yield
    for channel, mult in original.items():
        safe_gain_writer(channel, mult)  # D-009 validated even on restore
```

### Pi-loopback physical safety

The software has NO WAY to verify that speakers are disconnected. The `--loopback-confirmed` flag is a human attestation that transfers physical-safety responsibility to the operator. Without it, the framework assumes speakers are connected and enforces full pi-full safety constraints.

**Loopback setup:** Physical patch cables from ADA8200 analog outputs to ADA8200 analog inputs, per channel. No software routing shortcut.

---

## 6. Tier Validation Boundaries

### What each tier validates vs. does NOT validate

| Tier | Validates | Does NOT validate |
|---|---|---|
| **mock** | UI rendering, HTTP routing, form validation, SVG interaction, WebSocket message handling | Any backend behavior, any PipeWire interaction, any real data |
| **local-demo** | Real PW behavior, pw-dump parsing, gain node mutation, mode transitions, graph topology with software nodes, convolver reload cycle, filter deployment | USB audio timing, hardware node properties, real gain staging, xrun behavior |
| **pi-loopback** | USB audio timing, hardware node discovery (F-246 class), signal path integrity, gain staging end-to-end (D-009 verification), filter application (correct coefficients on correct channels), electrical latency baseline, xrun behavior under USB isochronous pressure | Room correction effectiveness, acoustic time alignment, thermal/mechanical protection under real load, impedance interactions, acoustic crosstalk |
| **pi-full** | Everything pi-loopback validates + room correction effectiveness, acoustic measurements, SPL accuracy, real-load thermal behavior, UMIK-1 calibration | Nothing — full verification tier |

### Pi-loopback false confidence risks (documented, mitigated)

1. **Flat response hides correction failures.** ADA8200 loopback is +/-0.5 dB flat. "Room correction verification" tests pass trivially. **Mitigation:** Tests must distinguish "filter application" from "acoustic outcome" in names and assertions.

2. **No impedance/load interaction.** US-092 thermal model accuracy untestable. **Mitigation:** Thermal protection tests on loopback verify gain clamping fires, not model fidelity.

3. **No acoustic propagation delay.** Loopback: sub-millisecond. Real speakers: 3-30ms. **Mitigation:** Time alignment tests parametrize expected delay ranges per tier.

4. **Electrical crosstalk != acoustic crosstalk.** ADA8200 isolation ~80-90 dB vs frequency-dependent acoustic coupling. **Mitigation:** Channel isolation tests on loopback note electrical-only scope.

5. **No transient danger.** USBStreamer transients into loopback = harmless. **Mitigation:** Safety mechanism tests verify software fires but cannot verify hardware protection.

---

## 7. Test Classification

### Current tests by tier requirement

| Tier | File count | Test count (approx) |
|------|-----------|---------------------|
| Mock (unit/ + integration/) | 22 + 20 = 42 files | ~250 tests |
| Local-demo (e2e/) | 3+1 files | ~25 tests |
| Pi-loopback (e2e/) | 0 (NEW: ~15 proposed) | ~15 tests |
| Pi-full (e2e/) | 0 (future) | TBD |

### US-090/092-097 backend requirements

| Story | AC | Minimum tier |
|-------|-----|-------------|
| US-090 | Filter form layout, progress indicator | mock |
| US-090 | Apply Filters (`pw-cli s` via `set_mult()`) | local-demo |
| US-090 | D-009 compliance check | local-demo |
| US-090 | Convolver reload (`pw-cli destroy` cycle) | local-demo |
| US-092 | Thermal ceiling on config activation | local-demo |
| US-092 | Hard limit enforcement (gain clamp) | local-demo |
| US-092 | Profile switch timing | local-demo |
| US-092 | SPL feedback limiting | pi-full |
| US-092 | Xmax mechanical protection | pi-full |
| US-093 | Amp config form CRUD | mock |
| US-093 | Calibration computation (real DAC config) | local-demo |
| US-094 | ISO 226 display, SPL selector | mock |
| US-095 | Pan/zoom SVG interaction | mock |
| US-095 | Graph shows real PW topology | local-demo |
| US-095 | Verified on Pi | pi-loopback (minimum) |
| US-096 | Calibration verification | pi-full |
| US-097 | Steps 3,4,5,9 (sweep + capture) | pi-full |

---

## 8. New Tests to Write

### Phase 1b: E2E infrastructure + new tests

**Port from bash (`test-integration.sh` checks 2-5, 8-9):**
- `test_gm_get_graph_info` — GM RPC returns valid graph info
- `test_gm_get_links` — GM RPC returns link list
- `test_level_bridge_levels` — level-bridge returns current levels (x2 instances)
- `test_timestamp_monotonicity` — pcm-bridge timestamps increase monotonically
- `test_pcm_bridge_v2_header` — pcm-bridge v2 response has correct header

**7 new API-only tests:**
- `test_config_gains_real` — GET /api/v1/config returns real PW gain values
- `test_config_gain_write_readback` — POST gain, GET verifies change persisted
- `test_graph_topology_real` — GET /api/v1/graph/topology returns real node/link data
- `test_mode_transition_dj` — POST mode=dj, verify graph topology changes
- `test_mode_transition_live` — POST mode=live, verify graph topology changes
- `test_quantum_change` — Verify quantum metadata changes on mode transition
- `test_status_real` — GET /api/v1/status against real stack

### Phase 2: Reload-pw tests (QE-recommended)

**`test_filter_deploy_real.py` (3-5 tests, `@pytest.mark.needs_pw` + `@pytest.mark.destructive`):**
- `test_reload_pw_requires_confirmation` — POST without confirmed=true returns 400
- `test_reload_pw_succeeds` — POST with confirmed=true returns 200 (exercises `pw-cli destroy`)
- `test_convolver_recovers_after_reload` — After reload, GET /api/v1/config returns gains (GM re-links)
- `test_filter_versions_lists_real_coeffs` — GET /api/v1/filters/versions returns entries
- `test_deploy_crossover_only` — POST deploy with crossover_only mode (lower priority)

Note: Convolver auto-recreate is PipeWire filter-chain module behavior (not WirePlumber). Verified viable on both local-demo and pi-loopback.

### Phase 3: Pi-loopback tests

**`test_loopback_measurement.py` (~15 tests, `@pytest.mark.needs_usb_audio`):**
- USB audio device enumeration (UMIK-1, USBStreamer visible as ALSA devices)
- Real DAC/ADC round-trip latency (signal-gen -> USBStreamer out -> ADA8200 loopback -> in)
- Real gain staging verification (D-009 Mult values produce expected dBFS)
- Frequency response flatness (+/-3 dB 20Hz-20kHz on loopback)
- IR is clean impulse (energy ratio > 0.5, opposite of room-sim test)
- Correction filter is near-unity (flat loopback needs no correction)
- Thermal behavior under sustained audio load

Latency thresholds: Phase 1 wide range (0.5-10ms) for discovery, Phase 2 tighten to +/-1ms around measured ADA8200 baseline (expected 1-3ms for sigma-delta converters at 48kHz).

---

## 9. Nix Run Targets

| Target | Backend | Command |
|--------|---------|---------|
| `nix run .#test-unit` | mock | `pytest tests/unit/` |
| `nix run .#test-integration-browser` | mock (subprocess) | `pytest tests/integration/` |
| `nix run .#test-e2e` | local-demo | `local-demo.sh bg && pytest tests/e2e/ -m "not needs_usb_audio"` |
| `nix run .#test-pi-loopback` | pi-loopback | `pytest tests/e2e/ -m "not needs_acoustic" --loopback-confirmed` |
| `nix run .#test-pi-full` | pi-full | `pytest tests/e2e/ --owner-confirmed --destructive` |

---

## 10. Migration Plan

### Phase 1a: Conftest Restructuring (pure refactoring, zero new tests)

1. Create `tests/unit/` directory
2. Create `tests/unit/conftest.py` with `PI_AUDIO_MOCK=1`, `SessionConfig` patch, `client` fixture
3. Move 22 test files from `tests/` root to `tests/unit/` (`git mv`)
4. Strip root `tests/conftest.py` to: marker registration, tier-skip `pytest_collection_modifyitems`, shared fixtures only
5. Update nix run targets (`test-unit` replaces old `test` target)
6. Verify: `pytest tests/unit/` passes identically to previous `pytest tests/`

**Files moved to `tests/unit/` (22 total):**

Uses `client` fixture (15):
test_calibration.py, test_calibration_verify.py, test_collectors.py,
test_filter_routes.py, test_graph_routes.py, test_hardware_routes.py,
test_measurement_integration.py, test_measurement_pipeline_integration.py,
test_pcm_mode2.py, test_server.py, test_speaker_lifecycle_integration.py,
test_speaker_routes.py, test_thermal_limiter.py, test_thermal_monitor.py,
test_thermal_wiring.py

Inherits mock environment (7):
test_activate_integration.py, test_audio_mute.py, test_measurement_session.py,
test_phase1_validation.py, test_protection_integration.py, test_pw_helpers.py,
test_spa_config_parser.py

### Phase 1b: E2E Infrastructure + New Tests

1. Add shared fixtures to root `tests/conftest.py` (`local_demo_url`, `_probe_server`, `base_url`)
2. Enhance `tests/e2e/conftest.py` with `backend_type` detection, safety fixtures, `real_page`
3. Port bash checks 2-5, 8-9 to `tests/e2e/test_audio_flow.py`
4. Add 7 new API-only tests to `tests/e2e/`
5. Add `nix run .#test-pi-loopback` and `nix run .#test-pi-full` targets to `flake.nix`
6. Deprecate `scripts/test-integration.sh` (owner decision: deprecate entirely once ported)

### Phase 2: Reload-pw + Mock Data Refresh

1. Create `tests/e2e/test_filter_deploy_real.py` (3-5 tests)
2. Update stale mock data in `app/mock/mock_data.py` (remove `cdsp_state`, fix `chunksize`, make `gm_links_desired` dynamic)
3. Add capture-replay mechanism for pw-dump snapshots (CI data shape validation)

### Phase 3: Pi-Loopback Tests

1. Create `tests/e2e/test_loopback_measurement.py` (~15 tests)
2. Create `tests/e2e/test_usb_device_discovery.py`
3. Measure ADA8200 DAC/ADC baseline latency, tighten test thresholds

---

## 11. Open Items (Owner Decisions — RESOLVED)

1. **`test-integration.sh` deprecation:** YES — deprecate entirely once checks are ported to pytest.
2. **Pi loopback physical setup:** Physical patch cables (ADA8200 output -> input per channel). No software routing.
3. **Pi-full test cadence:** Full releases only, not per-commit or per-session.

---

## 12. Approvals

| Role | Status | Key contributions |
|------|--------|-------------------|
| Architect | APPROVED | Two-axis model, safety matrix, tier boundaries, conftest layering, Phase 1a/1b split |
| QE | APPROVED | 17/3/0 test classification, marker hierarchy, conftest PI_AUDIO_MOCK risk, reload-pw gap, loopback measurement analysis |
| AD | APPROVED | 5 loopback false confidence risks, 4 mitigations, mock-as-code-path-bypass analysis, per-story AC classification, 5 blocking safety constraints |
| Owner | ANSWERED | 3 open questions resolved (deprecate shell tests, physical loopback, release-only pi-full) |
