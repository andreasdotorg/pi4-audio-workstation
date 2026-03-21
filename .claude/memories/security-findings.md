# Security Findings

## Topic: F-036 VNC 8-character password limit (2026-03-21)

**Context:** Security specialist review of network-facing services.
**Learning:** VNC RFB protocol password auth is limited to 8 characters with
DES-based challenge-response. wayvnc uses this protocol. Currently Medium
severity -- escalates to High before US-018 (guest device access). Related to
existing F-013 (TLS for VNC). The password length limitation is a protocol
constraint, not a configuration issue.
**Source:** Security specialist defect filing in `docs/project/defects.md`.
**Tags:** f-036, vnc, wayvnc, rfb, password, des, authentication, us-018

## Topic: F-037 (HIGH) Web UI has no authentication (2026-03-21)

**Context:** Security specialist review identified that the FastAPI web UI on
port 8080 has no authentication mechanism.
**Learning:** Anyone on the local network can: control the signal generator via
`/ws/siggen`, trigger measurements, and access live PCM audio streams. TLS
(D-032) provides encryption but not authentication. The web UI service file
(`configs/systemd/user/pi4-audio-webui.service`) binds `0.0.0.0:8080` --
network-facing. Recommended fix: HTTP Basic Auth over TLS. This is HIGH
severity because the signal generator can produce audio output through the PA
system, making unauthenticated access a safety concern (ties into Section 3 of
safety.md -- signal-gen is the sole measurement output path).
**Source:** Security specialist defect filing in `docs/project/defects.md`.
**Tags:** f-037, web-ui, authentication, tls, signal-gen, safety, network, fastapi, port-8080
