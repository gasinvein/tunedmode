#!/usr/bin/env python3

import os
import sys
import signal
import logging
import threading
from configparser import ConfigParser
import functools
import inspect
import traceback
import dbus
import dbus.service
import dbus.mainloop.glib
import dbus.exceptions
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
RES_REJECTED = -2


def log(message, level=logging.INFO):
    """Log provided message somewhere."""
    # TODO make logging to stderr OR to syslog
    print(message, file=sys.stderr)


def dbus_handle_exceptions(func):
    @functools.wraps(func)
    def _impl(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except dbus.exceptions.DBusException as ex:
            # only log DBusExceptions once
            raise ex
        except Exception as ex:
            log(f"Exception {ex} occured in {func}", logging.ERROR)
            log(traceback.format_exc(), logging.DEBUG)
            raise ex
    # HACK: functools.wraps() does not copy the function signature and
    # dbus-python doesn't support varargs. As such we need to copy the
    # signature from the function to the newly decorated function otherwise the
    # decorators in dbus-python will manipulate the arg stack and fail
    # miserably.
    #
    # Note: This can be removed if we ever stop using dbus-python.
    #
    # Ref: https://gitlab.freedesktop.org/dbus/dbus-python/-/issues/12
    #
    _impl.__signature__ = inspect.signature(func)
    return _impl


def get_process_name(pid):
    """Get cmdline of a process by it's PID."""
    proc_cmd = None
    if psutil.pid_exists(pid):
        proc_cmd = psutil.Process(pid=pid).cmdline()[0]
    return proc_cmd


def pidfd_to_pid(pid_fd: int) -> int:
    with open(f'/proc/self/fdinfo/{pid_fd}', 'r') as f:
        fdinfo_text = f.read()
    for line in fdinfo_text.splitlines():
        field, value = line.split(maxsplit=1)
        if field == 'Pid:':
            return int(value)
    raise ValueError(fdinfo_text)


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
            self._unregister_game(pid, pid)

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

    def _register_allowed(self, caller_pid: dbus.types.Int32, game_pid: dbus.types.Int32):
        #TODO: Actually do some check if caller is permitted to register game
        return True

    def _unregister_allowed(self, caller_pid: dbus.types.Int32, game_pid: dbus.types.Int32):
        #TODO: Actually do some check if caller is permitted to unregister game
        return True

    def _query_allowed(self, caller_pid: dbus.types.Int32, game_pid: dbus.types.Int32):
        #TODO: Actually do some check if caller is permitted to query status of game
        return True

    def _register_game(self, caller_pid: dbus.types.Int32, game_pid: dbus.types.Int32):
        game_cmd = get_process_name(game_pid) or ''
        caller_cmd = get_process_name(caller_pid) or ''
        log(f'Request: register {game_pid} ({game_cmd}) by {caller_pid} ({caller_cmd})')
        if not self._register_allowed(caller_pid, game_pid):
            return RES_REJECTED
        if game_pid in self.registred_games:
            log(f'Process: {game_pid} is already registred', logging.ERROR)
            return RES_ERROR
        success, _ = self._switch_profile(self.gaming_profile)
        if success:
            self.registred_games.add(game_pid)
            self._watch_process(game_pid)
            return RES_SUCCESS
        return RES_ERROR

    def _unregister_game(self, caller_pid: dbus.types.Int32, game_pid: dbus.types.Int32):
        game_cmd = get_process_name(game_pid) or ''
        caller_cmd = get_process_name(caller_pid) or ''
        log(f'Request: unregister {game_pid} ({game_cmd}) by {caller_pid} ({caller_cmd})')
        if not self._unregister_allowed(caller_pid, game_pid):
            return RES_REJECTED
        if game_pid not in self.registred_games:
            log(f'Process: {game_pid} is not registred', logging.ERROR)
            return RES_ERROR
        if not self.registred_games - {game_pid}:
            log("No more registred PIDs left")
            success, _ = self._switch_profile(self.initial_profile)
            if not success:
                return RES_ERROR
        self.registred_games.remove(game_pid)
        return RES_SUCCESS

    def _query_status(self, caller_pid: dbus.types.Int32, game_pid: dbus.types.Int32):
        game_cmd = get_process_name(game_pid) or ''
        caller_cmd = get_process_name(caller_pid) or ''
        log(f'Request: status {game_pid} ({game_cmd}) by {caller_pid} ({caller_cmd})')
        if not self._query_allowed(caller_pid, game_pid):
            return RES_REJECTED
        ret = 0
        if self.registred_games:
            ret += 1
            if game_pid in self.registred_games:
                ret += 1
        return ret

    @dbus.service.method(TUNEDMODE_BUS_NAME, in_signature='i', out_signature='i')
    @dbus_handle_exceptions
    def RegisterGame(self, i: dbus.types.Int32): #pylint: disable=invalid-name
        """D-Bus method implementing corresponding gamemoded method."""
        return self._register_game(i, i)

    @dbus.service.method(TUNEDMODE_BUS_NAME, in_signature='ii', out_signature='i')
    @dbus_handle_exceptions
    def RegisterGameByPID(self, caller_pid: dbus.types.Int32, game_pid: dbus.types.Int32): #pylint: disable=invalid-name
        """D-Bus method implementing corresponding gamemoded method."""
        return self._register_game(caller_pid, game_pid)

    @dbus.service.method(TUNEDMODE_BUS_NAME, in_signature='hh', out_signature='i')
    @dbus_handle_exceptions
    def RegisterGameByPIDFd(self, caller_pidfd: dbus.types.UnixFd, game_pidfd: dbus.types.UnixFd): #pylint: disable=invalid-name
        """D-Bus method implementing corresponding gamemoded method."""
        caller_pid = pidfd_to_pid(caller_pidfd.take())
        game_pid = pidfd_to_pid(game_pidfd.take())
        return self._register_game(caller_pid, game_pid)

    @dbus.service.method(TUNEDMODE_BUS_NAME, in_signature='i', out_signature='i')
    @dbus_handle_exceptions
    def UnregisterGame(self, i: dbus.types.Int32): #pylint: disable=invalid-name
        """D-Bus method implementing corresponding gamemoded method."""
        return self._unregister_game(i, i)

    @dbus.service.method(TUNEDMODE_BUS_NAME, in_signature='ii', out_signature='i')
    @dbus_handle_exceptions
    def UnregisterGameByPID(self, caller_pid: dbus.types.Int32, game_pid: dbus.types.Int32): #pylint: disable=invalid-name
        """D-Bus method implementing corresponding gamemoded method."""
        return self._unregister_game(caller_pid, game_pid)

    @dbus.service.method(TUNEDMODE_BUS_NAME, in_signature='hh', out_signature='i')
    @dbus_handle_exceptions
    def UnregisterGameByPIDFd(self, caller_pidfd: dbus.types.UnixFd, game_pidfd: dbus.types.UnixFd): #pylint: disable=invalid-name
        """D-Bus method implementing corresponding gamemoded method."""
        caller_pid = pidfd_to_pid(caller_pidfd.take())
        game_pid = pidfd_to_pid(game_pidfd.take())
        return self._unregister_game(caller_pid, game_pid)

    @dbus.service.method(TUNEDMODE_BUS_NAME, in_signature='i', out_signature='i')
    @dbus_handle_exceptions
    def QueryStatus(self, i: dbus.types.Int32): #pylint: disable=invalid-name
        """D-Bus method implementing corresponding gamemoded method."""
        return self._query_status(i, i)

    @dbus.service.method(TUNEDMODE_BUS_NAME, in_signature='ii', out_signature='i')
    @dbus_handle_exceptions
    def QueryStatusByPID(self, caller_pid: dbus.types.Int32, game_pid: dbus.types.Int32): #pylint: disable=invalid-name
        """D-Bus method implementing corresponding gamemoded method."""
        return self._query_status(caller_pid, game_pid)

    @dbus.service.method(TUNEDMODE_BUS_NAME, in_signature='hh', out_signature='i')
    @dbus_handle_exceptions
    def QueryStatusByPIDFd(self, caller_pidfd: dbus.types.UnixFd, game_pidfd: dbus.types.UnixFd): #pylint: disable=invalid-name
        """D-Bus method implementing corresponding gamemoded method."""
        caller_pid = pidfd_to_pid(caller_pidfd.take())
        game_pid = pidfd_to_pid(game_pidfd.take())
        return self._query_status(caller_pid, game_pid)


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
