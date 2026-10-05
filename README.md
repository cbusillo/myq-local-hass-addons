# myQ Local

Experimental local control of a **stock MYQ-G0401-ES hub, firmware 1.10**, with
an HBW9546 door sensor. A Home Assistant app terminates the hub's per-device
TLS-PSK connection and presents an MQTT garage-door cover through your existing
broker. No replacement broker or firmware flashing is involved.

The protocol was validated with an owner-observed local open/close cycle and
matching sensor reports on one specimen. The packaged app is a separate
validation target. Other hardware and firmware versions are not qualified.

## Installation

1. In Home Assistant, open **Settings → Add-ons → Add-on Store**, use the
   three-dot menu → **Repositories**, and add
   `https://github.com/cbusillo/myq-local-hass-addons`. Then install **myQ
   Local** from the store. Installing the local `myq_local` directory as a
   local app also works; this source tree includes `repository.yaml` and the
   app's `config.yaml` and Dockerfile.
2. Set **Hub IP** to the hub's reserved IPv4 address. If your router applies
   source NAT when forwarding the hub, set **Translated peer IP** to that
   router's LAN address. Leave **Control enabled** off initially.
3. Start the app and open its web UI. Import your private `enrollment.json`
   file. Restart the app after importing or replacing enrollment.
4. Redirect **only this hub's TCP 8883** connection to the Home Assistant
   host's app port, default **18883**. Block that hub's direct cloud path,
   including IPv6. See [network setup](docs/network.md). The app does not
   change your router automatically.
5. Confirm the MQTT cover reports the actual door state. Test sensor reception
   in its final garage mounting location.
6. Enable **Control enabled** and restart the app only when ready for a
   supervised open/close qualification. The cover exposes open and close;
   stop and percentage positioning are deliberately absent because they have
   not been established for this hub.

The app obtains broker connection details from Supervisor's existing MQTT
service. If that service advertises credentials that your broker overrides,
set **MQTT username** and **MQTT password** to your existing broker login in
this app's configuration. Leave both blank for automatic service credentials;
the broker address and TLS settings still come from Supervisor. These options
are stored privately by Supervisor and may be included in app backups. This
app does not create users or restart the broker. Its setup web UI is exposed through Home Assistant ingress, not a
separate host web port. Keep the hub listener LAN-only.

## One-time enrollment

The current proven enrollment route requires a one-time hardware read of
per-device credentials. A hardware-free enrollment path has not been found;
this is not proof that one is impossible. Once the enrollment file is imported,
ordinary operation does not use a programmer or firmware image.

The first package imports an expert-prepared bundle. A reproducible guided
acquisition and sensor-binding wizard for other owners is still needed before
claiming a consumer-ready installation. See [enrollment](docs/enrollment.md).

Keep enrollment private. It contains the device identity, TLS PSK, and paired
door identifier. Never publish it, a raw firmware image, or an unredacted
capture in an issue. The app does not return enrollment contents in its web UI
or diagnostics. App data and Home Assistant backups may contain the key.

## State and command behavior

Only freshly authenticated, target-matched status reports drive availability.
State `2` is closed; state `9` is not closed. The Home Assistant cover uses
`open` for not-closed, which includes partial opening; it does not claim 100%
travel. Commands do not optimistically change state. Unknown or stale status
makes the cover unavailable.

Motion requires an explicit `OPEN` or `CLOSE` publication, controls enabled,
a current hub connection and matching fresh state. Retained and duplicate
commands are rejected. Commands expire after two seconds in the bridge queue;
MQTT and hub reconnections discard pending requests. MQTT 5 command messages
require a positive expiry no greater than two seconds; the discovery config
sets this using Home Assistant's built-in message expiry. A paused control
loop also rejects commands until it resumes. Network delivery time after a
broker sends a message is still a qualification limit. A write is never retried.
If movement remains unconfirmed, the session rejects further movement until a
matching status transition or a fresh connection. Check the physical door
before restarting the app in that situation.

This app is not an independent safety system. The opener's physical safety
controls remain authoritative; use the wall control or remote when needed.
Do not infer obstruction or battery condition from the currently uninterpreted
status bits.

## Development

Python 3.13+ with an OpenSSL build supporting TLS-PSK is required; the app image
uses Python 3.14. Dependencies are locked with uv.

```sh
uv sync
uv run python -m unittest discover -s tests -v
uv run ruff check .
uv run ruff format --check .
uv build
docker build -t myq-local:0.1.0-test myq_local
uv run python tests/container_smoke.py
```

The container smoke test creates and removes an isolated MQTT broker and app.
Its hub runs on loopback with invented credentials; it never contacts a real
garage device. [Protocol evidence](docs/protocol.md) separates field validation
from synthetic tests and remaining gaps.

## Credits and license

This project is **AGPL-3.0-or-later**. Its design is adapted from
[StanleyCA/MyQ-Security2.0-HomeAssistant](https://github.com/StanleyCA/MyQ-Security2.0-HomeAssistant)
(AGPL-3.0), a local myQ bridge for the 050DCTWF logic board; this project adapts
that approach to the stock MYQ-G0401-ES hub and re-implements the runtime for
that hardware. See [CREDITS.md](CREDITS.md) for full attribution, including the
additional research consulted. The AGPL firmware/capture research tools used
during discovery are not included in this runtime package. myQ and Chamberlain
are trademarks of the Chamberlain Group; this project is not affiliated with
Chamberlain Group.
