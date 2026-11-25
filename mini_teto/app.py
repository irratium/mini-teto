"""Mini Teto: a desktop pet for any Linux desktop.

She lives in a corner of the screen. Click her, right-click for her menu,
scroll over her to pet her, grab her and throw her.

How she gets on screen:
  * Wayland with layer-shell (Hyprland, KDE Plasma, sway, niri, river, labwc,
    Wayfire, COSMIC, ...): one transparent overlay over the work area that
    only takes the pointer over her and her speech bubble.
  * X11, and Wayland desktops without layer-shell (GNOME) through XWayland:
    two small unmanaged windows, one for her and one for the bubble, moved
    around the screen. Tiling window managers leave them alone.
"""

import datetime
import getpass
import json
import math
import os
import random
import shutil
import socket
import subprocess
import sys
import threading
import time

try:
    import pwd
except ImportError:               # Windows
    pwd = None

WIN = sys.platform == "win32"

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = sys._MEIPASS if getattr(sys, "frozen", False) else os.path.dirname(HERE)   # PyInstaller unpacks the sprites there
SPRITES = os.path.join(ROOT, "sprites")
if WIN:
    CONFIG_DIR = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "mini-teto")
    STATE_DIR = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "mini-teto")
else:
    CONFIG_DIR = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "mini-teto")
    STATE_DIR = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"), "mini-teto")
SKIN_DIR = os.path.join(CONFIG_DIR, "skin")
SOCKET = os.environ.get("MINI_TETO_SOCKET") or os.path.join(os.environ.get("XDG_RUNTIME_DIR") or "/tmp", f"mini-teto-{os.getuid() if hasattr(os, 'getuid') else 0}.sock")
ADDR = ("127.0.0.1", 47625)      # Windows: commands travel over the loopback instead of a unix socket

ART_W, ART_H = 29, 31
FRAMES = ["idle", "blink", "talk", "happy", "sleep", "shock", "dizzy", "cheer", "wink", "eat", "chew"]

DEFAULTS = {
    "scale": 4,            # screen pixels per art pixel
    "side": "right",       # which bottom corner is home
    "lang": "auto",        # auto | ru | en
    "voice": True,         # chirps while she types (not her singing, not the crunching)
    "sounds": True,
    "volume": 0.6,
    "chatter": "normal",   # quiet | normal | chatty
    "monitor": -1,         # -1: primary
    "x11_managed": False,  # X11: a managed always-on-top window instead of an unmanaged one
}

HUNGER_SECONDS = 3 * 3600      # from full to empty
FEEDS_TO_FULL = 3              # baguettes from empty to full
FLY_HUNGER = 0.01              # satiety lost per second in the air (a 2 s throw costs 2%)
FEED_TIMEOUT = 45              # seconds a baguette is held out before she gives up

INK = (0.353, 0.122, 0.169)
PAPER = (1.0, 0.973, 0.973)
PINK = (0.965, 0.788, 0.812)
RED = (0.839, 0.259, 0.373)
LILAC = (0.561, 0.420, 0.788)
SKY = (0.231, 0.576, 0.769)
GOLD = (0.945, 0.812, 0.420)


def load_json(path, fallback):
    try:
        with open(path, encoding="utf-8") as f:
            return {**fallback, **json.load(f)}
    except (OSError, ValueError):
        return dict(fallback)


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def user_name():
    try:
        gecos = pwd.getpwuid(os.getuid()).pw_gecos.split(",")[0].strip() if pwd else ""
        if gecos:
            return gecos
    except KeyError:
        pass
    return getpass.getuser()


def read_battery():
    """(percent, status) or None."""
    if WIN:
        from . import winplat
        return winplat.battery()
    for bat in ("BAT0", "BAT1", "battery"):
        base = f"/sys/class/power_supply/{bat}"
        if os.path.exists(base + "/capacity"):
            try:
                return int(open(base + "/capacity").read()), open(base + "/status").read().strip()
            except (OSError, ValueError):
                return None
    return None


def read_cpu():
    """(idle, total) counters or None."""
    if WIN:
        from . import winplat
        return winplat.cpu()
    try:
        f = [int(x) for x in open("/proc/stat").readline().split()[1:]]
        return f[3] + f[4], sum(f)
    except (OSError, ValueError, IndexError):
        return None


# --- choosing how to get on screen (before GTK is imported) ----------------------

def pick_backend(argv):
    """Returns "layer" or "x11"; re-executes under XWayland when it has to."""
    forced = os.environ.get("MINI_TETO_BACKEND")
    if forced in ("layer", "x11"):
        return forced
    if os.environ.get("WAYLAND_DISPLAY"):
        import gi
        gi.require_version("Gtk", "3.0")
        ok = False
        try:
            gi.require_version("GtkLayerShell", "0.1")
            from gi.repository import Gtk, GtkLayerShell
            Gtk.init_check(None)
            ok = GtkLayerShell.is_supported() if hasattr(GtkLayerShell, "is_supported") else True
        except (ValueError, ImportError):
            ok = False
        if ok:
            return "layer"
        if os.environ.get("DISPLAY"):
            env = dict(os.environ, GDK_BACKEND="x11", MINI_TETO_BACKEND="x11")
            os.execve(sys.executable, [sys.executable, "-m", "mini_teto"] + argv, env)
        sys.exit("mini-teto: this Wayland desktop has neither layer-shell nor XWayland; nothing to draw on")
    return "x11"


# =================================================================================

