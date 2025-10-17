import asyncio
import logging
import threading
from logging.handlers import RotatingFileHandler
import time
from typing import Optional

import paho.mqtt.client as mqtt

from configuration.YamlConfigurationHelper import YamlConfigurationHelper
from ness.DxPanel import DxPanel

logger = logging.getLogger(__name__)

MQTT_TOPIC_STATUS_CONNECTION = "ness/status/connection"
MQTT_TOPIC_STATUS_ARMED = "ness/status/armed_status"
MQTT_TOPIC_STATUS_ALARMED = "ness/status/alarmed_status"
MQTT_TOPIC_STATUS_ZONE = "ness/status/{zone}"


class ResilientMQTT:
    def __init__(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
        client_id: Optional[str] = None,
    ):
        self._host = host
        self._port = port
        self._user = user
        self._password = password

        self._c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
        self._c.username_pw_set(user, password)
        # Last Will helps detect client death
        self._c.will_set(
            MQTT_TOPIC_STATUS_CONNECTION,
            '{"type":"status","event":"offline"}',
            qos=1,
            retain=True,
        )

        # Backoff parameters
        self._min_backoff = 1
        self._max_backoff = 30

        # Callbacks
        self._c.on_connect = self._on_connect
        self._c.on_disconnect = self._on_disconnect
        self._c.on_publish = self._on_publish
        self._connected = threading.Event()

        # Start network loop thread
        self._c.loop_start()

        # Initial connect with retry
        self._blocking_reconnect_loop()

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        rc = getattr(reason_code, "value", reason_code)
        if rc == 0:
            logger.info("MQTT connected")
            self._connected.set()
            # Mark online
            try:
                client.publish(
                    MQTT_TOPIC_STATUS_CONNECTION,
                    '{"type":"status","event":"online"}',
                    qos=1,
                    retain=True,
                )
            except Exception:
                logger.exception("Failed to publish online status")
        else:
            logger.warning("MQTT connect failed rc=%s", reason_code)
            self._connected.clear()

    def _on_disconnect(self, client, userdata, reason_code, properties):
        logger.warning("MQTT disconnected rc=%s", reason_code)
        self._connected.clear()
        # Kick off a background reconnect loop
        asyncio.get_event_loop().call_soon_threadsafe(self._ensure_reconnect_async)

    def _on_publish(self, client, userdata, mid, reason_code, properties):
        # Hook available if you later want metrics
        pass

    def _blocking_reconnect_loop(self):
        """Try to connect until success. Runs in caller thread."""
        backoff = self._min_backoff
        while True:
            try:
                # connect_async lets the loop thread handle socket lifecycle
                self._c.connect_async(self._host, self._port, keepalive=30)
                return
            except Exception:
                logger.exception("MQTT connect_async raised, will retry")
                time.sleep(backoff)
                backoff = min(self._max_backoff, backoff * 2)

    def _ensure_reconnect_async(self):
        """Schedule reconnect attempts from the asyncio loop without blocking it."""

        async def _task():
            backoff = self._min_backoff
            while not self._c.is_connected():
                try:
                    self._c.reconnect()  # fast path if socket is available
                    await asyncio.sleep(0.1)
                    if self._c.is_connected():
                        return
                except Exception:
                    # Fall back to connect_async which rebuilds sockets
                    try:
                        self._c.connect_async(self._host, self._port, keepalive=30)
                    except Exception:
                        logger.exception("connect_async failed inside ensure_reconnect")
                await asyncio.sleep(backoff)
                backoff = min(self._max_backoff, backoff * 2)

        asyncio.create_task(_task())

    def publish(self, topic, payload, qos=1, retain=False, timeout=5.0, retries=3):
        attempt = 0
        while True:
            attempt += 1
            try:
                # wait until connected (bounded)
                if not self._connected.wait(timeout=timeout):
                    raise RuntimeError("not connected")

                info = self._c.publish(topic, payload, qos=qos, retain=retain)

                # Paho 2.1.0 may return None; rely on is_published() instead
                deadline = time.monotonic() + timeout
                while not info.is_published():
                    if time.monotonic() > deadline:
                        raise TimeoutError("PUBACK timeout")
                    if not self._c.is_connected():
                        raise RuntimeError("lost connection during publish")
                    time.sleep(0.05)

                if info.rc == mqtt.MQTT_ERR_SUCCESS:
                    return True
                raise RuntimeError(f"publish failed rc={info.rc}")

            except Exception as e:
                logger.warning(
                    "Publish attempt %d failed for %s: %s", attempt, topic, e
                )
                if attempt > retries:
                    return False
                self._ensure_reconnect_async()
                time.sleep(min(0.5 * attempt, 2.0))

    # Expose is_connected if needed
    def is_connected(self) -> bool:
        return self._c.is_connected()


