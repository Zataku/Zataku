"""Menu sound effects in the style of Among Us, generated in code (no audio files needed).

    play("click")     short rising blip, for button presses
    play("start")     two-step rising chirp, when a sort or preview begins
    play("complete")  bright four-note "task complete" chime

Sounds are written once to a temp folder as .wav files and played without
blocking. Only Windows has sound (winsound); elsewhere play() does nothing.
"""
import math
import struct
import tempfile
import threading
import wave
from pathlib import Path

try:
    import winsound
except ImportError:  # macOS / Linux
    winsound = None

RATE = 22050
BELL = ((1, 1.0), (2, 0.4), (3.01, 0.15))   # (multiple of the note, loudness) overtones
SOFT = ((1, 1.0), (2, 0.15))


def note(freq, secs, glide_to=None, decay=8.0, overtones=SOFT):
    """One note as floats: a quick fade-in, then dying away; optionally sliding in pitch."""
    samples, phase, n = [], 0.0, int(RATE * secs)
    for i in range(n):
        t = i / RATE
        f = freq if glide_to is None else freq + (glide_to - freq) * i / n
        phase += 2 * math.pi * f / RATE
        envelope = min(1.0, t / 0.004) * math.exp(-decay * t)
        samples.append(envelope * sum(level * math.sin(k * phase) for k, level in overtones))
    return samples


def mix(*parts):
    """Overlay (start_secs, samples) parts into one sound."""
    out = [0.0] * max(int(at * RATE) + len(s) for at, s in parts)
    for at, s in parts:
        start = int(at * RATE)
        for i, v in enumerate(s):
            out[start + i] += v
    return out


SOUNDS = {
    "click": lambda: mix((0, note(700, 0.07, glide_to=1150, decay=35))),
    "start": lambda: mix((0, note(520, 0.12, glide_to=780, decay=12)),
                         (0.09, note(780, 0.2, glide_to=1170, decay=10))),
    "complete": lambda: mix((0.00, note(1047, 0.25, decay=9, overtones=BELL)),    # C
                            (0.09, note(1319, 0.25, decay=9, overtones=BELL)),    # E
                            (0.18, note(1568, 0.25, decay=9, overtones=BELL)),    # G
                            (0.27, note(2093, 0.6, decay=5, overtones=BELL))),    # high C
}

# Bump the version when the sounds above change, so old copies aren't reused.
_folder = Path(tempfile.gettempdir()) / "image-sorter-sounds-v1"


def _path(name):
    path = _folder / f"{name}.wav"
    if not path.exists():
        samples = SOUNDS[name]()
        peak = max(abs(v) for v in samples) or 1.0
        _folder.mkdir(exist_ok=True)
        # Write under a temporary name first: prepare() may be writing the same sound
        # on another thread, and a half-written file must never be played.
        tmp = path.with_name(f"{name}.{threading.get_ident()}.tmp")
        with wave.open(str(tmp), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(RATE)
            w.writeframes(b"".join(struct.pack("<h", int(v / peak * 0.8 * 32767)) for v in samples))
        tmp.replace(path)
    return path


def prepare():
    """Write all the sounds ahead of time, so the first click isn't delayed."""
    if winsound:
        for name in SOUNDS:
            _path(name)


def play(name):
    if winsound:
        try:
            winsound.PlaySound(str(_path(name)),
                               winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
        except (OSError, RuntimeError):
            pass  # no sound device; carry on silently
