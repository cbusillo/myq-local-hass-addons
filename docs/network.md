# Network setup and rollback

The stock firmware initiates its TLS connection to the vendor's endpoint. A
local listener alone will not redirect that connection. This app requires a
router capable of routing this one hub to the app.

Use a DHCP reservation for the hub and Home Assistant host. Scope destination
NAT to the hub's IPv4 source address and TCP destination port 8883; translate
the destination to Home Assistant's app port, default 18883. If your router
needs hairpin source NAT, restrict that rule to the same hub source and exact
Home Assistant destination/port, and configure that translated peer address
in the app.

Block the enrolled hub's direct WAN path in both IP versions. Preserve every
other client and existing broker port. Confirm rule order and generated rules,
not just that a router API accepted the configuration. Do not expose this app
listener on the public internet or make a router-wide TLS redirect.

Before applying, save the original rules and prepare their exact removal and
readback. Start with a bounded transaction and independent automatic rollback.
Power-cycle only the hub after the listener and routing are ready, so it creates
a fresh connection. The app does not operate an outlet itself.

To roll back: stop the app, remove only the owned hub-specific redirect and
isolation rules, verify the original router configuration, then reconnect the
hub normally. Confirm cloud connectivity independently; a restored router
configuration alone is not proof the hub reconnected.

Local mode replaces the cloud connection, so the native myQ app can appear
offline during local operation. No configuration on an existing MQTT broker
needs to be replaced or reset.
