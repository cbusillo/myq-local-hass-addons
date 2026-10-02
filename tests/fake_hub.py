"""Invented credentials and loopback-only door simulator for container tests."""

import socket
import ssl
import time

from myq_local.protocol import frame, string

IDENTITY = b"AA12345678"
KEY = bytes(range(16))
DOOR = bytes.fromhex("841234567800")


def publish(suffix, body):
    topic = b"S/AA/" + IDENTITY + b"/" + suffix
    return frame(0x30, len(topic).to_bytes(2, "big") + topic + body)


def run():
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ctx.minimum_version = ctx.maximum_version = ssl.TLSVersion.TLSv1_2
    ctx.set_ciphers("PSK-AES128-CBC-SHA")
    ctx.set_psk_client_callback(lambda hint: (IDENTITY.decode(), KEY))
    with (
        socket.create_connection(("127.0.0.1", 8883), timeout=5) as raw,
        ctx.wrap_socket(raw) as tls,
    ):
        tls.settimeout(0.5)
        tls.sendall(frame(0x10, b"\0\x04MQTT\x04\x02\x01\x68\0\x0a" + IDENTITY))
        topic = b"G/" + IDENTITY + b"/#"
        tls.sendall(
            frame(0x82, b"\0\x01" + len(topic).to_bytes(2, "big") + topic + b"\0")
        )
        tls.sendall(publish(b"003/0000", b""))
        tls.sendall(publish(b"014/0008", DOOR))
        state = 2

        def report():
            tls.sendall(
                publish(
                    b"011/0000",
                    DOOR
                    + b"\x81\0"
                    + (state << 16 | 0x6000).to_bytes(3, "little")
                    + b"\0",
                )
            )

        report()
        print("READY", flush=True)
        pending = bytearray()
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            try:
                data = tls.recv(4096)
            except TimeoutError:
                continue
            if not data:
                break
            pending.extend(data)
            while len(pending) >= 2:
                assert pending[1] < 128
                size = 2 + pending[1]
                if len(pending) < size:
                    break
                header, body = pending[0], bytes(pending[2:size])
                del pending[:size]
                if header != 0x30:
                    continue
                topic, at = string(body, 0)
                if topic.endswith(b"/012/0040"):
                    continue
                assert topic == b"G/" + IDENTITY + b"/011/0000"
                rc2 = body[at:]
                assert len(rc2) == 12 and rc2[:6] == DOOR
                mid = int.from_bytes(rc2[6:8], "little")
                value = int.from_bytes(rc2[8:11], "little")
                if mid == 0x80:
                    assert value == 0
                    report()
                else:
                    assert mid == 0x280 and value in (0x10100, 0x100)
                    state = 9 if value == 0x10100 else 2
                    print("OPEN" if state == 9 else "CLOSE", flush=True)
                    report()


if __name__ == "__main__":
    run()
