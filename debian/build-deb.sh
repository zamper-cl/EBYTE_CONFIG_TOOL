#!/usr/bin/env bash
# Copyright (C) 2026 Zamper.io
# Licensed under the GNU General Public License v3.0. See LICENSE.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
NAME="configurador-e95"
VERSION="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$ROOT/ebyte_dtu/__init__.py")"
if [ -z "$VERSION" ]; then
  echo "No se encontró la versión en ebyte_dtu/__init__.py" >&2
  exit 1
fi

PKGDIR="$ROOT/build/debian-pkg"
DIST="$ROOT/dist"
SHARE="$PKGDIR/usr/share/$NAME"

rm -rf "$PKGDIR"
mkdir -p "$SHARE/docs/img" \
  "$PKGDIR/usr/bin" \
  "$PKGDIR/usr/share/applications" \
  "$PKGDIR/usr/share/doc/$NAME" \
  "$PKGDIR/DEBIAN" \
  "$DIST"

cp -a "$ROOT/ebyte_dtu" "$SHARE/"
find "$SHARE/ebyte_dtu" -type d -name __pycache__ -prune -exec rm -rf {} +
cp "$ROOT/docs/img/modo-config.jpeg" "$SHARE/docs/img/"
cp "$ROOT/LICENSE" "$PKGDIR/usr/share/doc/$NAME/copyright"
cp "$ROOT/debian/configurador-e95.desktop" "$PKGDIR/usr/share/applications/"

cat > "$PKGDIR/usr/bin/$NAME" << EOF
#!/bin/sh
export PYTHONPATH=/usr/share/$NAME
exec python3 -m ebyte_dtu "\$@"
EOF
chmod 755 "$PKGDIR/usr/bin/$NAME"

SIZE="$(du -sk "$PKGDIR" | cut -f1)"
cat > "$PKGDIR/DEBIAN/control" << EOF
Package: $NAME
Version: $VERSION
Section: electronics
Priority: optional
Architecture: all
Depends: python3 (>= 3.10), python3-pyqt6, python3-serial
Maintainer: TLM <tleiva@zamper.cl>
Homepage: https://github.com/zamper-cl/EBYTE_CONFIG_TOOL
Installed-Size: $SIZE
Description: Configurador del E95-DTU y E860-DTU
 Configura por el puerto serie los radios E95-DTU(900SL22-485)
 y E95-DTU(900SL30-485), y el interruptor inalámbrico
 E860-DTU(X0X0-900SLxx)-V2.
EOF

DEB="$DIST/${NAME}_${VERSION}_all.deb"
dpkg-deb --root-owner-group --build "$PKGDIR" "$DEB"
echo "$DEB"
