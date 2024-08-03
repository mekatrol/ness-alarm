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


def post_mqtt_zone_status(mqttc: mqtt.Client, area: int, zone: int, event: str):
    msg_info = mqttc.publish(
        f"ness/status/{zone}",
        f'{{ "type": "status", "area": {area}, "zone": {zone}, "event": "{ event }" }}',
        qos=1,
    )
    unacked_publish = set()
    unacked_publish.add(msg_info.mid)
    msg_info.wait_for_publish()


def post_mqtt_armed_status(mqttc: mqtt.Client, event: str):
    msg_info = mqttc.publish(
        f"ness/status/armed_status",
        f'{{ "type": "status", "event": "{ event }" }}',
        qos=1,
    )
    unacked_publish = set()
    unacked_publish.add(msg_info.mid)
    msg_info.wait_for_publish()
    
def post_mqtt_alarmed_status(mqttc: mqtt.Client, event: str):
    msg_info = mqttc.publish(
        f"ness/status/alarmed_status",
        f'{{ "type": "status", "event": "{ event }" }}',
        qos=1,
    )
    unacked_publish = set()
    unacked_publish.add(msg_info.mid)
    msg_info.wait_for_publish()

def post_alarm_update(mqtt: mqtt.Client, alarm_panel: DxPanel):
    event = "unarmed"
    if alarm_panel.armed == True:
        event = "armed"
    
    post_mqtt_armed_status(mqtt, event)

    event = "notalarmed"
    if alarm_panel.alarmed_state() == True:
        event = "alarmed"
    
    post_mqtt_alarmed_status(mqtt, event)

    for zone in alarm_panel.zones:
        event_type_name = alarm_panel.event_type_name(zone.state)
        post_mqtt_zone_status(mqtt, zone.area, zone.number, event_type_name)


# Post state change events as soon as they occur
async def state_changed_loop(mqtt: mqtt.Client, alarm_panel: DxPanel):
    while True:
        if alarm_panel.read_and_clear_state_change():
            post_alarm_update(mqtt, alarm_panel)

        # Only sleep for 100 ms
        await asyncio.sleep(0.1)


# Post state change events periodically
async def monitor_loop(mqtt: mqtt.Client, alarm_panel: DxPanel):
    while True:
        post_alarm_update(mqtt, alarm_panel)

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
        # log_levels = logging.getLevelNamesMapping()
        # log_level = log_levels[config["logging"]["level"]]
        logging.basicConfig(filename=config["logging"]["file-name"], level="DEBUG")

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
    try:
        asyncio.run(main())
        asyncio.run(asyncio.sleep(5))
    except Exception as ex:
        logger.error(f"Exec error: '{ex}'")