def post_mqtt_zone_status(mqttc: ResilientMQTT, area: int, zone: int, event: str):
    mqttc.publish(
        f"{MQTT_TOPIC_STATUS_ZONE.format(zone=zone)}",
        f'{{"type":"status","area":{area},"zone":{zone},"event":"{event}"}}',
        qos=1,
    )


def post_mqtt_armed_status(mqttc: ResilientMQTT, event: str):
    mqttc.publish(
        MQTT_TOPIC_STATUS_ARMED,
        f'{{"type":"status","event":"{event}"}}',
        qos=1,
    )


def post_mqtt_alarmed_status(mqttc: ResilientMQTT, event: str):
    mqttc.publish(
        MQTT_TOPIC_STATUS_ALARMED,
        f'{{"type":"status","event":"{event}"}}',
        qos=1,
    )


def post_alarm_update(mqttc: ResilientMQTT, alarm_panel: DxPanel):
    for zone in alarm_panel.zones:
        post_mqtt_zone_status(
            mqttc, zone.area, zone.number, alarm_panel.event_type_name(zone.state)
        )


async def state_changed_loop(mqttc: ResilientMQTT, alarm_panel: DxPanel):
    while True:
        if alarm_panel.read_and_clear_state_change():
            post_alarm_update(mqttc, alarm_panel)
        await asyncio.sleep(0.1)


async def monitor_loop(mqttc: ResilientMQTT, alarm_panel: DxPanel):
    while True:
        post_alarm_update(mqttc, alarm_panel)
        await asyncio.sleep(10)


async def alarm_loop(alarm_panel: DxPanel):
    await alarm_panel.loop()


async def main():
    # Read config
    configHelper = YamlConfigurationHelper("config.yaml", "config.debug.yaml")
    config = await configHelper.read()

    # Logging with size-based rotation
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.handlers.clear()
    handler = RotatingFileHandler(
        filename=config["logging"]["file-name"],
        maxBytes=config["logging"].get("max-bytes", 5 * 1024 * 1024),  # 5 MB default
        backupCount=config["logging"].get("backup-count", 3),  # keep 3 backups
        encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )
    root.addHandler(handler)

    mqttc = ResilientMQTT(
        host=config["mqtt"]["host"],
        port=config["mqtt"]["port"],
        user=config["mqtt"]["user"],
        password=config["mqtt"]["password"],
    )

    alarm_panel = DxPanel(
        config["serial"]["device"],
        config["serial"]["baud_rate"],
        config["serial"]["zones"],
    )

    alarm_task = asyncio.create_task(alarm_loop(alarm_panel))
    monitor_task = asyncio.create_task(monitor_loop(mqttc, alarm_panel))
    state_changed_task = asyncio.create_task(state_changed_loop(mqttc, alarm_panel))

    await asyncio.wait([alarm_task, monitor_task, state_changed_task])


if __name__ == "__main__":
    try:
        asyncio.run(main())
        asyncio.run(asyncio.sleep(5))
    except Exception:
        logger.exception("Fatal error")
