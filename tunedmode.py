#!/usr/bin/env python3

import os
import sys
import signal
import logging
import threading
from configparser import ConfigParser
import dbus
import dbus.service
import dbus.mainloop.glib
from xdg.BaseDirectory import save_config_path
import psutil
from gi.repository import GLib


TUNEDMODE_BUS_NAME = 'com.feralinteractive.GameMode'
TUNEDMODE_BUS_PATH = '/com/feralinteractive/GameMode'

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


class TunedMode(dbus.service.Object):
    """DBus daemon implementing GameMode-compatible interface."""

    def __init__(self, dbus_name, dbus_path):
        """Gather initial settings and config options."""
        super().__init__(dbus_name, dbus_path)
        self.system_bus = dbus.SystemBus()
        self.tuned_obj = self.system_bus.get_object('com.redhat.tuned', '/Tuned')
        self.tuned = dbus.Interface(self.tuned_obj, 'com.redhat.tuned.control')
        self.registred_games = set()
        self.initial_profile = self.tuned.active_profile()
        self.config = ConfigParser()
        self._read_config()
        self.gaming_profile = self.config['tuned']['gaming-profile']
        if self.gaming_profile not in self.tuned.profiles():
            raise ValueError(f'Gaming profile "{self.gaming_profile}" doesn\'t exist')
        log(f'Initial profile is "{self.initial_profile}", '
            f'gaming profile is "{self.gaming_profile}"')

    def __enter__(self):
        """Set thing up."""
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        """Make sure TuneD profile it set back to initial value."""
        log("Stopping tunedmode...")
        self._switch_profile(self.initial_profile)
        self.system_bus.close()
        if exc_value:
            raise

    def _read_config(self):
        config_path = os.path.join(save_config_path('tunedmode'), 'tunedmode.ini')
        self.config.read_dict(CONFIG_DEFAULTS)
        self.config.read(config_path)
        if not os.path.isfile(config_path):
            with open(config_path, 'w') as config_file:
                self.config.write(config_file)

    def __watch_process_worker(self, pid: int):
        if psutil.pid_exists(pid):
            psutil.Process(pid).wait()
            log(f"Process: {pid} exited")
        else:
            log(f"Process: {pid} does not exist (already exited?)")
        if pid in self.registred_games:
            self.UnregisterGame(pid)

    def _watch_process(self, pid: int):
        watcher_thread = threading.Thread(target=self.__watch_process_worker, args=(pid,))
        watcher_thread.daemon = True
        watcher_thread.start()
        return watcher_thread

    def _switch_profile(self, profile: str):
        if profile == self.tuned.active_profile():
            return (True, "Requested profile is already active")
        log(f'Switching to profile "{profile}"')
        success, msg = self.tuned.switch_profile(profile)
        if not success:
            log(f'Switching to "{profile}" failed: {msg}')
        return (success, msg)

    @dbus.service.method(TUNEDMODE_BUS_NAME, in_signature='i', out_signature='i')
    def RegisterGame(self, i: dbus.types.Int32): #pylint: disable=invalid-name
        """D-Bus method implementing corresponding gamemoded method."""
        proc_name = get_process_name(i) or ''
        log(f'Request: register {i} ({proc_name})')
        if i in self.registred_games:
            log(f'Process: {i} is already registred', logging.ERROR)
            return RES_ERROR
        success, _ = self._switch_profile(self.gaming_profile)
        if success:
            self.registred_games.add(i)
            self._watch_process(i)
            return RES_SUCCESS
        return RES_ERROR

    @dbus.service.method(TUNEDMODE_BUS_NAME, in_signature='i', out_signature='i')
    def UnregisterGame(self, i: dbus.types.Int32): #pylint: disable=invalid-name
        """D-Bus method implementing corresponding gamemoded method."""
        proc_name = get_process_name(i) or ''
        log(f'Request: unregister {i} ({proc_name})')
        if i not in self.registred_games:
            log(f'Process: {i} is not registred', logging.ERROR)
            return RES_ERROR
        if not self.registred_games - {i}:
            log("No more registred PIDs left")
            success, _ = self._switch_profile(self.initial_profile)
            if not success:
                return RES_ERROR
        self.registred_games.remove(i)
        return RES_SUCCESS

    @dbus.service.method(TUNEDMODE_BUS_NAME, in_signature='i', out_signature='i')
    def QueryStatus(self, i: dbus.types.Int32): #pylint: disable=invalid-name
        """D-Bus method implementing corresponding gamemoded method."""
        proc_name = get_process_name(i) or ''
        log(f'Request: status {i} ({proc_name})')
        ret = 0
        if self.registred_games:
            ret += 1
            if i in self.registred_games:
                ret += 1
        return ret


def run_tunedmode():
    """Run the daemon with provided config."""
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    session_bus = dbus.SessionBus()
    bus_name = dbus.service.BusName(TUNEDMODE_BUS_NAME, bus=session_bus)
    with TunedMode(bus_name, TUNEDMODE_BUS_PATH):
        loop = GLib.MainLoop()
        signal.signal(signal.SIGTERM, lambda n, f: loop.quit())
        signal.signal(signal.SIGINT, lambda n, f: loop.quit())
        loop.run()


def main():
    """Start TunedMode from command line."""
    run_tunedmode()

if __name__ == '__main__':
    main()
