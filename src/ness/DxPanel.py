import asyncio
import logging
import serial

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

# General states
ST_ARMED_AWAY = 0x24
ST_ARMED_HOME = 0x25
ST_DISARMED = 0x2F

# Zone states
ZS_UNSEALED = 0x00
ZS_SEALED = 0x01
ZS_ALARM = 0x02
ZS_ALARM_RESTORE = 0x03
ZS_MANUAL_EXCLUDE = 0x04
ZS_MANUAL_INCLUDE = 0x05


class AlarmZone:
    def __init__(self, area: int, zone_number: int, zone_name: str):
        self.area = area
        self.number = zone_number
        self.name = zone_name
        self.state = ZS_SEALED


class DxPanel:
    def __init__(self, serial_port, baud_rate, zone_count: int):
        self.logger = logging.getLogger(__name__)
        self.uart = serial.Serial(serial_port, baudrate=baud_rate, timeout=0.1)
        self.armed = False
        self.alarmed = False
        self.zones = []
        self.state_changed = False

        # Create zones
        for i in range(zone_count):
            self.zones.append(AlarmZone(0, i + 1, f"Zone {i + 1}"))

    def read_and_clear_state_change(self) -> bool:
        state_changed = self.state_changed
        self.state_changed = False
        return state_changed

    # Simple helper to get message type name string from message type byte code
    def message_type_name(self, message_type) -> str:
        if message_type == MT_SYSTEM_STATUS:
            return "MT_SYSTEM_STATUS"
        if message_type == MT_USER_INTERFACE:
            return "MT_USER_INTERFACE"
        return "MT_UNKNOWN"

    # Simple helper to get event type name string from message type byte code
    def event_type_name(self, event_type) -> str:
        if event_type == ZS_SEALED:
            return "EVT_SEALED"
        if event_type == ZS_UNSEALED:
            return "EVT_UNSEALED"
        if event_type == ZS_ALARM:
            return "EVT_ALARM"
        if event_type == ZS_ALARM_RESTORE:
            return "EVT_ALARM_RESTORE"
        if event_type == ZS_MANUAL_EXCLUDE:
            return "EVT_MANUAL_EXCLUDE"
        if event_type == ZS_MANUAL_INCLUDE:
            return "EVT_MANUAL_INCLUDE"
        if event_type == ST_ARMED_AWAY:
            return "ST_ARMED_AWAY"
        if event_type == ST_ARMED_HOME:
            return "ST_ARMED_HOME"
        if event_type == ST_DISARMED:
            return "ST_DISARMED"
        return f"EVT_UNKNOWN: {event_type}"

    # Simple helper to get start bit strings from start byte
    def start_bits(self, start) -> str:
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
    def event_checksum(self, message) -> int:
        checksum = 0

        while len(message) > 0:
            n = int(message[0:2], 16)
            checksum += n
            message = message[2:]
        return 0x100 - (checksum & 0xFF)

    # Calculate checksum, returns tuple with [message_type, calculated_checksum]
    def checksum(self, message) -> tuple[int, int]:
        # This message assumes caller has verified message is at least 8 characters long

        # Get the message type, it decides how we calculate checksum
        message_type = int(message[MP_MESSAGE_TYPE_BEGIN:MP_MESSAGE_TYPE_END], 16)

        if message_type == MT_SYSTEM_STATUS or message_type == MT_USER_INTERFACE:
            return (message_type, self.event_checksum(message))

        # Unknown message type so just return zero checksum
        return (MT_UNKNOWN, 0x00)

    def alarmed_state(self) -> bool:
        # Default to not in alarm
        alarmed = False

        # Check if any zone in alarm
        for zone in self.zones:
            if zone.state == ZS_ALARM:
                alarmed = True

        # Return alarm state
        return alarmed

    async def loop(self):
        while True:
            # Yeild time for a bit
            await asyncio.sleep(0.5)

            # Data will be a byte (UTF8) string with CRLF termination (e.g. b'87018361000200240316085613e4\r\n')
            # remove any CRLF at and of line read
            utf8_message = self.uart.readline().rstrip()

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
                message_type, calculated_checksum = self.checksum(message)

                # Make sure the received checksum matches the calculated checksum (i.e. no transmission noise errors)
                if not rxd_checksum == "{:02x}".format(calculated_checksum):
                    # Checksum error so ignore this message
                    continue

                # Make sure message type was valid
                if message_type == MT_UNKNOWN:
                    # Do not process any further
                    continue

                # For status messages then publish a MQTT event
                if message_type == MT_SYSTEM_STATUS:
                    event_type = int(
                        message[MP_MESSAGE_EVENT_BEGIN:MP_MESSAGE_EVENT_END], 16
                    )

                    if event_type == ST_ARMED_AWAY or event_type == ST_ARMED_HOME:
                        self.logger.debug(
                            f"Armed changed to '{self.event_type_name(message_type)}'"
                        )

                        self.armed = True

                        # Signal that state changed
                        self.state_changed = True

                        continue

                    if event_type == ST_DISARMED:
                        self.logger.debug(
                            f"Armed changed to '{self.event_type_name(message_type)}'"
                        )

                        self.armed = False

                        # Signal that state changed
                        self.state_changed = True

                        continue

                    area = int(message[MP_MESSAGE_AREA_BEGIN:MP_MESSAGE_AREA_END], 16)
                    zone_index = int(
                        message[MP_MESSAGE_ZONE_BEGIN:MP_MESSAGE_ZONE_END], 16
                    )

                    # Update valid zones
                    if zone_index > 0 and zone_index <= len(self.zones):
                        zone = self.zones[zone_index - 1]
                        if zone.state != event_type:
                            self.logger.debug(
                                f"Zone '{zone.name}' changed to '{self.event_type_name(event_type)}' from '{self.event_type_name(zone.state)}'"
                            )
                            # Signal that state changed
                            self.state_changed = True

                        zone.area = area
                        zone.state = event_type
