# Security Policy

## Supported Versions

Only the latest release of the add-on is supported. Fixes ship in a new release
built from `main`.

## Reporting a Vulnerability

Report suspected vulnerabilities privately through GitHub's
[Report a vulnerability](https://github.com/cbusillo/myq-local-hass-addons/security/advisories/new)
form. Do not open a public issue for a vulnerability.

Include the add-on version, the impact, and the smallest steps that reproduce
it.

Do not send enrollment files, credentials, device identifiers, raw captures,
network details, or other personal data. Use redacted or made-up values.

This is a single-maintainer project. Reports are handled on a best-effort
basis, and I aim to reply within seven days.

## Scope

This add-on can open and close garage doors, so reports about these are
especially important:

- moving a door without an explicit, authorized command;
- exposing enrollment material, credentials, or device identifiers;
- unsafe handling of data received from the device or the MQTT broker; and
- dependency, container image, or GitHub Actions supply-chain problems.

Problems in myQ device firmware or Chamberlain services should go to
Chamberlain.
