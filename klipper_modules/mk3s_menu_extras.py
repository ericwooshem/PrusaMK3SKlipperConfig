# MK3S+ LCD menu extras.
#
#   - SD-card file list sorted by date on LCD.
#   - Folder navigation in Print Files on LCD.
#   - Cancel Object from LCD.
#   - Knob print speed adjustment on the main screen while printing.
#   - Scrolling overflow status-screen text.
#   - GET_HOST_IP gcode command that resolves the host IP and saves it to
#     save_variables as 'host_ip' (shown on the LCD: Support > IP).
#   - PUSH_MENU gcode command that opens a named LCD menu programmatically
#     (used to pop the filament-type picker after an fsensor auto-load).
#   - MENU_BACK gcode command that pops one page back in the LCD menu
#     (used to auto-return to the main menu when a wizard finishes).
#
# Install: copy this file to the host's klippy/extras/ directory
#   (e.g. /home/pi/klipper/klippy/extras/mk3s_menu_extras.py)
# and add a [mk3s_menu_extras] section to printer.cfg, ABOVE any
# [display]/[menu] sections (it registers the "exclobjlist" menu type used by
# the Cancel Object menu). Then restart Klipper
#
# This file may be distributed under the terms of the GNU GPLv3 license.

import logging
import os
import subprocess

from extras.display import menu as menu_mod

VALID_GCODE_EXTS = ('gcode', 'g', 'gco')

_SCROLL_KEYS = ('up', 'down', 'fast_up', 'fast_down')

# Capture the stock handler before patching. The wrapper chains through it.
_orig_key_event = menu_mod.MenuManager.key_event


def _host_ip():
    # Return the host's primary IPv4 address, or None on failure.
    try:
        out = subprocess.check_output(['hostname', '-I'],
                                      timeout=3.0).decode().strip()
        return out.split()[0] if out else None
    except Exception:
        return None


def _sdcard_dir(sdcard):
    for attr in ("sdcard_dirname", "sdcard_path"):
        value = getattr(sdcard, attr, None)
        if value:
            return value
    return None


def _is_gcode(name):
    ext = name[name.rfind('.') + 1:].lower()
    return ext in VALID_GCODE_EXTS


def _mtime(path):
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def _dir_has_gcode(path):
    for root, _dirs, files in os.walk(path):
        for fname in files:
            if _is_gcode(fname):
                return True
    return False


def _make_print_cb(relpath):
    def _cb(el, context):
        el.manager.queue_gcode('M23 /%s' % str(relpath))
        el.manager.exit()
        return ''
    return _cb


def _exclude_current_cb():
    def _cb(el, context):
        el.manager.queue_gcode('EXCLUDE_OBJECT CURRENT=1')
        el.manager.exit()
        return ''
    return _cb


def _exclude_obj_cb(name):
    def _cb(el, context):
        el.manager.queue_gcode('EXCLUDE_OBJECT NAME=%s' % str(name))
        el.manager.exit()
        return ''
    return _cb


class FolderMenu(menu_mod.MenuList):
    def __init__(self, manager, config, **kwargs):
        super(FolderMenu, self).__init__(manager, config, **kwargs)
        self.sdcard_dir = kwargs.get('sdcard_dir')
        self.relpath = kwargs.get('path', '')

    def _populate(self):
        super(FolderMenu, self)._populate()
        _add_dir_entries(self, self.sdcard_dir, self.relpath)


def _add_dir_entries(container, sdcard_dir, relpath):
    path = (os.path.join(sdcard_dir, *relpath.split('/'))
            if relpath else sdcard_dir)
    try:
        entries = os.listdir(path)
    except OSError:
        return
    entries = [n for n in entries if not n.startswith('.')]
    dirs = sorted(
        [n for n in entries if os.path.isdir(os.path.join(path, n))],
        key=lambda n: (-_mtime(os.path.join(path, n)), n))
    files = sorted(
        [n for n in entries
         if os.path.isfile(os.path.join(path, n)) and _is_gcode(n)],
        key=lambda n: (-_mtime(os.path.join(path, n)), n))
    for d in dirs:
        if not _dir_has_gcode(os.path.join(path, d)):
            continue
        sub = (relpath + '/' + d) if relpath else d
        container.insert_item(FolderMenu(
            container.manager, None, name=d,
            sdcard_dir=sdcard_dir, path=sub))
    for f in files:
        rel = (relpath + '/' + f) if relpath else f
        container.insert_item(container.manager.menuitem_from(
            'command', name=repr(f), gcode=_make_print_cb(rel)))


def _populate_with_folders(self):
    menu_mod.MenuList._populate(self)
    sdcard = self.manager.printer.lookup_object('virtual_sdcard', None)
    if sdcard is None:
        return
    sdcard_dir = _sdcard_dir(sdcard)
    if not sdcard_dir or not os.path.isdir(sdcard_dir):
        return
    _add_dir_entries(self, sdcard_dir, '')


