#!/bin/sh
# Instala una sola vez los permisos para WiiDeck / WiiSim (en Modo Escritorio, desde Konsole):
#     sudo sh install-udev.sh
# Opciones:
#     --keep-driver   no desactivar el driver del nucleo hid_wiimote (por defecto se desactiva: se pelea con estos programas)
#     --open-uinput   /dev/uinput accesible a todos (0666) si el acceso por sesion (uaccess) no te funciona
#     --remove        deshace todo
set -e
HERE="$(dirname "$(readlink -f "$0")")"
if [ "$(id -u)" -ne 0 ]; then exec sudo sh "$(readlink -f "$0")" "$@"; fi

KEEP=0; OPEN=0; REMOVE=0
for a in "$@"; do
  case "$a" in
    --keep-driver) KEEP=1 ;;
    --open-uinput) OPEN=1 ;;
    --remove) REMOVE=1 ;;
  esac
done

if [ "$REMOVE" -eq 1 ]; then
  rm -f /etc/udev/rules.d/99-wiideck.rules /etc/modprobe.d/wiideck-no-hid-wiimote.conf /etc/modules-load.d/wiideck-uinput.conf
  udevadm control --reload-rules || true
  echo "Desinstalado. Reinicia (o reconecta la Dolphin Bar) para volver al estado anterior."
  exit 0
fi

cp "$HERE/99-wiideck.rules" /etc/udev/rules.d/99-wiideck.rules
if [ "$OPEN" -eq 1 ]; then
  sed -i 's/MODE="0660", GROUP="input"/MODE="0666"/' /etc/udev/rules.d/99-wiideck.rules
fi

# uinput: necesario para crear el raton y el gamepad virtuales
echo uinput > /etc/modules-load.d/wiideck-uinput.conf
modprobe uinput 2>/dev/null || true

# El driver del nucleo hid_wiimote reconfigura el mando por su cuenta y choca con la lectura directa
if [ "$KEEP" -eq 0 ]; then
  printf 'blacklist hid_wiimote\ninstall hid_wiimote /bin/false\n' > /etc/modprobe.d/wiideck-no-hid-wiimote.conf
  if lsmod | grep -q '^hid_wiimote'; then
    rmmod hid_wiimote 2>/dev/null || echo "(hid_wiimote no se pudo descargar ahora: se aplicara al reiniciar)"
  fi
fi

udevadm control --reload-rules
udevadm trigger --subsystem-match=hidraw --subsystem-match=misc || true

echo
echo "Listo. Desconecta y vuelve a conectar la Dolphin Bar (modo 4) y comprueba con:"
echo "    python3 $HERE/wiideck/wiideck.py --check"
