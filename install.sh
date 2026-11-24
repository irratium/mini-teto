#!/usr/bin/env bash
# mini Teto installer.  Run it from the folder that holds `mini_teto/` and `sprites/`.
#   ./install.sh              install (and start her on login)
#   ./install.sh --no-autostart
#   ./install.sh --uninstall  remove the program (settings and love stay; see the end)
set -euo pipefail

APP=mini-teto
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}/$APP"
BIN="$HOME/.local/bin/$APP"
AUTOSTART="${XDG_CONFIG_HOME:-$HOME/.config}/autostart/$APP.desktop"
MENU="${XDG_DATA_HOME:-$HOME/.local/share}/applications/$APP.desktop"

if [[ "${1:-}" == "--uninstall" ]]; then
    "$BIN" quit 2>/dev/null || true
    rm -rf "$DATA" "$BIN" "$AUTOSTART" "$MENU"
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
if [[ "${1:-}" != "--no-autostart" ]]; then
    printf '%s\nX-GNOME-Autostart-enabled=true\n' "$ENTRY" > "$AUTOSTART"
fi

echo "Installed. Start her with:  $APP"
case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) echo "note: add ~/.local/bin to your PATH to use the 'mini-teto' command." ;; esac
echo "Commands: mini-teto say hi | feed | sing | hide | quit      Uninstall: ./install.sh --uninstall"