class MenuExclObjectList(menu_mod.MenuList):
    def _populate(self):
        super(MenuExclObjectList, self)._populate()
        excl = self.manager.printer.lookup_object('exclude_object', None)
        if excl is None:
            return
        status = excl.get_status(None)
        objects = status.get('objects') or []
        excluded = set(status.get('excluded_objects') or [])
        current = status.get('current_object')
        if current and current not in excluded:
            self.insert_item(self.manager.menuitem_from(
                'command', name='Currently: %s' % current,
                gcode=_exclude_current_cb()))
        for obj in objects:
            name = obj.get('name')
            if not name or name in excluded or name == current:
                continue
            self.insert_item(self.manager.menuitem_from(
                'command', name=name, gcode=_exclude_obj_cb(name)))


_speed_opts = {'step': 0.01, 'fast_step': 0.25, 'min': 0.1, 'max': 5.0,
               'deadzone': 3, 'deadzone_timeout': 0.5}


def _adjust_speed(manager, key):
    try:
        gcmd = manager.printer.lookup_object('gcode_move')
        factor = gcmd.get_status()['speed_factor']
        if key.endswith('down'):
            factor += _speed_opts['step']
        else:
            factor -= _speed_opts['step']
        factor = max(_speed_opts['min'], min(_speed_opts['max'], factor))
        manager.queue_gcode("M220 S%d" % round(factor * 100))
    except Exception:
        logging.exception("mk3s_menu_extras: speed adjust failed")


_scroll_cfg = {'step': 0.5, 'hold': 1.0}
_scroll_state = {'text': None, 'start': 0.0}


def _display_draw_text(display, orig, row, col, mixed_text, eventtime):
    # Scroll full-width status-screen text that overflows the row (stock
    # Klipper only scrolls selected menu items, not the status screen).
    if (not (display.menu is not None and display.menu.running)
            and col == 0 and mixed_text and '~' not in mixed_text):
        width, _height = display.get_dimensions()
        if len(mixed_text) > width:
            text = mixed_text
            step = _scroll_cfg['step']
            hold_steps = max(1, int(round(_scroll_cfg['hold'] / step)))
            if _scroll_state['text'] != text:
                _scroll_state['text'] = text
                _scroll_state['start'] = eventtime
            overflow = len(text) - width
            cycle = overflow + 2 * hold_steps
            pos = int((eventtime - _scroll_state['start']) / step) % cycle
            if pos < hold_steps:
                offset = 0
            elif pos < hold_steps + overflow:
                offset = pos - hold_steps
            else:
                offset = overflow
            mixed_text = text[offset:offset + width]
    return orig(row, col, mixed_text, eventtime)


def _key_event(self, key, eventtime):
    # Long-press the knob (while idle, not printing) to open the axis-move
    # screen with Z selected and already in edit mode, like Prusa firmware:
    # turn the knob to move Z, short-press the knob to confirm and return.
    if key == 'long_click' and not getattr(self, '_z_move_active', False):
        try:
            state = self.printer.lookup_object('idle_timeout').state
        except Exception:
            state = None
        if state != 'Printing':
            was_running = self.is_running()
            if not was_running:
                self.begin(eventtime)
            cur = self.stack_peek()
            cur_index = None
            if cur is not None:
                sel = cur.selected_item()
                if sel is not None:
                    cur_index = cur.index_of(sel)
            self._z_move_prev = (was_running, cur, cur_index)
            try:
                move = self.lookup_menuitem(
                    '__main __settings __move_1mm')
                self.stack_push(move)
                zitem = self.lookup_menuitem(
                    '__main __settings __move_1mm __axis_z')
                z_index = move.index_of(zitem)
                if z_index is not None:
                    move.select_at(z_index)
                    zitem.start_editing()
                    self._z_move_active = True
                else:
                    # Z not homed yet: stay in the move menu without
                    # auto-editing so a force move can be used instead.
                    self._z_move_active = False
            except Exception:
                logging.exception('Failed to open Z move menu')
                if not was_running:
                    self.exit()
            self.display.request_redraw()
            return
    # Short-press the knob while in the Z move screen: confirm and return.
    if getattr(self, '_z_move_active', False) and key == 'click':
        was_running, prev, idx = getattr(
            self, '_z_move_prev', (True, None, None))
        self._z_move_active = False
        if self.stack_size() > 0:
            self.stack_peek().stop_editing()
        if was_running:
            self.back(force=True)
            if prev is not None and idx is not None:
                prev.select_at(idx)
        else:
            self.stack_pop()
            self.running = False
        self.display.request_redraw()
        return
    # Encoder-wheel print speed adjustment on the main screen while printing.
    if key in _SCROLL_KEYS and not self.running:
        try:
            state = self.printer.lookup_object('idle_timeout').state
        except Exception:
            state = None
        if state == 'Printing':
            direction = 'down' if key.endswith('down') else 'up'
            dz = getattr(self, '_speed_deadzone', None)
            if (dz is None or dz[0] != direction
                    or eventtime - dz[2] > _speed_opts['deadzone_timeout']):
                dz = (direction, 0, eventtime)
            self._speed_deadzone = (direction, dz[1] + 1, eventtime)
            if self._speed_deadzone[1] > _speed_opts['deadzone']:
                _adjust_speed(self, key)
            self.display.request_redraw()
            return
    self._speed_deadzone = None
    return _orig_key_event(self, key, eventtime)


