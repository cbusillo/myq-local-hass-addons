"""Private enrollment storage; credentials never enter diagnostics or argv."""

import json
import os
import re
import secrets
import stat
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path


class InvalidProfile(ValueError):
    pass


@dataclass(frozen=True)
class Profile:
    identity: bytes = field(repr=False)
    psk: bytes = field(repr=False)
    door_id: bytes | None = field(default=None, repr=False)

    @property
    def bound(self) -> bool:
        return self.door_id is not None

    def payload(self) -> bytes:
        row = {
            "schema": 1 if self.bound else 2,
            "model": "MYQ-G0401-ES",
            "identity": self.identity.decode("ascii"),
            "psk": self.psk.hex(),
        }
        if self.door_id is not None:
            row["door_id"] = self.door_id.hex()
        return (json.dumps(row, indent=2) + "\n").encode()

    def bind(self, door_id: bytes) -> "Profile":
        if len(door_id) != 6 or door_id[0] != 0x84:
            raise InvalidProfile("invalid_door_id")
        return Profile(self.identity, self.psk, door_id)

    @classmethod
    def parse(cls, payload: bytes):
        if len(payload) > 4096:
            raise InvalidProfile("profile_too_large")
        try:
            row = json.loads(payload)
            if not isinstance(row, dict):
                raise TypeError()
            schema = row.get("schema")
            keys = {"schema", "model", "identity", "psk"}
            if schema == 1:
                keys.add("door_id")
            if (
                set(row) != keys
                or type(schema) is not int
                or schema not in (1, 2)
                or row["model"] != "MYQ-G0401-ES"
            ):
                raise ValueError()
            for name, length in (("identity", 10), ("psk", 32)):
                if not isinstance(row[name], str) or not re.fullmatch(
                    r"[0-9a-fA-F]{" + str(length) + "}", row[name]
                ):
                    raise ValueError()
            door_id = None
            if schema == 1:
                if not isinstance(row["door_id"], str) or not re.fullmatch(
                    r"[0-9a-fA-F]{12}", row["door_id"]
                ):
                    raise ValueError()
                door_id = bytes.fromhex(row["door_id"])
            profile = cls(
                row["identity"].encode("ascii"),
                bytes.fromhex(row["psk"]),
                door_id,
            )
            if profile.door_id is not None and profile.door_id[0] != 0x84:
                raise ValueError()
            return profile
        except (ValueError, TypeError, KeyError, UnicodeError):
            raise InvalidProfile("invalid_profile") from None

    @classmethod
    def load(cls, path: Path):
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            info = os.fstat(fd)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o600
            ):
                raise InvalidProfile("profile_requires_owner_only_file")
            return cls.parse(os.read(fd, 4097))
        finally:
            os.close(fd)


def save_profile(path: Path, payload: bytes):
    Profile.parse(payload)
    fd, name = tempfile.mkstemp(prefix=".enrollment-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


class EnrollmentState:
    """Private, process-local view of authenticated sensor-binding progress."""

    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.RLock()
        self.candidates = ()
        self.tokens = {}
        self.states = {}
        self.changes = {}

    def record_inventory(self, identifiers: tuple[bytes, ...]) -> None:
        compatible = tuple(sorted(value for value in identifiers if value[0] == 0x84))
        with self.lock:
            profile = Profile.load(self.path)
            if profile.bound:
                return
            old_tokens = self.tokens
            self.candidates = compatible
            self.tokens = {
                value: old_tokens.get(value, secrets.token_urlsafe(18))
                for value in compatible
            }
            self.states = {value: self.states.get(value) for value in compatible}
            self.changes = {value: self.changes.get(value, 0) for value in compatible}

    def record_state(self, identifier: bytes, state: int) -> None:
        if state not in (2, 9):
            return
        with self.lock:
            if identifier not in self.tokens:
                return
            previous = self.states.get(identifier)
            if previous is not None and previous != state:
                self.changes[identifier] += 1
            self.states[identifier] = state

    def status(self) -> dict[str, object]:
        with self.lock:
            if not self.path.exists():
                return {"enrolled": False, "bound": False, "candidates": []}
            profile = Profile.load(self.path)
            rows = []
            if not profile.bound:
                for index, identifier in enumerate(self.candidates, 1):
                    state = self.states.get(identifier)
                    rows.append(
                        {
                            "token": self.tokens[identifier],
                            "label": f"Sensor {index}",
                            "state": (
                                "closed"
                                if state == 2
                                else "not closed"
                                if state == 9
                                else "waiting"
                            ),
                            "changes": self.changes.get(identifier, 0),
                        }
                    )
            return {
                "enrolled": True,
                "bound": profile.bound,
                "candidates": rows,
            }

    def bind(self, token: str) -> None:
        with self.lock:
            matches = [
                identifier
                for identifier, candidate_token in self.tokens.items()
                if secrets.compare_digest(candidate_token, token)
            ]
            if len(matches) != 1:
                raise InvalidProfile("unknown_sensor_candidate")
            identifier = matches[0]
            if len(self.candidates) > 1 and self.changes.get(identifier, 0) == 0:
                raise InvalidProfile("sensor_identification_required")
            profile = Profile.load(self.path)
            if profile.bound:
                raise InvalidProfile("profile_already_bound")
            save_profile(self.path, profile.bind(identifier).payload())
