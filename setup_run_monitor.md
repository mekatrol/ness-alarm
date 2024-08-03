# NESS Alarm

## Monitoring program

### Clone repo

```bash
 git clone https://github.com/mekatrol/ness-alarm.git
```

### Create virtual environment

```bash
python -m venv venv
```

### Activate environment

```bash
source venv/bin/activate
```

### Install requirements

```bash
pip install -r requirements.txt
```

### Configure settings

```yaml
# NOTE: if you create a file named config.debug.yaml then the configuration settings in that file
#       will override the configuration settings in this file. Because config.debug.yaml is
#       GIT ignored then you can add sensitive settings (e.g. passwords, tokens, etc) to that file
#       without concern for committing the sensitive information.
#
#       You only need to define the values that you want to override. You do not need to repeat any
#       configuration setting values here that are not different.

logging:
  file-name: "log.txt"
  level: "INFO"

mqtt:
  host: "homeassistant.lan"
  port: 1883
  user: "<insert mqtt user name here>"
  password: "<insert mqtt password here>"

serial:
  device: "/dev/ttyUSB0"
  baud_rate: 9600
  zones: 8      
```

### Create service file

```bash
sudo nano /lib/systemd/system/alarm_monitor.service
```

### Paste service content

```ini
[Unit]
Description=Alarm Monitor Service
Wants=network-online.target
After=network.target network-online.target

[Service]
User=pi
ExecStartPre=/bin/sleep 60
ExecStart=/usr/bin/python3 /home/pi/repos/ness-alarm/src/main.py
WorkingDirectory=/home/pi/repos/ness-alarm/src
Restart=on-abort

[Install]
WantedBy=multi-user.target
```

### Enable service

```bash
 sudo systemctl enable alarm_monitor.service
 ```

### Start service

```bash
sudo systemctl start alarm_monitor.service
```

### Check status

```bash
sudo systemctl status alarm_monitor.service

```
