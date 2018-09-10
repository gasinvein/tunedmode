#!/usr/bin/env python3

from pydbus import SystemBus, SessionBus
from gi.repository import GLib
from configparser import ConfigParser
from xdg.BaseDirectory import save_config_path
import os


TUNEDMODE_BUS_NAME = 'com.feralinteractive.GameMode'

CONFIG_DEFAULTS = {
    'tuned': {
        'game-profile': 'latency-performance'
    }
}


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

    def __init__(self, config, system_bus):
        self.tuned = system_bus.get('com.redhat.tuned', '/Tuned')
        self.registred_games = set()
        self.previous_profile = self.tuned.active_profile()
        print(f'Initial profile is {self.previous_profile}')
        self.game_profile = config['tuned']['game-profile']

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        print(f'Switching back to profile {self.previous_profile}')
        success, msg = self.tuned.switch_profile(self.previous_profile)
        if not success:
            print(f'Switching to {self.previous_profile} failed: {msg}')
        return success

    def RegisterGame(self, i):
        print(f'Register game {i}')
        if i in self.registred_games:
            raise ValueError(f'Process {i} is already known')
        success, msg = self.tuned.switch_profile(self.game_profile)
        if success:
            self.registred_games.add(i)
        return 0

    def UnregisterGame(self, i):
        print(f'Unregister game {i}')
        if i in self.registred_games:
            self.registred_games.remove(i)
        else:
            raise ValueError(f'Process {i} is not known')
        if len(self.registred_games) == 0:
            success, msg = self.tuned.switch_profile(self.previous_profile)
        return 0

    def QueryStatus(self, i):
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


if __name__ == '__main__':
    loop = GLib.MainLoop()
    with SessionBus() as session_bus:
        with SystemBus() as system_bus:
            c = init_config(os.path.join(save_config_path('tunedmode'), 'tunedmode.conf'))
            with TunedMode(config=c, system_bus=system_bus) as tuned_mode:
                with session_bus.publish(TUNEDMODE_BUS_NAME, tuned_mode):
                    loop.run()
