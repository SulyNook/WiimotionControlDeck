#!/bin/sh
# Genera WiiDeck-<arch>.AppImage, WiiSim-<arch>.AppImage y WiiDeck-decky.zip. Necesita conexion a internet.
#   sh build.sh            -> las AppImage de WiiDeck y WiiSim
#   sh build.sh wiideck    -> solo WiiDeck
#   sh build.sh decky      -> el plugin de Decky (necesita node + pnpm): WiiDeck-decky.zip
set -e
cd "$(dirname "$0")"
ARCH="${ARCH:-x86_64}"
WHAT="${1:-all}"
fetch_tool() {
  if [ ! -x ./appimagetool ]; then
    curl -L -o appimagetool "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-$ARCH.AppImage"
    chmod +x appimagetool
  fi
}

build_decky() {
  D=decky/WiiDeck
  mkdir -p "$D/py_modules"
  cp common/wiilink.py common/deckcore.py "$D/py_modules/"
  (cd "$D" && pnpm install && pnpm build)
  rm -rf pkg-decky && mkdir -p pkg-decky/WiiDeck
  cp -r "$D/plugin.json" "$D/main.py" "$D/package.json" "$D/dist" "$D/py_modules" pkg-decky/WiiDeck/
  rm -f WiiDeck-decky.zip
  (cd pkg-decky && zip -qr ../WiiDeck-decky.zip WiiDeck)
  rm -rf pkg-decky
  echo "Listo: WiiDeck-decky.zip  (Decky -> Ajustes -> Desarrollador -> Instalar plugin desde ZIP)"
}

build() {   # build <carpeta> <Nombre>
  APP="$1"; NAME="$2"
  rm -rf "AppDir-$APP"
  mkdir -p "AppDir-$APP/usr/share/$APP"
  cp "$APP"/*.py "AppDir-$APP/usr/share/$APP/"
  cp common/wiilink.py common/deckcore.py "AppDir-$APP/usr/share/$APP/"
  cp "$APP/AppRun" "$APP/$APP.desktop" "$APP/$APP.png" "AppDir-$APP/"
  cp "$APP/$APP.png" "AppDir-$APP/.DirIcon"
  chmod +x "AppDir-$APP/AppRun"
  ARCH="$ARCH" ./appimagetool --appimage-extract-and-run "AppDir-$APP" "$NAME-$ARCH.AppImage"
  rm -rf "AppDir-$APP"
  echo "Listo: $NAME-$ARCH.AppImage"
}

case "$WHAT" in
  decky)   build_decky ;;
  wiideck) fetch_tool; build wiideck WiiDeck ;;
  wiisim)  fetch_tool; build wiisim WiiSim ;;
  *) fetch_tool; build wiideck WiiDeck; build wiisim WiiSim ;;
esac
