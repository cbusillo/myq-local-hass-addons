"""Opt-in isolated broker/app/TLS-hub smoke test; never reaches a real hub."""

import json
import re
import subprocess
import tempfile
import threading
import time
import urllib.request
import uuid
from pathlib import Path

import paho.mqtt.client as mqtt
from paho.mqtt.packettypes import PacketTypes
from paho.mqtt.properties import Properties
from test_product import BUNDLE

ROOT = Path(__file__).resolve().parents[1]


def docker(*args):
    return subprocess.check_output(
        ["docker", *args], text=True, stderr=subprocess.STDOUT
    ).strip()


def wait(predicate, seconds=20):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.1)
    raise AssertionError("condition_timeout")


def run():
    run_id = uuid.uuid4().hex[:12]
    network = f"myq-test-{run_id}"
    broker_name = f"{network}-broker"
    app_name = f"{network}-app"
    reader = hub = None
    messages = []
    actions = []
    created = []
    with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
        path = Path(temporary)
        (path / "mosquitto.conf").write_text(
            "listener 1883\nallow_anonymous true\npersistence false\n"
        )
        options = {
            "hub_ip": "127.0.0.1",
            "name": "Synthetic garage",
            "control_enabled": True,
            "broker": {"host": broker_name, "port": 1883},
        }
        (path / "options.json").write_text(json.dumps(options))
        try:
            docker("network", "create", network)
            created.append(("network", network))
            docker(
                "run",
                "-d",
                "--name",
                broker_name,
                "--network",
                network,
                "-p",
                "127.0.0.1::1883",
                "-v",
                f"{path}/mosquitto.conf:/mosquitto/config/mosquitto.conf:ro",
                "eclipse-mosquitto:2.0.22",
            )
            created.append(("container", broker_name))
            broker_port = int(docker("port", broker_name, "1883/tcp").rsplit(":", 1)[1])
            connected = threading.Event()
            reader = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv5)

            def connected_cb(client, userdata, flags, reason, properties):
                client.subscribe("#", qos=0)
                connected.set()

            reader.on_connect = connected_cb
            reader.on_message = lambda c, u, m: messages.append(
                (m.topic, m.payload.decode())
            )
            reader.connect("127.0.0.1", broker_port)
            reader.loop_start()
            assert connected.wait(5)
            docker(
                "run",
                "-d",
                "--name",
                app_name,
                "--network",
                network,
                "-p",
                "127.0.0.1::8099",
                "-v",
                f"{path}/options.json:/data/options.json:ro",
                "-v",
                f"{ROOT}/tests/fake_hub.py:/test/fake_hub.py:ro",
                "myq-local:0.1.0-test",
            )
            created.append(("container", app_name))
            ui_port = int(docker("port", app_name, "8099/tcp").rsplit(":", 1)[1])
            base = f"http://127.0.0.1:{ui_port}"
            html = None

            def page():
                nonlocal html
                try:
                    with urllib.request.urlopen(base, timeout=1) as response:
                        html = response.read().decode()
                    return True
                except OSError:
                    return False

            wait(page)
            token = json.loads(re.search(r"const csrf=(.*?);", html).group(1))
            request = urllib.request.Request(
                base + "/enroll",
                data=BUNDLE,
                headers={"Content-Type": "application/json", "X-Setup-Token": token},
            )
            with urllib.request.urlopen(request, timeout=5) as response:
                assert response.status == 200
            wait(lambda: "Local hub listener ready" in docker("logs", app_name))
            hub = subprocess.Popen(
                ["docker", "exec", app_name, "python", "/test/fake_hub.py"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            def collect():
                for line in hub.stdout:
                    actions.append(line.strip())

            collector = threading.Thread(target=collect, daemon=True)
            collector.start()
            wait(lambda: "READY" in actions)
            wait(
                lambda: any(
                    topic.endswith("/state") and payload == "closed"
                    for topic, payload in messages
                )
            )
            configs = [
                (topic, json.loads(payload))
                for topic, payload in messages
                if topic.endswith("/config")
            ]
            assert len(configs) >= 1
            config = configs[-1][1]
            assert (
                config["optimistic"] is False
                and config["payload_stop"] is None
                and "position_topic" not in config
            )
            command = config["command_topic"]
            expiry = Properties(PacketTypes.PUBLISH)
            expiry.MessageExpiryInterval = 2
            reader.publish(command, "OPEN", retain=True).wait_for_publish(3)
            time.sleep(1)
            assert actions == ["READY"], "retained_motion_was_not_rejected"
            reader.publish(command, "", retain=True).wait_for_publish(3)
            reader.publish(command, "CLOSE", properties=expiry).wait_for_publish(3)
            time.sleep(0.5)
            assert actions == ["READY"], "closed_to_close_moved"
            for _ in range(2):
                prior = len(actions)
                reader.publish(command, "OPEN", properties=expiry).wait_for_publish(3)
                wait(
                    lambda prior=prior: (
                        len(actions) == prior + 1 and actions[-1] == "OPEN"
                    )
                )
                wait(
                    lambda: any(
                        topic == config["state_topic"] and payload == "open"
                        for topic, payload in messages
                    )
                )
                reader.publish(command, "CLOSE", properties=expiry).wait_for_publish(3)
                wait(
                    lambda prior=prior: (
                        len(actions) == prior + 2 and actions[-1] == "CLOSE"
                    )
                )
            assert actions == ["READY", "OPEN", "CLOSE", "OPEN", "CLOSE"]
            print(
                json.dumps(
                    {
                        "container_smoke": "passed",
                        "invented_credentials_only": True,
                        "retained_command_rejected": True,
                        "two_explicit_cycles": True,
                        "state_topic_nonoptimistic": True,
                    }
                )
            )
        finally:
            if reader:
                reader.disconnect()
                reader.loop_stop()
            if hub:
                hub.terminate()
                try:
                    hub.communicate(timeout=3)
                except subprocess.TimeoutExpired:
                    hub.kill()
                    hub.communicate(timeout=3)
            for kind, name in reversed(created):
                subprocess.run(
                    ["docker", "rm", "-f", name]
                    if kind == "container"
                    else ["docker", "network", "rm", name],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )


if __name__ == "__main__":
    run()
