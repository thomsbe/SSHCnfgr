#!/usr/bin/env bash
set -euo pipefail

# Baut ein Linux x86_64 AppImage inkl. .zsync-Datei und eingebetteter
# gh-releases-zsync Update-Information fuer Gear Lever / AppImageUpdate.
#
# Voraussetzungen (Linux x86_64):
#   - uv + Python-Umgebung mit [qt] Extra + pyinstaller
#   - zsync (zsyncmake), rsvg-convert (librsvg2-bin), curl/wget

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

VERSION="$(uv run python -c "from sshcnfgr import __version__; print(__version__)")"
ARCH="${ARCH:-x86_64}"
REPO_OWNER="${REPO_OWNER:-thomsbe}"
REPO_NAME="${REPO_NAME:-SSHCnfgr}"
UPDATE_TAG="${UPDATE_TAG:-latest}"

APPDIR="$ROOT_DIR/build/appimage/AppDir"
DIST_DIR="$ROOT_DIR/dist"
OUT_APPIMAGE="$DIST_DIR/SSHCnfgr-${VERSION}-${ARCH}.AppImage"

echo "==> Baue SSHCnfgr ${VERSION} AppImage (${ARCH})"

rm -rf "$ROOT_DIR/build/appimage" "$ROOT_DIR/build/pyinstaller"
mkdir -p "$APPDIR/usr/bin" \
         "$APPDIR/usr/share/applications" \
         "$APPDIR/usr/share/metainfo" \
         "$APPDIR/usr/share/icons/hicolor/scalable/apps" \
         "$APPDIR/usr/share/icons/hicolor/256x256/apps" \
         "$DIST_DIR"

SVG_SRC="$ROOT_DIR/src/sshcnfgr/assets/sshcnfgr.svg"
PNG_STAGE="$ROOT_DIR/build/appimage/sshcnfgr.png"
PYINSTALLER_EXTRA_DATA=()
if command -v rsvg-convert >/dev/null 2>&1; then
  rsvg-convert -w 256 -h 256 "$SVG_SRC" -o "$PNG_STAGE"
  PYINSTALLER_EXTRA_DATA=(--add-data "$PNG_STAGE:sshcnfgr/assets")
fi

echo "==> Bundling mit PyInstaller (onedir)..."
uv run --extra qt --with pyinstaller pyinstaller \
  --noconfirm \
  --clean \
  --onedir \
  --name sshcnfgr \
  --distpath "$ROOT_DIR/build/pyinstaller/dist" \
  --workpath "$ROOT_DIR/build/pyinstaller/work" \
  --specpath "$ROOT_DIR/build/pyinstaller" \
  --paths "$ROOT_DIR/src" \
  --add-data "$ROOT_DIR/src/sshcnfgr/tui.tcss:sshcnfgr" \
  --add-data "$SVG_SRC:sshcnfgr/assets" \
  "${PYINSTALLER_EXTRA_DATA[@]}" \
  --collect-submodules sshcnfgr \
  "$ROOT_DIR/packaging/appimage/entry.py"

echo "==> Befuelle AppDir..."
cp -a "$ROOT_DIR/build/pyinstaller/dist/sshcnfgr/." "$APPDIR/usr/bin/"

cat <<'EOF' > "$APPDIR/AppRun"
#!/bin/sh
HERE="$(dirname "$(readlink -f "${0}")")"
export PATH="${HERE}/usr/bin:${PATH}"
exec "${HERE}/usr/bin/sshcnfgr" "$@"
EOF
chmod +x "$APPDIR/AppRun"

cp "$ROOT_DIR/packaging/appimage/de.tbaer.sshcnfgr.desktop" \
   "$APPDIR/usr/share/applications/de.tbaer.sshcnfgr.desktop"
cp "$ROOT_DIR/packaging/appimage/de.tbaer.sshcnfgr.desktop" \
   "$APPDIR/de.tbaer.sshcnfgr.desktop"

cp "$ROOT_DIR/packaging/appimage/de.tbaer.sshcnfgr.appdata.xml" \
   "$APPDIR/usr/share/metainfo/de.tbaer.sshcnfgr.appdata.xml"

PNG_OUT="$APPDIR/usr/share/icons/hicolor/256x256/apps/de.tbaer.sshcnfgr.png"

cp "$SVG_SRC" "$APPDIR/usr/share/icons/hicolor/scalable/apps/de.tbaer.sshcnfgr.svg"
cp "$SVG_SRC" "$APPDIR/de.tbaer.sshcnfgr.svg"

if [ -f "$PNG_STAGE" ]; then
  cp "$PNG_STAGE" "$PNG_OUT"
  cp "$PNG_STAGE" "$APPDIR/de.tbaer.sshcnfgr.png"
  cp "$PNG_STAGE" "$APPDIR/.DirIcon"
else
  cp "$SVG_SRC" "$APPDIR/.DirIcon"
fi

APPIMAGETOOL="${APPIMAGETOOL:-$ROOT_DIR/build/appimagetool-${ARCH}.AppImage}"
if [ ! -x "$APPIMAGETOOL" ]; then
  echo "==> Lade appimagetool herunter..."
  curl -fsSL \
    "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-${ARCH}.AppImage" \
    -o "$APPIMAGETOOL"
  chmod +x "$APPIMAGETOOL"
fi

OUT_FILENAME="SSHCnfgr-${VERSION}-${ARCH}.AppImage"
OUT_APPIMAGE="$DIST_DIR/$OUT_FILENAME"
UPDATE_INFO="gh-releases-zsync|${REPO_OWNER}|${REPO_NAME}|${UPDATE_TAG}|SSHCnfgr-*-${ARCH}.AppImage.zsync"
echo "==> Erzeuge AppImage mit Update-Info: ${UPDATE_INFO}"

# Aus DIST_DIR heraus ausfuehren, damit zsyncmake die .zsync-Datei direkt neben
# dem AppImage ablegt und einen sauberen relativen Dateinamen einbettet.
(
  cd "$DIST_DIR"
  ARCH="$ARCH" APPIMAGE_EXTRACT_AND_RUN=1 "$APPIMAGETOOL" \
    --no-appstream \
    -u "$UPDATE_INFO" \
    "$APPDIR" \
    "$OUT_FILENAME"
)

if [ ! -f "${OUT_APPIMAGE}.zsync" ]; then
  echo "Fehler: ${OUT_APPIMAGE}.zsync wurde nicht erzeugt (ist zsync installiert?)" >&2
  exit 1
fi

(cd "$DIST_DIR" && sha256sum "$(basename "$OUT_APPIMAGE")" "$(basename "${OUT_APPIMAGE}.zsync")" > "SSHCnfgr-${VERSION}-${ARCH}.SHA256SUMS.txt")

echo "==> Fertig:"
ls -lh "$OUT_APPIMAGE" "${OUT_APPIMAGE}.zsync" "$DIST_DIR/SSHCnfgr-${VERSION}-${ARCH}.SHA256SUMS.txt"
