# Buzzer clicks for LCD menu navigation.
#
# Plays click sounds on the buzzer while navigating the LCD menus. The mode is
# stored in save_variables as 'sound_mode' (Silent / Assist / Loud):
#   - Silent: no sounds
#   - Assist: click on button presses, light click while scrolling
#   - Loud:   louder click on button presses (no scroll sounds)
#
# Toggle the mode from the LCD: Settings > Sound.
#
# Also provides a GET_HOST_IP gcode command that resolves the host IP and saves
# it to save_variables as 'host_ip' (shown on the LCD: Support > IP). This
# avoids needing the third-party gcode_shell_command extension.
#
# Install: copy this file to the host's klippy/extras/ directory
#   (e.g. /home/pi/klipper/klippy/extras/menu_beep.py)
# and add a [menu_beep] section to printer.cfg.
# Then restart Klipper (systemctl restart klipper, or Restart Firmware).
#
# This file may be distributed under the terms of the GNU GPLv3 license.

import logging
import subprocess

from extras.display import menu as menu_mod

_PIN_NAME = 'BEEPER_pin'
_DEFAULT_MODE = 'Assist'


def _host_ip():
    # Return the host's primary IPv4 address, or None on failure.
    try:
        out = subprocess.check_output(['hostname', '-I'],
                                      timeout=3.0).decode().strip()
        return out.split()[0] if out else None
    except Exception:
        return None

# active MenuBeep instance, used by the patched key_event handler
_beep = None

# Class-level patch of MenuManager.key_event. It chains with any other patch
# (e.g. sdcard_menu_sort) because each wrapper calls the previously assigned
# handler.
_orig_key_event = menu_mod.MenuManager.key_event


def _key_event(self, key, eventtime):
    ret = _orig_key_event(self, key, eventtime)
    if _beep is not None:
        try:
            _beep.on_key(self, key, eventtime)
        except Exception:
            logging.exception("menu_beep: error handling key event")
    return ret


class MenuBeep:
    def __init__(self, config):
        global _beep
        self.printer = config.get_printer()
        self.gcode = self.printer.lookup_object('gcode')
        self.pin_name = config.get('pin', _PIN_NAME)
        # press click (Assist mode)
        self.click_ms = config.getint('click_ms', 25)
        self.click_freq = config.getint('click_freq', 200)
        # scroll tick (Assist mode)
        self.scroll_ms = config.getint('scroll_ms', 12)
        self.scroll_freq = config.getint('scroll_freq', 300)
        # press click (Loud mode)
        self.loud_ms = config.getint('loud_ms', 60)
        self.loud_freq = config.getint('loud_freq', 120)
        self.scroll_interval = config.getfloat('scroll_interval', 0.04,
                                               above=0.)
        self._last_scroll_beep = 0.
        self._host_ip = None
        self.gcode.register_command(
            'GET_HOST_IP', self.cmd_GET_HOST_IP,
            desc=self.cmd_GET_HOST_IP_help)
        _beep = self

    cmd_GET_HOST_IP_help = "Print and save the host IP address"
    def cmd_GET_HOST_IP(self, gcmd):
        self._host_ip = _host_ip()
        if self._host_ip:
            try:
                self.gcode.run_script_from_command(
                    "SAVE_VARIABLE VARIABLE=host_ip VALUE='\"%s\"'"
                    % (self._host_ip,))
            except Exception:
                logging.exception("menu_beep: failed to save host_ip")
            gcmd.respond_info("Host IP: %s  Web UI: http://%s"
                              % (self._host_ip, self._host_ip))
        else:
            gcmd.respond_info("Unable to determine host IP address.")

    def _get_mode(self):
        try:
            sv = self.printer.lookup_object('save_variables', None)
            if sv is None:
                return _DEFAULT_MODE
            return sv.allVariables.get('sound_mode', _DEFAULT_MODE)
        except Exception:
            return _DEFAULT_MODE

    def _pin_scale(self):
        # SET_PIN VALUE is in 0..scale units; 0.5 duty == scale/2
        try:
            pin = self.printer.lookup_object('output_pin ' + self.pin_name,
                                             None)
            if pin is not None:
                scale = getattr(pin, 'scale', None)
                if scale:
                    return float(scale)
        except Exception:
            pass
        return 1000.

    def _beep(self, manager, freq, duration_ms):
        value = max(1, int(0.5 * self._pin_scale()))
        cycle_time = 1.0 / max(1, int(freq))
        script = ("SET_PIN PIN=%s VALUE=%d CYCLE_TIME=%.6f\n"
                  "G4 P%d\n"
                  "SET_PIN PIN=%s VALUE=0"
                  % (self.pin_name, value, cycle_time, duration_ms,
                     self.pin_name))
        manager.queue_gcode(script)

    def on_key(self, manager, key, eventtime):
        mode = self._get_mode()
        if mode == 'Silent':
            return
        if key in ('click', 'long_click', 'back'):
            if mode == 'Assist':
                self._beep(manager, self.click_freq, self.click_ms)
            elif mode == 'Loud':
                self._beep(manager, self.loud_freq, self.loud_ms)
        elif key in ('up', 'down', 'fast_up', 'fast_down'):
            # only tick on scrolls that actually move the menu
            if mode == 'Assist' and manager.running:
                if eventtime - self._last_scroll_beep < self.scroll_interval:
                    return
                self._last_scroll_beep = eventtime
                self._beep(manager, self.scroll_freq, self.scroll_ms)

    def get_status(self, eventtime):
        return {'mode': self._get_mode(), 'host_ip': self._host_ip}


menu_mod.MenuManager.key_event = _key_event


def load_config(config):
    return MenuBeep(config)
