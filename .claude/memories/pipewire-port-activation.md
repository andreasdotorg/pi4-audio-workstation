# PipeWire Port Activation Model

## Topic: WirePlumber required for port activation on all node types except loopback (2026-03-29)

**Context:** Session 3 discovered adapter and filter-chain nodes need WP for port
activation. Session 4 (T-111-01 spike) confirmed spa-node-factory nodes also require
WP, completing the picture across all node factory types.

**Learning:** PipeWire 1.6.x requires WirePlumber for port activation on ALL node types:

| Node type | Factory | WP required? | Without WP |
|-----------|---------|--------------|------------|
| adapter (null-audio-sink, etc.) | `adapter` | YES | suspended, 0 ports |
| filter-chain | `filter-chain` module | YES | suspended, 0 ports |
| spa-node-factory | `spa-node-factory` | YES | error state, 0 ports |
| loopback | `loopback` module | NO | self-activating, ports created |

Without WP, nodes are created and `node.group` grouping is applied correctly,
but ports never appear. `support.node.driver` does not substitute for WP's
activation role — spa-node-factory with this flag enters `error` state instead
of `suspended`.

**Minimum viable WP config** for local-demo/embedded use (avoids WP auto-linking
that conflicts with GraphManager per D-039):
- `policy.standard = disabled` — no auto-linking
- `policy.node = required` — port activation still works

This is a **permanent architectural constraint** until upstream PipeWire changes
the activation model. D-056 (full WP removal) cannot proceed without an alternative
port activation mechanism.

**Source:** Architect, confirmed across sessions 3 and 4. Session 3: adapter +
filter-chain empirically verified by worker. Session 4: spa-node-factory verified
via T-111-01 spike (3 variants tested).

**Tags:** pipewire, wireplumber, port-activation, node-types, adapter, filter-chain,
spa-node-factory, loopback, D-056, D-039, architectural-constraint, local-demo
