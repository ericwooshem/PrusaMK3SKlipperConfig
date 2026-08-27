I wanted klipper on my MK3S+, but couldn't find any LCD configurations that replicated the default interface closely enough. So I made my own :D.

The following instructions were 80% written by AI. Hopefully it makes sense.
This repo is based on [charminULTRA/Klipper-Input-Shaping-MK3S-Upgrade](https://github.com/charminULTRA/Klipper-Input-Shaping-MK3S-Upgrade) and [Mithrandil/klipper-config-prusa-mk2s](https://github.com/Mithrandil/klipper-config-prusa-mk2s/).

All changes were made by AI. (So there are likely nonsense comments in the cfg files. I looked over comments in printer.cfg though, so those ones should make sense.)

**Warning:** I increased machine limits and driver current. Use with caution.

There are still some bugs and visual glitches, but nothing too serious.

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

---

# Automatically Mount USB Drives Inside the Prusa G-Code Directory

This setup automatically mounts USB storage devices as folders directly inside:

```text
/home/pi/printer_data/gcodes/
```

For example, a USB drive with UUID `A644-39EC` will appear as:

```text
/home/pi/printer_data/gcodes/A644-39EC/
```

The resulting directory might look like:

```text
gcodes/
├── BENCHY.GCODE
├── TEST.GCODE
└── A644-39EC/
    ├── FROM_USB.GCODE
    └── MODEL.GCODE
```

Existing files in `gcodes` remain visible. The USB is mounted only on its own UUID directory.

When the USB is removed, its UUID directory is removed automatically.

## 1. Create the mount helper

Create:

```bash
sudo nano /usr/local/sbin/usb-mount.sh
```

Paste:

```bash
#!/bin/bash
set -euo pipefail

ACTION="${1:-}"
KERNEL="${2:-}"

if [ -z "$ACTION" ] || [ -z "$KERNEL" ]; then
    echo "Usage: usb-mount.sh mount|unmount sda1" >&2
    exit 2
fi

DEV="/dev/$KERNEL"
STATE_DIR="/run/usb-mount"
BASE_DIR="/home/pi/printer_data/gcodes"

mkdir -p "$STATE_DIR" "$BASE_DIR"

get_mountpoint() {
    local uuid label name

    uuid="$(blkid -o value -s UUID "$DEV" 2>/dev/null || true)"
    label="$(blkid -o value -s LABEL "$DEV" 2>/dev/null || true)"

    if [ -n "$uuid" ]; then
        name="$uuid"
    elif [ -n "$label" ]; then
        name="$label"
    else
        name="$KERNEL"
    fi

    name="$(printf '%s' "$name" | tr -cd 'A-Za-z0-9._-')"

    printf '%s/%s\n' "$BASE_DIR" "$name"
}

case "$ACTION" in
    mount)
        FSTYPE="$(blkid -o value -s TYPE "$DEV" 2>/dev/null || true)"

        if [ -z "$FSTYPE" ]; then
            echo "No filesystem detected on $DEV" >&2
            exit 1
        fi

        MNT="$(get_mountpoint)"

        mkdir -p "$MNT"
        echo "$MNT" > "$STATE_DIR/$KERNEL"

        case "$FSTYPE" in
            vfat|exfat|ntfs|ntfs3)
                UID_PI="$(id -u pi 2>/dev/null || echo 1000)"
                GID_PI="$(id -g pi 2>/dev/null || echo 1000)"

                mount \
                    -t "$FSTYPE" \
                    -o "rw,nosuid,nodev,noatime,uid=$UID_PI,gid=$GID_PI,umask=022" \
                    "$DEV" "$MNT"
                ;;
            *)
                mount \
                    -t "$FSTYPE" \
                    -o rw,nosuid,nodev,noatime \
                    "$DEV" "$MNT"
                ;;
        esac
        ;;

    unmount)
        if [ -f "$STATE_DIR/$KERNEL" ]; then
            MNT="$(cat "$STATE_DIR/$KERNEL")"

            umount "$MNT" 2>/dev/null ||
                umount -l "$MNT" 2>/dev/null ||
                true

            rmdir "$MNT" 2>/dev/null || true
            rm -f "$STATE_DIR/$KERNEL"
        fi
        ;;

    *)
        echo "Usage: usb-mount.sh mount|unmount sda1" >&2
        exit 2
        ;;
esac
```

Save and make it executable:

```bash
sudo chmod +x /usr/local/sbin/usb-mount.sh
```

## 2. Create the systemd service

Create:

```bash
sudo nano /etc/systemd/system/usb-mount@.service
```

Paste:

```ini
[Unit]
Description=Auto-mount USB storage %I
BindsTo=dev-%i.device
After=dev-%i.device

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/local/sbin/usb-mount.sh mount %I
ExecStop=/usr/local/sbin/usb-mount.sh unmount %I
```

Reload systemd:

```bash
sudo systemctl daemon-reload
```

## 3. Create the udev rule

Create:

```bash
sudo nano /etc/udev/rules.d/99-usb-mount.rules
```

Paste:

```udev
ACTION=="add", SUBSYSTEM=="block", ENV{ID_BUS}=="usb", ENV{ID_FS_USAGE}=="filesystem", TAG+="systemd", ENV{SYSTEMD_WANTS}+="usb-mount@%k.service"
```

Reload:

```bash
sudo udevadm control --reload-rules
```

## 4. Test it

Unplug the USB drive, wait a few seconds, and plug it back in. The drive should be mounted in the gcode folder.
