#!/usr/bin/env python3

from pydbus import SystemBus, SessionBus
from gi.repository import GLib

TUNEDMODE_BUS_NAME = 'com.feralinteractive.GameMode'


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

    def __init__(self, system_bus):
        self.tuned = system_bus.get('com.redhat.tuned', '/Tuned')
        self.registred_games = set()
        self.previous_profile = self.tuned.active_profile()
        print(f'Initial profile is {self.previous_profile}')
        #TODO unhardcode performance profile name
        self.game_profile = 'latency-performance'

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
        if i in self.registred_games:
            return 1
        else:
            return 0


if __name__ == '__main__':
    loop = GLib.MainLoop()
    with SessionBus() as session_bus:
        with SystemBus() as system_bus:
            with session_bus.publish(TUNEDMODE_BUS_NAME, TunedMode(system_bus=system_bus)):
                loop.run()
