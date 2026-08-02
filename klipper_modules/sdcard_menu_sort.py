# Sort the LCD SD-card file list by modification time (newest first) and
# navigate into subdirectories from the LCD.
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


class SDCardMenuSort:
    def __init__(self, config):
        menu_mod.MenuVSDList._populate = _populate_with_folders
        logging.info(
            "sdcard_menu_sort: SD menu shows folders, newest files first")

    def get_status(self, eventtime):
        return {}


def load_config(config):
    return SDCardMenuSort(config)
