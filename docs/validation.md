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

Live installation and owner-observed acceptance belong in private local
operations evidence. No public repository or release has been published.
