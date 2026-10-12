import json
import os
import struct
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from myq_local.acquire import (
    PAGE_BASE,
    PAGE_COUNT,
    PAGE_SIZE,
    AcquisitionError,
    _parse_page,
    _run,
    acquire_g0401_pages,
)
from myq_local.enroll import (
    EnrollmentError,
    extract_050dctwf,
    extract_g0401,
    extract_g0401_region,
    load_community_tools,
    main,
)

DOOR = bytes.fromhex("841234567800")
IDENTITY = b"AA12345678"
KEY = bytes(range(16))


def wrapped_key():
    _, psmtool = load_community_tools()
    return psmtool.encrypt_block(KEY[:8]) + psmtool.encrypt_block(KEY[8:])


def g0401_image(old_sequence=19, new_sequence=20, omit_newest=()):
    data = bytearray(b"\xff" * (8 * 1024 * 1024))
    for page, sequence in ((1, old_sequence), (2, new_sequence)):
        base = 0x202000 + page * 4096
        struct.pack_into("<II", data, base, 0x635E | sequence << 16, 1024)
    base = 0x202000 + 2 * 4096
    values = {
        0xE08: IDENTITY[:4],
        0xE0C: IDENTITY[4:8],
        0xE10: IDENTITY[8:] + b"\0\0",
        **{
            0xE14 + offset: wrapped_key()[offset : offset + 4]
            for offset in range(0, 16, 4)
        },
    }
    cursor = 10
    for logical, value in values.items():
        if logical in omit_newest:
            continue
        struct.pack_into("<I", data, base + cursor * 4, int.from_bytes(value, "little"))
        struct.pack_into("<I", data, base + (cursor + 1) * 4, logical | 1 << 16)
        cursor += 2
    return bytes(data)


def record(name, value, object_id):
    return (
        b"\x55\xaa\xff"
        + struct.pack("<IHHB", 0, len(value), object_id, len(name))
        + name
        + value
    )


def image_050():
    data = bytearray(b"\xff" * (4 * 1024 * 1024))
    table = 0x4000
    data[table : table + 4] = b"WMPT"
    struct.pack_into("<HHII", data, table + 4, 1, 1, 5, 0)
    entry = table + 16
    struct.pack_into("<BB", data, entry, 1, 0)
    data[entry + 2 : entry + 10] = b"psm_seed"
    struct.pack_into("<III", data, entry + 12, 0x10000, 0x1000, 1)
    records = record(b"myq_sn", IDENTITY, 1) + record(b"myq_aes", wrapped_key(), 2)
    data[0x10000 : 0x10000 + len(records)] = records
    return bytes(data)


