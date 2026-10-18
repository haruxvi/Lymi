#!/bin/sh
# Instala lymi para este usuario, sin root ni gestor de paquetes. Legible a proposito:
# es lo unico que corre con tus permisos, asi que conviene poder leerlo entero.
#
#   ./instalar.sh                 instala
#   ./instalar.sh --al-iniciar    ademas abre lymi al iniciar sesion
#
# Programa:  ~/.local/opt/lymi
# Comandos:  ~/.local/bin/lymi (ventana) y ~/.local/bin/lymi-cli (terminal)
# Menu:      ~/.local/share/applications/lymi.desktop
# Datos:     ~/.local/share/lymi (desinstalar no los toca)
set -eu

origen="$(cd "$(dirname "$0")" && pwd)"
programa="${HOME}/.local/opt/lymi"
bin="${HOME}/.local/bin"
apps="${XDG_DATA_HOME:-${HOME}/.local/share}/applications"
iconos="${XDG_DATA_HOME:-${HOME}/.local/share}/icons/hicolor/256x256/apps"

if [ ! -x "${origen}/lymi/lymi" ]; then
  echo "No encuentro ${origen}/lymi/lymi: corre este script desde la carpeta descomprimida." >&2
  exit 1
fi

mkdir -p "${programa}" "${bin}" "${apps}" "${iconos}"
rm -rf "${programa:?}/"*
cp -R "${origen}/lymi/." "${programa}/"
cp "${origen}/lymi.png" "${iconos}/lymi.png"
ln -sf "${programa}/lymi" "${bin}/lymi"
ln -sf "${programa}/lymi-cli" "${bin}/lymi-cli"

escritorio() {
  cat <<EOF
[Desktop Entry]
Type=Application
Name=lymi
Comment=Agentes locales con cada token anotado
Exec=${programa}/lymi
Icon=lymi
Terminal=false
Categories=Office;Utility;Development;
StartupWMClass=lymi
EOF
}
escritorio > "${apps}/lymi.desktop"

if [ "${1:-}" = "--al-iniciar" ]; then
  autostart="${XDG_CONFIG_HOME:-${HOME}/.config}/autostart"
  mkdir -p "${autostart}"
  escritorio > "${autostart}/lymi.desktop"
  echo "lymi se abrira al iniciar sesion (quitalo borrando ${autostart}/lymi.desktop)."
fi

command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "${apps}" >/dev/null 2>&1 || true

echo "lymi instalado en ${programa}."
case ":${PATH}:" in
  *":${bin}:"*) ;;
  *) echo "Agrega ${bin} a tu PATH para usar 'lymi' y 'lymi-cli' desde la terminal." ;;
esac
echo "Comprueba que no habla con nadie: lymi --verificar-red 60"
