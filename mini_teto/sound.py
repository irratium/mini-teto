"""Mini Teto's sounds, synthesised in plain Python (no numpy) and mixed into one
long-lived raw audio stream: pw-cat, pacat or aplay, whichever is there.

One stream instead of a player per sound: a chirp per letter would otherwise
open and drop a stream several times a second, which screen sharing and
mixers choke on. The stream closes after half a minute of quiet."""

import math
from array import array
import queue
import random
import shutil
import struct
import subprocess
import sys
import threading
import time

try:
    import fcntl
except ImportError:           # not Linux: no pipe tuning
    fcntl = None

RATE = 24000
BLOCK = 240                # 10 ms
IDLE_CLOSE = 12.0
NOTES = {"C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5, "F#": 6, "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11}


def note_hz(name):
    octave = int(name[-1])
    return 440.0 * 2 ** ((NOTES[name[:-1]] + (octave - 4) * 12 - 9) / 12)


def n(sec):
    return int(RATE * sec)


def envelope(length, attack, release):
    a, r = max(1, n(attack)), max(1, n(release))
    out = [1.0] * length
    for i in range(min(a, length)):
        out[i] = i / a
    for i in range(min(r, length)):
        out[length - 1 - i] *= i / r
    return out


def lowpass(xs, a):
    y, acc = [], 0.0
    for v in xs:
        acc += a * (v - acc)
        y.append(acc)
    return y


def sweep(f0, f1, sec, shape="sine"):
    count = n(sec)
    out, ph = [], 0.0
    for i in range(count):
        f = f0 + (f1 - f0) * i / max(1, count - 1)
        ph += 2 * math.pi * f / RATE
        s = math.sin(ph)
        out.append((1.0 if s >= 0 else -1.0) * 0.6 if shape == "square" else s)
    return out


def noise(sec):
    return [random.uniform(-1, 1) for _ in range(n(sec))]


def bell(freq, sec, decay=6.0):
    out = []
    for i in range(n(sec)):
        t = i / RATE
        out.append((math.sin(2 * math.pi * freq * t) + 0.35 * math.sin(2 * math.pi * freq * 2.01 * t)) * math.exp(-decay * t) * 0.55)
    return out


def mixin(dst, src, at, gain=1.0):
    for i, v in enumerate(src):
        j = at + i
        if j < len(dst):
            dst[j] += v * gain


def scale(xs, k):
    return [v * k for v in xs]


def make(name, pitch=1.0):
    if name == "blip":
        f = 520 * pitch
        x = lowpass(sweep(f * 1.08, f * 0.94, 0.045, "square"), 0.35)
        e = envelope(len(x), 0.002, 0.02)
        return [a * b * 0.55 for a, b in zip(x, e)]
    if name == "pop":
        x = sweep(900 * pitch, 320 * pitch, 0.06)
        return [a * b * 0.5 for a, b in zip(x, envelope(len(x), 0.001, 0.04))]
    if name == "boing":
        out, ph = [], 0.0
        for i in range(n(0.42)):
            t = i / RATE
            f = 220 + 260 * abs(math.sin(2 * math.pi * 2.6 * t)) * math.exp(-3 * t)
            ph += 2 * math.pi * f / RATE
            out.append(math.sin(ph) * math.exp(-4 * t) * 0.6)
        return out
    if name == "crunch":
        out = [0.0] * n(0.28)
        for k in range(5):
            burst = lowpass(noise(0.035), 0.55)
            e = envelope(len(burst), 0.001, 0.03)
            mixin(out, [a * b for a, b in zip(burst, e)], n(0.02 + k * 0.05 + random.uniform(0, 0.01)), 0.7 - k * 0.1)
        return scale(out, 0.6)
    if name == "jingle":
        out = [0.0] * n(0.9)
        for i, note in enumerate(["C6", "E6", "G6", "C7"]):
            mixin(out, bell(note_hz(note), 0.5, 7), n(0.09 * i), 0.8)
        return out
    if name == "chime":
        out = [0.0] * n(0.68)
        mixin(out, bell(1318.5, 0.5), 0)
        mixin(out, bell(1975.5, 0.55), n(0.11))
        return scale(out, 0.7)
    if name == "open":
        x = sweep(380, 980, 0.14)
        return [a * b * 0.4 for a, b in zip(x, envelope(len(x), 0.01, 0.08))]
    return None


def voice(freq, sec):
    """A sung "la": a buzzy tone with vibrato through a soft low-pass."""
    count = n(sec)
    out, ph = [], 0.0
    e = envelope(count, 0.03, min(0.12, sec / 3))
    acc = acc2 = 0.0
    for i in range(count):
        t = i / RATE
        vib = 1 + 0.012 * math.sin(2 * math.pi * 5.5 * t) * min(1.0, t / 0.15)
        ph += freq * vib / RATE
        saw = 2 * (ph % 1.0) - 1
        acc += 0.18 * (saw - acc)
        acc2 += 0.5 * (saw - acc2)
        onset = min(1.0, max(0.3, t / 0.04))
        out.append((acc * 0.7 + acc2 * 0.25) * e[i] * onset * 0.55)
    return out


def sing(score):
    out = []
    for item in score.split():
        note, _, ms = item.partition(":")
        sec = max(0.05, int(ms or 250) / 1000)
        out += [0.0] * n(sec) if note == "-" else voice(note_hz(note), sec)
    return out


def candidates():
    out = []
    if shutil.which("pw-cat"):
        out.append(["pw-cat", "--playback", "--raw", "--format", "s16", "--rate", str(RATE), "--channels", "1",
                    "-P", "{ media.name = \"mini Teto\" node.name = \"mini-teto\" }", "-"])
    if shutil.which("pacat"):
        out.append(["pacat", "--playback", "--raw", "--format=s16le", f"--rate={RATE}", "--channels=1",
                    "--client-name=mini Teto", "--stream-name=mini Teto", "--latency-msec=40"])
    if shutil.which("aplay"):
        out.append(["aplay", "-q", "-t", "raw", "-f", "S16_LE", "-r", str(RATE), "-c", "1"])
    return out


class WinStream:
    """Looks like the player process the mixer loop expects, but plays through sounddevice (PortAudio)."""

    def __init__(self):
        import sounddevice as sd
        self.s = sd.RawOutputStream(samplerate=RATE, channels=1, dtype="int16", latency="low")
        self.s.start()
        self.stdin = self

    def write(self, data):
        self.s.write(data)

    def flush(self):
        pass

    def close(self):
        try:
            self.s.stop()
            self.s.close()
        except Exception:
            pass

    def poll(self):
        return None if self.s.active else 1

    def wait(self, timeout=None):
        pass

    def kill(self):
        self.close()


def player_command():
    """The first player that accepts a moment of silence."""
    if sys.platform == "win32":
        try:
            import sounddevice as sd
            sd.query_devices(kind="output")
            return "winaudio"
        except Exception:
            return None
    silence = b"\0" * (RATE // 50 * 2)
    for cmd in candidates():
        try:
            r = subprocess.run(cmd, input=silence, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=4)
            if r.returncode == 0:
                return cmd
        except (OSError, subprocess.TimeoutExpired):
            continue
    return None


class Sound:
    """play(name, volume, pitch) and sing(score, volume) from any thread."""

    def __init__(self):
        self.q = queue.Queue()
        self.cache = {}
        self.cmd = None
        self.enabled = True          # until the probe finds no player
        threading.Thread(target=self._start, daemon=True).start()

    def _start(self):
        self.cmd = player_command()
        if self.cmd is None:
            self.enabled = False
            return
        self._run()

    def play(self, name, volume=0.6, pitch=1.0):
        if self.enabled and volume > 0:
            self.q.put(("fx", name, volume, pitch))

    def sing(self, score, volume=0.6):
        if self.enabled and volume > 0:
            self.q.put(("sing", score, volume, 1.0))

    def _render(self, kind, what, pitch):
        if kind == "sing":
            return sing(what)
        key = (what, round(pitch, 2))
        if what in ("crunch",):
            return make(what, pitch)
        if key not in self.cache:
            made = make(what, pitch)
            self.cache[key] = array("f", made) if made else made
        return self.cache[key]

    failures = 0

    def _open(self, old):
        self._close(old)
        if self.failures > 5:          # the player keeps dying: give up quietly
            self.enabled = False
            return None
        if self.cmd == "winaudio":
            try:
                return WinStream()
            except Exception:
                self.failures += 1
                return None
        try:
            proc = subprocess.Popen(self.cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            self.failures += 1
            return None
        if fcntl is not None:
            try:                       # F_SETPIPE_SZ: a small pipe, so a cut-off song really stops
                fcntl.fcntl(proc.stdin.fileno(), 1031, 4096)
            except (OSError, ValueError, AttributeError):
                pass
        return proc

    @staticmethod
    def _close(proc):
        if proc is None:
            return
        try:
            proc.stdin.close()
        except (BrokenPipeError, OSError):
            pass
        try:
            proc.wait(timeout=1)
        except Exception:
            proc.kill()

    def _run(self):
        proc, last = None, 0.0
        voices = []
        while True:
            try:
                item = self.q.get(timeout=0 if voices else 1.0)
                while True:
                    kind, what, vol, pitch = item
                    samples = self._render(kind, what, pitch)
                    if kind == "sing":         # a new song cuts off the one still going
                        voices = [v for v in voices if v[3] != "sing"]
                    if samples:
                        voices.append([samples, 0, vol, kind])
                    item = self.q.get_nowait()
            except queue.Empty:
                pass
            if not voices:
                if proc and time.monotonic() - last > IDLE_CLOSE:
                    self._close(proc)
                    proc = None
                continue
            if proc is None or proc.poll() is not None:
                proc = self._open(proc)
                if proc is None:
                    voices = []
                    continue
            block = [0.0] * BLOCK
            for v in voices:
                s, pos, vol, _ = v
                chunk = s[pos:pos + BLOCK]
                for i, x in enumerate(chunk):
                    block[i] += x * vol
                v[1] += BLOCK
            voices = [v for v in voices if v[1] < len(v[0])]
            data = struct.pack("<%dh" % BLOCK, *(max(-32767, min(32767, int(x * 32767))) for x in block))
            try:
                proc.stdin.write(data)
                proc.stdin.flush()
                last = time.monotonic()
            except (BrokenPipeError, OSError):
                self._close(proc)
                proc = None
                voices = []