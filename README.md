# NESS Alarm DX8/DX16 alarm protocol examples

## Overview

Example communication with NESS alarm DX8/DX16 panels. Taken from the NESS website link [D8x/D16x ASCII Protocol Rev13](https://drive.google.com/file/d/1vl8Gs1GY-gKAPSiU8yjCzrgQxm8ybhQh/view?usp=sharing).

The was found by navigating to [ness.com.au](https://ness.com.au) -> support -> Security Alarm Panels -> Ness Control Panel Software and on that page there is a link to the protocol `D8x/D16x ASCII Protocol Rev13` (which seems to be hosted on a Goolge drive).

A [copy](./Ness_D8-D16_ASCII_protocol_rev13.pdf) is included in this repo for easy reference.

## Configuring the panel

To enable communications the following isntaller options need to be set:

- P90E 1E - Enable Remote Access
- P90E 7E - Will send regular event updates, e.g. `b'820003601700877d'`

- P199E 1E - : Send Address. The address is the last digit of Acc No.2 (P73E).
- P199E 2E - : Send Time Stamp.

- P199E 3E - : Send Alarms.

- P199E 4E - : Send Warnings.

- P199E 5E - : Send Access Events.

- P199E 6E - : Send Zone Seal State. (D8x/D16x V6 and later.)

- P199E 7E - : Send test ASCII string. Sends test data periodically, used for testing the serial port (D8x/
D16x V6 and later.)

**If you have multiple alarm panels then P73E can be used to set an account number for each panel which will then be transmitted as the address (last digit) so that events can be attributed to a particular panel.**

## Hardware

### NESS cable

I obtained the NESS panel cable on ebay.com.au from reseller *mw-security* using search term 'NESS IP ETHERNET MODULE IP232 SERIAL LEAD 3 4 WAY DB9 RS232 Programing cable'.

### RS232

- USB Serial Cable with PL2303 Chipset USB to RS232 DB9 9 Pin Male Adapter [Amazon.com.au](https://amazon.com.au)
- JAYCAR Arduino Compatible RS-232 to TTL UART Converter Module (XC3724) - this one requires a null modem cable between Alarm and the RS232 module, but this could depend on the actual cable plugged into NESS alarm and how pins 2 & 3 on the DB9 are connected.

### Controller

I used one of my old Raspberry Pis and connected to the panel successfully usingboth of:

- the USB to RS232 serial port in Linux is a USB one e.g. to `/dev/ttyUSB0`
- UART0 serial port in Linux is `/dev/serial0`

## Installed

![image](installed.png)
