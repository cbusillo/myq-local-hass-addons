"""Home Assistant app entry point; MQTT service is discovered, never replaced."""

import argparse
import ipaddress
import json
import logging
import os
import signal
import threading
import urllib.request
import uuid
from pathlib import Path

from .mqtt_bridge import Bridge, BrokerSettings
from .profile import InvalidProfile, Profile
from .server import run_server
from .setup_ui import setup_server

LOG = logging.getLogger(__name__)


def settings(options):
    if "broker" in options:
        row = options["broker"]
        return BrokerSettings(
            row["host"],
            int(row.get("port", 1883)),
            row.get("username", ""),
            row.get("password", ""),
            bool(row.get("tls", False)),
        )
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        raise ValueError("supervisor_mqtt_service_required")
    request = urllib.request.Request(
        "http://supervisor/services/mqtt", headers={"Authorization": f"Bearer {token}"}
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=10) as response:
        payload = response.read(65537)
    if len(payload) > 65536:
        raise ValueError("service_response_limit")
    data = json.loads(payload)
    if data.get("result") != "ok":
        raise ValueError("mqtt_service_unavailable")
    row = data["data"]
    return BrokerSettings(
        row["host"],
        int(row["port"]),
        row["username"],
        row["password"],
        bool(row["ssl"]),
    )


def run(data_dir: Path, options_path: Path):
    data_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    options = json.loads(options_path.read_text())
    if type(options.get("control_enabled", False)) is not bool:
        raise ValueError("invalid_control_option")
    hub_ip = str(ipaddress.IPv4Address(options["hub_ip"]))
    peers = {hub_ip}
    if options.get("translated_peer_ip"):
        peers.add(str(ipaddress.IPv4Address(options["translated_peer_ip"])))
    stop = threading.Event()

    def stopped(signum, frame):
        stop.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, stopped)
    profile_path = data_dir / "enrollment.json"
    ui = setup_server(profile_path, port=int(options.get("ui_port", 8099)))
    ui_thread = threading.Thread(target=ui.serve_forever, daemon=True)
    ui_thread.start()
    bridge = None
    try:
        while not stop.is_set() and not profile_path.exists():
            stop.wait(1)
        if stop.is_set():
            return
        profile = Profile.load(profile_path)
        node_path = data_dir / "node_id"
        if not node_path.exists():
            node_path.write_text(uuid.uuid4().hex)
            node_path.chmod(0o600)
        node_id = node_path.read_text().strip()
        if not (len(node_id) == 32 and all(c in "0123456789abcdef" for c in node_id)):
            raise ValueError("invalid_node_id")
        bridge = Bridge(
            settings(options),
            node_id,
            options.get("name", "Garage door"),
            control_enabled=options.get("control_enabled", False),
        )
        bridge.start()
        run_server(
            profile, bridge, stop, peers, port=int(options.get("hub_port", 8883))
        )
    finally:
        stop.set()
        ui.shutdown()
        ui.server_close()
        ui_thread.join(timeout=3)
        if bridge:
            bridge.stop()


def main():
    os.umask(0o077)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=Path("/data"))
    parser.add_argument("--options", type=Path, default=Path("/data/options.json"))
    args = parser.parse_args()
    try:
        run(args.data_dir, args.options)
    except (OSError, ValueError, KeyError, InvalidProfile) as error:
        LOG.error("Startup failed: %s", type(error).__name__)
        raise SystemExit(1)
