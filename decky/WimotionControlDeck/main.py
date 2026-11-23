"""
WimotionControlDeck - Decky Loader plugin (backend).
Wraps deckcore.DeckService: Wii remote -> pointer, virtual gamepad, gyro (DSU). Runs as root ("flags": ["root"]),
so it needs no udev rules for the Dolphin Bar or for /dev/uinput; the configuration is stored in the user's folder.

  * Main switch = COMPLETE SHUTDOWN: closes the remotes (with rumble off), the virtual devices and the
    DSU server. Profiles and settings are kept and restored when it is turned back on.
  * "Restart" = shut everything down and start again, reading the saved configuration (this also happens automatically on wake from suspend).
"""
import asyncio
import os
import sys

import decky

HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (os.path.join(HERE, "py_modules"), os.path.join(HERE, "..", "..", "common")):   # the second: running from the repository
    if os.path.exists(os.path.join(_p, "deckcore.py")):
        sys.path.insert(0, _p)
        break
import deckcore as dc  # noqa: E402


class Plugin:
    svc = None
    error = ""
    loop = None

    # ------------------------------------------------------------------ lifecycle
    def _open_qam(self):
        """Home + Plus held: the controller (another thread) asks the UI to open Steam's ... menu."""
        if self.loop is not None:
            asyncio.run_coroutine_threadsafe(decky.emit("open_qam"), self.loop)

    def _notify(self, title, body):
        """Mode/profile change (another thread): the UI shows it as a Steam toast notification."""
        if self.loop is not None:
            asyncio.run_coroutine_threadsafe(decky.emit("notify", title, body), self.loop)

    async def _run(self, fn, *args):
        return await asyncio.get_event_loop().run_in_executor(None, fn, *args)

    async def _start(self):
        """Starts the service. Returns True if it ended up running."""
        self.error = ""
        try:
            await self._run(self.svc.start)
            decky.logger.info("WimotionControlDeck %s started" % dc.VERSION)
        except dc.AlreadyRunning as e:
            self.error = str(e)
            decky.logger.warning(self.error)
        except Exception as e:  # the plugin must never take Decky down
            self.error = "WimotionControlDeck could not start: %r" % e
            decky.logger.exception(self.error)
        return self.svc.started

    async def _main(self):
        self.loop = asyncio.get_event_loop()
        dc.configure_paths(decky.DECKY_USER_HOME)
        self.svc = dc.DeckService()
        self.svc.on_open_qam = self._open_qam
        self.svc.on_notify = self._notify
        if dc.load_config()["enabled"]:
            await self._start()
        else:
            decky.logger.info("WimotionControlDeck is off (it was left that way last time)")

    async def _unload(self):
        if self.svc and self.svc.started:
            await self._run(self.svc.stop)
        decky.logger.info("WimotionControlDeck stopped")

    async def _uninstall(self):
        await self._unload()

    # ------------------------------------------------------------------ API for the UI
    def _ok(self):
        return self.svc is not None and self.svc.started

    async def get_status(self):
        if not self._ok():
            return {"running": False, "active": False, "error": self.error,
                    "enabled": bool(self.svc and dc.load_config()["enabled"] and self.error)}
        st = self.svc.status()
        st["running"] = True
        st["active"] = True
        st["error"] = ""
        return st

    async def set_enabled(self, enabled):
        """Main switch: ENABLE starts everything; DISABLE shuts it down completely (and remembers the state)."""
        if self.svc is None:
            return False
        if enabled:
            if not self.svc.started:
                cfg = dc.load_config()
                cfg["enabled"] = True
                dc.save_config(cfg)
                await self._start()
        else:
            self.error = ""
            if self.svc.started:
                self.svc.cfg["enabled"] = False          # stop() saves the configuration
                await self._run(self.svc.stop)
            else:
                cfg = dc.load_config()
                cfg["enabled"] = False
                dc.save_config(cfg)
        return self._ok()

    async def restart(self):
        """Shuts everything down and starts it again (keeps profiles and settings)."""
        if self.svc is None:
            return False
        self.error = ""
        if self.svc.started:
            await self._run(self.svc.restart)
        else:
            await self._start()
        return self._ok()

    async def get_bindings(self, mode=None, profile=None):
        if not self._ok():
            return None
        return self.svc.bindings_view(mode or None, profile or None)

    async def set_mode(self, mode):
        if self._ok():
            self.svc.ctrl.set_mode(mode)
        return self._ok()

    async def set_profile(self, profile):
        if self._ok():
            self.svc.ctrl.set_profile(profile)
        return self._ok()

    async def create_profile(self, name, copy_from=None):
        """New profile: a COPY of the one given in copy_from (or blank if none is given). Returns its id (or None if the name is invalid / there are too many)."""
        return self.svc.ctrl.create_profile(name, copy_from or None) if self._ok() else None

    async def free_dsu_port(self, port=26760):
        """Stops the program (SteamDeckGyroDSU-like) occupying port 26760 so that WimotionControlDeck can serve it."""
        if not self._ok():
            return [False, "WimotionControlDeck is off"]
        ok, msg = self.svc.free_dsu_port(int(port))
        return [ok, msg]

    async def eden_shake(self, direction, repeat=0.0):
        """"Test shake" button: fires the synthetic shake toward the emulator (repeat > 0: repeats it for that many seconds)."""
        return bool(self._ok() and self.svc.ctrl.eden_shake(direction, float(repeat or 0.0)))

    async def set_quick_profiles(self, ids):
        """Profiles that + and - cycle through on the remote."""
        return bool(self._ok() and self.svc.ctrl.set_quick_profiles(list(ids or [])))

    async def delete_profile(self, profile):
        return bool(self._ok() and self.svc.ctrl.delete_profile(profile))

    async def set_option(self, key, value):
        return bool(self._ok() and self.svc.set_option(key, value))

    async def apply_bindings(self, changes):
        """Applies at once the changes accumulated in the editor: list of [profile, mode, input, value]. All or nothing."""
        return bool(self._ok() and self.svc.ctrl.apply_bindings([tuple(c) for c in (changes or [])]))

    async def set_binding(self, input_name, value, mode=None, profile=None):
        return bool(self._ok() and self.svc.ctrl.set_binding(input_name, value, mode or None, profile or None))

    async def reset_bindings(self, mode=None, profile=None):
        if self._ok():
            self.svc.ctrl.reset_bindings(mode or None, profile or None)
        return self._ok()

    async def calibrate(self):
        if self._ok():
            self.svc.ctrl.calibrate_gyro()
        return self._ok()
