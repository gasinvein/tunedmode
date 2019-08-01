#!/usr/bin/env python3

import os
import sys
import signal
import logging
import threading
from configparser import ConfigParser
from pydbus import SystemBus, SessionBus
from xdg.BaseDirectory import save_config_path
import psutil
from gi.repository import GLib


TUNEDMODE_BUS_NAME = 'com.feralinteractive.GameMode'

CONFIG_DEFAULTS = {
    'tuned': {
        'gaming-profile': 'latency-performance'
    }
}

RES_SUCCESS = 0
RES_ERROR = -1

def log(message, level=logging.INFO):
    """Log provided message somewhere."""
    # TODO make logging to stderr OR to syslog
    print(message, file=sys.stderr)


def get_process_name(pid):
    """Get cmdline of a process by it's PID."""
    proc_cmd = None
    if psutil.pid_exists(pid):
        proc_cmd = psutil.Process(pid=pid).cmdline()[0]
    return proc_cmd


class TunedMode:
    """DBus daemon implementing GameMode-compatible interface."""

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
        """Gather initial settings and config options."""
        self.tuned = system_bus.get('com.redhat.tuned', '/Tuned')
        self.registred_games = set()
        self.initial_profile = self.tuned.active_profile()
        self.gaming_profile = config['tuned']['gaming-profile']
        if self.gaming_profile not in self.tuned.profiles():
            raise ValueError(f'Gaming profile "{self.gaming_profile}" doesn\'t exist')
        log(f'Initial profile is "{self.initial_profile}", '
            f'gaming profile is "{self.gaming_profile}"')

    def __enter__(self):
        """Set thing up."""
        return self

    def __exit__(self, *args, **kwargs):
        """Make sure TuneD profile it set back to initial value."""
        self._switch_profile(self.initial_profile)

    def __watch_process_worker(self, pid: int):
        process = psutil.Process(pid)
        process.wait()
        print(f"Process: {process.pid} exited")
        if process.pid in self.registred_games:
            self.UnregisterGame(process.pid)
        return process

    def _watch_process(self, pid: int):
        watcher_thread = threading.Thread(target=self.__watch_process_worker, args=(pid,))
        watcher_thread.daemon = True
        watcher_thread.start()
        return watcher_thread

    def _switch_profile(self, profile: str):
        log(f'Switching to profile "{profile}"')
        success, msg = self.tuned.switch_profile(profile)
        if not success:
            log(f'Switching to "{profile}" failed: {msg}')
        return (success, msg)

    def RegisterGame(self, i, dbus_context=None): #pylint: disable=invalid-name
        """D-Bus method implementing corresponding gamemoded method."""
        proc_name = get_process_name(i) or ''
        if dbus_context is not None:
            log(f'Request: register {i} ({proc_name})')
        if i in self.registred_games:
            raise ValueError(f'Process {i} is already known')
        success, _ = self._switch_profile(self.gaming_profile)
        if success:
            self.registred_games.add(i)
            self._watch_process(i)
            return RES_SUCCESS
        return RES_ERROR

    def UnregisterGame(self, i, dbus_context=None): #pylint: disable=invalid-name
        """D-Bus method implementing corresponding gamemoded method."""
        proc_name = get_process_name(i) or ''
        if dbus_context is not None:
            log(f'Request: unregister {i} ({proc_name})')
        if i not in self.registred_games:
            raise ValueError(f'Process {i} is not known')
        if not self.registred_games - {i}:
            log("No more registred PIDs left")
            success, _ = self._switch_profile(self.initial_profile)
            if not success:
                return RES_ERROR
        self.registred_games.remove(i)
        return RES_SUCCESS

    def QueryStatus(self, i, dbus_context=None): #pylint: disable=invalid-name
        """D-Bus method implementing corresponding gamemoded method."""
        proc_name = get_process_name(i) or ''
        if dbus_context is not None:
            log(f'Request: status {i} ({proc_name})')
        # TODO ensure that we return exactly what client expects
        if i in self.registred_games:
            return RES_SUCCESS
        return RES_ERROR


def init_config(config_path):
    """Load config file and populate it if empty."""
    config = ConfigParser()
    config.read_dict(CONFIG_DEFAULTS)
    config.read(config_path)
    if not os.path.isfile(config_path):
        with open(config_path, 'w') as config_file:
            config.write(config_file)
    return config


def run_tunedmode(config_path):
    """Run the daemon with provided config."""
    config = init_config(config_path)
    loop = GLib.MainLoop()
    with SessionBus() as session_bus:
        with SystemBus() as system_bus:
            with TunedMode(config=config,
                           system_bus=system_bus,
                           session_bus=session_bus) as tuned_mode:
                with session_bus.publish(TUNEDMODE_BUS_NAME, tuned_mode):
                    signal.signal(signal.SIGTERM, lambda n, f: loop.quit())
                    signal.signal(signal.SIGINT, lambda n, f: loop.quit())
                    loop.run()


if __name__ == '__main__':
    run_tunedmode(
        config_path=os.path.join(save_config_path('tunedmode'), 'tunedmode.ini')
    )
