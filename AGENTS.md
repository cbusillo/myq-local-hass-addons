# myQ Local

Keep product code and tests portable. Never add real enrollment files, firmware,
raw captures, device identifiers, credentials, or private topology to Git.

Use uv and the gates in README.md. Tests use invented credentials and loopback
or isolated containers. Live motion requires an owner who is watching a clear
door, and one explicit command followed by their observation. Do not retry a
motion request after an uncertain send.

Keep protocol evidence separate from packaged, installed, and owner-observed
acceptance. Unknown status bits are not safety interlocks or battery readings.

Preserve the existing Home Assistant broker and HomeKit exposure. The app starts
with controls disabled. Router changes are outside product source and require
exact scope, rollback, and independent validation.
