"""The Windows side of mini Teto.

Her drawing code is the same cairo code as on Linux. What differs lives here:
  * windows: Tk toplevels with a colour key (black is see-through and
    click-through), three of them: her, the speech bubble, the baguette
  * text: Pillow draws it (Segoe UI), cairo paints the result
  * timers and the main loop: Tk's, behind the small GLib/Gtk look-alikes below
  * monitors, battery, CPU load, fullscreen detection: ctypes and the Win32 API
Nothing here is imported on Linux, and nothing at import time needs Windows.
"""

import ctypes
import itertools
import math
import os
import queue
import sys
import time
import traceback
from collections import OrderedDict
from ctypes import wintypes

cairo = None                  # set by init()


# --- the little GLib / Gtk look-alikes the shared code calls -------------------------------------
class _Loop:
    """timeout_add & co. on top of Tk's after(); idle_add is safe from other threads."""

    def __init__(self):
        self.root = None
        self.ids = itertools.count(1)
        self.live = {}
        self.q = queue.Queue()

    class Error(Exception):
        pass

    def timeout_add(self, ms, fn, *args):
        sid = next(self.ids)

        def tick():
            if sid not in self.live:
                return
            try:
                again = fn(*args)
            except Exception:
                traceback.print_exc()
                again = False
            if again and sid in self.live:
                self.live[sid] = self.root.after(max(1, int(ms)), tick)
            else:
                self.live.pop(sid, None)

        self.live[sid] = self.root.after(max(1, int(ms)), tick)
        return sid

    def timeout_add_seconds(self, seconds, fn, *args):
        return self.timeout_add(int(seconds * 1000), fn, *args)

    def source_remove(self, sid):
        handle = self.live.pop(sid, None)
        if handle is not None:
            try:
                self.root.after_cancel(handle)
            except Exception:
                pass

    def idle_add(self, fn, *args):
        self.q.put((fn, args))

    def pump(self):
        try:
            while True:
                fn, args = self.q.get_nowait()
                try:
                    fn(*args)
                except Exception:
                    traceback.print_exc()
        except queue.Empty:
            pass
        self.root.after(25, self.pump)


GLib = _Loop()


class _Gtk:
    @staticmethod
    def main():
        GLib.root.mainloop()
        try:
            GLib.root.destroy()
        except Exception:
            pass

    @staticmethod
    def main_quit(*_):
        GLib.root.quit()


class _Any:
    def __getattr__(self, name):
        return 0


class _Gdk:
    EventMask = _Any()        # the shared code builds an event mask it never uses here


Gtk = _Gtk()
Gdk = _Gdk()


def init():
    """Before anything else: a log file (a windowed exe has no console), DPI, Tk, cairo."""
    global cairo
    import cairo as _cairo
    cairo = _cairo
    try:
        base = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "mini-teto")
        os.makedirs(base, exist_ok=True)
        log = open(os.path.join(base, "log.txt"), "a", encoding="utf-8", buffering=1)
        if sys.stderr is None or getattr(sys, "frozen", False):
            sys.stderr = log
        if sys.stdout is None:
            sys.stdout = log
    except OSError:
        pass
    try:                                  # real pixels, not scaled ones
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass
    import tkinter
    GLib.root = tkinter.Tk()
    GLib.root.withdraw()
    GLib.pump()


# --- Win32 --------------------------------------------------------------------------------------
class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
                ("dwFlags", wintypes.DWORD)]


class _PowerStatus(ctypes.Structure):
    _fields_ = [("ACLineStatus", ctypes.c_ubyte), ("BatteryFlag", ctypes.c_ubyte),
                ("BatteryLifePercent", ctypes.c_ubyte), ("SystemStatusFlag", ctypes.c_ubyte),
                ("BatteryLifeTime", wintypes.DWORD), ("BatteryFullLifeTime", wintypes.DWORD)]


_u = None


