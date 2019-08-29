# TunedMode
A small daemon which pretends to be the GameMode dbus service, but instead switches Tuned profiles.

E.g. when a RegisterGame() call is received from a GameMode client, it switches profile to "performance", and switches it back when no more games are registered.
