"""Independent implementation of the owner-observed stock-hub protocol."""

import hmac
import time
from collections import deque


class ProtocolError(ValueError):
    pass


def require(condition, code):
    if not condition:
        raise ProtocolError(code)


def string(data, offset):
    require(offset + 2 <= len(data), "short_string")
    length = int.from_bytes(data[offset : offset + 2], "big")
    start = offset + 2
    require(start + length <= len(data), "short_string")
    return data[start : start + length], start + length


def frame(header, body):
    require(len(body) <= 512, "packet_limit")
    length = len(body)
    encoded = bytearray()
    while True:
        digit = length % 128
        length //= 128
        encoded.append(digit | (128 if length else 0))
        if not length:
            break
    return bytes([header]) + encoded + body


class Session:
    def __init__(self, profile, clock=time.monotonic):
        self.profile, self.clock = profile, clock
        self.connected = self.subscribed = self.started = self.bound = False
        self.state = None
        self.state_at = 0.0
        self.pending = None
        self.buffer = bytearray()
        self.partial_at = None
        self.frame_times = deque()

    def publish(self, suffix, body):
        topic = b"G/" + self.profile.identity + b"/" + suffix
        return frame(0x30, len(topic).to_bytes(2, "big") + topic + body)

    def rc2(self, message, value):
        return self.publish(
            b"011/0000",
            self.profile.door_id
            + message.to_bytes(2, "little")
            + value.to_bytes(3, "little")
            + b"\0",
        )

    def poll(self):
        require(self.bound, "not_bound")
        return self.rc2(0x80, 0)

    def fresh(self):
        return (
            self.bound and self.state in (2, 9) and self.clock() - self.state_at <= 90
        )

    def command(self, action):
        require(action in ("OPEN", "CLOSE"), "unsupported_command")
        require(self.fresh(), "fresh_state_required")
        require(self.pending is None, "motion_pending")
        require(self.state == (2 if action == "OPEN" else 9), "state_mismatch")
        self.pending = action
        # Mark attempted before write; never replay an uncertain send.
        return self.rc2(0x280, 0x10100 if action == "OPEN" else 0x100)

    def feed(self, data):
        self.buffer.extend(data)
        require(len(self.buffer) <= 4096, "buffer_limit")
        replies, updates = [], []
        while len(self.buffer) >= 2:
            length, end = 0, None
            for index in range(1, min(len(self.buffer), 5)):
                byte = self.buffer[index]
                length |= (byte & 127) << (7 * (index - 1))
                if not byte & 128:
                    require(index == 1 or byte != 0, "noncanonical_length")
                    end = index + 1
                    break
            require(length <= 512, "packet_limit")
            if end is None:
                require(len(self.buffer) < 5, "invalid_length")
                break
            if len(self.buffer) < end + length:
                break
            header, body = self.buffer[0], bytes(self.buffer[end : end + length])
            del self.buffer[: end + length]
            now = self.clock()
            while self.frame_times and now - self.frame_times[0] > 60:
                self.frame_times.popleft()
            self.frame_times.append(now)
            require(len(self.frame_times) <= 512, "packet_rate_limit")
            output, update = self.packet(header, body)
            replies.extend(output)
            if update is not None:
                updates.append(update)
        if self.buffer:
            if self.partial_at is None:
                self.partial_at = self.clock()
            require(self.clock() - self.partial_at < 2, "partial_packet_timeout")
        else:
            self.partial_at = None
        return replies, updates

    def packet(self, header, body):
        if header == 0x10:
            require(not self.connected, "duplicate_connect")
            name, at = string(body, 0)
            require(
                name == b"MQTT" and len(body) >= at + 4 and body[at] == 4,
                "connect_format",
            )
            flags = body[at + 1]
            require(
                not flags & 0xC1
                and flags & 2
                and (flags & 4 or not flags & 0x38)
                and (flags >> 3 & 3) != 3,
                "connect_flags",
            )
            require(body[at + 2 : at + 4] == b"\x01\x68", "keepalive")
            identity, at = string(body, at + 4)
            require(
                hmac.compare_digest(identity, self.profile.identity),
                "identity_mismatch",
            )
            if flags & 4:
                topic, at = string(body, at)
                _, at = string(body, at)
                require(
                    topic and not any(c in topic for c in (0, 35, 43)), "will_topic"
                )
                topic.decode("utf-8", errors="strict")
            require(at == len(body), "connect_extra")
            self.connected = True
            return [b"\x20\x02\0\0"], None
        require(self.connected, "connect_required")
        if header == 0x82:
            require(
                not self.subscribed and len(body) >= 2 and body[:2] != b"\0\0",
                "subscribe_format",
            )
            topic, at = string(body, 2)
            require(
                topic == b"G/" + self.profile.identity + b"/#" and body[at:] == b"\0",
                "subscribe_target",
            )
            self.subscribed = True
            return [b"\x90\x03" + body[:2] + b"\0"], None
        if header == 0xC0:
            require(not body, "ping_format")
            return [b"\xd0\0"], None
        require(header == 0x30 and self.subscribed, "unsupported_packet")
        topic, at = string(body, 0)
        prefix = b"S/" + self.profile.identity[:2] + b"/" + self.profile.identity + b"/"
        require(topic.startswith(prefix), "topic_identity")
        suffix = topic[len(prefix) :]
        require(
            len(suffix) == 8
            and suffix[3:4] == b"/"
            and suffix[:3].isdigit()
            and suffix[4:].isdigit(),
            "topic_suffix",
        )
        payload = body[at:]
        if suffix == b"003/0000":
            require(not payload and not self.started, "startup_replay")
            self.started = True
            return [self.publish(b"012/0040", bytes(32))], None
        if suffix == b"014/0008":
            require(
                self.started
                and not self.bound
                and 0 < len(payload) <= 108
                and len(payload) % 6 == 0,
                "inventory_format",
            )
            ids = [payload[i : i + 6] for i in range(0, len(payload), 6)]
            require(
                len(set(ids)) == len(ids) and ids.count(self.profile.door_id) == 1,
                "target_binding",
            )
            self.bound = True
            return [self.poll()], None
        if suffix == b"011/0000":
            require(self.bound and len(payload) == 12, "rc2_format")
            if (
                hmac.compare_digest(payload[:6], self.profile.door_id)
                and payload[6:8] == b"\x81\0"
            ):
                require(not (payload[10] & 0xF0 or payload[11]), "reserved_bits")
                value = int.from_bytes(payload[8:11], "little")
                self.state = (value >> 16) & 15
                self.state_at = self.clock()
                if (self.pending == "OPEN" and self.state == 9) or (
                    self.pending == "CLOSE" and self.state == 2
                ):
                    self.pending = None
                return [], self.state
        return [], None