class EnrollmentTests(unittest.TestCase):
    def test_g0401_extracts_current_records(self):
        result = extract_g0401(g0401_image(), DOOR)
        self.assertEqual(
            (result.identity, result.psk, result.door_id), (IDENTITY, KEY, DOOR)
        )

    def test_g0401_defaults_to_unbound_enrollment(self):
        result = extract_g0401(g0401_image())
        payload = json.loads(result.payload())
        self.assertEqual(payload["schema"], 2)
        self.assertEqual(payload["identity"], IDENTITY.decode())
        self.assertEqual(payload["psk"], KEY.hex())
        self.assertNotIn("door_id", payload)

    def test_g0401_sequence_wrap_selects_zero_as_newest(self):
        result = extract_g0401(g0401_image(255, 0), DOOR)
        self.assertEqual(result.psk, KEY)

    def test_g0401_extracts_from_targeted_pages(self):
        image = g0401_image()
        result = extract_g0401_region(
            image[PAGE_BASE : PAGE_BASE + PAGE_COUNT * PAGE_SIZE], DOOR
        )
        self.assertEqual(
            (result.identity, result.psk, result.door_id), (IDENTITY, KEY, DOOR)
        )

    def test_g0401_never_mixes_credentials_across_pages(self):
        with self.assertRaisesRegex(EnrollmentError, "record_incomplete"):
            extract_g0401(g0401_image(19, 20, omit_newest=(0xE20,)), DOOR)

    def test_050_reuses_preserved_parser(self):
        result = extract_050dctwf(image_050(), DOOR)
        self.assertEqual(
            (result.identity, result.psk, result.door_id), (IDENTITY, KEY, DOOR)
        )

    def test_ambiguous_and_wrong_images_stop(self):
        with self.assertRaisesRegex(EnrollmentError, "8_mib"):
            extract_g0401(b"x", DOOR)
        duplicate = bytearray(image_050())
        extra = record(b"myq_sn", IDENTITY, 3)
        duplicate[0x10100 : 0x10100 + len(extra)] = extra
        with self.assertRaisesRegex(EnrollmentError, "record_ambiguous"):
            extract_050dctwf(bytes(duplicate), DOOR)

    def test_cli_writes_owner_only_file_without_secret_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "image.bin"
            output = Path(tmp) / "enrollment.json"
            image.write_bytes(g0401_image())
            stdout, stderr = StringIO(), StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = main(
                    [
                        "extract",
                        "--model",
                        "MYQ-G0401-ES",
                        "--image",
                        str(image),
                        "--output",
                        str(output),
                    ]
                )
            self.assertEqual(code, 0)
            self.assertEqual(os.stat(output).st_mode & 0o777, 0o600)
            payload = json.loads(output.read_text())
            self.assertEqual(payload["model"], "MYQ-G0401-ES")
            self.assertEqual(payload["psk"], KEY.hex())
            self.assertNotIn("door_id", payload)
            combined = stdout.getvalue() + stderr.getvalue()
            self.assertNotIn(IDENTITY.decode(), combined)
            self.assertNotIn(KEY.hex(), combined)
            self.assertEqual(main(["profiles"]), 0)

    def test_050_cli_still_requires_device_id_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "image.bin"
            image.write_bytes(image_050())
            with redirect_stderr(StringIO()):
                code = main(
                    [
                        "extract",
                        "--model",
                        "050DCTWF",
                        "--image",
                        str(image),
                        "--output",
                        str(Path(tmp) / "bundle.json"),
                    ]
                )
            self.assertEqual(code, 2)

    def test_050_bundle_uses_community_configuration_names(self):
        result = json.loads(extract_050dctwf(image_050(), DOOR).payload())
        self.assertEqual(result["serial"], IDENTITY.decode())
        self.assertEqual(result["device_id"], DOOR.hex())
        self.assertNotIn("identity", result)
        self.assertNotIn("door_id", result)

    def test_acquisition_reads_each_page_twice(self):
        region = g0401_image()[PAGE_BASE : PAGE_BASE + PAGE_COUNT * PAGE_SIZE]
        calls = []

        def fake_run(argv, _timeout):
            calls.append(argv)
            if "--version" in argv:
                return "Open On-Chip Debugger 0.12.0\n"
            command = argv[-1]
            if command == "init; shutdown":
                return "Info : Target voltage: 3.23\nInfo : SWD DPIDR 0x6ba02477\n"
            address = int(command.split()[1])
            page = (address - 0x08000000 - PAGE_BASE) // PAGE_SIZE
            data = region[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]
            lines = ["DPIDR 0x6ba02477", "AP1_IDR 0x84770001"]
            lines.extend(
                f"PAGE_WORD 0x{address + offset:08x} "
                f"0x{int.from_bytes(data[offset : offset + 4], 'little'):08x}"
                for offset in range(0, PAGE_SIZE, 4)
            )
            lines.append(f"PAGE_COMPLETE {address} {PAGE_SIZE};")
            return "\n".join(lines)

        with patch("myq_local.acquire._run", side_effect=fake_run):
            acquired, voltage = acquire_g0401_pages(Path(sys.executable))
        self.assertEqual(acquired, region)
        self.assertEqual(voltage, 3.23)
        self.assertEqual(len(calls), 8)

    def test_acquisition_stops_on_repeated_read_mismatch(self):
        region = bytearray(
            g0401_image()[PAGE_BASE : PAGE_BASE + PAGE_COUNT * PAGE_SIZE]
        )
        page_reads = 0

        def fake_run(argv, _timeout):
            nonlocal page_reads
            if "--version" in argv:
                return "Open On-Chip Debugger 0.12.0\n"
            command = argv[-1]
            if command == "init; shutdown":
                return "Info : Target voltage: 3.23\nInfo : SWD DPIDR 0x6ba02477\n"
            address = int(command.split()[1])
            data = bytearray(region[:PAGE_SIZE])
            page_reads += 1
            if page_reads == 2:
                data[0] ^= 1
            lines = ["DPIDR 0x6ba02477", "AP1_IDR 0x84770001"]
            lines.extend(
                f"PAGE_WORD 0x{address + offset:08x} "
                f"0x{int.from_bytes(data[offset : offset + 4], 'little'):08x}"
                for offset in range(0, PAGE_SIZE, 4)
            )
            lines.append(f"PAGE_COMPLETE {address} {PAGE_SIZE};")
            return "\n".join(lines)

        with (
            patch("myq_local.acquire._run", side_effect=fake_run),
            self.assertRaisesRegex(AcquisitionError, "repeated_page_read_mismatch"),
        ):
            acquire_g0401_pages(Path(sys.executable))
        self.assertEqual(page_reads, 2)

    def test_acquisition_stops_on_unsupported_voltage(self):
        with (
            patch(
                "myq_local.acquire._run",
                side_effect=[
                    "Open On-Chip Debugger 0.12.0\n",
                    "Info : Target voltage: 1.80\nInfo : SWD DPIDR 0x6ba02477\n",
                ],
            ),
            self.assertRaisesRegex(AcquisitionError, "target_voltage"),
        ):
            acquire_g0401_pages(Path(sys.executable))

    def test_acquisition_stops_on_preflight_identity_change(self):
        with (
            patch(
                "myq_local.acquire._run",
                side_effect=[
                    "Open On-Chip Debugger 0.12.0\n",
                    "Info : Target voltage: 3.23\nInfo : SWD DPIDR 0x00000001\n",
                ],
            ),
            self.assertRaisesRegex(AcquisitionError, "debug_port_identity"),
        ):
            acquire_g0401_pages(Path(sys.executable))

    def test_acquisition_stops_on_incomplete_page(self):
        with (
            patch(
                "myq_local.acquire._run",
                side_effect=[
                    "Open On-Chip Debugger 0.12.0\n",
                    "Info : Target voltage: 3.23\nInfo : SWD DPIDR 0x6ba02477\n",
                    "DPIDR 0x6ba02477\nAP1_IDR 0x84770001\n",
                ],
            ),
            self.assertRaisesRegex(AcquisitionError, "incomplete_or_misaddressed"),
        ):
            acquire_g0401_pages(Path(sys.executable))

    def test_acquisition_stops_on_identity_change(self):
        base = [
            "Open On-Chip Debugger 0.12.0\n",
            "Info : Target voltage: 3.23\nInfo : SWD DPIDR 0x6ba02477\n",
        ]
        with (
            patch(
                "myq_local.acquire._run",
                side_effect=base + ["DPIDR 0x6ba02477\nAP1_IDR 0x00000000\n"],
            ),
            self.assertRaisesRegex(AcquisitionError, "identity_changed"),
        ):
            acquire_g0401_pages(Path(sys.executable))

    def test_page_parser_rejects_openocd_error(self):
        address = 0x08000000 + PAGE_BASE
        data = b"\xff" * PAGE_SIZE
        lines = ["DPIDR 0x6ba02477", "AP1_IDR 0x84770001", "Error: fault"]
        lines.extend(
            f"PAGE_WORD 0x{address + offset:08x} "
            f"0x{int.from_bytes(data[offset : offset + 4], 'little'):08x}"
            for offset in range(0, PAGE_SIZE, 4)
        )
        lines.append(f"PAGE_COMPLETE {address} {PAGE_SIZE};")
        with self.assertRaisesRegex(AcquisitionError, "reported_error"):
            _parse_page("\n".join(lines), address)

    def test_page_parser_rejects_shifted_words_and_missing_marker(self):
        address = 0x08000000 + PAGE_BASE
        data = b"\xff" * PAGE_SIZE

        def output(start, include_marker):
            lines = ["DPIDR 0x6ba02477", "AP1_IDR 0x84770001"]
            lines.extend(
                f"PAGE_WORD 0x{start + offset:08x} "
                f"0x{int.from_bytes(data[offset : offset + 4], 'little'):08x}"
                for offset in range(0, PAGE_SIZE, 4)
            )
            if include_marker:
                lines.append(f"PAGE_COMPLETE {address} {PAGE_SIZE};")
            return "\n".join(lines)

        with self.assertRaisesRegex(AcquisitionError, "misaddressed"):
            _parse_page(output(address + 4, True), address)
        with self.assertRaisesRegex(AcquisitionError, "completion_marker"):
            _parse_page(output(address, False), address)

    def test_acquisition_rejects_other_openocd_versions(self):
        with (
            patch(
                "myq_local.acquire._run",
                return_value="Open On-Chip Debugger 0.13.0\n",
            ),
            self.assertRaisesRegex(AcquisitionError, "version_must_be_0_12_0"),
        ):
            acquire_g0401_pages(Path(sys.executable))

    def test_bounded_runner_terminates_a_timed_out_process(self):
        program = (
            "import signal,time;"
            "signal.signal(signal.SIGTERM, signal.SIG_IGN);"
            "time.sleep(60)"
        )
        with self.assertRaisesRegex(AcquisitionError, "timed_out"):
            _run([sys.executable, "-c", program], 0.05)

    def test_acquire_cli_confirms_fixture_and_keeps_secrets_private(self):
        with tempfile.TemporaryDirectory() as tmp:
            door_id = Path(tmp) / "door-id"
            output = Path(tmp) / "enrollment.json"
            door_id.write_text(DOOR.hex())
            door_id.chmod(0o600)
            region = g0401_image()[PAGE_BASE : PAGE_BASE + PAGE_COUNT * PAGE_SIZE]
            stdout, stderr = StringIO(), StringIO()
            with (
                patch("builtins.input", return_value="READY"),
                patch(
                    "myq_local.enroll.acquire_g0401_pages",
                    return_value=(region, 3.23),
                ) as acquire,
                redirect_stdout(stdout),
                redirect_stderr(stderr),
            ):
                code = main(
                    [
                        "acquire",
                        "--model",
                        "MYQ-G0401-ES",
                        "--firmware",
                        "1.10",
                        "--door-id-file",
                        str(door_id),
                        "--output",
                        str(output),
                    ]
                )
            self.assertEqual(code, 0)
            acquire.assert_called_once_with(None)
            self.assertEqual(os.stat(output).st_mode & 0o777, 0o600)
            combined = stdout.getvalue() + stderr.getvalue()
            self.assertNotIn(IDENTITY.decode(), combined)
            self.assertNotIn(KEY.hex(), combined)

    def test_acquire_cli_cancellation_never_starts_programmer(self):
        with tempfile.TemporaryDirectory() as tmp:
            door_id = Path(tmp) / "door-id"
            door_id.write_text(DOOR.hex())
            door_id.chmod(0o600)
            with (
                patch("builtins.input", return_value="no"),
                patch("myq_local.enroll.acquire_g0401_pages") as acquire,
                redirect_stdout(StringIO()),
                redirect_stderr(StringIO()),
            ):
                code = main(
                    [
                        "acquire",
                        "--model",
                        "MYQ-G0401-ES",
                        "--firmware",
                        "1.10",
                        "--door-id-file",
                        str(door_id),
                        "--output",
                        str(Path(tmp) / "enrollment.json"),
                    ]
                )
            self.assertEqual(code, 2)
            acquire.assert_not_called()
            self.assertFalse((Path(tmp) / "enrollment.json").exists())

    def test_acquire_cli_rejects_bad_output_before_programmer(self):
        with tempfile.TemporaryDirectory() as tmp:
            door_id = Path(tmp) / "door-id"
            door_id.write_text(DOOR.hex())
            door_id.chmod(0o600)
            output = Path(tmp) / "enrollment.json"
            output.symlink_to(Path(tmp) / "missing-target")
            with (
                patch("builtins.input", return_value="READY"),
                patch("myq_local.enroll.acquire_g0401_pages") as acquire,
                redirect_stdout(StringIO()),
                redirect_stderr(StringIO()),
            ):
                code = main(
                    [
                        "acquire",
                        "--model",
                        "MYQ-G0401-ES",
                        "--firmware",
                        "1.10",
                        "--door-id-file",
                        str(door_id),
                        "--output",
                        str(output),
                    ]
                )
            self.assertEqual(code, 2)
            acquire.assert_not_called()

    def test_output_reservation_cleans_up_failed_permission_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            door_id = Path(tmp) / "door-id"
            door_id.write_text(DOOR.hex())
            door_id.chmod(0o600)
            output = Path(tmp) / "enrollment.json"
            with (
                patch("os.fchmod", side_effect=OSError("mock fchmod failure")),
                patch("myq_local.enroll.acquire_g0401_pages") as acquire,
                redirect_stdout(StringIO()),
                redirect_stderr(StringIO()),
            ):
                code = main(
                    [
                        "acquire",
                        "--model",
                        "MYQ-G0401-ES",
                        "--firmware",
                        "1.10",
                        "--door-id-file",
                        str(door_id),
                        "--output",
                        str(output),
                    ]
                )
            self.assertEqual(code, 2)
            acquire.assert_not_called()
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
