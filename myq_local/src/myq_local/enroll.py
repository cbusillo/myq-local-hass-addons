"""Local-only enrollment extraction for supported myQ hardware profiles."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import stat
import struct
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

from myq_local.acquire import AcquisitionError, acquire_g0401_pages


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
                    (
                        "device_id" if self.model == "050DCTWF" else "door_id"
                    ): self.door_id.hex(),
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


def _private_value(path: Path) -> str:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o600
        ):
            raise EnrollmentError("private_input_requires_owner_only_file")
        return os.read(fd, 128).decode("ascii").strip()
    finally:
        os.close(fd)


def _door_id(value: str, model: str) -> bytes:
    if not re.fullmatch(r"[0-9a-fA-F]{12}", value):
        raise EnrollmentError("door_id_requires_12_hex_characters")
    result = bytes.fromhex(value)
    if model == "MYQ-G0401-ES" and result[0] != 0x84:
        raise EnrollmentError("door_id_does_not_match_supported_sensor_family")
    return result


def _newest_sequence(pages: list[tuple[int, int, int]]) -> tuple[int, int, int]:
    if len(pages) == 1:
        return pages[0]
    candidates = []
    for candidate in pages:
        if all(
            candidate is other or 1 <= ((candidate[0] - other[0]) & 0xFF) <= 127
            for other in pages
        ):
            candidates.append(candidate)
    if len(candidates) != 1:
        raise EnrollmentError("g0401_append_log_generation_ambiguous")
    return candidates[0]


def extract_g0401_region(data: bytes, door_id: bytes) -> Credentials:
    if len(data) != 3 * 4096:
        raise EnrollmentError("g0401_region_must_contain_three_pages")
    _, psmtool = load_community_tools()
    pages = []
    for page in range(3):
        offset = page * 4096
        header, limit = struct.unpack_from("<II", data, offset)
        if header & 0xFFFF == 0x635E and header >> 31 == 0:
            pages.append((header >> 16 & 0xFF, limit, offset))
    if not pages:
        raise EnrollmentError("g0401_append_log_not_found")
    sequences = [row[0] for row in pages]
    if len(sequences) != len(set(sequences)):
        raise EnrollmentError("g0401_append_log_generation_ambiguous")
    _sequence, limit, offset = _newest_sequence(pages)
    locations: dict[int, int] = {}
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


def extract_g0401(data: bytes, door_id: bytes) -> Credentials:
    if len(data) != 8 * 1024 * 1024:
        raise EnrollmentError("g0401_image_must_be_exactly_8_mib")
    return extract_g0401_region(data[0x202000:0x205000], door_id)


def extract_050dctwf(data: bytes, door_id: bytes) -> Credentials:
    if len(data) not in (4 * 1024 * 1024, 8 * 1024 * 1024):
        raise EnrollmentError("050dctwf_image_must_be_4_or_8_mib")
    fwtool, psmtool = load_community_tools()
    tables = fwtool.find_partition_tables(data)
    if not tables:
        raise EnrollmentError("050dctwf_partition_table_not_found")
    generation = max(table.generation for table in tables)
    newest_tables = [table for table in tables if table.generation == generation]
    signatures = {
        tuple(
            (entry.name, entry.start, entry.size, entry.generation)
            for entry in table.entries
        )
        for table in newest_tables
    }
    if len(signatures) != 1:
        raise EnrollmentError("050dctwf_partition_table_generation_ambiguous")
    table = newest_tables[0]
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


def reserve_private(path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    try:
        os.fchmod(fd, 0o600)
    except BaseException:
        abort_private(path, fd)
        raise
    return fd


def finish_private(fd: int, payload: bytes) -> None:
    view = memoryview(payload)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise OSError("private_output_write_failed")
        view = view[written:]
    os.fsync(fd)
    os.close(fd)


def abort_private(path: Path, fd: int) -> None:
    try:
        os.close(fd)
    except OSError:
        pass
    finally:
        path.unlink(missing_ok=True)


def write_private(path: Path, payload: bytes) -> None:
    fd = reserve_private(path)
    try:
        finish_private(fd, payload)
    except BaseException:
        abort_private(path, fd)
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
    extract.add_argument("--door-id-file", required=True, type=Path)
    extract.add_argument("--output", required=True, type=Path)
    acquire = sub.add_parser(
        "acquire", help="read G0401 enrollment directly through an ST-Link/V2"
    )
    acquire.add_argument("--model", required=True, choices=("MYQ-G0401-ES",))
    acquire.add_argument("--firmware", required=True, choices=("1.10",))
    acquire.add_argument("--door-id-file", required=True, type=Path)
    acquire.add_argument("--output", required=True, type=Path)
    acquire.add_argument("--openocd", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "profiles":
        print(
            "MYQ-G0401-ES  maintained  guided ST-Link/SWD credential-page acquisition"
        )
        print(
            "050DCTWF       community   CH341/SPI image; this tool imports an existing verified dump"
        )
        return 0
    try:
        door_id = _door_id(_private_value(args.door_id_file), args.model)
        if args.command == "acquire":
            output_fd = reserve_private(args.output)
            try:
                print(
                    "Connect only ST-Link/V2 GND to J3 pin 3, SWDIO to pin 2, "
                    "and SWCLK to pin 4. Power the hub with its normal adapter. "
                    "Leave J3 pin 1, reset, SWIM, 3.3 V, and 5 V disconnected."
                )
                print(
                    "The reader performs one preflight and two reads of each of "
                    "three credential pages. It never resets, halts, or writes "
                    "target memory."
                )
                try:
                    confirmation = input("Type READY to begin: ")
                except EOFError as error:
                    raise EnrollmentError(
                        "fixture_confirmation_not_received"
                    ) from error
                if confirmation != "READY":
                    raise EnrollmentError("fixture_confirmation_not_received")
                region, voltage = acquire_g0401_pages(args.openocd)
                credentials = extract_g0401_region(region, door_id)
                finish_private(output_fd, credentials.payload())
            except BaseException:
                abort_private(args.output, output_fd)
                raise
            print(
                f"Connection verified at {voltage:.2f} V. Enrollment written "
                "privately for MYQ-G0401-ES after six matching page reads: "
                f"{args.output}"
            )
            return 0
        data = args.image.read_bytes()
        credentials = (
            extract_g0401(data, door_id)
            if args.model == "MYQ-G0401-ES"
            else extract_050dctwf(data, door_id)
        )
        write_private(args.output, credentials.payload())
    except (
        AcquisitionError,
        EnrollmentError,
        OSError,
        ValueError,
        struct.error,
    ) as error:
        print(f"Enrollment stopped: {error}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Enrollment stopped by user; no automatic retry.", file=sys.stderr)
        return 130
    noun = (
        "Community credential bundle"
        if credentials.model == "050DCTWF"
        else "Enrollment"
    )
    print(f"{noun} written privately for {credentials.model}: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
