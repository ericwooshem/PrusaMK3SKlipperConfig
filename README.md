I wanted klipper on my MK3S+, but couldn't find any LCD configurations that replicated the default interface closely enough. So I made my own :D.

The following instructions were 80% written by AI. Hopefully it makes sense.
This repo is based on [charminULTRA/Klipper-Input-Shaping-MK3S-Upgrade](https://github.com/charminULTRA/Klipper-Input-Shaping-MK3S-Upgrade) and [Mithrandil/klipper-config-prusa-mk2s](https://github.com/Mithrandil/klipper-config-prusa-mk2s/). All changes were made by AI.

**Warning:** I increased machine limits and driver current. Use with caution.

# Prusa MK3S+ Klipper Config

A complete Klipper configuration for the **Original Prusa i3 MK3S+** focused on performance while aiming to replicate the familiar stock Prusa interface.

## Features

- Nearly-replicated standard MK3S LCD interface + enhancements
- Increased MK3S machine limits (more dangerous :D)
- Live Z-offset adjustment with automatic persistence without SAVE_CONFIG
- Exclude-object LCD support
- USB Gcode support with automatic disk mounting and file sorting
- Automatically restart Klipper when MCU reconnects (no need to press "Firmware Restart" when MCU boots after Klipper)


## Installation

### 1. Install Klipper + Moonraker + Mainsail/Fluidd on your host

Follow the [official Klipper install guide](https://www.klipper3d.org/Installation.html) for your host (e.g. Raspberry Pi, or a client install that runs Klipper but flash via USB). That guide covers obtaining an OS image (MainsailOS) or installing via KIAUH, building and flashing the micro-controller to the Einsy Rambo board, and setting the `[mcu]` serial path. Don't repeat those steps here.

### 2. Clone this repository

```bash
cd ~
git clone https://github.com/<your-username>/PrusaMK3SKlipperConfig
```

### 3. Copy the config files (and the `lcdconfig` folder) to `~/printer_data/config/`

### 4. Copy `klipper_modules/mk3s_menu_extras.py` to `~/klipper/klippy/extras/`

### 5. Tune YOUR printer

The config is tuned for my printer. You may want to recalibrate:
- Extruder rotation distance
- PID values (extruder + bed)
- Pressure advance
- Input shaper
- Skew correction

## Klipper MCU Auto-Restart Setup

## 1. Find the printer USB path

Find the path:
```bash
ls /dev/serial/by-id/
```

Copy the printer's device name. The full path will look similar to:

```text
/dev/serial/by-id/usb-Prusa_Research__prusa3d.com__Original_Prusa_i3_MK3_CZPX4222X004XK90480-if00
```

## 2. Install `jq`

```bash
sudo apt update
sudo apt install -y jq
```

## 3. Create the watcher script

```bash
sudo nano /usr/local/bin/klipper-mcu-watch.sh
```

Paste:

```bash
#!/bin/bash

DEVICE="/dev/serial/by-id/usb-Prusa_Research__prusa3d.com__Original_Prusa_i3_MK3_CZPX4222X004XK90480-if00"

while true; do
    if [ -e "$DEVICE" ]; then
        STATE=$(curl -s http://127.0.0.1:7125/server/info | jq -r '.result.klippy_state')
        CONNECTED=$(curl -s http://127.0.0.1:7125/server/info | jq -r '.result.klippy_connected')

        if [ "$CONNECTED" != "true" ] || [ "$STATE" != "ready" ]; then
            sleep 10

            STATE=$(curl -s http://127.0.0.1:7125/server/info | jq -r '.result.klippy_state')
            CONNECTED=$(curl -s http://127.0.0.1:7125/server/info | jq -r '.result.klippy_connected')

            if [ "$CONNECTED" != "true" ] || [ "$STATE" != "ready" ]; then
                systemctl restart klipper
                sleep 60
            fi
        fi
    fi

    sleep 5
done
```

Replace the `DEVICE=` path with the path from Step 1.

Save.

## 5. Make the script executable

```bash
sudo chmod +x /usr/local/bin/klipper-mcu-watch.sh
```

## 6. Create the systemd service

```bash
sudo nano /etc/systemd/system/klipper-mcu-watch.service
```

Paste:

```ini
[Unit]
Description=Klipper MCU Connection Watcher
After=network.target moonraker.service klipper.service

[Service]
Type=simple
ExecStart=/usr/local/bin/klipper-mcu-watch.sh
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Save with **Ctrl+O**, Enter, then **Ctrl+X**.

## 7. Enable and start it

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now klipper-mcu-watch.service
```

## 8. Check status

```bash
systemctl status klipper-mcu-watch.service
```

It should show:

```text
Active: active (running)
```
