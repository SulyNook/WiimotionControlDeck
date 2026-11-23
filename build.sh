#!/bin/sh
# Builds WimotionControlDeck-<arch>.AppImage, WiiSim-<arch>.AppImage and WimotionControlDeck-decky.zip. Needs internet access.
#   sh build.sh            -> both AppImages (WimotionControlDeck and WiiSim)
#   sh build.sh wimotioncontroldeck -> WimotionControlDeck AppImage only
#   sh build.sh wiisim     -> WiiSim AppImage only
#   sh build.sh decky      -> Decky plugin only (needs node + pnpm): WimotionControlDeck-decky.zip
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
  D=decky/WimotionControlDeck
  mkdir -p "$D/py_modules"
  cp common/wiilink.py common/deckcore.py "$D/py_modules/"
  (cd "$D" && pnpm install && pnpm build)
  rm -rf pkg-decky && mkdir -p pkg-decky/WimotionControlDeck
  cp -r "$D/plugin.json" "$D/main.py" "$D/package.json" "$D/dist" "$D/py_modules" pkg-decky/WimotionControlDeck/
  rm -f WimotionControlDeck-decky.zip
  (cd pkg-decky && zip -qr ../WimotionControlDeck-decky.zip WimotionControlDeck)
  rm -rf pkg-decky
  echo "Done: WimotionControlDeck-decky.zip  (Decky -> Settings -> Developer -> Install plugin from ZIP)"
}

build() {   # build <folder> <Name>
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
  echo "Done: $NAME-$ARCH.AppImage"
}

case "$WHAT" in
  decky)   build_decky ;;
  wimotioncontroldeck) fetch_tool; build wimotioncontroldeck WimotionControlDeck ;;
  wiisim)  fetch_tool; build wiisim WiiSim ;;
  *) fetch_tool; build wimotioncontroldeck WimotionControlDeck; build wiisim WiiSim ;;
esac
