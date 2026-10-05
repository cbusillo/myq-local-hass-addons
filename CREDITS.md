# Credits and provenance

This project stands on prior work by others. It is licensed **AGPL-3.0-or-later**
to match its upstream foundation.

## Foundation

- **[StanleyCA/MyQ-Security2.0-HomeAssistant](https://github.com/StanleyCA/MyQ-Security2.0-HomeAssistant)**
  (AGPL-3.0). This project's design is adapted from StanleyCA's local myQ bridge:
  a device-facing TLS-PSK endpoint and Mosquitto broker, a Python protocol
  bridge, and a Home Assistant MQTT-discovery garage-door cover. StanleyCA's
  bridge targets the **050DCTWF** logic board (firmware 3.13). This project
  adapts that approach to a different device — the stock **MYQ-G0401-ES** hub
  (firmware 1.10) — and its runtime was re-implemented for that hardware rather
  than copied, but it would not exist without StanleyCA's work and documentation.

## Additional research consulted

- **[fuxxociety/MyQ-ESP-transplant](https://github.com/fuxxociety/MyQ-ESP-transplant)**
  — replacing a myQ Wi-Fi module with an ESP8266/ESPHome.
- **[wnayes — Notes on LiftMaster garage door openers with myQ](https://gist.github.com/wnayes/928247b6fa4afd1a6bfa773494dbec1f)**
  — protocol and service notes.
- **McAfee Labs, "We Be Jammin' — Bypassing Chamberlain myQ Garage Doors"**
  — background security research.

## Trademark

myQ and Chamberlain are trademarks of the Chamberlain Group. This project is not
affiliated with, endorsed by, or sponsored by the Chamberlain Group.