def user32():
    global _u
    if _u is None:
        u = ctypes.WinDLL("user32", use_last_error=True)
        u.GetParent.argtypes, u.GetParent.restype = [wintypes.HWND], wintypes.HWND
        u.GetWindowLongW.argtypes, u.GetWindowLongW.restype = [wintypes.HWND, ctypes.c_int], ctypes.c_long
        u.SetWindowLongW.argtypes, u.SetWindowLongW.restype = [wintypes.HWND, ctypes.c_int, ctypes.c_long], ctypes.c_long
        u.SetWindowPos.argtypes = [wintypes.HWND, ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_uint]
        u.GetForegroundWindow.restype = wintypes.HWND
        u.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        u.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        u.MonitorFromWindow.argtypes, u.MonitorFromWindow.restype = [wintypes.HWND, wintypes.DWORD], wintypes.HANDLE
        u.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MONITORINFO)]
        u.GetAsyncKeyState.argtypes, u.GetAsyncKeyState.restype = [ctypes.c_int], ctypes.c_short
        _u = u
    return _u


def monitors():
    """[((x, y, w, h) of the work area, is_primary)], in desktop pixels."""
    u = user32()
    out = []
    proc = ctypes.WINFUNCTYPE(ctypes.c_int, wintypes.HANDLE, wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)

    def cb(hmon, hdc, rect, data):
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        if u.GetMonitorInfoW(hmon, ctypes.byref(mi)):
            r = mi.rcWork
            out.append(((r.left, r.top, r.right - r.left, r.bottom - r.top), bool(mi.dwFlags & 1)))
        return 1

    callback = proc(cb)                   # keep it alive during the call
    u.EnumDisplayMonitors.argtypes = [wintypes.HDC, ctypes.POINTER(wintypes.RECT), proc, wintypes.LPARAM]
    u.EnumDisplayMonitors(None, None, callback, 0)
    return out or [((0, 0, 1280, 720), True)]


def battery():
    """(percent, "Charging" | "Discharging") or None without a battery."""
    s = _PowerStatus()
    if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(s)):
        return None
    if s.BatteryFlag == 128 or s.BatteryLifePercent > 100:
        return None
    return s.BatteryLifePercent, ("Charging" if (s.BatteryFlag & 8 or s.ACLineStatus == 1) else "Discharging")


def cpu():
    """(idle, total) system times, like the numbers from /proc/stat."""
    idle, kernel, user = (wintypes.FILETIME() for _ in range(3))
    if not ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
        return None

    def n(f):
        return (f.dwHighDateTime << 32) | f.dwLowDateTime
    return n(idle), n(kernel) + n(user)         # the kernel time includes the idle time


def fullscreen_in_front():
    """Is the foreground window covering a whole monitor (a game, a video)?"""
    u = user32()
    hwnd = u.GetForegroundWindow()
    if not hwnd:
        return False
    name = ctypes.create_unicode_buffer(64)
    u.GetClassNameW(hwnd, name, 64)
    if name.value in ("Progman", "WorkerW", "Shell_TrayWnd", "SHELLDLL_DefView"):
        return False                                # the desktop itself
    r = wintypes.RECT()
    if not u.GetWindowRect(hwnd, ctypes.byref(r)):
        return False
    mi = MONITORINFO()
    mi.cbSize = ctypes.sizeof(MONITORINFO)
    if not u.GetMonitorInfoW(u.MonitorFromWindow(hwnd, 2), ctypes.byref(mi)):
        return False
    m = mi.rcMonitor
    return r.left <= m.left and r.top <= m.top and r.right >= m.right and r.bottom >= m.bottom


# --- text: Pillow draws it, cairo paints it ---------------------------------------------------------
_fonts = {}
_masks = OrderedDict()


