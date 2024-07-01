import serial

# message types
MT_UNKNOWN = 0xFF
MT_SYSTEM_STATUS = 0x61
MT_USER_INTERFACE = 0x60

# message positions (for ASCII strings)
MP_START_BEGIN = 0
MP_START_END = MP_START_BEGIN + 2

MP_MESSAGE_TYPE_BEGIN = 6
MP_MESSAGE_TYPE_END = MP_MESSAGE_TYPE_BEGIN + 2

# Start byte bits
SB_ADDRESS_INCLUDED = 0x01
SB_BASIC_HEADER = 0x02  # According to spec, this bit is always set in the start byte
SB_TIME_STAMP = 0x04  # Set if the time stamp is included in the message
SB_ASCII = 0x80  # According to spec, this bit is always set in the start byte

# USB serial '/dev/ttyUSB0'
# UART 0 serial '/dev/serial0'

uart = serial.Serial("/dev/ttyUSB0", baudrate=9600, timeout=3.0)


def message_type_name(message_type) -> str:
    if message_type == MT_SYSTEM_STATUS:
        return "MT_SYSTEM_STATUS"
    if message_type == MT_USER_INTERFACE:
        return "MT_USER_INTERFACE"
    return "MT_UNKNOWN"


def start_bits(start) -> str:
    bit_str = ""

    if start & SB_ASCII:
        bit_str += "SB_ASCII, "

    if start & SB_BASIC_HEADER:
        bit_str += "SB_BASIC_HEADER, "

    if start & SB_TIME_STAMP:
        bit_str += "SB_TIME_STAMP, "

    if start & SB_ADDRESS_INCLUDED:
        bit_str += "SB_ADDRESS_INCLUDED, "

    # return bit strings but trailing whitespace and commas
    return bit_str.rstrip().rstrip(",")


def event_checksum(message) -> int:
    checksum = 0

    while len(message) > 0:
        n = int(message[0:2], 16)
        checksum += n
        message = message[2:]
    return 0x100 - (checksum & 0xFF)


# Calculate checksum, returns tuple with [message_type, calculated_checksum]
def checksum(message) -> tuple[int, int]:
    # this message assumes caller has verified message is at least 8 characters long

    # get the message type, it decides how we calculate checksum
    message_type = int(message[MP_MESSAGE_TYPE_BEGIN:MP_MESSAGE_TYPE_END], 16)

    if message_type == MT_SYSTEM_STATUS or message_type == MT_USER_INTERFACE:
        return [message_type, event_checksum(message)]

    # Unknown message type so just return zero checksum
    return [MT_UNKNOWN, 0x00]


while True:
    # data will be a byte (UTF8) string with CRLF termination (e.g. b'87018361000200240316085613e4\r\n')
    # remove any CRLF at and of line read
    utf8_message = uart.readline().rstrip()

    # event messages need to be at least 8 ASCII characters (4 bytes) long to be valid
    # as the message type is in characters 6,7 (4th byte), eg the message type 0x61
    # is at characters 6,7 (4th byte) in the following message
    #         ▼▼
    # b'8701836100020024031709020643\r\n'

    # if there was no data available then the len of utf8_message will be zero,
    # however we also need a message of at least 8 characters long to get the
    if len(utf8_message) >= 8:
        # we can convert to python unicode string and strip trailing CRLF
        unicode_message = utf8_message.decode().rstrip()

        # received checksum (is the last two characters of the message)
        rxd_checksum = unicode_message[-2:]

        # message is everything except checksum
        message = unicode_message[:-2]

        # calculate the checksum for the received message
        message_type, calculated_checksum = checksum(message)

        # make sure message type was valid
        if message_type == MT_UNKNOWN:
            # do not process any further
            print("Unknown message type", message)
            continue

        if not rxd_checksum == "{:02x}".format(calculated_checksum):
            # checksum error so ignore this message
            print(
                "Invalid checksum", rxd_checksum, "{:02x}".format(calculated_checksum)
            )
            continue

        start = int(message[MP_START_BEGIN:MP_START_END], 16)

        print(message)
        print(f"{message_type_name(message_type)} | {start_bits(start)}\r\n")
