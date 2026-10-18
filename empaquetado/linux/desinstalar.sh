#!/bin/sh
# Quita lymi de este usuario. Tus datos (~/.local/share/lymi) se quedan: son tuyos.
set -eu

rm -rf "${HOME}/.local/opt/lymi"
rm -f "${HOME}/.local/bin/lymi" "${HOME}/.local/bin/lymi-cli"
rm -f "${XDG_DATA_HOME:-${HOME}/.local/share}/applications/lymi.desktop"
rm -f "${XDG_DATA_HOME:-${HOME}/.local/share}/icons/hicolor/256x256/apps/lymi.png"
rm -f "${XDG_CONFIG_HOME:-${HOME}/.config}/autostart/lymi.desktop"
echo "lymi desinstalado. Tus datos siguen en ${XDG_DATA_HOME:-${HOME}/.local/share}/lymi; borralos a mano si quieres."
