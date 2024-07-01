import asyncio
import serial
import paho.mqtt.client as mqtt
import logging
from configuration.YamlConfigurationHelper import YamlConfigurationHelper

# Message types
MT_UNKNOWN = 0xFF
MT_SYSTEM_STATUS = 0x61
MT_USER_INTERFACE = 0x60

# Message positions (for ASCII strings)
MP_START_BEGIN = 0
MP_START_END = MP_START_BEGIN + 2

MP_MESSAGE_TYPE_BEGIN = 6
MP_MESSAGE_TYPE_END = MP_MESSAGE_TYPE_BEGIN + 2

MP_MESSAGE_EVENT_BEGIN = 8
MP_MESSAGE_EVENT_END = MP_MESSAGE_EVENT_BEGIN + 2

MP_MESSAGE_ZONE_BEGIN = 10
MP_MESSAGE_ZONE_END = MP_MESSAGE_ZONE_BEGIN + 2

MP_MESSAGE_AREA_BEGIN = 12
MP_MESSAGE_AREA_END = MP_MESSAGE_AREA_BEGIN + 2

# Start byte bits
SB_ADDRESS_INCLUDED = 0x01  # Set if the panel address (last digit of account code - see panel installer address P73E)
SB_BASIC_HEADER = 0x02  # According to spec, this bit is always set in the start byte
SB_TIME_STAMP = 0x04  # Set if the time stamp is included in the message
SB_ASCII = 0x80  # According to spec, this bit is always set in the start byte

# Create logger
logger = logging.getLogger(__name__)

# USB serial '/dev/ttyUSB0'
# UART 0 serial '/dev/serial0'

uart = serial.Serial("/dev/ttyUSB0", baudrate=9600, timeout=3.0)
unacked_publish = set()
mqttc = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)


def init_mqtt(config):
    # MQTT set up
    mqttc.user_data_set(unacked_publish)
    mqttc.username_pw_set(
        username=config["mqtt"]["user"], password=config["mqtt"]["password"]
    )
    mqttc.connect(config["mqtt"]["host"], config["mqtt"]["port"])
    mqttc.loop_start()


# Simple helper to get message type name string from message type byte code
def message_type_name(message_type) -> str:
    if message_type == MT_SYSTEM_STATUS:
        return "MT_SYSTEM_STATUS"
    if message_type == MT_USER_INTERFACE:
        return "MT_USER_INTERFACE"
    return "MT_UNKNOWN"


# Simple helper to get event type name string from message type byte code
def event_type_name(event_type) -> str:
    if event_type == 0x00:
        return "EVT_SEALED"
    if event_type == 0x01:
        return "EVT_UNSEALED"
    if event_type == 0x02:
        return "EVT_ALARM"
    if event_type == 0x03:
        return "EVT_ALARM_RESTORE"
    if event_type == 0x04:
        return "EVT_MANUAL_EXCLUDE"
    if event_type == 0x05:
        return "EVT_MANUAL_INCLUDE"
    return "EVT_UNKNOWN"


# Simple helper to get start bit strings from start byte
def start_bits(start) -> str:
    bit_str = ""

    if start & SB_ASCII:
        bit_str += "SB_ASCII | "

    if start & SB_BASIC_HEADER:
        bit_str += "SB_BASIC_HEADER | "

    if start & SB_TIME_STAMP:
        bit_str += "SB_TIME_STAMP | "

    if start & SB_ADDRESS_INCLUDED:
        bit_str += "SB_ADDRESS_INCLUDED | "

    # Return bit strings but trailing whitespace and commas
    return bit_str.rstrip().rstrip(" | ")


# Calculate the checksum of an event message
def event_checksum(message) -> int:
    checksum = 0

    while len(message) > 0:
        n = int(message[0:2], 16)
        checksum += n
        message = message[2:]
    return 0x100 - (checksum & 0xFF)


# Calculate checksum, returns tuple with [message_type, calculated_checksum]
def checksum(message) -> tuple[int, int]:
    # This message assumes caller has verified message is at least 8 characters long

    # Get the message type, it decides how we calculate checksum
    message_type = int(message[MP_MESSAGE_TYPE_BEGIN:MP_MESSAGE_TYPE_END], 16)

    if message_type == MT_SYSTEM_STATUS or message_type == MT_USER_INTERFACE:
        return [message_type, event_checksum(message)]

    # Unknown message type so just return zero checksum
    return [MT_UNKNOWN, 0x00]


def post_mqtt_status(area, zone, event):
    msg_info = mqttc.publish(
        f"ness/status/{zone}",
        f'{{ "type": "status", "area": {area}, "zone": {zone}, "event": "{ event_type_name(event) }" }}',
        qos=1,
    )
    unacked_publish.add(msg_info.mid)
    msg_info.wait_for_publish()


async def main():
    try:
        # Read configuration
        configHelper = YamlConfigurationHelper("config.yaml", "config.debug.yaml")
        config = await configHelper.read()

        # Configure logging
        log_levels = logging.getLevelNamesMapping()
        log_level = log_levels[config["logging"]["level"]]
        logging.basicConfig(filename=config["logging"]["file-name"], level=log_level)

        init_mqtt(config)

        # Loop forever
        while True:
            # Data will be a byte (UTF8) string with CRLF termination (e.g. b'87018361000200240316085613e4\r\n')
            # remove any CRLF at and of line read
            utf8_message = uart.readline().rstrip()

            # Event messages need to be at least 8 ASCII characters (4 bytes) long to be valid
            # as the message type is in characters 6,7 (4th byte), eg the message type 0x61
            # is at characters 6,7 (4th byte) in the following message
            #         ▼▼
            # b'8701836100020024031709020643\r\n'

            # If there was no data available then the message length will be zero,
            # however we also need a message of at least 8 characters long to get the message type
            if len(utf8_message) >= 8:
                # Convert to python unicode string
                unicode_message = utf8_message.decode()

                # Received checksum is the last two characters of the message
                rxd_checksum = unicode_message[-2:]

                # Message is everything except checksum
                message = unicode_message[:-2]

                # Calculate the checksum for the recieved message
                message_type, calculated_checksum = checksum(message)

                # Make sure the received checksum matches the calculated checksum (i.e. no transmission noise errors)
                if not rxd_checksum == "{:02x}".format(calculated_checksum):
                    # Checksum error so ignore this message
                    print(
                        "Invalid checksum",
                        rxd_checksum,
                        "{:02x}".format(calculated_checksum),
                    )
                    continue

                # Make sure message type was valid
                if message_type == MT_UNKNOWN:
                    # Do not process any further
                    print("Unknown message type", message)
                    continue

                # Get the start bit
                start = int(message[MP_START_BEGIN:MP_START_END], 16)

                # Display some message detail for info
                print(message)
                print(f"{message_type_name(message_type)}, {start_bits(start)}\r\n")

                # For status messages then publish a MQTT event
                if message_type == MT_SYSTEM_STATUS:
                    event = int(
                        message[MP_MESSAGE_EVENT_BEGIN:MP_MESSAGE_EVENT_END], 16
                    )
                    area = int(message[MP_MESSAGE_AREA_BEGIN:MP_MESSAGE_AREA_END], 16)
                    zone = int(message[MP_MESSAGE_ZONE_BEGIN:MP_MESSAGE_ZONE_END], 16)
                    post_mqtt_status(area, zone, event)
    finally:
        logger.debug("All tasks have completed")


if __name__ == "__main__":
    asyncio.run(main())
