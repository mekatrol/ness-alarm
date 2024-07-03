import asyncio
import paho.mqtt.client as mqtt
import logging
from configuration.YamlConfigurationHelper import YamlConfigurationHelper
from ness.DxPanel import DxPanel

# Create logger
logger = logging.getLogger(__name__)


def init_mqtt(config) -> mqtt.Client:
    unacked_publish = set()
    mqttc = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    mqttc.user_data_set(unacked_publish)
    mqttc.username_pw_set(
        username=config["mqtt"]["user"], password=config["mqtt"]["password"]
    )
    mqttc.connect(config["mqtt"]["host"], config["mqtt"]["port"])
    mqttc.loop_start()
    return mqttc


def post_mqtt_status(mqttc: mqtt.Client, area: int, zone: int, event: str):
    msg_info = mqttc.publish(
        f"ness/status/{zone}",
        f'{{ "type": "status", "area": {area}, "zone": {zone}, "event": "{ event }" }}',
        qos=1,
    )
    unacked_publish = set()
    unacked_publish.add(msg_info.mid)
    msg_info.wait_for_publish()


async def state_changed_loop(mqtt: mqtt.Client, alarm_panel: DxPanel):
    while True:
        if alarm_panel.read_and_clear_state_change():
            for zone in alarm_panel.zones:
                post_mqtt_status(
                    mqtt,
                    zone.area,
                    zone.number,
                    alarm_panel.event_type_name(zone.state),
                )

        # Only sleep for 100 ms
        await asyncio.sleep(0.1)


async def monitor_loop(mqtt: mqtt.Client, alarm_panel: DxPanel):
    while True:
        for zone in alarm_panel.zones:
            event_type_name = alarm_panel.event_type_name(zone.state)
            post_mqtt_status(mqtt, zone.area, zone.number, event_type_name)

        # This is just a keep alive message so can sleep for 10 seconds
        await asyncio.sleep(10)


async def alarm_loop(alarm_panel: DxPanel):
    await alarm_panel.loop()


async def main():
    try:
        # Read configuration
        configHelper = YamlConfigurationHelper("config.yaml", "config.debug.yaml")
        config = await configHelper.read()

        # Configure logging
        log_levels = logging.getLevelNamesMapping()
        log_level = log_levels[config["logging"]["level"]]
        logging.basicConfig(filename=config["logging"]["file-name"], level=log_level)

        mqtt = init_mqtt(config)

        # USB serial '/dev/ttyUSB0'
        # UART 0 serial '/dev/serial0'
        alarm_panel = DxPanel(
            config["serial"]["device"],
            config["serial"]["baud_rate"],
            config["serial"]["zones"],
        )

        alarm_task = asyncio.create_task(alarm_loop(alarm_panel))
        monitor_task = asyncio.create_task(monitor_loop(mqtt, alarm_panel))
        state_changed_task = asyncio.create_task(state_changed_loop(mqtt, alarm_panel))

        # Loop forever
        await asyncio.wait([alarm_task, monitor_task, state_changed_task])
    except Exception as e:
        logging.error("Error at %s", exc_info=e)
    finally:
        logger.debug("All tasks have completed")


if __name__ == "__main__":
    asyncio.run(main())
