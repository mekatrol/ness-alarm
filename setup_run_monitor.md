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

```

### Create start shell script

```bash
cd ~/
nano alarm_monitor_start.sh
```

### Paste script content

```bash
cd /home/pi/repos/ness-alarm/src/
source ./venv/bin/activate
python3 ./main.py
cd ~/
```

### Create service file

```bash
sudo nano /lib/systemd/system/alarm_monitor.service
```

### Paste service content

```ini
[Unit]
Description=Alarm Monitor
After=multi-user.target

[Service]
Type=simple
ExecStart=/bin/bash /home/pi/run_alarm_monitor.sh
Restart=on-abort
User=pi
Group=pi

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
