import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from myq_local.mqtt_bridge import Bridge, BrokerSettings
from myq_local.profile import InvalidProfile, Profile, save_profile
from myq_local.protocol import ProtocolError, Session, frame

IDENTITY = b"AA12345678"
DOOR = bytes.fromhex("841234567800")
BUNDLE = json.dumps(
    {
        "schema": 1,
        "model": "MYQ-G0401-ES",
        "identity": IDENTITY.decode(),
        "psk": bytes(range(16)).hex(),
        "door_id": DOOR.hex(),
    }
).encode()


def client_publish(suffix, body):
    topic = b"S/AA/" + IDENTITY + b"/" + suffix
    return frame(0x30, len(topic).to_bytes(2, "big") + topic + body)


def connect_session(session, inventory=DOOR):
    connect = b"\0\x04MQTT\x04\x02\x01\x68\0\x0a" + IDENTITY
    session.feed(frame(0x10, connect))
    topic = b"G/" + IDENTITY + b"/#"
    session.feed(frame(0x82, b"\0\x01" + len(topic).to_bytes(2, "big") + topic + b"\0"))
    session.feed(client_publish(b"003/0000", b""))
    return session.feed(client_publish(b"014/0008", inventory))


def status(session, code, door=DOOR):
    return session.feed(
        client_publish(
            b"011/0000",
            door + b"\x81\0" + (code << 16 | 0x6000).to_bytes(3, "little") + b"\0",
        )
    )


