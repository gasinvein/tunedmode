# TunedMode
A small daemon which pretends to be the GameMode dbus service, but instead switches Tuned profiles.

E.g. when a RegisterGame() call is received from a GameMode client, it switches profile to "performance", and switches it back when no more games are registered.

## Requirements

* [Tuned](https://github.com/redhat-performance/tuned), obviously
* Python 3, with modules
  * PyGObject
  * dbus
  * psutil
  * pyxdg

## Installation

This shim uses the same bus name as GameMode, and thus conflicts with it.
Make sure that GameMode is not installed.

```bash
meson --prefix ~/.local . build
ninja -C build install
```