def run(argv):
    if WIN:
        from . import winplat as P
        P.init()
        backend = "win"
        cairo, Gdk, GLib, Gtk, Gio = P.cairo, P.Gdk, P.GLib, P.Gtk, None
    else:
        backend = pick_backend(argv)
        if backend == "x11":
            os.environ.setdefault("GDK_BACKEND", "x11")

        import cairo
        import gi
        gi.require_version("Gtk", "3.0")
        gi.require_version("Gdk", "3.0")
        gi.require_version("Pango", "1.0")
        gi.require_version("PangoCairo", "1.0")
        from gi.repository import Gdk, Gio, GLib, Gtk, Pango, PangoCairo

    from . import lines as L
    from .sound import Sound

    if backend == "layer":
        gi.require_version("GtkLayerShell", "0.1")
        from gi.repository import GtkLayerShell

    FONT = "Fredoka,Nunito,Comic Neue,Noto Sans,Noto Sans JP,Noto Sans CJK JP,Sans"
    MENU_W, SLIDER_X, SLIDER_END = 220, 100, 52     # menu bubble width; the volume slider's span inside it

    # --- text -------------------------------------------------------------------------
    if WIN:
        layout_for, draw_text = P.layout_for, P.draw_text
    else:
        def layout_for(cr, text, size, bold=True, width=None):
            lay = PangoCairo.create_layout(cr)
            desc = Pango.FontDescription.from_string(f"{FONT} {'Bold' if bold else ''} {size}")
            lay.set_font_description(desc)
            if width:
                lay.set_width(int(width * Pango.SCALE))
                lay.set_wrap(Pango.WrapMode.WORD_CHAR)
            lay.set_text(text, -1)
            return lay

        def draw_text(cr, text, x, y, size, color, bold=True, width=None, outline=None):
            lay = layout_for(cr, text, size, bold, width)
            cr.save()
            cr.move_to(x, y)
            if outline:
                PangoCairo.layout_path(cr, lay)
                cr.set_source_rgb(*outline)
                cr.set_line_width(3)
                cr.set_line_join(cairo.LINE_JOIN_ROUND)
                cr.stroke_preserve()
                cr.set_source_rgb(*color)
                cr.fill()
            else:
                cr.set_source_rgb(*color)
                PangoCairo.show_layout(cr, lay)
            cr.restore()
            return lay.get_pixel_size()


    def rounded(cr, x, y, w, h, r):
        cr.new_sub_path()
        cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
        cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
        cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
        cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
        cr.close_path()

    def draw_baguette(cr, x, y, length, direction=1, tilt=-0.5):
        """A baguette whose tip is at (x, y), lying away from it along `direction`."""
        th = length * 0.26
        lw = max(1.2, length * 0.03)
        cr.save()
        cr.translate(x, y)
        cr.scale(direction, 1)
        cr.rotate(tilt)
        rounded(cr, 0, -th / 2, length, th, th / 2)
        cr.set_source_rgb(0.725, 0.482, 0.173)
        cr.fill_preserve()
        cr.set_source_rgb(*INK)
        cr.set_line_width(lw)
        cr.stroke()
        rounded(cr, th * 0.25, -th / 2 + lw, length - th * 0.5, th * 0.42, th * 0.2)
        cr.set_source_rgb(0.925, 0.722, 0.384)
        cr.fill()
        cr.set_source_rgb(1.0, 0.93, 0.74)
        cr.set_line_width(max(1.0, th * 0.12))
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        for k in range(4):
            xx = length * (0.22 + k * 0.19)
            cr.move_to(xx - th * 0.14, th * 0.12)
            cr.line_to(xx + th * 0.14, -th * 0.3)
            cr.stroke()
        cr.restore()

    # =================================================================================
    class Teto:
        def __init__(self):
            self.cfg = load_json(os.path.join(CONFIG_DIR, "config.json"), DEFAULTS)
            self.state = load_json(os.path.join(STATE_DIR, "state.json"), {"love": 0, "sat": 1.0, "sat_at": time.time()})
            for gone in ("bread_day", "bread_box"):      # the bread of the day is gone
                self.state.pop(gone, None)
            self.sound = Sound()
            self.name = user_name()
            self.load_sprites()

            # body
            self.bx = self.by = 0.0
            self.vx = self.vy = 0.0
            self.phase = "home"          # home | held | fly | rest | walk
            self.facing = 1
            self.impact = 0.0
            self.squash = 1.0
            self.squash_t = None
            self.sway = 0.0
            self.drag_vx = 0.0
            self.trail = []
            self.grab_off = (0, 0)
            self.press_at = None
            self.moved = False
            self.rest_until = 0.0

            # head
            self.mood = "idle"
            self.mood_until = 0.0
            self.petting_until = 0.0
            self.pokes = 0
            self.last_poke = 0.0
            self.last_touch = time.time()
            self.text = ""
            self.shown = 0
            self.sticky = False
            self.voice = True
            self.hush_at = 0.0
            self.menu = False
            self.menu_hover = -1
            self.hidden = False
            self.hide_timer = 0
            self.tick = 0
            self.music = {"status": "", "artist": "", "title": ""}
            self.last_track = ""
            self.last_music_line = 0.0
            self.warned_low = False
            self.last_hot = 0.0
            self.hot_ticks = 0
            self.cpu_prev = None
            self.booted = False

            # food
            self.feeding = False
            self.cursor = (0.0, 0.0)
            self.next_hop = self.next_beg = self.feed_until = 0.0
            self.last_hunger_say = 0.0
            self.vol_drag = False
            self.last_frame = 0.0
            self.frame_ms = 16
            try:                                  # a 144 Hz monitor gets ~7 ms frames; capped so it stays light
                disp = Gdk.Display.get_default()
                rate = max(disp.get_monitor(i).get_refresh_rate() for i in range(disp.get_n_monitors()))
                if rate > 0:
                    self.frame_ms = max(6, min(16, int(1000000 / rate)))
            except Exception:
                pass
            self.n_logic = self.n_draw = 0
            if os.environ.get("MINI_TETO_DEBUG"):
                GLib.timeout_add_seconds(1, self.debug_fps)

            self.stage = (P.WinStage if backend == "win" else LayerStage if backend == "layer" else X11Stage)(self)
            GLib.timeout_add(125, self.on_tick)
            GLib.timeout_add(16, self.on_frame)
            GLib.timeout_add(38, self.on_type)
            GLib.timeout_add_seconds(5, self.on_watch)
            GLib.timeout_add_seconds(60, self.trim_memory)
            GLib.timeout_add(2500, self.greet)
            self.schedule_chatter()
            self.start_music_watch()

        # --- config ---------------------------------------------------------------------
        @property
        def lang(self):
            want = self.cfg.get("lang", "auto")
            if want in ("ru", "en"):
                return want
            loc = (os.environ.get("LC_ALL") or os.environ.get("LC_MESSAGES") or os.environ.get("LANG") or "").lower()
            return "ru" if loc.startswith(("ru", "uk", "be")) else "en"

        def save(self):
            save_json(os.path.join(CONFIG_DIR, "config.json"), self.cfg)

        def save_state(self):
            save_json(os.path.join(STATE_DIR, "state.json"), self.state)

        @property
        def px(self):
            return max(2, min(9, int(self.cfg.get("scale", 4))))

        @property
        def bw(self):
            return ART_W * self.px

        @property
        def bh(self):
            return ART_H * self.px

        def satiety(self):
            """1.0 full .. 0.0 starving; it drains by itself, in HUNGER_SECONDS from full."""
            drained = (time.time() - self.state.get("sat_at", time.time())) / HUNGER_SECONDS
            return max(0.0, min(1.0, self.state.get("sat", 1.0) - drained))

        def vol(self, k=1.0):
            return self.cfg["volume"] * k if self.cfg.get("sounds", True) else 0

        def play(self, name, pitch=1.0, k=1.0):
            self.sound.play(name, self.vol(k), pitch)

        # --- sprites --------------------------------------------------------------------
        def load_sprites(self):
            self.sprites = {}
            for name in FRAMES:
                for d in (SKIN_DIR, SPRITES):
                    p = os.path.join(d, name + ".png")
                    if os.path.exists(p):
                        try:
                            self.sprites[name] = cairo.ImageSurface.create_from_png(p)
                            break
                        except Exception:
                            pass
            if "idle" not in self.sprites:
                sys.exit("mini-teto: sprites missing in " + SPRITES)

        # --- geometry -------------------------------------------------------------------
        def area(self):
            return self.stage.area()       # (w, h) of the usable stage

        def fits(self, x, y):
            """Is her whole body over monitors? (the space beside a smaller monitor is a wall)"""
            got = 0.0
            for rx, ry, rw, rh in self.stage.rects():
                ix = min(x + self.bw, rx + rw) - max(x, rx)
                iy = min(y + self.bh, ry + rh) - max(y, ry)
                if ix > 0 and iy > 0:
                    got += ix * iy
            return got >= self.bw * self.bh - 1

        def floor_y(self):
            """The bottom of whichever monitor she is standing over."""
            return self.stage.floor_at(self.bx + self.bw / 2) - self.bh - 2

        def home_x(self):
            x, _, w, _ = self.stage.monitor_rect()       # her monitor's corner
            return x + w - self.bw - 24 if self.cfg["side"] == "right" else x + 24

        def go_home(self):
            self.bx = self.home_x()
            self.by = self.floor_y()
            self.phase = "home"
            self.facing = 1 if self.cfg["side"] == "right" else -1

        # --- talking --------------------------------------------------------------------
        def say(self, line, sticky=False, voice=True, **vals):
            if self.hidden:
                return
            self.text = L.fill(line, name=self.name, **vals)
            self.shown = 0
            self.sticky = sticky
            self.voice = voice
            self.menu = False
            self.hush_at = 0
            self.stage.changed(bubble=True)

        def say_from(self, key, **vals):
            self.say(L.pick(self.lang, key), **vals)

        def quiet(self):
            self.text = ""
            self.shown = 0
            self.stage.changed(bubble=True)

        def on_type(self):
            if self.text and self.shown < len(self.text):
                ch = self.text[self.shown]
                self.shown += 1
                if self.voice and self.cfg.get("voice", True) and ch.isalnum() and self.shown % 2 == 1:
                    code = ord(ch.lower()) % 7
                    self.sound.play("blip", self.vol(0.55), 0.9 + code * 0.045)
                if self.shown >= len(self.text) and not self.sticky:
                    self.hush_at = time.time() + 1.6 + len(self.text.split()) * 0.38
                self.stage.changed(bubble=True)
            elif self.text and self.hush_at and time.time() > self.hush_at and not self.menu:
                self.quiet()
            return True

        @property
        def talking(self):
            return bool(self.text) and self.shown < len(self.text)

        # --- moods ----------------------------------------------------------------------
        def set_mood(self, m, sec=0):
            self.mood = m
            self.mood_until = time.time() + sec if sec else 0
            self.stage.changed()

        def settle(self):
            if self.phase in ("held", "fly", "chase"):
                return
            playing = self.music.get("status") == "Playing"
            idle_min = (time.time() - self.last_touch) / 60
            h = datetime.datetime.now().hour
            drowsy = not playing and idle_min > (6 if 1 <= h < 6 else 20)
            self.mood = "dance" if playing else ("sleep" if drowsy else "idle")
            self.stage.changed()

        def touched(self):
            self.last_touch = time.time()
            if self.mood == "sleep":
                self.set_mood("happy", 1.5)
                self.say_from("wake")
                return True
            return False

        # --- frames ---------------------------------------------------------------------
        def frame(self):
            m, t = self.mood, self.tick
            if self.phase in ("held", "fly"):
                return "shock"
            if self.phase == "chase" and self.feeding:
                if self.by < self.floor_y() - 4:
                    return "cheer"
                return "talk" if t % 4 < 2 else "happy"
            if m == "dizzy":
                return "dizzy"
            if m == "sleep":
                return "sleep"
            if m == "eat":
                return "eat" if t % 6 < 3 else "chew"
            if m == "sing" or (self.sticky and self.text):
                return "talk" if t % 3 != 1 else "happy"
            if self.talking:
                return "talk" if t % 2 else "idle"
            if m == "dance":
                return "cheer" if t % 8 < 4 else "happy"
            if time.time() < self.petting_until:
                return "wink" if t % 6 < 3 else "happy"
            if m in ("happy", "shock"):
                return m
            return "blink" if t % 37 in (0, 2) else "idle"

        def bob(self):
            t, px = self.tick, self.px
            if self.mood == "sleep":
                return [0, 0, 1, 1, 1, 0][t % 6] * px * 0.5
            if self.mood in ("dance", "sing"):
                return [0, -2, -4, -2][t % 4] * px * 0.5
            if self.phase == "walk" or (self.phase == "chase" and self.by >= self.floor_y() - 1):
                return [0, -2][t % 2] * px
            return [0, 0, 0, 0, -1, -1, -1, -1][t % 8] * px * 0.25

        def target_sway(self):
            if self.phase == "held":
                return max(-28, min(28, -self.drag_vx / 45))
            if self.phase == "fly":
                return max(-40, min(40, self.vx / 30))
            if self.phase == "chase":
                return max(-14, min(14, self.vx / 40))
            if self.mood == "dance":
                return [-8, 0, 8, 0][(self.tick // 2) % 4]
            if self.mood == "dizzy":
                return math.sin(self.tick * 0.9) * 6
            return 0

        # --- clocks ---------------------------------------------------------------------
        def on_tick(self):
            self.tick += 1
            now = time.time()
            if self.mood_until and now > self.mood_until:
                self.mood_until = 0
                self.settle()
            if self.mood == "idle" and self.tick % 240 == 0:
                self.settle()
                if self.mood == "sleep":
                    self.say_from("sleepy")
                    self.text and setattr(self, "voice", False)
            if self.phase == "rest" and now > self.rest_until:
                self.phase = "walk" if abs(self.bx - self.home_x()) > 4 else "home"
            if not self.hidden:
                self.stage.changed()
            return True

        def on_frame(self):
            now = time.time()
            dt = min(0.05, max(0.004, now - self.last_frame)) if self.last_frame else 0.016
            self.last_frame = now
            moving = self.phase in ("fly", "walk", "chase")
            if self.phase == "fly":
                self.vy += 2600 * dt
                self.state["sat"], self.state["sat_at"] = max(0.0, self.satiety() - FLY_HUNGER * dt), now
                inside = self.fits(self.bx, self.by)      # if she starts outside (dragged there), let her out
                nx = self.bx + self.vx * dt
                if not inside or self.fits(nx, self.by):
                    self.bx = nx
                else:                                     # the edge of a monitor: bounce
                    self.vx = -self.vx * 0.55
                    self.play("pop", 0.8, 0.5)
                ny = self.by + self.vy * dt
                if self.vy > 0 or not inside or self.fits(self.bx, ny):
                    self.by = ny
                else:                                     # a ceiling
                    self.vy = -self.vy * 0.3
                w = self.area()[0]
                if self.bx < 0:
                    self.bx, self.vx = 0, -self.vx * 0.55
                    self.play("pop", 0.8, 0.5)
                if self.bx > w - self.bw:
                    self.bx, self.vx = w - self.bw, -self.vx * 0.55
                    self.play("pop", 0.8, 0.5)
                if self.by < 0:
                    self.by, self.vy = 0, -self.vy * 0.4
                if self.by >= self.floor_y():
                    self.by = self.floor_y()
                    self.impact = max(self.impact, abs(self.vy))
                    self.squash_t = time.time()
                    if abs(self.vy) > 650:
                        self.vy, self.vx = -self.vy * 0.42, self.vx * 0.75
                        self.play("boing", 0.9 + random.random() * 0.2)
                    else:
                        self.vy = self.vx = 0
                        self.phase = "rest"
                        hard = self.impact > 1500
                        self.rest_until = time.time() + (3.4 if hard else 1.4)
                        self.landed(hard)
                if abs(self.vx) > 30:
                    self.facing = 1 if self.vx > 0 else -1
            elif self.phase == "walk":
                d = self.home_x() - self.bx
                self.facing = 1 if d > 0 else -1
                self.bx += math.copysign(min(abs(d), 170 * dt), d)
                self.by = self.floor_y()                 # monitors can differ in height
                if not self.fits(self.bx, self.by):      # a wall in the way: no point walking
                    d = 0
                if abs(d) < 1:
                    self.go_home()
                    self.settle()
            elif self.phase == "chase":
                self.chase(dt)
            # landing squash, a short springy curve
            sq = 1.0
            if self.squash_t:
                t = time.time() - self.squash_t
                if t < 0.33:
                    sq = 1 - 0.18 * math.exp(-t * 9) * math.cos(t * 30)
                else:
                    self.squash_t = None
            target = self.target_sway()
            self.sway += (target - self.sway) * 0.25
            active = moving or self.squash_t or abs(self.sway - target) > 0.2 or sq != self.squash
            if active:
                self.squash = sq
                self.stage.changed()
            self.n_logic += 1
            GLib.timeout_add(self.frame_ms if active else 33, self.on_frame)
            return False

        def debug_fps(self):
            print(f"mini-teto: {self.n_logic} logic frames/s, {self.n_draw} pet draws/s", flush=True)
            self.n_logic = self.n_draw = 0
            return True

        # --- the world --------------------------------------------------------------------
        def greet(self):
            self.booted = True
            h = datetime.datetime.now().hour
            part = "night" if h < 5 else "morning" if h < 12 else "day" if h < 18 else "evening" if h < 23 else "night"
            self.say_from("greet_" + part)
            self.settle()
            return False

        def schedule_chatter(self):
            minutes = {"quiet": 0, "normal": 9, "chatty": 3}.get(self.cfg.get("chatter"), 9)
            if minutes:
                GLib.timeout_add_seconds(int(minutes * 60 + random.random() * 120), self.chatter)

        def chatter(self):
            if not (self.text or self.menu or self.mood == "sleep" or self.hidden or self.feeding):
                if self.satiety() < 0.35 and random.random() < 0.5:
                    self.say_from("hungry_hint")
                else:
                    self.say_from("chat")
            self.schedule_chatter()
            return False

        def on_watch(self):
            self.check_hunger()
            bat = read_battery()
            if bat:
                cap, status = bat
                low = cap <= 15 and status != "Charging"
                if low and not self.warned_low:
                    self.warned_low = True
                    self.set_mood("shock", 2)
                    self.say_from("battery_low", n=cap)
                if not low:
                    self.warned_low = False
                if status == "Charging" and getattr(self, "_was", "") not in ("Charging", "") and self.booted:
                    self.say_from("charging")
                self._was = status
            cpu = read_cpu()
            if cpu:
                idle, total = cpu
                if self.cpu_prev:
                    dt, di = total - self.cpu_prev[1], idle - self.cpu_prev[0]
                    load = 1 - di / dt if dt else 0
                    self.hot_ticks = self.hot_ticks + 1 if load > 0.88 else 0
                    if self.hot_ticks >= 3 and time.time() - self.last_hot > 600:
                        self.last_hot = time.time()
                        self.set_mood("shock", 1.8)
                        self.say_from("cpu_hot", n=round(load * 100))
                self.cpu_prev = (idle, total)
            return True

        def start_music_watch(self):
            """Listens to MPRIS players over D-Bus inside this process: no playerctl
            child processes at all (each one cost ~100 MiB and they piled up)."""
            if WIN:                      # no D-Bus: ask Windows' media session instead
                from . import winplat
                winplat.start_media_watch(lambda st, ar, ti: GLib.idle_add(self.on_music, st, ar, ti))
                return
            self.players = {}            # bus name -> {"status", "artist", "title"}
            try:
                bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            except GLib.Error:
                return
            self._bus = bus              # keep the connection alive

            def changed(conn, sender, path, iface, signal, params, *_):
                try:
                    which, props, _inv = params.unpack()
                    if which != "org.mpris.MediaPlayer2.Player":
                        return
                    st = self.players.setdefault(sender, {"status": "", "artist": "", "title": ""})
                    if "PlaybackStatus" in props:
                        st["status"] = props["PlaybackStatus"]
                    md = props.get("Metadata")
                    if md is not None:
                        art = md.get("xesam:artist", "")
                        st["artist"] = ", ".join(art) if isinstance(art, (list, tuple)) else str(art)
                        st["title"] = str(md.get("xesam:title", ""))
                    if len(self.players) > 16:       # players come and go: keep the table small
                        self.players.pop(next(iter(self.players)))
                    self.on_music(st["status"], st["artist"], st["title"])
                except Exception:
                    pass

            bus.signal_subscribe(None, "org.freedesktop.DBus.Properties", "PropertiesChanged",
                                 "/org/mpris/MediaPlayer2", None, Gio.DBusSignalFlags.NONE, changed)

        def trim_memory(self):
            try:
                import ctypes
                ctypes.CDLL("libc.so.6").malloc_trim(0)
            except Exception:
                return False
            return True

        def on_music(self, status, artist, title):
            was = self.music.get("status")
            self.music = {"status": status, "artist": artist, "title": title}
            if status != was and self.mood in ("idle", "dance", "sleep"):
                self.settle()
            if not self.booted or status != "Playing" or not title or title == self.last_track:
                return False
            self.last_track = title
            if time.time() - self.last_music_line < 120 or self.text:
                return False
            self.last_music_line = time.time()
            me = any(k in (artist + " " + title).lower() for k in ("teto", "テト", "重音", "kasane"))
            if me or random.random() < 0.45:
                self.say_from("music_teto" if me else "music", title=title, artist=artist or "?")
            return False

        # --- things she does ------------------------------------------------------------------
        def eat(self):
            self.touched()
            self.set_mood("eat", 4.2)
            self.say_from("eat")
            for i in range(4):
                GLib.timeout_add(900 * (i + 1), lambda: (self.play("crunch"), False)[1])

        def sing(self):
            self.touched()
            songs = L.SONGS
            bag = getattr(self, "song_bag", None)
            if not bag:                                # a new cycle: every song once, in random order
                bag = list(range(len(songs)))
                random.shuffle(bag)
                if len(bag) > 1 and bag[-1] == getattr(self, "last_song", None):
                    bag[0], bag[-1] = bag[-1], bag[0]  # never the same song twice in a row across cycles
                self.song_bag = bag
            self.last_song = bag.pop()
            song = songs[self.last_song % len(songs)]
            self.say(song["words"], voice=False)
            self.sound.sing(song["score"], self.vol(0.8))      # asked for outright: sings even with the voice switch off
            secs = sum(int(i.partition(":")[2] or 250) for i in song["score"].split()) / 1000
            self.set_mood("sing", max(2.0, secs + 0.3))

        # --- food -----------------------------------------------------------------------------------------
        def hunger_interval(self, sat):
            """Seconds between her complaints: every 30 min at half full, every 5 min when empty."""
            return 300 + max(0.0, min(0.5, sat)) / 0.5 * 1500

        def check_hunger(self):
            sat = self.satiety()
            if sat > 0.5:
                self.last_hunger_say = 0.0           # fed enough: the next hunger speaks at once
                return
            now = time.time()
            if now - self.last_hunger_say < self.hunger_interval(sat):
                return
            if not self.booted or self.text or self.menu or self.hidden or self.feeding or self.mood == "sleep":
                return                               # busy: try again in 5 seconds
            self.last_hunger_say = now
            self.say_from("hungry_1" if sat > 0.2 else "hungry_2" if sat > 0.0 else "starving")
            if sat <= 0.2:
                self.set_mood("shock", 1.6)

        def feed(self):
            """A baguette on the pointer; she runs after it and jumps for it."""
            self.touched()
            if self.feeding or self.phase in ("held", "fly"):
                return
            if self.satiety() >= 0.99:
                self.say_from("full_refuse")
                self.set_mood("happy", 1.6)
                return
            now = time.time()
            self.feeding = True
            self.phase = "chase"
            self.mood = "feed"
            self.mood_until = 0
            self.vx = self.vy = 0.0
            self.next_hop = 0.0
            self.next_beg = now + 3.0
            self.feed_until = now + FEED_TIMEOUT
            self.cursor = self.stage.pointer()
            self.stage.feed_begin()
            self.say_from("feed_start")
            self.play("open", 1.3)

        def end_feed(self, why=None):
            if not self.feeding:
                return
            self.feeding = False
            self.stage.feed_end()
            self.mood = "idle"
            if why:
                self.say_from(why)

        def caught(self):
            """She got the baguette."""
            self.end_feed()
            sat = min(1.0, self.satiety() + 1.0 / FEEDS_TO_FULL)
            self.state["sat"], self.state["sat_at"] = sat, time.time()
            self.save_state()
            self.set_mood("eat", 4.2)
            full = sat > 0.99
            self.say_from("fed_full" if full else "fed_more")
            for i in range(4):
                GLib.timeout_add(900 * (i + 1), lambda: (self.play("crunch"), False)[1])
            if full:
                GLib.timeout_add(3700, lambda: (self.play("chime"), False)[1])

        def chase(self, dt):
            """Per frame while she is after the baguette (and while she lands afterwards)."""
            now = time.time()
            fy = self.floor_y()
            w = self.area()[0]
            if self.feeding:
                cx, cy = self.stage.pointer()
                self.cursor = (cx, cy)
                dx = cx - self.bw / 2 - self.bx
                goal = 0.0 if abs(dx) < 6 else max(-520.0, min(520.0, dx * 7))
                self.vx += (goal - self.vx) * 0.22
                if abs(self.vx) > 25:
                    self.facing = 1 if self.vx > 0 else -1
                if self.by >= fy - 0.5 and now > self.next_hop and cy < self.by + self.bh * 0.35:
                    need = max(40.0, self.by - cy + self.bh * 0.5)     # rise that puts the baguette inside her
                    self.vy = -min(1550.0, math.sqrt(2 * 2600 * need))
                    self.next_hop = now + 0.32
                    self.play("pop", 1.1 + random.random() * 0.2, 0.5)
            else:
                self.vx *= 0.8
            self.vy += 2600 * dt
            inside = self.fits(self.bx, self.by)
            nx = max(0.0, min(w - self.bw, self.bx + self.vx * dt))
            if not inside or self.fits(nx, self.by):
                self.bx = nx
            else:
                self.vx = 0.0                            # the edge of a monitor
            ny = self.by + self.vy * dt
            if self.vy > 0 or not inside or self.fits(self.bx, ny):
                self.by = ny
            else:
                self.vy = 0.0                            # a ceiling
            if self.by < 0:
                self.by, self.vy = 0.0, 0.0
            if self.by >= fy:
                if self.vy > 500:
                    self.squash_t = now
                self.by, self.vy = fy, 0.0
                if not self.feeding:
                    self.phase = "rest"
                    self.rest_until = now + (4.4 if self.mood == "eat" else 1.0)
                    return
            if not self.feeding:
                return
            cx, cy = self.cursor
            if self.bx <= cx <= self.bx + self.bw and self.by + self.bh * 0.1 <= cy <= self.by + self.bh * 0.95:
                self.caught()
            elif now > self.feed_until:
                self.end_feed("feed_timeout")
            elif now > self.next_beg and not self.talking:
                self.next_beg = now + 3.2 + random.random() * 2
                self.say_from("feed_beg")

        def hide(self, minutes=60):
            self.end_feed()
            self.quiet()
            self.menu = False
            self.hidden = True
            self.stage.set_visible(False)
            if self.hide_timer:
                GLib.source_remove(self.hide_timer)
            self.hide_timer = GLib.timeout_add_seconds(max(1, int(minutes * 60)), self.hide_over)

        def hide_over(self):
            self.hide_timer = 0
            return self.show()

        def show(self):
            if self.hide_timer:
                GLib.source_remove(self.hide_timer)
                self.hide_timer = 0
            if self.hidden:
                self.hidden = False
                self.stage.set_visible(True)
                self.say_from("back")
            return False

        # --- the pointer ------------------------------------------------------------------------
        def poke(self):
            if self.touched():
                return
            now = time.time()
            self.pokes = self.pokes + 1 if now - self.last_poke < 2.5 else 1
            self.last_poke = now
            self.play("pop", 1.0 + self.pokes * 0.08)
            if self.pokes >= 5:
                self.set_mood("shock", 1.8)
                self.say_from("poke")
                self.pokes = 0
            else:
                self.set_mood("happy", 1.2)
                if self.pokes == 1:
                    self.say_from("click")

        def pet(self):
            self.touched()
            fresh = time.time() > self.petting_until
            self.petting_until = time.time() + 1.4
            if fresh and (not self.text or len(self.text) > 14):
                self.say_from("pet")
            self.state["love"] = self.state.get("love", 0) + 1
            if self.state["love"] % 10 == 0:
                self.save_state()
            self.set_mood("happy", 1.6)

        def press(self, x, y, button):
            if self.feeding:                      # any click takes the baguette away
                self.end_feed("feed_cancel")
                return
            if button == 3:
                self.toggle_menu()
                return
            self.press_at = (x, y)
            self.grab_off = (x - self.bx, y - self.by)
            self.moved = False
            self.trail = [(x, y, time.time())]

        def motion(self, x, y):
            self.cursor = (x, y)
            if not self.press_at:
                return
            if not self.moved and math.hypot(x - self.press_at[0], y - self.press_at[1]) > 8:
                self.moved = True
                self.phase = "held"
                self.menu = False
                self.touched()
                self.mood = "held"
                self.say_from("held")
                self.play("open", 1.2)
            if not self.moved:
                return
            w, _ = self.area()
            self.bx = max(-self.bw / 2, min(w - self.bw / 2, x - self.grab_off[0]))
            self.by = max(0, min(self.floor_y(), y - self.grab_off[1]))
            now = time.time()
            self.trail = [p for p in self.trail + [(x, y, now)] if now - p[2] < 0.09]
            if len(self.trail) > 1:
                a, b = self.trail[0], self.trail[-1]
                self.drag_vx = (b[0] - a[0]) / max(0.001, b[2] - a[2])
            self.stage.changed()

        def release(self, x, y):
            if self.vol_drag:
                self.menu_release()
                return
            if not self.press_at:
                return
            self.press_at = None
            if self.moved:
                now = time.time()
                s = [p for p in self.trail if now - p[2] < 0.09]
                vx = vy = 0.0
                if len(s) > 1:
                    a, b = s[0], s[-1]
                    dt = max(0.001, b[2] - a[2])
                    vx, vy = (b[0] - a[0]) / dt, (b[1] - a[1]) / dt
                self.vx, self.vy = max(-4000, min(4000, vx)), max(-4000, min(4000, vy))
                self.impact = 0
                self.drag_vx = 0
                self.phase = "fly"
                self.mood = "idle"
                if math.hypot(vx, vy) > 600:
                    self.play("boing")
                return
            self.poke()

        def fling(self, vx, vy):
            """Throw her from a script: `mini-teto fling -1800 -1500`."""
            if self.phase == "held":
                return
            self.vx, self.vy = vx, vy
            self.impact = 0
            self.phase = "fly"
            self.mood = "idle"
            self.play("boing")

        def landed(self, hard):
            self.save_state()                              # the throw cost her some energy
            if len(self.stage.rects()) > 1:               # she lives on the monitor she was dropped on
                idx = self.stage.index_at(self.bx + self.bw / 2)
                if idx != self.cfg.get("monitor", -1):
                    self.cfg["monitor"] = idx
                    self.save()
            if hard:
                self.set_mood("dizzy", 3.2)
                self.say_from("thrown")
                self.play("boing", 0.7)
            else:
                self.set_mood("happy", 1.2)
                self.say_from("dropped")

        # --- the menu ---------------------------------------------------------------------------
        def menu_items(self):
            """(label, action); an action of None is the volume slider."""
            m = L.LINES[self.lang]["menu"]
            return [
                (m["volume"], None),
                (m["voice_on"] if self.cfg.get("voice", True) else m["voice_off"], lambda: self.set_cfg("voice", not self.cfg.get("voice", True))),
                (m["feed"], self.feed),
                (m["chat"], lambda: self.say_from("chat")),
                (m["sing"], self.sing),
                (m["bigger"], lambda: self.set_cfg("scale", min(9, self.px + 1))),
                (m["smaller"], lambda: self.set_cfg("scale", max(2, self.px - 1))),
                (m["side_left"] if self.cfg["side"] == "right" else m["side_right"],
                 lambda: self.set_cfg("side", "left" if self.cfg["side"] == "right" else "right")),
                (m["lang"], lambda: self.set_cfg("lang", "en" if self.lang == "ru" else "ru")),
                (m["hide"], lambda: self.hide(60)),
                (m["quit"], Gtk.main_quit),
            ]

        def toggle_menu(self):
            self.touched()
            self.menu = not self.menu
            self.menu_hover = -1
            if self.menu:
                self.text = ""
                self.play("pop", 1.4)
            self.stage.changed(bubble=True)

        def set_cfg(self, key, value):
            self.cfg[key] = value
            self.save()
            if key in ("scale", "side"):
                self.go_home()
                self.stage.resized()
            self.stage.changed(bubble=True)

        def menu_click(self, i):
            items = self.menu_items()
            if 0 <= i < len(items) and items[i][1] is not None:
                self.menu = False
                self.play("pop", 1.2)
                items[i][1]()
                self.stage.changed(bubble=True)

        def menu_press(self, x, y, bx, by):
            """A click inside the open menu; bx, by: the menu's top-left in the same coordinates."""
            i = self.menu_row_at(x, y, bx, by)
            items = self.menu_items()
            if not 0 <= i < len(items):
                return
            if items[i][1] is None:                       # the slider: grab it
                if x >= bx + SLIDER_X - 12:
                    self.vol_drag = True
                    self.menu_move(x, bx)
                return
            self.menu_click(i)

        def menu_move(self, x, bx):
            x0, x1 = bx + SLIDER_X, bx + MENU_W - SLIDER_END
            v = round(max(0.0, min(1.0, (x - x0) / (x1 - x0))) * 20) / 20
            if v != self.cfg.get("volume"):
                self.cfg["volume"] = v
                self.stage.changed(bubble=True)

        def menu_release(self):
            if self.vol_drag:
                self.vol_drag = False
                self.save()
                self.play("pop", 1.2)          # a sample at the new volume

        # --- painting ---------------------------------------------------------------------------
        def paint_pet(self, cr, x, y):
            """The pet with its effects; x, y: where the sprite's top-left goes."""
            px, bw, bh = self.px, self.bw, self.bh
            t = self.tick
            self.n_draw += 1
            # shadow on the floor
            fy = self.floor_y()
            lift = max(0, fy - self.by)
            sw = bw * 0.62 * max(0.35, 1 - lift / 600)
            cr.save()
            cr.translate(x + bw / 2, y + bh + lift - 3)
            cr.scale(sw / 2, sw * 0.11)
            cr.arc(0, 0, 1, 0, 2 * math.pi)
            cr.restore()
            cr.set_source_rgba(*INK, 0.25 * max(0.2, 1 - lift / 600))
            cr.fill()

            surf = self.sprites.get(self.frame()) or self.sprites["idle"]
            sx = bw / surf.get_width() if surf.get_width() != ART_W else px
            sy = bh / surf.get_height() if surf.get_height() != ART_H else px
            cr.save()
            yy = y + self.bob()
            pivot_y = yy if self.phase == "held" else yy + bh
            cr.translate(x + bw / 2, pivot_y)
            cr.rotate(math.radians(self.sway))
            cr.translate(0, (yy + bh) - pivot_y)
            cr.scale(self.facing * (2 - self.squash), self.squash)
            cr.translate(-bw / 2, -bh)
            cr.scale(sx, sy)
            cr.set_source_surface(surf, 0, 0)
            cr.get_source().set_filter(cairo.FILTER_NEAREST)
            cr.paint()
            cr.restore()

            # effects
            if self.mood in ("dance", "sing") or (self.sticky and self.text):
                for i, (glyph, col) in enumerate((("♪", RED), ("♫", LILAC), ("♬", SKY))):
                    tt = ((t + i * 6) % 18) / 18
                    gx = x + bw * (0.95 if i == 1 else 0.05 + i * 0.4) + math.sin(tt * 6 + i) * 6
                    gy = y + bh * 0.15 - tt * 70 - 20
                    cr.push_group()
                    draw_text(cr, glyph, gx, gy, 14 + i * 2, col, outline=PAPER)
                    cr.pop_group_to_source()
                    cr.paint_with_alpha(1 - tt)
            if self.mood == "sleep":
                for i in range(3):
                    tt = ((t + i * 8) % 24) / 24
                    cr.push_group()
                    draw_text(cr, "z", x + bw * 0.7 + tt * 30, y + bh * 0.1 - tt * 50 - 16, 11 + tt * 8, LILAC, outline=PAPER)
                    cr.pop_group_to_source()
                    cr.paint_with_alpha(min(1, (1 - tt) * 1.5))
            if time.time() < self.petting_until:
                for i in range(4):
                    tt = ((t * 1.5 + i * 4) % 16) / 16
                    cr.push_group()
                    draw_text(cr, "❤", x + bw * (0.1 + i * 0.22), y + bh * 0.2 - tt * 60 - 16, 12 + (i % 2) * 5, RED, outline=PAPER)
                    cr.pop_group_to_source()
                    cr.paint_with_alpha(1 - tt)
            if self.mood == "dizzy":
                for i in range(3):
                    a = t * 0.5 + i * math.pi * 2 / 3
                    draw_text(cr, "★", x + bw / 2 + math.cos(a) * bw * 0.42 - 8, y + bh * 0.02 + math.sin(a) * bw * 0.12 - 10, 13, GOLD, outline=INK)
            if self.mood == "eat":
                for i in range(4):
                    tt = ((t + i * 3) % 10) / 10
                    cr.set_source_rgba(*((0.925, 0.722, 0.384) if i % 2 else (0.725, 0.482, 0.173)), 1 - tt)
                    cr.rectangle(x + bw * 0.55 + (i - 1.5) * px * 2 + tt * 6, y + bh * 0.5 + tt * bh * 0.45, px, px)
                    cr.fill()

        def paint_baguette(self, cr, x, y, ref_x=None):
            """The baguette on the pointer, lying away from her (ref_x: the pointer's x on the stage)."""
            side = 1 if (x if ref_x is None else ref_x) >= self.bx + self.bw / 2 else -1
            draw_baguette(cr, x, y, 22 * self.px, side, -0.5 + math.sin(self.tick * 0.7) * 0.06)

        def bubble_size(self, cr):
            if self.menu:
                return MENU_W, 34 + 28 * len(self.menu_items()) + 8
            lay = layout_for(cr, self.text, 11, True, 270)
            w, h = lay.get_pixel_size()
            return min(300, max(70, w + 30)), h + 24

        def paint_bubble(self, cr, x, y, w, h, tail_x, below):
            # hard shadow, fill, ink outline, tail
            for dx, dy, col in ((0, 3, INK), (0, 0, PAPER)):
                rounded(cr, x + dx, y + dy, w, h, 14)
                cr.set_source_rgb(*col)
                cr.fill()
            tx = max(x + 16, min(x + w - 30, tail_x - 8))
            cr.move_to(tx, y + (0 if below else h))
            cr.line_to(tx + 8, y + (-10 if below else h + 10))
            cr.line_to(tx + 16, y + (0 if below else h))
            cr.close_path()
            cr.set_source_rgb(*PAPER)
            cr.fill_preserve()
            cr.set_source_rgb(*INK)
            cr.set_line_width(2)
            cr.stroke()
            rounded(cr, x, y, w, h, 14)
            cr.set_source_rgb(*INK)
            cr.set_line_width(2)
            cr.stroke()
            # re-cover the tail's join so the outline reads as one line
            cr.set_source_rgb(*PAPER)
            cr.rectangle(tx + 1.5, y + (-1 if below else h - 3), 13, 4)
            cr.fill()
            if self.menu:
                m = L.LINES[self.lang]["menu"]
                draw_text(cr, f"{m['title']} · {self.state.get('love', 0)} ❤", x + 14, y + 9, 10, RED)
                # hunger: a little baguette and a bar that empties over three hours
                sat = self.satiety()
                gx, gy, gw = x + w - 14 - 58, y + 12, 58
                rounded(cr, gx, gy, gw, 9, 4.5)
                cr.set_source_rgb(*PINK)
                cr.fill()
                if sat > 0.01:
                    rounded(cr, gx, gy, max(9, gw * sat), 9, 4.5)
                    cr.set_source_rgb(*(RED if sat < 0.2 else GOLD))
                    cr.fill()
                rounded(cr, gx, gy, gw, 9, 4.5)
                cr.set_source_rgb(*INK)
                cr.set_line_width(1.5)
                cr.stroke()
                draw_baguette(cr, gx - 27, gy + 10, 22, 1, -0.35)
                for i, (label, act) in enumerate(self.menu_items()):
                    ry = y + 32 + i * 28
                    if act is None:                                   # the volume slider
                        vol = max(0.0, min(1.0, self.cfg.get("volume", 0.6)))
                        x0, x1, cy = x + SLIDER_X, x + w - SLIDER_END, ry + 12
                        draw_text(cr, label, x + 18, ry + 3, 10.5, INK)
                        rounded(cr, x0, cy - 3, x1 - x0, 6, 3)
                        cr.set_source_rgb(*PINK)
                        cr.fill()
                        rounded(cr, x0, cy - 3, max(6, (x1 - x0) * vol), 6, 3)
                        cr.set_source_rgb(*RED)
                        cr.fill()
                        cr.arc(x0 + (x1 - x0) * vol, cy, 7, 0, 2 * math.pi)
                        cr.set_source_rgb(*PAPER)
                        cr.fill_preserve()
                        cr.set_source_rgb(*INK)
                        cr.set_line_width(2)
                        cr.stroke()
                        draw_text(cr, f"{round(vol * 100)}%", x + w - 42, ry + 3, 9.5, INK)
                        continue
                    if i == self.menu_hover:
                        rounded(cr, x + 8, ry, w - 16, 24, 9)
                        cr.set_source_rgb(*PINK)
                        cr.fill()
                    draw_text(cr, label, x + 18, ry + 3, 10.5, INK)
            else:
                draw_text(cr, self.text[: self.shown], x + 15, y + 12, 11, INK, True, w - 30)

        def menu_row_at(self, x, y, bx, by):
            i = int((y - by - 32) // 28)
            return i if 0 <= i < len(self.menu_items()) and y - by >= 32 else -1

    # =================================================================================
    # Stages: how she gets onto the screen
    # =================================================================================
    def transparent(win):
        screen = win.get_screen()
        visual = screen.get_rgba_visual()
        if visual is not None and screen.is_composited():
            win.set_visual(visual)
            return True
        return False

    EVENTS = (Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK | Gdk.EventMask.POINTER_MOTION_MASK
              | Gdk.EventMask.SCROLL_MASK | Gdk.EventMask.SMOOTH_SCROLL_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK)

    class Rect:
        def __init__(self, x, y, width, height):
            self.x, self.y, self.width, self.height = x, y, width, height

    class Monitors:
        """Her stage spans all monitors; these answer 'which monitor is she over'.
        Needs rects(): one (x, y, w, h) per monitor, in stage coordinates."""

        def rect_index(self, cx):
            rs = self.rects()

            def gap(i):
                x, _, w, _ = rs[i]
                return 0 if x <= cx < x + w else min(abs(cx - x), abs(cx - x - w))
            return min(range(len(rs)), key=gap)

        def index_at(self, cx):
            return self.rect_index(cx)

        def floor_at(self, cx):
            _, y, _, h = self.rects()[self.rect_index(cx)]
            return y + h

        def monitor_rect(self):
            rs = self.rects()
            return rs[home_index(self.t, len(rs))]

    class LayerStage(Monitors):
        """One overlay per monitor, all drawing the same stage; input only over her and the bubble."""

        def __init__(self, teto):
            self.t = teto
            teto.stage = self
            self.w = self.h = 0
            self.bubble_rect = None
            self.last_boxes = []
            self.whole = False
            self.cells = []
            display = Gdk.Display.get_default()
            for i in range(display.get_n_monitors()):
                mon = display.get_monitor(i)
                win = Gtk.Window()
                GtkLayerShell.init_for_window(win)
                GtkLayerShell.set_namespace(win, "mini-teto")
                GtkLayerShell.set_layer(win, GtkLayerShell.Layer.TOP)
                for edge in (GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT, GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.BOTTOM):
                    GtkLayerShell.set_anchor(win, edge, True)
                if hasattr(GtkLayerShell, "set_keyboard_mode"):
                    GtkLayerShell.set_keyboard_mode(win, GtkLayerShell.KeyboardMode.NONE)
                GtkLayerShell.set_monitor(win, mon)
                transparent(win)
                win.set_app_paintable(True)
                win.add_events(EVENTS)
                cell = {"win": win, "mon": mon, "w": 0, "h": 0, "ox": 0, "oy": 0}
                self.cells.append(cell)
                win.connect("draw", self.draw, cell)
                win.connect("size-allocate", self.allocated, cell)
                win.connect("button-press-event", lambda w, e, c=cell: (self.press(e, c), True)[1])
                win.connect("button-release-event", lambda w, e, c=cell: (teto.release(*self.xy(e, c)), self.changed(), True)[2])
                win.connect("motion-notify-event", self.motion, cell)
                win.connect("scroll-event", lambda w, e: (teto.pet(), True)[1])
                win.connect("destroy", Gtk.main_quit)
                win.show_all()

        def xy(self, e, cell):
            return e.x + cell["ox"], e.y + cell["oy"]        # stage coordinates

        def rects(self):
            return [(c["ox"], c["oy"], c["w"], c["h"]) if c["w"] else (0, 0, 1280, 720) for c in self.cells]

        def area(self):
            return (self.w or 1280, self.h or 720)

        def allocated(self, win, rect, cell):
            first = self.w == 0
            cell["w"], cell["h"] = rect.width, rect.height
            # a surface sits inside its monitor's panels; assume it is bottom-aligned and centred
            placed = []
            for c in self.cells:
                if c["w"]:
                    g = c["mon"].get_geometry()
                    placed.append((c, g.x + (g.width - c["w"]) // 2, g.y + g.height - c["h"]))
            ux, uy = min(p[1] for p in placed), min(p[2] for p in placed)
            for c, x, y in placed:
                c["ox"], c["oy"] = x - ux, y - uy
            self.w = max(c["ox"] + c["w"] for c, _, _ in placed)
            self.h = max(c["oy"] + c["h"] for c, _, _ in placed)
            if first or self.t.phase == "home":
                self.t.go_home()
            for c in self.cells:
                c["win"].queue_draw()

        def resized(self):
            self.changed(bubble=True)

        def set_visible(self, on):
            for c in self.cells:
                c["win"].set_visible(on)

        def press(self, e, cell):
            x, y = self.xy(e, cell)
            b = self.bubble_rect
            if self.t.feeding:
                self.t.press(x, y, e.button)
                return
            if b and b[0] <= x <= b[0] + b[2] and b[1] <= y <= b[1] + b[3]:
                if self.t.menu:
                    self.t.menu_press(x, y, b[0], b[1])
                else:
                    self.t.quiet()
                return
            self.t.press(x, y, e.button)

        def motion(self, w, e, cell):
            x, y = self.xy(e, cell)
            b = self.bubble_rect
            if self.t.vol_drag and b:
                self.t.menu_move(x, b[0])
            elif self.t.menu and b and b[0] <= x <= b[0] + b[2] and b[1] <= y <= b[1] + b[3]:
                i = self.t.menu_row_at(x, y, b[0], b[1])
                if i != self.t.menu_hover:
                    self.t.menu_hover = i
                    self.changed(bubble=True)
            self.t.motion(x, y)
            return True

        def damage(self):
            """Where something is drawn now: her with her effects, the bubble's reach, the baguette."""
            t, pad = self.t, 110
            boxes = [(t.bx - pad, t.by - pad, t.bw + 2 * pad, t.bh + 2 * pad)]
            if t.text or t.menu:
                boxes.append((t.bx + t.bw / 2 - 380, t.by - 380, 760, t.bh + 760))
            if t.feeding:
                boxes.append((t.cursor[0] - 170, t.cursor[1] - 170, 340, 340))
            return boxes

        def changed(self, bubble=False):
            """Queue only what changed (now and last time) on the overlays it touches: a full
            monitor redrawn 60 times a second is what made it choppy."""
            whole = bool(self.t.press_at or self.t.feeding)
            if whole != self.whole:                    # every overlay's input region changes: redraw them all,
                self.whole = whole                     # or one keeps catching clicks over a whole monitor
                for c in self.cells:
                    c["win"].queue_draw()
            boxes = self.damage()
            todo, self.last_boxes = boxes + self.last_boxes, boxes
            for c in self.cells:
                for x, y, w, h in todo:
                    x0, y0 = max(x, c["ox"]), max(y, c["oy"])
                    x1, y1 = min(x + w, c["ox"] + c["w"]), min(y + h, c["oy"] + c["h"])
                    if x1 > x0 and y1 > y0:
                        c["win"].queue_draw_area(int(x0 - c["ox"]), int(y0 - c["oy"]), int(x1 - x0) + 2, int(y1 - y0) + 2)

        def pointer(self):
            return self.t.cursor

        def feed_begin(self):
            for c in self.cells:
                gw = c["win"].get_window()
                if gw is not None:          # the baguette is her cursor now
                    gw.set_cursor(Gdk.Cursor.new_from_name(Gdk.Display.get_default(), "none"))
            self.changed()

        def feed_end(self):
            for c in self.cells:
                gw = c["win"].get_window()
                if gw is not None:
                    gw.set_cursor(None)
            self.changed()

        def draw(self, win, cr, cell):
            t = self.t
            cr.set_operator(cairo.OPERATOR_SOURCE)
            cr.set_source_rgba(0, 0, 0, 0)
            cr.paint()
            cr.set_operator(cairo.OPERATOR_OVER)
            if t.hidden:
                if cell.get("rk") != "hidden" and win.get_window() is not None:     # nothing to click while hidden
                    cell["rk"] = "hidden"
                    win.input_shape_combine_region(cairo.Region())
                return
            ox, oy = cell["ox"], cell["oy"]
            cr.translate(-ox, -oy)                        # this overlay shows its part of the stage
            t.paint_pet(cr, t.bx, t.by)
            if t.feeding:
                t.paint_baguette(cr, *t.cursor)
            regions = [(int(t.bx - ox), int(t.by - oy), t.bw, t.bh)]
            self.bubble_rect = None
            if (t.text or t.menu) and t.phase != "fly":
                bw, bh = t.bubble_size(cr)
                frac = 0.78 if t.cfg["side"] == "right" else 0.22
                x = max(8, min(self.w - bw - 8, t.bx + t.bw / 2 - bw * frac))
                below = t.by < bh + 60
                y = t.by + t.bh + 14 if below else t.by + t.bob() - bh - 16
                t.paint_bubble(cr, x, y, bw, bh, t.bx + t.bw / 2, below)
                self.bubble_rect = (x, y, bw, bh)
                regions.append((int(x - ox), int(y - oy), int(bw), int(bh) + 4))
            whole = bool(t.press_at or t.feeding)   # held or feeding: the whole overlay, so a fast drag cannot escape
            key = "whole" if whole else tuple(regions)
            if cell.get("rk") != key and win.get_window() is not None:      # a Wayland round trip: only when it changed
                cell["rk"] = key
                if whole:
                    region = cairo.Region(cairo.RectangleInt(0, 0, cell["w"], cell["h"]))
                else:
                    region = cairo.Region([cairo.RectangleInt(*r) for r in regions])
                win.input_shape_combine_region(region)

    class X11Stage(Monitors):
        """Two small unmanaged windows: her, and the bubble."""

        M, MTOP = 48, 90             # room round her for the notes, hearts and stars

        def __init__(self, teto):
            self.t = teto
            teto.stage = self
            self.covered = False
            self.bubble_geom = None
            self.catch = None            # a transparent window over the screen while she is fed
            self._wa, self._wa_at = [], -10.0
            self._pos = self._shape = self._gw = self._bsize = None
            managed = teto.cfg.get("x11_managed")
            self.pet = self._window(managed)
            self.bub = self._window(managed)
            self.pet.connect("draw", self.draw_pet)
            self.bub.connect("draw", self.draw_bubble)
            self.pet.connect("button-press-event", lambda w, e: (teto.press(*self.stage_xy(e), e.button), True)[1])
            self.pet.connect("button-release-event", lambda w, e: (teto.release(*self.stage_xy(e)), True)[1])
            self.pet.connect("motion-notify-event", lambda w, e: (teto.motion(*self.stage_xy(e)), True)[1])
            self.pet.connect("scroll-event", lambda w, e: (teto.pet(), True)[1])
            self.bub.connect("button-press-event", self.bub_press)
            self.bub.connect("motion-notify-event", self.bub_motion)
            self.bub.connect("button-release-event", lambda w, e: (teto.menu_release(), True)[1])
            self.pet.connect("destroy", Gtk.main_quit)
            self.size_pet()
            teto.go_home()
            self.pet.show_all()
            self.place()
            GLib.timeout_add_seconds(2, self.keep_on_top)
            if shutil.which("xprop"):
                threading.Thread(target=self.watch_fullscreen, daemon=True).start()

        def _window(self, managed):
            if managed:
                w = Gtk.Window()
                w.set_decorated(False)
                w.set_keep_above(True)
                w.set_skip_taskbar_hint(True)
                w.set_skip_pager_hint(True)
                w.stick()
                w.set_type_hint(Gdk.WindowTypeHint.UTILITY)
                w.set_accept_focus(False)
            else:
                w = Gtk.Window(type=Gtk.WindowType.POPUP)
            w.set_title("mini Teto")
            self.composited = transparent(w)
            w.set_app_paintable(True)
            w.add_events(EVENTS)
            return w

        def workareas(self):
            now = time.monotonic()
            if now - self._wa_at > 2.0:                  # monitors do not change every frame
                display = Gdk.Display.get_default()
                self._wa = [display.get_monitor(i).get_workarea() for i in range(display.get_n_monitors())] or [Rect(0, 0, 1280, 720)]
                self._wa_at = now
            return self._wa

        def origin(self):
            ws = self.workareas()
            x, y = min(w.x for w in ws), min(w.y for w in ws)
            return Rect(x, y, max(w.x + w.width for w in ws) - x, max(w.y + w.height for w in ws) - y)

        def rects(self):
            g = self.origin()
            return [(w.x - g.x, w.y - g.y, w.width, w.height) for w in self.workareas()]

        def area(self):
            g = self.origin()
            return (g.width or 1280, g.height or 720)

        def stage_xy(self, e):
            g = self.origin()
            return e.x_root - g.x, e.y_root - g.y

        def size_pet(self):
            self.pet.resize(self.t.bw + 2 * self.M, self.t.bh + self.MTOP + 24)

        def resized(self):
            self.size_pet()
            self.place()

        def set_visible(self, on):
            self.pet.set_visible(on)
            if not on:
                self.bub.hide()

        def place(self):
            g = self.origin()
            gw = self.pet.get_window()
            if gw is not self._gw:                       # a new X window: forget what we told the old one
                self._gw, self._pos, self._shape = gw, None, None
            pos = (int(g.x + self.t.bx - self.M), int(g.y + self.t.by - self.MTOP))
            if pos != self._pos:
                self._pos = pos
                self.pet.move(*pos)
            if gw is not None and self._shape != (self.t.bw, self.t.bh):    # her click area only changes with her size
                self._shape = (self.t.bw, self.t.bh)
                self.pet.input_shape_combine_region(cairo.Region(cairo.RectangleInt(self.M, self.MTOP, self.t.bw, self.t.bh)))

        def changed(self, bubble=False):
            if self.t.hidden or self.covered:
                return
            self.place()
            self.pet.queue_draw()
            self.update_bubble(bubble)
            if self.catch is not None and self.catch.get_visible():
                self.catch.queue_draw()

        def pointer(self):
            if self.catch is not None and self.catch.get_visible():
                return self.t.cursor                       # fed by the catcher's motion events
            g = self.origin()
            _, px, py = Gdk.Display.get_default().get_default_seat().get_pointer().get_position()
            return (px - g.x, py - g.y)

        def feed_begin(self):
            if not self.composited:
                return                                     # no transparency: poll the pointer instead
            if self.catch is None:
                self.catch = w = self._window(False)
                w.connect("draw", self.draw_catch)
                w.connect("motion-notify-event", lambda w, e: (self.t.motion(*self.stage_xy(e)), True)[1])
                w.connect("button-press-event", lambda w, e: (self.t.press(*self.stage_xy(e), e.button), True)[1])
            g = self.origin()
            self.catch.resize(g.width or 1280, g.height or 720)
            self.catch.move(g.x, g.y)
            self.catch.show_all()
            gw = self.catch.get_window()
            if gw is not None:
                gw.set_cursor(Gdk.Cursor.new_from_name(Gdk.Display.get_default(), "none"))
            self.keep_on_top()                             # she stays above the catcher

        def feed_end(self):
            if self.catch is not None:
                self.catch.hide()

        def draw_catch(self, w, cr):
            cr.set_operator(cairo.OPERATOR_SOURCE)
            cr.set_source_rgba(0, 0, 0, 0)
            cr.paint()
            cr.set_operator(cairo.OPERATOR_OVER)
            if self.t.feeding:
                self.t.paint_baguette(cr, *self.t.cursor)

        def keep_on_top(self):
            if not self.t.hidden and not self.covered:
                for w in (self.pet, self.bub):
                    gw = w.get_window()
                    if gw is not None and w.get_visible():
                        gw.raise_()
            return True

        def watch_fullscreen(self):
            """Step aside while something is fullscreen (a video, a game)."""
            while True:
                time.sleep(3)
                try:
                    act = subprocess.run(["xprop", "-root", "_NET_ACTIVE_WINDOW"], capture_output=True, text=True, timeout=2).stdout
                    wid = act.strip().split()[-1]
                    full = False
                    if wid.startswith("0x") and wid != "0x0":
                        st = subprocess.run(["xprop", "-id", wid, "_NET_WM_STATE"], capture_output=True, text=True, timeout=2).stdout
                        full = "_NET_WM_STATE_FULLSCREEN" in st
                    if full != self.covered:
                        GLib.idle_add(self.set_covered, full)
                except Exception:
                    pass

        def set_covered(self, full):
            self.covered = full
            if self.t.hidden:
                return False
            if full:
                self.pet.hide()
                self.bub.hide()
            else:
                self.pet.show_all()
                self.changed(bubble=True)
            return False

        def draw_pet(self, w, cr):
            cr.set_operator(cairo.OPERATOR_SOURCE)
            cr.set_source_rgba(0, 0, 0, 0)
            cr.paint()
            cr.set_operator(cairo.OPERATOR_OVER)
            # the shadow belongs to the floor; here only while she is on it
            self.t.paint_pet(cr, self.M, self.MTOP)
            if not self.composited:
                # no compositor: cut the window to her outline instead
                s = cairo.ImageSurface(cairo.FORMAT_ARGB32, w.get_allocated_width(), w.get_allocated_height())
                c2 = cairo.Context(s)
                self.t.paint_pet(c2, self.M, self.MTOP)
                w.shape_combine_region(Gdk.cairo_region_create_from_surface(s))

        def update_bubble(self, force=True):
            t = self.t
            if not (t.text or t.menu) or t.phase == "fly":
                if self.bub.get_visible():
                    self.bub.hide()
                self.bubble_geom = None
                self._bsize = None
                return
            if force or self._bsize is None:             # text measured only when the text changed
                self._bsize = t.bubble_size(cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, 4, 4)))
            bw, bh = self._bsize
            w, h = self.area()
            frac = 0.78 if t.cfg["side"] == "right" else 0.22
            x = max(8, min(w - bw - 8, t.bx + t.bw / 2 - bw * frac))
            below = t.by < bh + 60
            y = t.by + t.bh + 14 if below else t.by + t.bob() - bh - 16
            g = self.origin()
            pad = 12
            geom = (x, y, bw, bh, below, pad)
            if geom == self.bubble_geom and not force and self.bub.get_visible():
                return                                   # nothing moved: nothing to do
            if self.bubble_geom is None or self.bubble_geom[2:4] != (bw, bh):
                self.bub.resize(int(bw + pad * 2), int(bh + pad * 2))
            self.bubble_geom = geom
            self.bub.move(int(g.x + x - pad), int(g.y + y - pad))
            if not self.bub.get_visible():
                self.bub.show_all()
            self.bub.queue_draw()

        def draw_bubble(self, w, cr):
            cr.set_operator(cairo.OPERATOR_SOURCE)
            cr.set_source_rgba(0, 0, 0, 0)
            cr.paint()
            cr.set_operator(cairo.OPERATOR_OVER)
            if not self.bubble_geom:
                return
            x, y, bw, bh, below, pad = self.bubble_geom
            self.t.paint_bubble(cr, pad, pad, bw, bh, pad + (self.t.bx + self.t.bw / 2 - x), below)
            if not self.composited:
                s = cairo.ImageSurface(cairo.FORMAT_ARGB32, w.get_allocated_width(), w.get_allocated_height())
                self.t.paint_bubble(cairo.Context(s), pad, pad, bw, bh, pad + (self.t.bx + self.t.bw / 2 - x), below)
                w.shape_combine_region(Gdk.cairo_region_create_from_surface(s))

        def bub_press(self, w, e):
            if self.t.menu and self.bubble_geom:
                pad = self.bubble_geom[5]
                self.t.menu_press(e.x, e.y, pad, pad)
            else:
                self.t.quiet()
            return True

        def bub_motion(self, w, e):
            if self.t.vol_drag and self.bubble_geom:
                self.t.menu_move(e.x, self.bubble_geom[5])
            elif self.t.menu and self.bubble_geom:
                pad = self.bubble_geom[5]
                i = self.t.menu_row_at(e.x, e.y, pad, pad)
                if i != self.t.menu_hover:
                    self.t.menu_hover = i
                    self.bub.queue_draw()
            return True

    def home_index(teto, n):
        """The monitor she lives on: the configured one, else the primary."""
        idx = int(teto.cfg.get("monitor", -1))
        if 0 <= idx < n:
            return idx
        display = Gdk.Display.get_default()
        primary = display.get_primary_monitor()
        for i in range(n):
            if display.get_monitor(i) == primary:
                return i
        return 0

    # --- commands from `mini-teto <cmd>` -----------------------------------------------------
    def serve(teto):
        try:
            os.unlink(SOCKET)
        except OSError:
            pass
        srv = socket.socket(socket.AF_INET if WIN else socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            if WIN:
                srv.bind(ADDR)
            else:
                srv.bind(SOCKET)
                os.chmod(SOCKET, 0o600)
            srv.listen(4)
        except OSError as e:
            print(f"mini-teto: no command socket ({e}); `mini-teto say …` will not reach her", file=sys.stderr)
            return

        def handle(cmd):
            name, _, arg = cmd.partition(" ")
            actions = {
                "say": lambda: teto.say(arg or "!"), "sing": teto.sing, "feed": teto.feed, "eat": teto.eat,
                "hide": lambda: teto.hide(float(arg or 60)), "show": teto.show,
                "poke": teto.poke, "menu": teto.toggle_menu, "home": teto.go_home, "quit": Gtk.main_quit,
                "fling": lambda: teto.fling(*[float(v) for v in (arg.split() + ["-1800", "-1500"])[:2]]),
            }
            if name in actions:
                actions[name]()
                teto.stage.changed(bubble=True)
            return False

        def loop():
            while True:
                conn, _ = srv.accept()
                with conn:
                    data = conn.recv(4096).decode(errors="replace").strip()
                if data:
                    GLib.idle_add(handle, data)

        threading.Thread(target=loop, daemon=True).start()

    teto = Teto()
    serve(teto)
    try:
        Gtk.main()
    finally:
        teto.save_state()
        try:
            os.unlink(SOCKET)
        except OSError:
            pass


def send(cmd):
    s = socket.socket(socket.AF_INET if WIN else socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(1)
    s.connect(ADDR if WIN else SOCKET)
    s.sendall(cmd.encode())
    s.close()


def take_lock():
    """One pet per session, even when the desktop's autostart and the WM's
    exec line both start her at once. None: another one holds it."""
    if WIN:
        import ctypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = k32.CreateMutexW(None, False, "mini-teto-single-instance")
        if ctypes.get_last_error() == 183:      # ERROR_ALREADY_EXISTS
            return None
        return handle or -1
    import fcntl
    try:
        fd = os.open(SOCKET + ".lock", os.O_RDWR | os.O_CREAT, 0o600)
    except OSError:
        return -1                       # nowhere to lock: just run
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return None
    return fd


USAGE = """mini-teto — a desktop pet

  mini-teto                start her (or wave at the one already running)
  mini-teto say <text>     make her say something
  mini-teto sing | feed | eat | poke | menu | home
  mini-teto fling [vx vy]  throw her
  mini-teto hide [minutes] / show
  mini-teto quit
"""


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    sys.setswitchinterval(0.0005)      # the sound thread must not hold the GIL for 5 ms at a stretch
    if argv and argv[0] in ("-h", "--help", "help"):
        print(USAGE)
        return 0
    if argv:
        try:
            send(" ".join(argv))
            return 0
        except OSError:
            if argv[0] != "start":
                print("mini-teto is not running; start it with `mini-teto`", file=sys.stderr)
                return 1
            argv = []
    try:
        send("show")
        send("poke")
        return 0
    except OSError:
        pass
    if take_lock() is None:
        return 0
    run(argv)
    return 0