class ProfileTests(unittest.TestCase):
    def test_profile_is_private_and_atomically_loaded(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "enrollment.json"
            save_profile(p, BUNDLE)
            loaded = Profile.load(p)
            self.assertEqual(loaded.identity, IDENTITY)
            self.assertEqual(loaded.door_id, DOOR)
            for value in (IDENTITY.decode(), bytes(range(16)).hex(), DOOR.hex()):
                self.assertNotIn(value, repr(loaded))
            p.chmod(0o644)
            with self.assertRaises(InvalidProfile):
                Profile.load(p)
            link = Path(tmp) / "link"
            link.symlink_to(p)
            with self.assertRaises(OSError):
                Profile.load(link)

    def test_invalid_profiles_do_not_replace_enrollment(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "enrollment.json"
            save_profile(p, BUNDLE)
            for data in (
                b"{}",
                b"[1]",
                b"x" * 4097,
                BUNDLE.replace(b'"schema": 1', b'"schema": true'),
            ):
                with self.assertRaises(InvalidProfile):
                    save_profile(p, data)
                self.assertEqual(p.read_bytes(), BUNDLE)


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.s = Session(Profile.parse(BUNDLE), clock=lambda: self.now)

    def test_exact_native_commands_and_repeatable_cycles(self):
        replies, _ = connect_session(self.s)
        self.assertEqual(replies[0][-12:], DOOR + b"\x80\0" + bytes(4))
        for _ in range(3):
            status(self.s, 2)
            self.assertEqual(
                self.s.command("OPEN")[-12:], DOOR + b"\x80\x02\x00\x01\x01\x00"
            )
            with self.assertRaisesRegex(ProtocolError, "motion_pending"):
                self.s.command("OPEN")
            status(self.s, 9)
            self.assertEqual(
                self.s.command("CLOSE")[-12:], DOOR + b"\x80\x02\x00\x01\x00\x00"
            )

    def test_inventory_reordering_and_other_door_do_not_change_target(self):
        other = b"\x84abcde"
        connect_session(self.s, other + DOOR)
        status(self.s, 9, door=other)
        self.assertIsNone(self.s.state)
        status(self.s, 2)
        self.assertEqual(self.s.command("OPEN")[-12:-6], DOOR)

    def test_missing_and_duplicate_binding_rejected(self):
        for inventory in (b"\x84abcde", DOOR + DOOR):
            self.setUp()
            with self.assertRaises(ProtocolError):
                connect_session(self.s, inventory)

    def test_stale_unknown_and_unbound_states_reject_motion(self):
        with self.assertRaises(ProtocolError):
            self.s.command("OPEN")
        connect_session(self.s)
        status(self.s, 2)
        self.now = 91
        with self.assertRaisesRegex(ProtocolError, "fresh_state"):
            self.s.command("OPEN")
        status(self.s, 7)
        self.assertFalse(self.s.fresh())
        with self.assertRaises(ProtocolError):
            self.s.command("CLOSE")
        with self.assertRaises(ProtocolError):
            self.s.command("STOP")

    def test_fragmentation_and_partial_timeout(self):
        raw = frame(0x10, b"\0\x04MQTT\x04\x02\x01\x68\0\x0a" + IDENTITY)
        result = []
        for byte in raw:
            output, _ = self.s.feed(bytes([byte]))
            result.extend(output)
        self.assertEqual(result, [b"\x20\x02\0\0"])
        self.s.feed(b"\x30\x20")
        self.now = 3
        with self.assertRaisesRegex(ProtocolError, "partial_packet"):
            self.s.feed(b"")

    def test_long_sessions_are_rate_bounded_not_packet_total_bounded(self):
        connect_session(self.s)
        for second in range(1200):
            self.now = float(second)
            self.assertEqual(self.s.feed(b"\xc0\0")[0], [b"\xd0\0"])
        with self.assertRaisesRegex(ProtocolError, "packet_rate"):
            for _ in range(600):
                self.s.feed(b"\xc0\0")

    def test_startup_replay_wrong_topic_and_bad_remaining_length_rejected(self):
        connect_session(self.s)
        for packet in (
            client_publish(b"003/0000", b""),
            b"\x30\x80\0",
            b"\x30\xff\xff\x7f",
        ):
            with self.assertRaises(ProtocolError):
                self.s.feed(packet)
            self.setUp()
            connect_session(self.s)
        wrong = client_publish(b"011/0000", bytes(12)).replace(IDENTITY, b"BB12345678")
        with self.assertRaises(ProtocolError):
            self.s.feed(wrong)


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.b = Bridge(
            BrokerSettings("localhost"),
            "testnode",
            "Garage",
            True,
            clock=lambda: self.now,
        )
        self.b.client = Mock()
        self.b.connected.set()
        self.b.new_hub_session()
        self.b.publish_state(2, True)

    def message(self, payload=b"OPEN", retain=False, dup=False):
        return SimpleNamespace(
            topic="myq_local/testnode/command", payload=payload, retain=retain, dup=dup
        )

    def test_only_fresh_explicit_messages_are_delivered(self):
        for msg in (
            self.message(retain=True),
            self.message(dup=True),
            self.message(b"STOP"),
            self.message(b"open"),
        ):
            self.b.on_message(None, None, msg)
        self.assertIsNone(self.b.take_command())
        self.b.on_message(None, None, self.message())
        self.assertEqual(self.b.take_command(), "OPEN")
        self.assertIsNone(self.b.take_command())

    def test_reconnect_and_hub_replacement_drop_queued_commands(self):
        self.b.on_message(None, None, self.message())
        self.b.on_disconnect(None, None, None, None, None)
        self.b.connected.set()
        self.assertIsNone(self.b.take_command())
        self.b.on_message(None, None, self.message())
        self.b.new_hub_session()
        self.b.publish_state(2, True)
        self.assertIsNone(self.b.take_command())

    def test_expired_and_disabled_commands_are_ignored(self):
        self.b.on_message(None, None, self.message())
        self.now = 3
        self.assertIsNone(self.b.take_command())
        self.b.control_enabled = False
        self.b.on_message(None, None, self.message())
        self.assertIsNone(self.b.take_command())

    def test_discovery_exposes_only_validated_controls(self):
        row = self.b.discovery()
        self.assertFalse(row["optimistic"])
        self.assertFalse(row["retain"])
        self.assertIsNone(row["payload_stop"])
        self.assertNotIn("position_topic", row)
        self.b.control_enabled = False
        self.assertIsNone(self.b.discovery()["payload_open"])
        self.assertIsNone(self.b.discovery()["payload_close"])
        self.b.on_connect(
            self.b.client, None, None, SimpleNamespace(is_failure=False), None
        )
        options = self.b.client.subscribe.call_args.kwargs["options"]
        self.assertTrue(options.retainAsPublished)
        self.assertEqual(options.retainHandling, 2)
