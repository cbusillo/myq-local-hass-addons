"""Bounded, read-only acquisition for the maintained G0401 profile."""

from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
from pathlib import Path


class AcquisitionError(ValueError):
    """The programmer operation could not produce verified input."""


PAGE_BASE = 0x202000
PAGE_SIZE = 4096
PAGE_COUNT = 3
EXPECTED_DPIDR = "0x6ba02477"
EXPECTED_AP1 = "0x84770001"
MIN_TARGET_VOLTAGE = 3.0
MAX_TARGET_VOLTAGE = 3.6


def find_openocd(explicit: Path | None = None) -> Path:
    candidate = str(explicit) if explicit is not None else shutil.which("openocd")
    if not candidate:
        raise AcquisitionError("openocd_0_12_not_found")
    path = Path(candidate).expanduser().resolve()
    if not path.is_file() or not os.access(path, os.X_OK):
        raise AcquisitionError("openocd_0_12_not_found")
    return path


def _stop(process: subprocess.Popen[str]) -> None:
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=0.2)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()


def _run(argv: list[str], timeout: float) -> str:
    try:
        process = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )
    except OSError as error:
        raise AcquisitionError("openocd_could_not_start") from error
    try:
        try:
            output, _ = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired as error:
            _stop(process)
            raise AcquisitionError("openocd_timed_out") from error
        except BaseException:
            _stop(process)
            raise
    finally:
        if process.stdout is not None:
            process.stdout.close()
    if process.returncode != 0:
        raise AcquisitionError("openocd_operation_failed")
    return output


def _require_supported_version(openocd: Path) -> None:
    output = _run([str(openocd), "--version"], 5)
    if not re.search(r"Open On-Chip Debugger 0\.12\.0(?:\s|$)", output):
        raise AcquisitionError("openocd_version_must_be_0_12_0")


def _connection_preflight(openocd: Path, config: Path) -> float:
    output = _run([str(openocd), "-f", str(config), "-c", "init; shutdown"], 10)
    identities = re.findall(r"\bSWD DPIDR (0x[0-9a-fA-F]+)", output)
    if identities != [EXPECTED_DPIDR]:
        raise AcquisitionError("unexpected_or_missing_debug_port_identity")
    voltages = re.findall(r"Target voltage:\s*([0-9]+(?:\.[0-9]+)?)", output)
    if len(voltages) != 1:
        raise AcquisitionError("target_voltage_unavailable")
    voltage = float(voltages[0])
    if not MIN_TARGET_VOLTAGE <= voltage <= MAX_TARGET_VOLTAGE:
        raise AcquisitionError("target_voltage_outside_supported_range")
    return voltage


def _parse_page(output: str, address: int) -> bytes:
    dpidr = re.findall(r"^DPIDR (0x[0-9a-fA-F]+)$", output, re.MULTILINE)
    ap1 = re.findall(r"^AP1_IDR (0x[0-9a-fA-F]+)$", output, re.MULTILINE)
    if dpidr != [EXPECTED_DPIDR] or ap1 != [EXPECTED_AP1]:
        raise AcquisitionError("programmer_identity_changed")
    if re.search(r"^Error\s*:", output, re.MULTILINE):
        raise AcquisitionError("openocd_reported_error")
    words = [
        (int(raw_address, 16), int(raw_value, 16))
        for raw_address, raw_value in re.findall(
            r"^PAGE_WORD (0x[0-9a-fA-F]+) (0x[0-9a-fA-F]+)$",
            output,
            re.MULTILINE,
        )
    ]
    expected_addresses = list(range(address, address + PAGE_SIZE, 4))
    if [word_address for word_address, _ in words] != expected_addresses:
        raise AcquisitionError("page_read_incomplete_or_misaddressed")
    if f"PAGE_COMPLETE {address} {PAGE_SIZE};" not in output:
        raise AcquisitionError("page_completion_marker_missing")
    return b"".join(value.to_bytes(4, "little") for _, value in words)


def acquire_g0401_pages(openocd_path: Path | None = None) -> tuple[bytes, float]:
    """Read the three credential pages twice and return them only when they match."""
    openocd = find_openocd(openocd_path)
    resources = Path(__file__).with_name("openocd")
    config = resources / "g0401.cfg"
    operation = resources / "read_g0401_page.tcl"
    if not config.is_file() or not operation.is_file():
        raise AcquisitionError("openocd_resources_unavailable")
    _require_supported_version(openocd)
    voltage = _connection_preflight(openocd, config)
    pages = []
    for page in range(PAGE_COUNT):
        address = 0x08000000 + PAGE_BASE + page * PAGE_SIZE
        reads = []
        for _read in range(2):
            output = _run(
                [
                    str(openocd),
                    "-f",
                    str(config),
                    "-f",
                    str(operation),
                    "-c",
                    f"read_g0401_page_once {address} {PAGE_SIZE}",
                ],
                30,
            )
            reads.append(_parse_page(output, address))
        if reads[0] != reads[1]:
            raise AcquisitionError("repeated_page_read_mismatch")
        pages.append(reads[0])
    return b"".join(pages), voltage
