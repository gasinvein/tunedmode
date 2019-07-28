#!/usr/bin/env python3

from pydbus import SystemBus, SessionBus
from gi.repository import GLib
from configparser import ConfigParser
from xdg.BaseDirectory import save_config_path
import os
import sys
import signal
import logging


TUNEDMODE_BUS_NAME = 'com.feralinteractive.GameMode'

CONFIG_DEFAULTS = {
    'tuned': {
        'gaming-profile': 'latency-performance'
    }
}


def log(message, level=logging.INFO):
    # TODO make logging to stderr OR to syslog
    print(message, file=sys.stderr)


class TunedMode(object):
    dbus = f"""
    <node>
        <interface name='{TUNEDMODE_BUS_NAME}'>
            <method name='RegisterGame'>
                <arg type='i' name='i' direction='in'/>
                <arg type='i' name='i' direction='out'/>
            </method>
            <method name='UnregisterGame'>
                <arg type='i' name='i' direction='in'/>
                <arg type='i' name='i' direction='out'/>
            </method>
            <method name='QueryStatus'>
                <arg type='i' name='i' direction='in'/>
                <arg type='i' name='i' direction='out'/>
            </method>
        </interface>
    </node>
    """

    def __init__(self, config, system_bus, session_bus):
        self.dbus = session_bus.get('org.freedesktop.DBus', '/org/freedesktop/DBus')
        self.tuned = system_bus.get('com.redhat.tuned', '/Tuned')
        self.registred_games = set()
        self.initial_profile = self.tuned.active_profile()
        self.gaming_profile = config['tuned']['gaming-profile']
        if self.gaming_profile not in self.tuned.profiles():
            raise ValueError(f'Gaming profile "{self.gaming_profile}" doesn\'t exist')
        log(f'Initial profile is "{self.initial_profile}", gaming profile is "{self.gaming_profile}"')

    def __enter__(self):
        return self

    def __exit__(self, *args, **kwargs):
        log(f'Switching back to profile "{self.initial_profile}"')
        success, msg = self.tuned.switch_profile(self.initial_profile)
        if not success:
            log(f'Switching to "{self.initial_profile}" failed: {msg}')

    def get_sender_pid(self, dbus_context):
        return self.dbus.GetConnectionUnixProcessID(dbus_context.sender)

    def RegisterGame(self, i, dbus_context):
        print(f'Register game {i}')
        if i in self.registred_games:
            raise ValueError(f'Process {i} is already known')
        success, msg = self.tuned.switch_profile(self.gaming_profile)
        if success:
            self.registred_games.add(i)
        return 0

    def UnregisterGame(self, i, dbus_context):
        print(f'Unregister game {i}')
        if i in self.registred_games:
            self.registred_games.remove(i)
        else:
            raise ValueError(f'Process {i} is not known')
        if len(self.registred_games) == 0:
            success, msg = self.tuned.switch_profile(self.initial_profile)
        return 0

    def QueryStatus(self, i, dbus_context):
        print(f'Status game {i}')
        # TODO ensure that we return exactly what client expects
        if i in self.registred_games:
            return 1
        else:
            return 0


def init_config(config_file):
    config = ConfigParser()
    config.read_dict(CONFIG_DEFAULTS)
    config.read(config_file)
    if not os.path.isfile(config_file):
        with open(config_file, 'w') as cf:
            config.write(cf)
    return config


def run_tunedmode(config_file):
    c = init_config(config_file)
    loop = GLib.MainLoop()
    with SessionBus() as session_bus:
        with SystemBus() as system_bus:
            with TunedMode(config=c, system_bus=system_bus, session_bus=session_bus) as tuned_mode:
                with session_bus.publish(TUNEDMODE_BUS_NAME, tuned_mode):
                    signal.signal(signal.SIGTERM, lambda n, f: loop.quit())
                    signal.signal(signal.SIGINT, lambda n, f: loop.quit())
                    loop.run()


if __name__ == '__main__':
    cf = os.path.join(save_config_path('tunedmode'), 'tunedmode.ini')
    run_tunedmode(cf)