class MK3SMenuExtras:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.gcode = self.printer.lookup_object('gcode')
        self._host_ip = None
        # --- SD sort / speed adjust settings ---
        _speed_opts.update(
            step=config.getfloat('speed_step', _speed_opts['step'], above=0.),
            fast_step=config.getfloat('speed_fast_step',
                                      _speed_opts['fast_step'], above=0.),
            min=config.getfloat('speed_min', _speed_opts['min'], above=0.),
            max=config.getfloat('speed_max', _speed_opts['max'], above=0.),
            deadzone=config.getint('speed_deadzone',
                                   _speed_opts['deadzone'], minval=0),
            deadzone_timeout=config.getfloat(
                'speed_deadzone_timeout',
                _speed_opts['deadzone_timeout'], minval=0.))
        _scroll_cfg.update(
            step=config.getfloat('scroll_step', _scroll_cfg['step'], above=0.),
            hold=config.getfloat('scroll_hold', _scroll_cfg['hold'],
                                 minval=0.))
        self.gcode.register_command(
            'GET_HOST_IP', self.cmd_GET_HOST_IP,
            desc=self.cmd_GET_HOST_IP_help)
        self.gcode.register_command(
            'PUSH_MENU', self.cmd_PUSH_MENU,
            desc=self.cmd_PUSH_MENU_help)
        self.gcode.register_command(
            'MENU_BACK', self.cmd_MENU_BACK,
            desc=self.cmd_MENU_BACK_help)
        # --- patch the menu system ---
        menu_mod.MenuVSDList._populate = _populate_with_folders
        menu_mod.menu_items['exclobjlist'] = MenuExclObjectList
        menu_mod.MenuManager.key_event = _key_event
        self.printer.register_event_handler('klippy:ready', self._handle_ready)
        logging.info(
            "mk3s_menu_extras: sorted SD list with folders, "
            "Cancel Object list, wheel speed adjust, and "
            "status-screen scrolling loaded")

    def _handle_ready(self):
        display = self.printer.lookup_object('display', None)
        if display is None:
            return
        orig = display.draw_text
        display.draw_text = lambda row, col, text, eventtime: \
            _display_draw_text(display, orig, row, col, text, eventtime)

    cmd_GET_HOST_IP_help = "Print and save the host IP address"
    def cmd_GET_HOST_IP(self, gcmd):
        self._host_ip = _host_ip()
        if self._host_ip:
            try:
                self.gcode.run_script_from_command(
                    "SAVE_VARIABLE VARIABLE=host_ip VALUE='\"%s\"'"
                    % (self._host_ip,))
            except Exception:
                logging.exception("mk3s_menu_extras: failed to save host_ip")
            gcmd.respond_info("Host IP: %s  Web UI: http://%s"
                              % (self._host_ip, self._host_ip))
        else:
            gcmd.respond_info("Unable to determine host IP address.")

    cmd_PUSH_MENU_help = ("Open a named LCD menu (menu namespace, e.g. "
                          "NAME=\"__main __loadf\")")
    def cmd_PUSH_MENU(self, gcmd):
        name = gcmd.get('NAME')
        menu = self.printer.lookup_object('menu', None)
        if menu is None:
            raise gcmd.error("No LCD menu system is available")
        item = menu.lookup_menuitem(name)
        if item is None:
            raise gcmd.error("Unknown menu item '%s'" % (name,))
        if not isinstance(item, menu_mod.MenuContainer):
            raise gcmd.error("Menu item '%s' is not a menu container" % (name,))
        reactor = self.printer.get_reactor()
        eventtime = reactor.monotonic()
        if not menu.is_running():
            menu.begin(eventtime)
        if not menu.push_container(item):
            # Rare: a menu item is mid-edit. Don't fail the caller, just skip.
            gcmd.respond_info("Could not open menu '%s'" % (name,))
            return
        menu.display.request_redraw()

    cmd_MENU_BACK_help = "Go back one page in the LCD menu"
    def cmd_MENU_BACK(self, gcmd):
        menu = self.printer.lookup_object('menu', None)
        if menu is None:
            raise gcmd.error("No LCD menu system is available")
        if not menu.is_running():
            return
        menu.back(True)
        menu.display.request_redraw()

    def get_status(self, eventtime):
        return {'host_ip': self._host_ip}


def load_config(config):
    return MK3SMenuExtras(config)
