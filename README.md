# myQ Local

Local Home Assistant bridges and research for supported myQ hardware. Start by
identifying the hardware and firmware you have because the enrollment and
protocol details are different.

| Hardware | Firmware | Project status | Start here |
| --- | --- | --- | --- |
| **MYQ-G0401-ES hub** with HBW9546 sensor | **1.10** | Current maintained target. The packaged app has passed an owner-observed Home Assistant open/close cycle on one specimen. | Continue with this README and the [enrollment guide](docs/enrollment.md). |
| **050DCTWF logic board** | **3.13** | Community reference imported from StanleyCA's tested project. The current maintainer does not own this hardware and cannot qualify changes on it yet. | Read the [050DCTWF community package](community/050dctwf/README.md). |

See [hardware support](docs/hardware-support.md) for the support boundary and
help identifying the applicable path.

The root Home Assistant app targets the **stock MYQ-G0401-ES hub, firmware
1.10**, with an HBW9546 door sensor. It terminates the hub's per-device TLS-PSK
connection and presents an MQTT garage-door cover through your existing broker.
No replacement broker or firmware flashing is involved.

The packaged app was validated with one explicit Home Assistant open request,
one explicit close request, owner-observed full-open and closed positions, and
matching sensor reports on one specimen. Other hardware and firmware versions
are not qualified by the current maintainer.

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

### One starting point

Run `uv run myq-enroll profiles` to identify the applicable enrollment path.
The assistant keeps the hardware-specific steps behind one command:

- `MYQ-G0401-ES` is the maintained profile. The current command can extract
  an enrollment bundle from an already acquired 8 MiB mapped image. Direct
  ST-Link acquisition remains gated until the removable fixture and complete
  preflight are documented and owner-observed.
- `050DCTWF` is a community profile. It accepts an existing verified 4 MiB or
  8 MiB SPI dump and reuses StanleyCA's preserved PSM parser. Hardware
  acquisition remains covered by the community flash guide.

For either model, supply the paired six-byte door ID as twelve hexadecimal
characters and choose a new output path. This example produces the G0401
bundle imported by the root app:

```sh
uv run myq-enroll extract \
  --model MYQ-G0401-ES \
  --image /private/path/to/your-image.bin \
  --door-id 84XXXXXXXXXX \
  --output /private/path/to/enrollment.json
```

The command refuses an existing output file, writes a new file with owner-only
permissions, and does not print credentials. Keep the input image and generated
file private. The 050DCTWF door ID still comes from its documented decrypted
MQTT capture workflow; dump parsing alone does not recover it. Its output is a
community credential bundle with `serial`, `psk`, and `door_id` fields for
the community app's configuration, rather than an import for the root G0401
app.

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
that hardware. StanleyCA's public 050DCTWF project is preserved under
[`community/050dctwf`](community/050dctwf/README.md) at a pinned source commit.
See [CREDITS.md](CREDITS.md) for full attribution, including the additional
research consulted. myQ and Chamberlain are trademarks of the Chamberlain
Group; this project is not affiliated with Chamberlain Group.
