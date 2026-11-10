"""Play a WAV file at transitions with what the OS already ships with.

``winsound`` on Windows, ``afplay`` on macOS and ``paplay`` or ``aplay`` on
Linux. Sound is played in the background, so the countdown never waits for
it (except the very last sound on Windows, see ``system_player``). A player
reports whether it managed to start, so the timer can fall back to the
terminal bell when it did not.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Optional

Player = Callable[[bool], bool]

# Linux players in order of preference: PulseAudio/PipeWire first, then ALSA.
_LINUX_PLAYERS = (("paplay", ()), ("aplay", ("-q",)))


class SoundError(ValueError):
    """The sound file is missing, unreadable or not a WAV file."""


def check_wav(path: Path) -> Path:
    """Return ``path`` if it is a readable RIFF/WAVE file, else raise SoundError."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(12)
    except FileNotFoundError:
        raise SoundError(f"sound file not found: {path}") from None
    except IsADirectoryError:
        raise SoundError(f"sound file is a directory: {path}") from None
    except OSError as exc:
        raise SoundError(f"cannot read sound file {path}: {exc.strerror or exc}") from None
    if len(head) < 12 or head[:4] != b"RIFF" or head[8:12] != b"WAVE":
        raise SoundError(f"not a WAV file: {path} (only RIFF/WAVE files are supported)")
    return path


def player_command(
    path: Path,
    platform: Optional[str] = None,
    which: Callable[[str], Optional[str]] = shutil.which,
) -> Optional[list[str]]:
    """The argv that plays ``path`` on macOS/Linux, or None if no player is installed.

    Windows uses ``winsound`` instead and has no command.
    """
    platform = sys.platform if platform is None else platform
    if platform.startswith("win"):
        return None
    if platform == "darwin":
        exe = which("afplay")
        return [exe, str(path)] if exe else None
    for name, flags in _LINUX_PLAYERS:
        exe = which(name)
        if exe:
            return [exe, *flags, str(path)]
    return None


def player_name(platform: Optional[str] = None) -> str:
    """What the README and warnings call the player on this platform."""
    platform = sys.platform if platform is None else platform
    if platform.startswith("win"):
        return "winsound"
    if platform == "darwin":
        return "afplay"
    return "paplay or aplay"


def system_player(
    path: Path,
    platform: Optional[str] = None,
    which: Callable[[str], Optional[str]] = shutil.which,
    popen: Callable[..., object] = subprocess.Popen,
    winsound: Any = None,
) -> Optional[Player]:
    """A function that starts playing ``path``, or None when nothing can play it.

    The returned function takes ``wait``: True for the last transition, so
    ``winsound`` (whose asynchronous sound dies with the process) finishes the
    sound before focusbell exits. It returns True if playback started and
    False if it failed (the caller then rings the bell instead). It never
    raises.
    """
    platform = sys.platform if platform is None else platform
    if platform.startswith("win"):
        if winsound is None:
            try:
                import winsound as _winsound  # type: ignore[import-not-found]
            except ImportError:
                return None
            winsound = _winsound
        flags = winsound.SND_FILENAME | winsound.SND_NODEFAULT

        def play_windows(wait: bool = False) -> bool:
            try:
                winsound.PlaySound(str(path), flags if wait else flags | winsound.SND_ASYNC)
                return True
            except Exception:  # noqa: BLE001 - sound is best effort
                return False

        return play_windows

    argv = player_command(path, platform, which)
    if argv is None:
        return None

    def play(wait: bool = False) -> bool:  # the child outlives us; no need to wait
        try:
            popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                  stderr=subprocess.DEVNULL)
            return True
        except Exception:  # noqa: BLE001 - sound is best effort
            return False

    return play
