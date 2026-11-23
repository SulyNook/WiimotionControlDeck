#!/bin/sh
# Installs, once, the permissions for WimotionControlDeck / WiiSim (Desktop Mode, from Konsole):
#     sudo sh install-udev.sh
# Opciones:
#     --keep-driver   do not disable the kernel hid_wiimote driver (disabled by default: it fights with these programs)
#     --open-uinput   make /dev/uinput world-writable (0666) if session access (uaccess) does not work
#     --remove        undo everything
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
  rm -f /etc/udev/rules.d/99-wimotioncontroldeck.rules /etc/modprobe.d/wimotioncontroldeck-no-hid-wiimote.conf /etc/modules-load.d/wimotioncontroldeck-uinput.conf
  udevadm control --reload-rules || true
  echo "Uninstalled. Reboot (or replug the Dolphin Bar) to return to the previous state."
  exit 0
fi

cp "$HERE/99-wimotioncontroldeck.rules" /etc/udev/rules.d/99-wimotioncontroldeck.rules
if [ "$OPEN" -eq 1 ]; then
  sed -i 's/MODE="0660", GROUP="input"/MODE="0666"/' /etc/udev/rules.d/99-wimotioncontroldeck.rules
fi

# uinput: needed to create the virtual mouse and gamepad
echo uinput > /etc/modules-load.d/wimotioncontroldeck-uinput.conf
modprobe uinput 2>/dev/null || true

# The kernel hid_wiimote driver reconfigures the remote on its own and clashes with direct reading
if [ "$KEEP" -eq 0 ]; then
  printf 'blacklist hid_wiimote\ninstall hid_wiimote /bin/false\n' > /etc/modprobe.d/wimotioncontroldeck-no-hid-wiimote.conf
  if lsmod | grep -q '^hid_wiimote'; then
    rmmod hid_wiimote 2>/dev/null || echo "(hid_wiimote could not be unloaded now: it will take effect after a reboot)"
  fi
fi

udevadm control --reload-rules
udevadm trigger --subsystem-match=hidraw --subsystem-match=misc || true

echo
echo "Done. Unplug and replug the Dolphin Bar (mode 4) and check with:"
echo "    python3 $HERE/wimotioncontroldeck/wimotioncontroldeck.py --check"
