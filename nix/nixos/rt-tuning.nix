# rt-tuning.nix — Runtime RT tuning for the Pi 4 Audio Workstation
#
# Kernel build configuration (PREEMPT_RT, structuredExtraConfig) lives in
# kernel-rt.nix. This module covers runtime tuning: sysctls and CPU governor.
#
# F-291: PipeWire was hitting the default 95% RT throttle under sustained
# load, causing periodic scheduling delays and xruns.
#
# Security review: approved by Security Specialist — single-user dedicated
# workstation on PREEMPT_RT, no untrusted users, no starvation risk.
{ config, lib, pkgs, ... }:

{
  # ── RT throttle: disabled ───────────────────────────────────────────
  # Default: 950000 (95% of each 1s period). A safety net for non-RT
  # kernels to prevent a runaway FIFO task from starving the system.
  # On PREEMPT_RT, all kernel work (including interrupt handlers) is
  # preemptible, so the starvation scenario doesn't apply. The throttle
  # causes periodic scheduling delays for PipeWire's RT thread under
  # sustained load, producing xruns.
  # BCM2835 hardware watchdog provides a backstop for true lockups.
  boot.kernel.sysctl."kernel.sched_rt_runtime_us" = -1;

  # ── CPU governor: performance ───────────────────────────────────────
  # Dedicated audio workstation — dynamic frequency scaling (ondemand,
  # schedutil) causes variable latency with zero benefit. The Pi 4 runs
  # at a fixed 1.8 GHz. Thermal management is handled by the kernel's
  # thermal governor (BCM2835_THERMAL + THERMAL_GOV_STEP_WISE) which
  # throttles independently of cpufreq if temperature exceeds limits.
  powerManagement.cpuFreqGovernor = "performance";
}
