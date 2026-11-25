#!/usr/bin/env bash
# mini Teto installer.  Run it from the folder that holds `mini_teto/` and `sprites/`.
#   ./install.sh              install (and start her on login)
#   ./install.sh --no-autostart
#   ./install.sh --no-fonts   (do not download fonts)
#   ./install.sh --uninstall  remove the program (settings and love stay; see the end)
set -euo pipefail

APP=mini-teto
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}/$APP"
BIN="$HOME/.local/bin/$APP"
AUTOSTART="${XDG_CONFIG_HOME:-$HOME/.config}/autostart/$APP.desktop"
MENU="${XDG_DATA_HOME:-$HOME/.local/share}/applications/$APP.desktop"
FONTDIR="${XDG_DATA_HOME:-$HOME/.local/share}/fonts/$APP"

if [[ "${1:-}" == "--uninstall" ]]; then
    "$BIN" quit 2>/dev/null || true
    rm -rf "$DATA" "$BIN" "$AUTOSTART" "$MENU" "$FONTDIR"
    command -v fc-cache >/dev/null && fc-cache -f >/dev/null 2>&1 || true
    echo "mini Teto removed."
    echo "Settings/state kept in ~/.config/$APP and ~/.local/state/$APP (delete them by hand for a clean slate)."
    exit 0
fi

[[ -f "$SRC/mini_teto/app.py" ]] || { echo "Run this next to the mini_teto/ folder."; exit 1; }
[[ -d "$SRC/sprites" ]]          || { echo "No sprites/ folder next to mini_teto/ - she would have no face."; exit 1; }

# --- dependencies ----------------------------------------------------------------------
if ! python3 - <<'EOF' 2>/dev/null
import gi
gi.require_version("Gtk", "3.0")
import cairo
EOF
then
    echo "Missing: Python GTK3 bindings (PyGObject + pycairo). Install them, then run this again:"
    echo "  Debian/Ubuntu: sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0"
    echo "  Fedora:        sudo dnf install python3-gobject python3-cairo gtk3"
    echo "  Arch:          sudo pacman -S python-gobject python-cairo gtk3"
    exit 1
fi
python3 -c 'import gi; gi.require_version("GtkLayerShell","0.1")' 2>/dev/null ||
    echo "note: gtk-layer-shell not found; fine on X11/GNOME, install it for Hyprland/KDE/sway (Wayland)."
command -v xprop >/dev/null || echo "note: xprop not found; on X11 she will not step aside for fullscreen windows."
command -v pw-cat >/dev/null || command -v pacat >/dev/null || command -v aplay >/dev/null ||
    echo "note: no pw-cat / pacat / aplay; she will be silent."

# --- fonts: her look (Fredoka), Cyrillic (Nunito), Japanese (Noto Sans JP); user-level, no root -------
GF=https://github.com/google/fonts/raw/main/ofl
download() {   # url file
    mkdir -p "$FONTDIR"
    if command -v curl >/dev/null; then curl -fsSL --retry 2 -o "$FONTDIR/$2" "$1"
    elif command -v wget >/dev/null; then wget -q -O "$FONTDIR/$2" "$1"
    else return 1; fi || { rm -f "$FONTDIR/$2"; return 1; }
}
install_fonts() {
    command -v fc-list >/dev/null || { echo "note: no fontconfig (fc-list); skipping fonts."; return 0; }
    fc-list | grep -qi fredoka || { echo "font: Fredoka";      download "$GF/fredoka/Fredoka%5Bwdth%2Cwght%5D.ttf" Fredoka.ttf || echo "  (download failed, skipped)"; }
    fc-list | grep -qi nunito  || { echo "font: Nunito";       download "$GF/nunito/Nunito%5Bwght%5D.ttf" Nunito.ttf || echo "  (download failed, skipped)"; }
    [[ -n "$(fc-list :lang=ja 2>/dev/null | head -1)" ]] || { echo "font: Noto Sans JP (Japanese)"; download "$GF/notosansjp/NotoSansJP%5Bwght%5D.ttf" NotoSansJP.ttf || echo "  (download failed, skipped)"; }
    fc-cache -f "$FONTDIR" >/dev/null 2>&1 || true
}
[[ " $* " == *" --no-fonts "* ]] || install_fonts

# --- files -------------------------------------------------------------------------------
mkdir -p "$DATA" "$(dirname "$BIN")" "$(dirname "$AUTOSTART")" "$(dirname "$MENU")"
rm -rf "$DATA/mini_teto" "$DATA/sprites"
cp -r "$SRC/mini_teto" "$SRC/sprites" "$DATA/"
find "$DATA" -name __pycache__ -prune -exec rm -rf {} +

cat > "$BIN" <<EOF
#!/usr/bin/env bash
cd "$DATA" && exec env PYTHONPATH="$DATA\${PYTHONPATH:+:\$PYTHONPATH}" python3 -m mini_teto "\$@"
EOF
chmod +x "$BIN"

ENTRY="[Desktop Entry]
Type=Application
Name=mini Teto
Comment=A desktop pet
Exec=$BIN
Icon=$DATA/sprites/idle.png
Terminal=false
Categories=Utility;"
printf '%s\n' "$ENTRY" > "$MENU"
if [[ " $* " != *" --no-autostart "* ]]; then
    printf '%s\nX-GNOME-Autostart-enabled=true\n' "$ENTRY" > "$AUTOSTART"
fi

echo "Installed. Start her with:  $APP"
case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) echo "note: add ~/.local/bin to your PATH to use the 'mini-teto' command." ;; esac
echo "Commands: mini-teto say hi | feed | sing | hide | quit      Uninstall: ./install.sh --uninstall"
