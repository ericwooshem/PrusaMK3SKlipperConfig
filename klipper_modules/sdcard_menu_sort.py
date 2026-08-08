# Extends the LCD menus:
#   - Sort the SD-card file list by modification time (newest first) and
#     navigate into subdirectories from the LCD.
#   - Register a "Cancel Object" list menu type ("exclobjlist") that lists
#     print objects and excludes the selected one on click, with the
#     currently printing object shown at the top.
#
# Install: copy this file to the host's klippy/extras/ directory
#   (e.g. /home/pi/klipper/klippy/extras/sdcard_menu_sort.py)
# and add a [sdcard_menu_sort] section to printer.cfg.
# Then restart Klipper (systemctl restart klipper, or Restart Firmware).
#
# This file may be distributed under the terms of the GNU GPLv3 license.

import logging
import os

from extras.display import menu as menu_mod

VALID_GCODE_EXTS = ('gcode', 'g', 'gco')


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


_orig_key_event = menu_mod.MenuManager.key_event

_speed_opts = {'step': 0.01, 'fast_step': 0.25, 'min': 0.1, 'max': 5.0,
               'deadzone': 3, 'deadzone_timeout': 0.5}


def _adjust_speed(manager, key):
    try:
        step = (_speed_opts['fast_step'] if key.startswith('fast')
                else _speed_opts['step'])
        gcmd = manager.printer.lookup_object('gcode_move')
        factor = gcmd.get_status()['speed_factor']
        if key.endswith('down'):
            factor += step
        else:
            factor -= step
        factor = max(_speed_opts['min'], min(_speed_opts['max'], factor))
        manager.queue_gcode("M220 S%d" % round(factor * 100))
    except Exception:
        logging.exception("sdcard_menu_sort: speed adjust failed")


def _key_event(self, key, eventtime):
    if key in ('up', 'down', 'fast_up', 'fast_down') and not self.running:
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
        key=lambda n: _mtime(os.path.join(path, n)), reverse=True)
    files = sorted(
        [n for n in entries
         if os.path.isfile(os.path.join(path, n)) and _is_gcode(n)],
        key=lambda n: _mtime(os.path.join(path, n)), reverse=True)
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


class SDCardMenuSort:
    def __init__(self, config):
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
        menu_mod.MenuVSDList._populate = _populate_with_folders
        menu_mod.MenuManager.key_event = _key_event
        menu_mod.menu_items['exclobjlist'] = MenuExclObjectList
        logging.info(
            "sdcard_menu_sort: SD menu shows folders, newest files first; "
            "wheel adjusts print speed on main screen; "
            "Cancel Object menu type 'exclobjlist' registered")

    def get_status(self, eventtime):
        return {}


def load_config(config):
    return SDCardMenuSort(config)