def _font(px, bold, symbol):
    key = (px, bold, symbol)
    if key not in _fonts:
        from PIL import ImageFont
        names = (["seguisym.ttf", "DejaVuSans.ttf"] if symbol else
                 ["segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"] if bold else
                 ["segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"])
        dirs = [os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"), "/usr/share/fonts/truetype/dejavu"]
        path = next((os.path.join(d, n) for n in names for d in dirs if os.path.exists(os.path.join(d, n))), None)
        root = sys._MEIPASS if getattr(sys, "frozen", False) else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        mine = os.path.join(root, "fonts", "symbol.ttf" if symbol else "bold.ttf" if bold else "regular.ttf")
        if os.path.exists(mine):                      # fonts/bold.ttf & regular.ttf: the font she has on Linux
            path = mine
        try:
            _fonts[key] = ImageFont.truetype(path, px) if path else ImageFont.load_default(px)
        except Exception:
            _fonts[key] = ImageFont.load_default()
    return _fonts[key]


def _symbol(ch):
    o = ord(ch)
    return 0x2190 <= o <= 0x2BFF or o >= 0x1F000      # arrows, hearts, notes, lightning: not in Segoe UI itself


def _runs(text):
    out = []
    for ch in text:
        s = _symbol(ch)
        if out and out[-1][1] == s:
            out[-1][0] += ch
        else:
            out.append([ch, s])
    return out


def _width(text, px, bold):
    return sum(_font(px, bold, s).getlength(r) for r, s in _runs(text))


def _wrap(text, px, bold, width):
    lines = []
    for para in text.split("\n"):
        if not width:
            lines.append(para)
            continue
        cur = ""
        for word in para.split(" "):
            trial = word if not cur else cur + " " + word
            if _width(trial, px, bold) <= width:
                cur = trial
                continue
            if cur:
                lines.append(cur)
                cur = ""
            while _width(word, px, bold) > width and len(word) > 1:     # a word wider than the bubble
                k = len(word)
                while k > 1 and _width(word[:k], px, bold) > width:
                    k -= 1
                lines.append(word[:k])
                word = word[k:]
            cur = word
        lines.append(cur)
    return lines or [""]


class Layout:
    """What PangoCairo's layout was to the shared code: wrapped text with get_pixel_size()."""

    def __init__(self, text, size, bold=True, width=None):
        self.px = max(9, int(round(size * 96 / 72)))
        self.bold = bold
        self.lh = int(self.px * 1.35)
        self.lines = _wrap(text, self.px, bold, width)
        self.w = int(math.ceil(max(_width(l, self.px, bold) for l in self.lines)))
        self.h = self.lh * len(self.lines)

    def get_pixel_size(self):
        return self.w, self.h


def layout_for(cr, text, size, bold=True, width=None):
    return Layout(text, size, bold, width)


_PAD = 3


def _mask(lay, text, size, bold, width, outlined):
    key = (text, size, bold, width, outlined)
    hit = _masks.get(key)
    if hit is not None:
        _masks.move_to_end(key)
        return hit[0]
    from PIL import Image, ImageDraw
    img = Image.new("L", (lay.w + 2 * _PAD + 2, lay.h + 2 * _PAD), 0)
    d = ImageDraw.Draw(img)
    for i, line in enumerate(lay.lines):
        x = _PAD
        for run, sym in _runs(line):
            f = _font(lay.px, lay.bold, sym)
            d.text((x, _PAD + i * lay.lh + (lay.lh - lay.px) // 3), run, font=f, fill=255, stroke_width=2 if outlined else 0)
            x += f.getlength(run)
    w, h = img.size
    stride = cairo.ImageSurface.format_stride_for_width(cairo.FORMAT_A8, w)
    buf = bytearray(stride * h)
    raw = img.tobytes()
    for y in range(h):
        buf[y * stride:y * stride + w] = raw[y * w:(y + 1) * w]
    surf = cairo.ImageSurface.create_for_data(buf, cairo.FORMAT_A8, w, h, stride)
    _masks[key] = (surf, buf)                       # the buffer must outlive the surface
    if len(_masks) > 160:
        _masks.popitem(last=False)
    return surf


def draw_text(cr, text, x, y, size, color, bold=True, width=None, outline=None):
    lay = Layout(text, size, bold, width)
    x, y = round(x) - _PAD, round(y) - _PAD
    if outline:
        cr.set_source_rgb(*outline)
        cr.mask_surface(_mask(lay, text, size, bold, width, True), x, y)
    cr.set_source_rgb(*color)
    cr.mask_surface(_mask(lay, text, size, bold, width, False), x, y)
    return lay.get_pixel_size()


# --- windows --------------------------------------------------------------------------------------------
class Rect:
    def __init__(self, x, y, width, height):
        self.x, self.y, self.width, self.height = x, y, width, height


class _Gdi:
    """Just enough GDI to hand a cairo image to Windows with real per-pixel alpha."""

    def __init__(self):
        g = ctypes.WinDLL("gdi32", use_last_error=True)
        g.CreateCompatibleDC.argtypes, g.CreateCompatibleDC.restype = [wintypes.HDC], wintypes.HDC
        g.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.POINTER(BITMAPINFOHEADER), wintypes.UINT,
                                       ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD]
        g.CreateDIBSection.restype = wintypes.HBITMAP
        g.SelectObject.argtypes, g.SelectObject.restype = [wintypes.HDC, wintypes.HGDIOBJ], wintypes.HGDIOBJ
        g.DeleteObject.argtypes = [wintypes.HGDIOBJ]
        self.g = g
        u = user32()
        u.UpdateLayeredWindow.argtypes = [wintypes.HWND, wintypes.HDC, ctypes.POINTER(wintypes.POINT),
                                          ctypes.POINTER(wintypes.SIZE), wintypes.HDC, ctypes.POINTER(wintypes.POINT),
                                          wintypes.DWORD, ctypes.POINTER(BLENDFUNCTION), wintypes.DWORD]
        u.UpdateLayeredWindow.restype = wintypes.BOOL


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG), ("biYPelsPerMeter", wintypes.LONG),
                ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [("BlendOp", ctypes.c_ubyte), ("BlendFlags", ctypes.c_ubyte),
                ("SourceConstantAlpha", ctypes.c_ubyte), ("AlphaFormat", ctypes.c_ubyte)]


_gdi = None


def gdi():
    global _gdi
    if _gdi is None:
        _gdi = _Gdi()
    return _gdi


class _Layer:
    """One topmost, never-focused window showing a cairo drawing with real per-pixel alpha
    (UpdateLayeredWindow): the same pixels as on Linux, and clicks pass through the clear ones."""

    def __init__(self, stage, win, click_through=False):
        self.stage, self.win, self.click_through = stage, win, click_through
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        self.label = win                  # mouse events are bound on the window itself
        self.visible = False
        self.size = (0, 0)
        self.hbmp = self.bits = self.memdc = self._hwnd = None

    def hwnd(self):
        if self._hwnd is None:
            self._hwnd = user32().GetParent(self.win.winfo_id())
        return self._hwnd

    def style(self):
        u, h = user32(), self.hwnd()
        ex = u.GetWindowLongW(h, -20) | 0x08000000 | 0x80 | 0x80000       # no activation, no Alt-Tab, layered
        if self.click_through:
            ex |= 0x20                                                     # the mouse goes through it
        u.SetWindowLongW(h, -20, ex)
        u.SetWindowPos(h, None, 0, 0, 0, 0, 0x37)

    def show(self):
        if not self.visible:
            self.win.deiconify()
            self.win.update_idletasks()
            self._hwnd = None
            self.style()
            self.visible = True

    def hide(self):
        if self.visible:
            self.win.withdraw()
            self.visible = False

    def front(self):
        if self.visible:
            user32().SetWindowPos(self.hwnd(), ctypes.c_void_p(-1), 0, 0, 0, 0, 0x13)

    def make_dib(self, w, h):
        g = gdi().g
        if self.memdc is None:
            self.memdc = g.CreateCompatibleDC(None)
        bmi = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)    # top-down BGRA
        bits = ctypes.c_void_p()
        hbmp = g.CreateDIBSection(None, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
        g.SelectObject(self.memdc, hbmp)
        if self.hbmp:
            g.DeleteObject(self.hbmp)
        self.hbmp, self.bits, self.size = hbmp, bits, (w, h)

    def draw(self, x, y, w, h, painter):
        self.show()
        c = self.stage.cairo
        surf = c.ImageSurface(c.FORMAT_ARGB32, w, h)          # starts fully transparent
        painter(c.Context(surf))
        surf.flush()
        data, stride = bytes(surf.get_data()), surf.get_stride()
        resized = self.size != (w, h)
        if resized:
            self.make_dib(w, h)
        if stride == 4 * w:
            ctypes.memmove(self.bits, data, 4 * w * h)
        else:
            for row in range(h):
                ctypes.memmove(self.bits.value + row * 4 * w, data[row * stride:row * stride + 4 * w], 4 * w)
        x, y = int(x), int(y)
        if resized:
            self.win.geometry(f"{w}x{h}+{x}+{y}")                # keep Tk's idea of the size right (note the + before a minus)
        blend = BLENDFUNCTION(0, 0, 255, 1)                       # cairo's premultiplied alpha
        user32().UpdateLayeredWindow(self.hwnd(), None, ctypes.byref(wintypes.POINT(x, y)),
                                     ctypes.byref(wintypes.SIZE(w, h)), self.memdc,
                                     ctypes.byref(wintypes.POINT(0, 0)), 0, ctypes.byref(blend), 2)


class WinStage:
    """Her stage on Windows: all monitors' work areas together, three small windows on it."""

    M, MTOP = 48, 90                 # room round her for the notes, hearts and stars

    def __init__(self, teto):
        import tkinter
        self.tk, self.cairo = tkinter, cairo
        self.t = teto
        teto.stage = self
        self.root = GLib.root
        self.covered = False
        self.bubble_geom = None
        self._bsize = None
        self._wa, self._wa_at = [], -10.0
        self._pending = False
        self._force_bubble = True
        self._was_down = True
        self.pet = _Layer(self, self.root)
        self.bub = _Layer(self, tkinter.Toplevel(self.root))
        self.bag = _Layer(self, tkinter.Toplevel(self.root), click_through=True)
        self.bub.win.withdraw()
        self.bag.win.withdraw()

        p = self.pet.label
        p.bind("<ButtonPress>", lambda e: self.t.press(*self.stage_xy(e), e.num))
        p.bind("<ButtonRelease>", lambda e: self.t.release(*self.stage_xy(e)))
        for seq in ("<Motion>", "<B1-Motion>", "<B3-Motion>"):
            p.bind(seq, lambda e: self.t.motion(*self.stage_xy(e)))
        p.bind("<MouseWheel>", lambda e: self.t.pet())
        b = self.bub.label
        b.bind("<ButtonPress>", self.bub_press)
        b.bind("<ButtonRelease>", lambda e: self.t.menu_release())
        for seq in ("<Motion>", "<B1-Motion>"):
            b.bind(seq, self.bub_motion)

        self.size_pet()
        teto.go_home()
        self.changed(bubble=True)
        GLib.timeout_add_seconds(2, self.keep_on_top)
        GLib.timeout_add_seconds(3, self.watch_fullscreen)

    # --- monitors ---------------------------------------------------------------------------------------
    def workareas(self):
        now = time.monotonic()
        if now - self._wa_at > 2.0:                  # monitors do not change every frame
            self._wa, self._wa_at = monitors(), now
        return self._wa

    def origin(self):
        ws = [w for w, _ in self.workareas()]
        x, y = min(w[0] for w in ws), min(w[1] for w in ws)
        return Rect(x, y, max(w[0] + w[2] for w in ws) - x, max(w[1] + w[3] for w in ws) - y)

    def rects(self):
        g = self.origin()
        return [(w[0] - g.x, w[1] - g.y, w[2], w[3]) for w, _ in self.workareas()]

    def area(self):
        g = self.origin()
        return (g.width or 1280, g.height or 720)

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
        idx = int(self.t.cfg.get("monitor", -1))
        if not 0 <= idx < len(rs):
            idx = next((i for i, (_, primary) in enumerate(self.workareas()) if primary), 0)
        return rs[idx]

    def stage_xy(self, e):
        g = self.origin()
        return e.x_root - g.x, e.y_root - g.y

    def pointer(self):
        g = self.origin()
        x, y = self.root.winfo_pointerxy()
        return (x - g.x, y - g.y)

    # --- what Teto asks of a stage -------------------------------------------------------------------------
    def size_pet(self):
        self.pet_size = (self.t.bw + 2 * self.M, self.t.bh + self.MTOP + 24)

    def resized(self):
        self.size_pet()
        self.changed(bubble=True)

    def set_visible(self, on):
        if on:
            self.changed(bubble=True)
        else:
            self.pet.hide()
            self.bub.hide()
            self.bag.hide()

    def changed(self, bubble=False):
        """Redraw soon (once per idle moment, however many times this is called)."""
        self._force_bubble = self._force_bubble or bubble
        if not self._pending:
            self._pending = True
            self.root.after_idle(self.flush)

    def flush(self):
        self._pending = False
        t = self.t
        if t.hidden or self.covered:
            return
        g = self.origin()
        w, h = self.pet_size
        self.pet.draw(g.x + t.bx - self.M, g.y + t.by - self.MTOP, w, h, lambda cr: t.paint_pet(cr, self.M, self.MTOP))
        self.update_bubble(self._force_bubble)
        self._force_bubble = False
        if t.feeding:
            self.draw_baguette()
        else:
            self.bag.hide()

    def update_bubble(self, force=True):
        t = self.t
        if not (t.text or t.menu) or t.phase == "fly":
            self.bub.hide()
            self.bubble_geom = None
            self._bsize = None
            return
        if force or self._bsize is None:             # text measured only when the text changed
            self._bsize = t.bubble_size(None)
        bw, bh = self._bsize
        w, _ = self.area()
        frac = 0.78 if t.cfg["side"] == "right" else 0.22
        x = max(8, min(w - bw - 8, t.bx + t.bw / 2 - bw * frac))
        below = t.by < bh + 60
        y = t.by + t.bh + 14 if below else t.by + t.bob() - bh - 16
        pad = 12
        geom = (x, y, bw, bh, below, pad)
        if geom == self.bubble_geom and not force and self.bub.visible:
            return
        self.bubble_geom = geom
        g = self.origin()
        self.bub.draw(g.x + x - pad, g.y + y - pad, int(bw + 2 * pad), int(bh + 2 * pad),
                      lambda cr: t.paint_bubble(cr, pad, pad, bw, bh, pad + (t.bx + t.bw / 2 - x), below))

    def bub_press(self, e):
        if self.t.menu and self.bubble_geom:
            pad = self.bubble_geom[5]
            self.t.menu_press(e.x, e.y, pad, pad)
        else:
            self.t.quiet()

    def bub_motion(self, e):
        if self.t.vol_drag and self.bubble_geom:
            self.t.menu_move(e.x, self.bubble_geom[5])
        elif self.t.menu and self.bubble_geom:
            pad = self.bubble_geom[5]
            i = self.t.menu_row_at(e.x, e.y, pad, pad)
            if i != self.t.menu_hover:
                self.t.menu_hover = i
                self.changed(bubble=True)

    # --- feeding: the baguette follows the real pointer, a click anywhere takes it away ------------------------
    def feed_begin(self):
        self._was_down = True                       # the click that chose "Feed" may still be down
        self.root.after(30, self.poll_click)

    def feed_end(self):
        self.bag.hide()

    def poll_click(self):
        if not self.t.feeding:
            return
        u = user32()
        down = bool((u.GetAsyncKeyState(1) | u.GetAsyncKeyState(2)) & 0x8000)
        if down and not self._was_down:
            self.t.press(*self.t.cursor, 1)
        self._was_down = down
        self.root.after(30, self.poll_click)

    def draw_baguette(self):
        t = self.t
        g = self.origin()
        cx, cy = t.cursor
        length = 22 * t.px
        w, h = int(2 * length + 60), int(length + 100)
        tipx, tipy = w // 2, int(h * 0.7)
        self.bag.draw(g.x + cx - tipx, g.y + cy - tipy, w, h, lambda cr: t.paint_baguette(cr, tipx, tipy, cx))

    # --- housekeeping -----------------------------------------------------------------------------------------
    def keep_on_top(self):
        if not self.t.hidden and not self.covered:
            for layer in (self.pet, self.bub, self.bag):
                layer.front()
        return True

    def watch_fullscreen(self):
        """Step aside while something is fullscreen (a video, a game)."""
        try:
            full = fullscreen_in_front()
        except Exception:
            full = False
        if full != self.covered:
            self.covered = full
            if not self.t.hidden:
                if full:
                    for layer in (self.pet, self.bub, self.bag):
                        layer.hide()
                else:
                    self.changed(bubble=True)
        return True


# --- music: Windows' own media session (what the volume flyout shows) --------------------------------------
def start_media_watch(callback):
    """callback(status, artist, title) from a background thread, with MPRIS-style statuses
    ("Playing" / "Paused" / "Stopped"). Needs the winrt-* packages; silent without them."""
    import threading

    def run():
        try:
            import asyncio
            from winrt.windows.media.control import (
                GlobalSystemMediaTransportControlsSessionManager as Manager,
                GlobalSystemMediaTransportControlsSessionPlaybackStatus as Status)
        except Exception:
            traceback.print_exc()
            return

        async def watch():
            mgr = await Manager.request_async()
            last = None
            while True:
                try:
                    pick = None
                    for s in mgr.get_sessions():
                        if s.get_playback_info().playback_status == Status.PLAYING:
                            pick = s
                            break
                    pick = pick or mgr.get_current_session()
                    if pick is None:
                        state = ("Stopped", "", "")
                    else:
                        playing = pick.get_playback_info().playback_status == Status.PLAYING
                        props = await pick.try_get_media_properties_async()
                        state = ("Playing" if playing else "Paused", props.artist or "", props.title or "")
                    if state != last:
                        last = state
                        callback(*state)
                except Exception:
                    traceback.print_exc()
                await asyncio.sleep(2)

        try:
            asyncio.run(watch())
        except Exception:
            traceback.print_exc()

    threading.Thread(target=run, daemon=True).start()
