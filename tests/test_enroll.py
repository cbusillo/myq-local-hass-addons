import json
import os
import struct
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from myq_local.enroll import (
    EnrollmentError,
    extract_050dctwf,
    extract_g0401,
    load_community_tools,
    main,
)

DOOR = bytes.fromhex("841234567800")
IDENTITY = b"AA12345678"
KEY = bytes(range(16))


def wrapped_key():
    _, psmtool = load_community_tools()
    return psmtool.encrypt_block(KEY[:8]) + psmtool.encrypt_block(KEY[8:])


def g0401_image():
    data = bytearray(b"\xff" * (8 * 1024 * 1024))
    for page, sequence in ((1, 19), (2, 20)):
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
                        "--door-id",
                        DOOR.hex(),
                        "--output",
                        str(output),
                    ]
                )
            self.assertEqual(code, 0)
            self.assertEqual(os.stat(output).st_mode & 0o777, 0o600)
            payload = json.loads(output.read_text())
            self.assertEqual(payload["model"], "MYQ-G0401-ES")
            self.assertEqual(payload["psk"], KEY.hex())
            combined = stdout.getvalue() + stderr.getvalue()
            self.assertNotIn(IDENTITY.decode(), combined)
            self.assertNotIn(KEY.hex(), combined)
            self.assertEqual(main(["profiles"]), 0)

    def test_050_bundle_uses_community_configuration_names(self):
        result = json.loads(extract_050dctwf(image_050(), DOOR).payload())
        self.assertEqual(result["serial"], IDENTITY.decode())
        self.assertNotIn("identity", result)


if __name__ == "__main__":
    unittest.main()
