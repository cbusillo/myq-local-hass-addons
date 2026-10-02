"""Private enrollment storage; credentials never enter diagnostics or argv."""

import json
import os
import re
import stat
import tempfile
from dataclasses import dataclass, field
from pathlib import Path


class InvalidProfile(ValueError):
    pass


@dataclass(frozen=True)
class Profile:
    identity: bytes = field(repr=False)
    psk: bytes = field(repr=False)
    door_id: bytes = field(repr=False)

    @classmethod
    def parse(cls, payload: bytes):
        if len(payload) > 4096:
            raise InvalidProfile("profile_too_large")
        try:
            row = json.loads(payload)
            if set(row) != {"schema", "model", "identity", "psk", "door_id"}:
                raise ValueError()
            if (
                type(row["schema"]) is not int
                or row["schema"] != 1
                or row["model"] != "MYQ-G0401-ES"
            ):
                raise ValueError()
            for name, length in (("identity", 10), ("psk", 32), ("door_id", 12)):
                if not isinstance(row[name], str) or not re.fullmatch(
                    r"[0-9a-fA-F]{" + str(length) + "}", row[name]
                ):
                    raise ValueError()
            profile = cls(
                row["identity"].encode("ascii"),
                bytes.fromhex(row["psk"]),
                bytes.fromhex(row["door_id"]),
            )
            if profile.door_id[0] != 0x84:
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
