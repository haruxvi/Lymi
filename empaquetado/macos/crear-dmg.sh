#!/bin/sh
# Empaqueta dist/lymi.app en un .dmg (solo en macOS: usa hdiutil, que viene con el sistema).
#
# Sin firma ni notarizacion de Apple (requieren una cuenta de desarrollador de pago),
# Gatekeeper avisa al abrirlo la primera vez: clic derecho -> Abrir. Lo que macOS
# consulta a Apple al abrir una app (OCSP y notarizacion) es del sistema, no de lymi.
set -eu

version="${1:-0.0.0}"
raiz="$(cd "$(dirname "$0")/../.." && pwd)"
app="${raiz}/dist/lymi.app"
salida="${raiz}/dist/lymi-${version}-macos.dmg"

[ -d "${app}" ] || { echo "No existe ${app}: corre antes pyinstaller empaquetado/lymi.spec" >&2; exit 1; }

temporal="$(mktemp -d)"
cp -R "${app}" "${temporal}/"
ln -s /Applications "${temporal}/Aplicaciones"
rm -f "${salida}"
hdiutil create -volname "lymi ${version}" -srcfolder "${temporal}" -ov -format UDZO "${salida}"
rm -rf "${temporal}"
echo "${salida}"
