# Experimental app validation

The first implementation received a read-only review by Google. The helper
requested Gemini 3.1 Pro (High); the CLI did not independently report the model.

- Reconnect availability: retained `offline` before subscription readiness is
  intentional. Current authenticated hub status restores availability within
  the two-second publication interval. Do not report online before readiness.
- Repeated publications: reproduced; state and availability are now published
  only when they change or a broker connection requires reseeding.
- Delivery freshness: app queue expiry alone does not bound broker delay.
  Discovery now uses Home Assistant's MQTT 5 `message_expiry_interval` of two
  seconds. The app rejects missing/expired/longer intervals and commands received
  while its control loop has been paused. Post-send network delivery time is
  still an explicit qualification gap; this is not a guarantee of end-to-end
  freshness under every network/host failure.

Seventeen product tests and an isolated container smoke test pass. The smoke test
uses a real broker and simulated TLS hub with invented credentials, rejects a
retained open, and exercises two explicit open/close cycles. It does not
establish installed Home Assistant or physical acceptance.

The setup UI was inspected in Chrome: initial layout readable, invalid file
rejected, invented valid file accepted with restart instruction. Narrow/mobile
viewport and HA ingress acceptance remain separate checks.

JetBrains inspection returned UNKNOWN / project_analysis_not_ready after its
internal retry budget. No clean IDE result is claimed.

## Installed acceptance

The packaged app passed an owner-observed Home Assistant test on one
MYQ-G0401-ES running firmware 1.10: exactly one open request and one close
request, physical full-open and closed confirmations, and corresponding Home
Assistant state reports. A restart also recovered fresh closed-state telemetry
without sending a motion command. The existing Home Assistant MQTT broker and
HomeKit exposure remained in use.

That acceptance does not qualify other hardware or firmware, prolonged service
stability, or a fresh installation by another owner.

## Enrollment acquisition acceptance

The packaged `myq-enroll acquire` command also passed an owner-observed run on
the same MYQ-G0401-ES. With an ST-Link/V2 attached to the documented J3 pins,
the command verified target voltage and debug identities, read each of the
three required credential pages twice, and refused to print or retain raw
firmware bytes. The resulting owner-only enrollment file matched the identity,
PSK, and door ID already accepted by the installed app. Temporary input and
output files were removed after comparison.

That result proves the bounded acquisition path on one specimen. Another owner
still needs to reproduce the fixture and workflow before it is described as a
consumer-ready installation.

## Sensor binding validation

The isolated container smoke test imports an unbound schema-2 enrollment,
authenticates a simulated hub with invented credentials, receives its paired
inventory, and confirms the one compatible sensor. It verifies that binding
sends no motion command and that Home Assistant discovery exposes no open or
close payload while the profile is unbound. After an app restart, the completed
schema-1 profile passes the existing state and explicit-command cycles.

Multiple-candidate tests require an observed state transition before a candidate
can be confirmed, preserve candidate labels across inventory reordering, and
never return raw device identifiers through the setup status endpoint. These
tests do not replace an owner-observed run against the installed hub.
