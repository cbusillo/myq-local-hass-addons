"""Local PSK listener. One authenticated hub session, state-based commands."""

import hmac
import logging
import socket
import ssl
import time

from .protocol import ProtocolError, Session

LOG = logging.getLogger(__name__)


def tls_context(profile):
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = context.maximum_version = ssl.TLSVersion.TLSv1_2
    context.set_ciphers("PSK-AES128-CBC-SHA")
    context.options |= ssl.OP_NO_TICKET | ssl.OP_NO_COMPRESSION
    context.set_psk_server_callback(
        lambda identity: (
            profile.psk
            if identity is not None
            and hmac.compare_digest(
                identity.encode("ascii", errors="replace"), profile.identity
            )
            else b""
        )
    )
    return context


def run_server(profile, bridge, stop, allowed_peers, host="0.0.0.0", port=8883):
    context = tls_context(profile)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((host, port))
        listener.listen(2)
        listener.settimeout(0.5)
        LOG.info("Local hub listener ready")
        while not stop.is_set():
            try:
                connection, address = listener.accept()
            except TimeoutError:
                continue
            bridge.new_hub_session()
            try:
                with connection:
                    if address[0] not in allowed_peers:
                        continue
                    connection.settimeout(5)
                    with context.wrap_socket(connection, server_side=True) as tls:
                        tls.settimeout(0.2)
                        session = Session(profile)
                        last_poll = last_publish = time.monotonic()
                        last_receive = time.monotonic()
                        while not stop.is_set():
                            bridge.tick()
                            try:
                                data = tls.recv(1024)
                            except TimeoutError:
                                data = None
                            if data == b"":
                                break
                            if data:
                                last_receive = time.monotonic()
                            if time.monotonic() - last_receive > 120:
                                break
                            output, states = session.feed(data or b"")
                            for packet in output:
                                tls.sendall(packet)
                            if states or time.monotonic() - last_publish >= 2:
                                bridge.publish_state(session.state, session.fresh())
                                last_publish = time.monotonic()
                            if session.bound and time.monotonic() - last_poll >= 30:
                                tls.sendall(session.poll())
                                last_poll = time.monotonic()
                            action = bridge.take_command()
                            if action:
                                try:
                                    packet = session.command(action)
                                except ProtocolError as error:
                                    LOG.info("Command rejected: %s", str(error))
                                    continue
                                tls.sendall(packet)
                                LOG.info("Explicit %s request sent once", action)
            except (OSError, ValueError, UnicodeError) as error:
                # No exception strings from TLS/network/profile data in logs.
                LOG.info("Hub session ended: %s", type(error).__name__)
            finally:
                bridge.new_hub_session()
