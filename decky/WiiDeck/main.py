"""
WiiDeck - plugin de Decky Loader (backend).
Envuelve deckcore.DeckService: el mando Wii -> puntero, gamepad virtual, giroscopio (DSU). Corre como root ("flags": ["root"]),
asi que no necesita reglas udev para la Dolphin Bar ni para /dev/uinput; la configuracion se guarda en la carpeta del usuario.
"""
import os
import sys

import decky

HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (os.path.join(HERE, "py_modules"), os.path.join(HERE, "..", "..", "common")):   # el segundo: ejecutar desde el repositorio
    if os.path.exists(os.path.join(_p, "deckcore.py")):
        sys.path.insert(0, _p)
        break
import deckcore as dc  # noqa: E402


class Plugin:
    svc = None
    error = ""

    async def _main(self):
        dc.configure_paths(decky.DECKY_USER_HOME)
        self.svc = dc.DeckService()
        try:
            self.svc.start()
            decky.logger.info("WiiDeck %s iniciado" % dc.VERSION)
        except dc.AlreadyRunning as e:
            self.error = str(e)
            self.svc = None
            decky.logger.warning(self.error)
        except Exception as e:  # el plugin nunca debe tumbar a Decky
            self.error = "WiiDeck no pudo iniciar: %r" % e
            self.svc = None
            decky.logger.exception(self.error)

    async def _unload(self):
        if self.svc:
            self.svc.stop()
            self.svc = None
        decky.logger.info("WiiDeck detenido")

    async def _uninstall(self):
        await self._unload()

    # ------------------------------------------------------------------ API para la interfaz
    def _ok(self):
        return self.svc is not None and self.svc.started

    async def get_status(self):
        if not self._ok():
            return {"running": False, "error": self.error or "WiiDeck no esta en marcha"}
        st = self.svc.status()
        st["running"] = True
        st["error"] = ""
        return st

    async def get_bindings(self, mode=None, profile=None):
        if not self._ok():
            return None
        return self.svc.bindings_view(mode or None, profile or None)

    async def set_enabled(self, enabled):
        if self._ok():
            self.svc.ctrl.set_enabled(bool(enabled))
        return self._ok()

    async def set_mode(self, mode):
        if self._ok():
            self.svc.ctrl.set_mode(mode)
        return self._ok()

    async def set_profile(self, profile):
        if self._ok():
            self.svc.ctrl.set_profile(profile)
        return self._ok()

    async def set_option(self, key, value):
        return bool(self._ok() and self.svc.set_option(key, value))

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
