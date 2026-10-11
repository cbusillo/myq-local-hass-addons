"""Private enrollment storage; credentials never enter diagnostics or argv."""

import hmac
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
        self.changed = set()
        self.identifying = False
        self.inventory_seen = False
        self.candidate_identity = None

    def _clear_binding_state(self) -> None:
        self.candidates = ()
        self.tokens = {}
        self.states = {}
        self.changed = set()
        self.identifying = False
        self.inventory_seen = False
        self.candidate_identity = None

    def replace(self, payload: bytes) -> None:
        with self.lock:
            save_profile(self.path, payload)
            self._clear_binding_state()

    def record_inventory(self, identity: bytes, identifiers: tuple[bytes, ...]) -> None:
        compatible = tuple(sorted(value for value in identifiers if value[0] == 0x84))
        with self.lock:
            profile = Profile.load(self.path)
            if profile.bound:
                return
            if not hmac.compare_digest(profile.identity, identity):
                self._clear_binding_state()
                return
            same_inventory = compatible == self.candidates
            old_tokens = self.tokens
            self.candidates = compatible
            self.inventory_seen = True
            self.candidate_identity = identity
            self.tokens = {
                value: old_tokens.get(value, secrets.token_urlsafe(18))
                for value in compatible
            }
            self.states = {value: self.states.get(value) for value in compatible}
            if not same_inventory:
                self.changed = set()
                self.identifying = False

    def record_state(self, identifier: bytes, state: int) -> None:
        if state not in (2, 9):
            return
        with self.lock:
            if identifier not in self.tokens:
                return
            previous = self.states.get(identifier)
            if self.identifying and previous is not None and previous != state:
                self.changed.add(identifier)
            self.states[identifier] = state

    def start_identification(self) -> None:
        with self.lock:
            if len(self.candidates) <= 1 or any(
                self.states.get(identifier) is None for identifier in self.candidates
            ):
                raise InvalidProfile("sensor_baseline_unavailable")
            self.changed = set()
            self.identifying = True

    def status(self) -> dict[str, object]:
        with self.lock:
            if not self.path.exists():
                return {
                    "enrolled": False,
                    "bound": False,
                    "inventory_seen": False,
                    "identifying": False,
                    "ambiguous": False,
                    "candidates": [],
                }
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
                            "changed": identifier in self.changed,
                        }
                    )
            return {
                "enrolled": True,
                "bound": profile.bound,
                "inventory_seen": self.inventory_seen,
                "identifying": self.identifying,
                "ambiguous": len(self.changed) > 1,
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
            profile = Profile.load(self.path)
            if profile.bound:
                raise InvalidProfile("profile_already_bound")
            if self.candidate_identity is None or not hmac.compare_digest(
                profile.identity, self.candidate_identity
            ):
                raise InvalidProfile("binding_identity_changed")
            if len(self.candidates) > 1 and (
                not self.identifying or self.changed != {identifier}
            ):
                raise InvalidProfile("sensor_identification_required")
            save_profile(self.path, profile.bind(identifier).payload())
