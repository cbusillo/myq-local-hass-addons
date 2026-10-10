"""Local-only enrollment extraction for supported myQ hardware profiles."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import struct
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType


class EnrollmentError(ValueError):
    """The input cannot be turned into an unambiguous enrollment result."""


@dataclass(frozen=True)
class Credentials:
    model: str
    identity: bytes
    psk: bytes
    door_id: bytes

    def payload(self) -> bytes:
        identity_name = "serial" if self.model == "050DCTWF" else "identity"
        return (
            json.dumps(
                {
                    "schema": 1,
                    "model": self.model,
                    identity_name: self.identity.decode("ascii"),
                    "psk": self.psk.hex(),
                    "door_id": self.door_id.hex(),
                },
                indent=2,
            )
            + "\n"
        ).encode()


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise EnrollmentError("community_parser_unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_community_tools() -> tuple[ModuleType, ModuleType]:
    """Load the preserved upstream parser without changing its source."""
    packaged = Path(__file__).with_name("_community")
    source = Path(__file__).resolve().parents[3] / "community/050dctwf/analysis"
    root = packaged if packaged.is_dir() else source
    fwtool = _load_module("myq_community_fwtool", root / "fwtool.py")
    previous = sys.modules.get("fwtool")
    sys.modules["fwtool"] = fwtool
    try:
        psmtool = _load_module("myq_community_psmtool", root / "psmtool.py")
    finally:
        if previous is None:
            sys.modules.pop("fwtool", None)
        else:
            sys.modules["fwtool"] = previous
    return fwtool, psmtool


def _door_id(value: str) -> bytes:
    if not re.fullmatch(r"[0-9a-fA-F]{12}", value):
        raise EnrollmentError("door_id_requires_12_hex_characters")
    result = bytes.fromhex(value)
    if result[0] != 0x84:
        raise EnrollmentError("door_id_does_not_match_supported_sensor_family")
    return result


def extract_g0401(data: bytes, door_id: bytes) -> Credentials:
    if len(data) != 8 * 1024 * 1024:
        raise EnrollmentError("g0401_image_must_be_exactly_8_mib")
    _, psmtool = load_community_tools()
    base = 0x202000
    pages = []
    for page in range(3):
        offset = base + page * 4096
        header, limit = struct.unpack_from("<II", data, offset)
        if header & 0xFFFF == 0x635E and header >> 31 == 0:
            pages.append((header >> 16 & 0xFF, limit, offset))
    if not pages:
        raise EnrollmentError("g0401_append_log_not_found")
    sequences = [row[0] for row in pages]
    if len(sequences) != len(set(sequences)):
        raise EnrollmentError("g0401_append_log_generation_ambiguous")
    locations: dict[int, int] = {}
    for _sequence, limit, offset in sorted(pages, reverse=True):
        words = struct.unpack_from("<1024I", data, offset)
        end = max((i for i, word in enumerate(words) if word != 0xFFFFFFFF), default=1)
        if limit >> 31 == 0:
            end = min(end, (limit & 0xFFFF) - 1)
        for index in range(end if end % 2 else end - 1, 2, -2):
            header = words[index]
            logical = header & 0xFFFF
            kind = header >> 16 & 0xFF
            if header >> 31 == 0 and kind == 1 and logical % 4 == 0 and logical < 4096:
                locations.setdefault(logical, offset + (index - 1) * 4)
    try:
        identity = b"".join(
            data[locations[x] : locations[x] + 4] for x in range(0xE08, 0xE14, 4)
        )[:10]
        wrapped = b"".join(
            data[locations[x] : locations[x] + 4] for x in range(0xE14, 0xE24, 4)
        )
    except KeyError as exc:
        raise EnrollmentError("g0401_current_credential_record_incomplete") from exc
    if not re.fullmatch(rb"[0-9a-fA-F]{10}", identity):
        raise EnrollmentError("g0401_identity_invalid")
    return Credentials(
        "MYQ-G0401-ES", identity, psmtool.unwrap_myq_aes(wrapped), door_id
    )


def extract_050dctwf(data: bytes, door_id: bytes) -> Credentials:
    if len(data) not in (4 * 1024 * 1024, 8 * 1024 * 1024):
        raise EnrollmentError("050dctwf_image_must_be_4_or_8_mib")
    fwtool, psmtool = load_community_tools()
    tables = fwtool.find_partition_tables(data)
    if not tables:
        raise EnrollmentError("050dctwf_partition_table_not_found")
    table = max(tables, key=lambda item: item.generation)
    partitions = [entry for entry in table.entries if entry.name == "psm_seed"]
    if len(partitions) != 1:
        raise EnrollmentError("050dctwf_psm_seed_partition_ambiguous")
    part = partitions[0]
    records = psmtool.parse_records(data, part.start, part.size)

    def active(name: bytes, length: int) -> bytes:
        values = [
            row.value for row in records if row.state == 0xFF and row.name == name
        ]
        if len(values) != 1 or len(values[0]) != length:
            raise EnrollmentError(f"050dctwf_{name.decode()}_record_ambiguous")
        return values[0]

    identity = active(b"myq_sn", 10)
    if not re.fullmatch(rb"[0-9a-fA-F]{10}", identity):
        raise EnrollmentError("050dctwf_identity_invalid")
    psk = psmtool.unwrap_myq_aes(active(b"myq_aes", 16))
    return Credentials("050DCTWF", identity, psk, door_id)


def write_private(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(path, flags, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="myq-enroll")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("profiles", help="show the two hardware-specific enrollment paths")
    extract = sub.add_parser(
        "extract", help="extract credentials from an existing local image"
    )
    extract.add_argument("--model", required=True, choices=("MYQ-G0401-ES", "050DCTWF"))
    extract.add_argument("--image", required=True, type=Path)
    extract.add_argument("--door-id", required=True)
    extract.add_argument("--output", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "profiles":
        print(
            "MYQ-G0401-ES  maintained  ST-Link/SWD mapped read; direct acquisition remains gated"
        )
        print(
            "050DCTWF       community   CH341/SPI image; this tool imports an existing verified dump"
        )
        return 0
    try:
        data = args.image.read_bytes()
        door_id = _door_id(args.door_id)
        credentials = (
            extract_g0401(data, door_id)
            if args.model == "MYQ-G0401-ES"
            else extract_050dctwf(data, door_id)
        )
        write_private(args.output, credentials.payload())
    except (EnrollmentError, OSError, ValueError, struct.error) as error:
        print(f"Enrollment stopped: {error}", file=sys.stderr)
        return 2
    noun = (
        "Community credential bundle"
        if credentials.model == "050DCTWF"
        else "Enrollment"
    )
    print(f"{noun} written privately for {credentials.model}: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
