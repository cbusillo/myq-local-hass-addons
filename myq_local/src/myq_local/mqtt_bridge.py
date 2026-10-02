"""Existing-broker integration: fresh sessions, no retained/replayed motion."""

import json
import queue
import threading
import time
import uuid
from dataclasses import dataclass, field

import paho.mqtt.client as mqtt
from paho.mqtt.subscribeoptions import SubscribeOptions


@dataclass(frozen=True)
class BrokerSettings:
    host: str
    port: int = 1883
    username: str = field(default="", repr=False)
    password: str = field(default="", repr=False)
    tls: bool = False


class Bridge:
    def __init__(
        self, settings, node_id, name, control_enabled=False, clock=time.monotonic
    ):
        self.clock = clock
        self.prefix = f"myq_local/{node_id}"
        self.node_id, self.name = node_id, name
        self.control_enabled = control_enabled
        self.commands = queue.Queue(maxsize=4)
        self.connected = threading.Event()
        self.lock = threading.RLock()
        self.generation = 0
        self.hub_epoch = 0
        self.hub_available = False
        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"myq-local-{uuid.uuid4().hex}",
            protocol=mqtt.MQTTv5,
        )
        self.client.max_queued_messages_set(16)
        if settings.username:
            self.client.username_pw_set(settings.username, settings.password)
        if settings.tls:
            self.client.tls_set()
        self.client.will_set(
            f"{self.prefix}/availability", "offline", qos=0, retain=True
        )
        self.client.on_connect = self.on_connect
        self.client.on_subscribe = self.on_subscribe
        self.client.on_disconnect = self.on_disconnect
        self.client.on_message = self.on_message
        self.settings = settings

    def discovery(self):
        return {
            "name": self.name,
            "unique_id": f"myq_local_{self.node_id}",
            "device_class": "garage",
            "command_topic": f"{self.prefix}/command",
            "state_topic": f"{self.prefix}/state",
            "availability_topic": f"{self.prefix}/availability",
            "optimistic": False,
            "retain": False,
            "qos": 0,
            "payload_open": "OPEN" if self.control_enabled else None,
            "payload_close": "CLOSE" if self.control_enabled else None,
            "payload_stop": None,
            "device": {
                "identifiers": [f"myq_local_{self.node_id}"],
                "manufacturer": "Local community integration",
                "model": "Stock MYQ-G0401-ES",
                "name": self.name,
            },
        }

    def invalidate_commands(self):
        self.generation += 1
        while True:
            try:
                self.commands.get_nowait()
            except queue.Empty:
                break

    def on_connect(self, client, userdata, flags, reason_code, properties):
        with self.lock:
            self.connected.clear()
            self.invalidate_commands()
            if reason_code.is_failure:
                return
            client.publish(f"{self.prefix}/availability", "offline", retain=True)
            client.publish(
                f"homeassistant/cover/{self.node_id}/config",
                json.dumps(self.discovery()),
                retain=True,
            )
            client.subscribe(
                f"{self.prefix}/command",
                options=SubscribeOptions(
                    qos=0, retainAsPublished=True, retainHandling=2
                ),
            )

    def on_subscribe(self, client, userdata, mid, reasons, properties):
        if reasons and not any(reason.is_failure for reason in reasons):
            self.connected.set()

    def on_disconnect(self, client, userdata, flags, reason_code, properties):
        with self.lock:
            self.connected.clear()
            self.invalidate_commands()

    def on_message(self, client, userdata, message):
        with self.lock:
            if (
                not self.control_enabled
                or not self.connected.is_set()
                or not self.hub_available
                or message.topic != f"{self.prefix}/command"
                or message.retain
                or message.dup
                or message.payload not in (b"OPEN", b"CLOSE")
            ):
                return
            item = (
                self.clock(),
                self.generation,
                self.hub_epoch,
                message.payload.decode("ascii"),
            )
            try:
                self.commands.put_nowait(item)
            except queue.Full:
                pass

    def new_hub_session(self):
        with self.lock:
            self.hub_epoch += 1
            self.hub_available = False
            self.invalidate_commands()
        self.publish_state(None, False)

    def take_command(self):
        while True:
            try:
                received, generation, epoch, action = self.commands.get_nowait()
            except queue.Empty:
                return None
            with self.lock:
                if (
                    self.connected.is_set()
                    and self.hub_available
                    and generation == self.generation
                    and epoch == self.hub_epoch
                    and 0 <= self.clock() - received <= 2
                ):
                    return action

    def publish_state(self, state, fresh):
        with self.lock:
            self.hub_available = fresh and state in (2, 9)
        if self.connected.is_set():
            value = "closed" if state == 2 else "open" if state == 9 else "None"
            self.client.publish(f"{self.prefix}/state", value, retain=True)
            self.client.publish(
                f"{self.prefix}/availability",
                "online" if self.hub_available else "offline",
                retain=True,
            )

    def start(self):
        self.client.connect_async(
            self.settings.host, self.settings.port, keepalive=30, clean_start=True
        )
        self.client.loop_start()

    def stop(self):
        self.hub_available = False
        if self.connected.is_set():
            self.client.publish(
                f"{self.prefix}/availability", "offline", retain=True
            ).wait_for_publish(timeout=2)
        self.connected.clear()
        self.client.disconnect()
        self.client.loop_stop()
