import configparser, os, re, traceback

import jinja2

MENU_FILE = os.path.join(os.path.dirname(__file__),
                         'config', 'lcdconfig', 'menu_original_prusa.cfg')

class Undef(jinja2.Undefined):
    pass


class Namespace:
    """Recursive namespace that returns Undefined for unknown attributes."""
    def __init__(self, **kw):
        self.__dict__.update(kw)

    def __getattr__(self, name):
        return Undef()

    def __getitem__(self, name):
        if name in self.__dict__:
            return self.__dict__[name]
        return Undef()

    def __contains__(self, name):
        return name in self.__dict__

    def get(self, name, default=None):
        return self.__dict__.get(name, default)

    def __repr__(self):
        return 'Namespace(%s)' % ','.join(self.__dict__)


def build_printer(state='standby'):
    extruder = Namespace(target=215.0, temperature=210.0)
    bed = Namespace(target=60.0, temperature=59.0)
    fan = Namespace(speed=0.25)
    homing_origin = Namespace(z=0.0)
    gcode_move = Namespace(
        gcode_position=Namespace(x=120.0, y=80.0, z=12.0),
        homing_origin=homing_origin,
        speed_factor=1.0,
        speed=1.0)
    toolhead = Namespace(
        homed_axes='xyz',
        position=Namespace(x=120.0, y=80.0, z=12.0),
        axis_minimum=Namespace(x=0.0, y=0.0, z=0.0),
        axis_maximum=Namespace(x=250.0, y=210.0, z=200.0),
        max_accel=6000.0)
    heaters = Namespace(available_heaters=['extruder', 'heater_bed'])
    idle_timeout = Namespace(state='Idle')
    print_stats = Namespace(state=state)
    cfgext = Namespace(max_temp=300.0, max_extrude_only_distance=50)
    cfgbed = Namespace(max_temp=120.0)
    cfg = Namespace(extruder=cfgext, heater_bed=cfgbed)
    configfile = Namespace(config=cfg)
    svars = Namespace(
        variables=Namespace(selected_bed='smooth',
                            home_menu_mode='traditional'))
    save_variables = Namespace(variables=svars.variables)
    macro = Namespace(mult=1.0)
    gcode_macro = Namespace(**{'ACCEL_STATE': macro})
    printer = Namespace(
        extruder=extruder, heater_bed=bed, fan=fan,
        gcode_move=gcode_move, toolhead=toolhead, heaters=heaters,
        idle_timeout=idle_timeout, print_stats=print_stats,
        configfile=configfile,
        save_variables=save_variables,
        gcode_macro=gcode_macro,
        display_status=Namespace(message='', progress=0.0))
    printer.__dict__['extruder'] = extruder
    printer.__dict__['heater_bed'] = bed
    printer.__dict__['gcode_move'] = gcode_move
    printer.__dict__['toolhead'] = toolhead
    printer.__dict__['idle_timeout'] = idle_timeout
    printer.__dict__['print_stats'] = print_stats
    printer.__dict__['save_variables'] = save_variables
    printer.__dict__['display_status'] = printer.display_status
    printer.__dict__['gcode_macro'] = gcode_macro
    return printer


def make_env():
    return jinja2.Environment(
        variable_start_string='{', variable_end_string='}',
        block_start_string='{%', block_end_string='%}',
        comment_start_string='{#', comment_end_string='#}',
        undefined=Undef)


def render_tpl(env, text, context, name):
    try:
        tpl = env.from_string(text)
        out = tpl.render(context)
        return out
    except Exception:
        print('  !! %s THREW:' % name)
        traceback.print_exc()
        return None


def main():
    cp = configparser.RawConfigParser(interpolation=None)
    cp.optionxform = str
    cp.read(MENU_FILE)
    env = make_env()

    print('=== SETTINGS menu items (idle / printing) ===')
    for state in ('standby', 'printing'):
        print('\n--- print_stats.state = %s ---' % state)
        printer = build_printer(state)
        menu = Namespace(ns='__main __settings', input=0.0, eventtime=0.0)
        ctx = {'printer': printer, 'menu': menu}
        for section in cp.sections():
            if not section.startswith('menu __main __settings'):
                continue
            depth = len([p for p in section.split(' ') if p.startswith('__')])
            if depth != 3:
                continue  # only direct children of __settings
            name = cp.get(section, 'name', raw=True)
            enable = cp.get(section, 'enable', raw=True) \
                if cp.has_option(section, 'enable') else None
            try:
                en = True if enable is None else bool(
                    __import__('ast').literal_eval(
                        render_tpl(env, enable, ctx, section)))
            except Exception:
                en = 'ENABLE THREW'
            nm = render_tpl(env, name, ctx, section)
            print('%-46s enable=%-8s name=%r' % (section, en, nm))


if __name__ == '__main__':
    main()
