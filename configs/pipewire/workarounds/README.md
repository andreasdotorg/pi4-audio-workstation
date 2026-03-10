# PipeWire Workarounds

Workaround configs for known PipeWire issues on the PREEMPT_RT kernel.
These are temporary fixes to be removed when the underlying issue is resolved.

---

## f020-pipewire-fifo.conf

**Defect:** F-020 -- PipeWire RT module fails to achieve SCHED_FIFO on PREEMPT_RT kernel
**Severity:** High
**Status:** Workaround (root cause unresolved)

### What it does

Systemd drop-in override that forces PipeWire to run with SCHED_FIFO priority 88.
This bypasses PipeWire's broken RT module self-promotion on PREEMPT_RT kernels.

### Why it is needed

PipeWire's `libspa-rt` module is configured for `rt.prio=88` but only achieves
`nice=-11` (SCHED_OTHER) on the PREEMPT_RT kernel. Without SCHED_FIFO, PipeWire
competes with GUI apps and system processes for CPU time, causing audible glitches
in the audio path.

### Approach chosen

**Option 2: systemd `CPUSchedulingPolicy=fifo`** was chosen over three alternatives:

| Option | Verdict | Reason |
|--------|---------|--------|
| 1. ExecStartPost with `chrt` | Rejected | Only promotes main PID, not worker threads. Timing-dependent -- PipeWire threads may not exist yet when ExecStartPost runs. |
| 2. systemd CPUSchedulingPolicy | **Chosen** | Applied at exec time before PipeWire starts. All forked threads inherit FIFO. Proven pattern (CamillaDSP F-018 uses this). |
| 3. udev rule | Rejected | udev manages devices, not userspace process scheduling. Not applicable. |
| 4. PipeWire config tuning | Rejected | The RT module IS loaded and configured (`rt.prio=88`) but fails to achieve FIFO on PREEMPT_RT. The config is correct; the module behavior is broken. No config knob can fix this. |

### Deployment

```bash
# On the Pi as user ela:
mkdir -p ~/.config/systemd/user/pipewire.service.d/
cp f020-pipewire-fifo.conf ~/.config/systemd/user/pipewire.service.d/override.conf
systemctl --user daemon-reload
systemctl --user restart pipewire.service
```

### Verification

```bash
# Check scheduling policy:
chrt -p $(pgrep -x pipewire)
# Expected: "current scheduling policy: SCHED_FIFO"
#           "current scheduling priority: 88"

# Check all PipeWire processes:
ps -eo pid,cls,rtprio,ni,comm | grep pipewire
# Expected: FF (FIFO) in CLS column, 88 in RTPRIO column
```

### Removal condition

Remove this workaround when either:
- The root cause of F-020 is identified and fixed (PipeWire RT module works on PREEMPT_RT)
- A PipeWire update resolves the self-promotion failure
- The project moves to a different audio server

To remove:
```bash
rm ~/.config/systemd/user/pipewire.service.d/override.conf
rmdir ~/.config/systemd/user/pipewire.service.d/  # if empty
systemctl --user daemon-reload
systemctl --user restart pipewire.service
```
