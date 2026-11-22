"""
WiiDeck - plugin de Decky Loader (backend).
Envuelve deckcore.DeckService: el mando Wii -> puntero, gamepad virtual, giroscopio (DSU). Corre como root ("flags": ["root"]),
asi que no necesita reglas udev para la Dolphin Bar ni para /dev/uinput; la configuracion se guarda en la carpeta del usuario.

  * Interruptor principal = APAGADO COMPLETO: cierra los mandos (con la vibracion apagada), los dispositivos virtuales y el
    servidor DSU. Los perfiles y ajustes se conservan y se recuperan al volver a activarlo.
  * "Reiniciar" = apagar todo y volver a arrancar leyendo la configuracion guardada (tambien se hace solo al despertar de suspender).
"""
import asyncio
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
    loop = None

    # ------------------------------------------------------------------ ciclo de vida
    def _open_qam(self):
        """Home + Plus mantenidos: el controlador (otro hilo) pide a la interfaz que abra el menu ... de Steam."""
        if self.loop is not None:
            asyncio.run_coroutine_threadsafe(decky.emit("open_qam"), self.loop)

    def _notify(self, title, body):
        """Cambio de modo/perfil (otro hilo): la interfaz lo muestra como notificacion emergente de Steam."""
        if self.loop is not None:
            asyncio.run_coroutine_threadsafe(decky.emit("notify", title, body), self.loop)

    async def _run(self, fn, *args):
        return await asyncio.get_event_loop().run_in_executor(None, fn, *args)

    async def _start(self):
        """Arranca el servicio. Devuelve True si quedo en marcha."""
        self.error = ""
        try:
            await self._run(self.svc.start)
            decky.logger.info("WiiDeck %s iniciado" % dc.VERSION)
        except dc.AlreadyRunning as e:
            self.error = str(e)
            decky.logger.warning(self.error)
        except Exception as e:  # el plugin nunca debe tumbar a Decky
            self.error = "WiiDeck no pudo iniciar: %r" % e
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
            decky.logger.info("WiiDeck esta apagado (se dejo asi la ultima vez)")

    async def _unload(self):
        if self.svc and self.svc.started:
            await self._run(self.svc.stop)
        decky.logger.info("WiiDeck detenido")

    async def _uninstall(self):
        await self._unload()

    # ------------------------------------------------------------------ API para la interfaz
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
        """Interruptor principal: ACTIVAR arranca todo; DESACTIVAR lo apaga del todo (y recuerda el estado)."""
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
                self.svc.cfg["enabled"] = False          # stop() guarda la configuracion
                await self._run(self.svc.stop)
            else:
                cfg = dc.load_config()
                cfg["enabled"] = False
                dc.save_config(cfg)
        return self._ok()

    async def restart(self):
        """Apaga todo y lo arranca de nuevo (conserva perfiles y ajustes)."""
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
        """Perfil nuevo: COPIA del indicado en copy_from (o en blanco si no se da). Devuelve su id (o None si el nombre no vale / hay demasiados)."""
        return self.svc.ctrl.create_profile(name, copy_from or None) if self._ok() else None

    async def eden_shake(self, direction, repeat=0.0):
        """Boton "Probar sacudida": lanza la sacudida sintetica hacia el emulador (repeat > 0: la repite ese numero de segundos)."""
        return bool(self._ok() and self.svc.ctrl.eden_shake(direction, float(repeat or 0.0)))

    async def set_quick_profiles(self, ids):
        """Perfiles por los que rotan + y - en el mando."""
        return bool(self._ok() and self.svc.ctrl.set_quick_profiles(list(ids or [])))

    async def delete_profile(self, profile):
        return bool(self._ok() and self.svc.ctrl.delete_profile(profile))

    async def set_option(self, key, value):
        return bool(self._ok() and self.svc.set_option(key, value))

    async def apply_bindings(self, changes):
        """Aplica de golpe los cambios acumulados en el editor: lista de [perfil, modo, entrada, valor]. Todo o nada."""
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
