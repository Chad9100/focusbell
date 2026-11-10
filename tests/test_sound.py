import io
import struct
import subprocess
from datetime import datetime, timezone

import pytest

from focusbell import config, sound, timer
from focusbell.cli import main
from focusbell.timer import build_schedule

SHORT_RUN = ("start", "--seconds", "--work", "1", "--short", "1", "--long", "1", "--cycles", "1")


def make_wav(path):
    """A tiny valid 8 kHz mono 8-bit WAV (silence)."""
    data = b"\x80" * 80
    fmt = struct.pack("<HHIIHH", 1, 1, 8000, 8000, 1, 8)
    body = b"WAVE" + b"fmt " + struct.pack("<I", len(fmt)) + fmt
    body += b"data" + struct.pack("<I", len(data)) + data
    path.write_bytes(b"RIFF" + struct.pack("<I", len(body)) + body)
    return path


def which_from(tools):
    return lambda name: tools.get(name)


class Clock:
    def __init__(self):
        self.t = 1_793_000_000.0

    def __call__(self):
        return self.t

    def sleep(self, seconds):
        self.t += seconds


class FakePlayer:
    """Stands in for ``system_player``: records the file and every play."""

    def __init__(self, works=True, available=True):
        self.works = works
        self.available = available
        self.paths = []
        self.plays = []

    def __call__(self, path):
        self.paths.append(path)
        if not self.available:
            return None

        def play(last):
            self.plays.append(last)
            return self.works

        return play


def run_cli(home, *argv, player=None):
    out, err = io.StringIO(), io.StringIO()
    clk = Clock()
    code = main(
        list(argv),
        stdout=out,
        stderr=err,
        environ={"FOCUSBELL_HOME": str(home)},
        clock=clk,
        sleep=clk.sleep,
        now=lambda: datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc),
        tz=timezone.utc,
        notifier=lambda: None,
        player=player or FakePlayer(),
    )
    return code, out.getvalue(), err.getvalue()


# ------------------------------------------------------------ check_wav


def test_check_wav_accepts_riff_wave(tmp_path):
    wav = make_wav(tmp_path / "ding.wav")
    assert sound.check_wav(wav) == wav


@pytest.mark.parametrize("content", [b"", b"RIFF", b"ID3\x03" + b"\0" * 20,
                                     b"RIFF\0\0\0\0AVI LIST"])
def test_check_wav_rejects_other_files(tmp_path, content):
    path = tmp_path / "ding.wav"
    path.write_bytes(content)
    with pytest.raises(sound.SoundError, match="not a WAV file"):
        sound.check_wav(path)


def test_check_wav_missing_file_and_directory(tmp_path):
    with pytest.raises(sound.SoundError, match="not found"):
        sound.check_wav(tmp_path / "nope.wav")
    with pytest.raises(sound.SoundError):
        sound.check_wav(tmp_path)


# ------------------------------------------------------------ players per OS


def test_macos_uses_afplay(tmp_path):
    argv = sound.player_command(tmp_path / "a b.wav", "darwin", which_from({"afplay": "/usr/bin/afplay"}))
    assert argv == ["/usr/bin/afplay", str(tmp_path / "a b.wav")]


def test_linux_prefers_paplay_then_aplay(tmp_path):
    wav = tmp_path / "x.wav"
    both = {"paplay": "/usr/bin/paplay", "aplay": "/usr/bin/aplay"}
    assert sound.player_command(wav, "linux", which_from(both)) == ["/usr/bin/paplay", str(wav)]
    only_alsa = {"aplay": "/usr/bin/aplay"}
    assert sound.player_command(wav, "linux", which_from(only_alsa)) == ["/usr/bin/aplay", "-q", str(wav)]


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_no_player_installed(tmp_path, platform):
    assert sound.player_command(tmp_path / "x.wav", platform, which_from({})) is None
    assert sound.system_player(tmp_path / "x.wav", platform, which_from({})) is None


def test_posix_player_starts_process_without_waiting(tmp_path):
    calls = []

    def popen(argv, **kwargs):
        calls.append((argv, kwargs))

    play = sound.system_player(tmp_path / "x.wav", "linux", which_from({"aplay": "/a"}), popen)
    assert play(False) is True and play(True) is True
    assert calls[0][0] == ["/a", "-q", str(tmp_path / "x.wav")]
    assert calls[0][1]["stdout"] is subprocess.DEVNULL


def test_posix_player_reports_launch_failure(tmp_path):
    def popen(argv, **kwargs):
        raise OSError("gone")

    play = sound.system_player(tmp_path / "x.wav", "darwin", which_from({"afplay": "/f"}), popen)
    assert play(False) is False


class FakeWinsound:
    SND_FILENAME = 0x20000
    SND_ASYNC = 0x1
    SND_NODEFAULT = 0x2

    def __init__(self, fail=False):
        self.fail = fail
        self.calls = []

    def PlaySound(self, name, flags):  # noqa: N802 - mirrors winsound
        if self.fail:
            raise RuntimeError("Failed to play sound")
        self.calls.append((name, flags))


def test_windows_plays_async_except_the_last_sound(tmp_path):
    ws = FakeWinsound()
    play = sound.system_player(tmp_path / "x.wav", "win32", winsound=ws)
    assert play(False) is True
    assert play(True) is True
    (name, first), (_, last) = ws.calls
    assert name == str(tmp_path / "x.wav")
    assert first & ws.SND_ASYNC and first & ws.SND_FILENAME and first & ws.SND_NODEFAULT
    assert not last & ws.SND_ASYNC  # must finish before the process exits


def test_windows_play_failure_returns_false(tmp_path):
    play = sound.system_player(tmp_path / "x.wav", "win32", winsound=FakeWinsound(fail=True))
    assert play(False) is False


# ------------------------------------------------------------ timer


def run_timer(**kwargs):
    clk = Clock()
    out = io.StringIO()
    result = timer.run(build_schedule(2, 1, 1, 2, 1), clock=clk, sleep=clk.sleep, out=out,
                       tty=False, **kwargs)
    return result, out.getvalue()


def test_timer_plays_sound_instead_of_bell():
    plays = []
    _, out = run_timer(sound=lambda last: plays.append(last) or True)
    assert plays == [False, False, False, True]  # 4 transitions, the last flagged
    assert "\a" not in out


@pytest.mark.parametrize("player", [lambda last: False,
                                    lambda last: (_ for _ in ()).throw(RuntimeError("x"))])
def test_timer_falls_back_to_bell(player):
    result, out = run_timer(sound=player)
    assert out.count("\a") == 4
    assert result.completed == 2


def test_timer_no_bell_plays_nothing():
    plays = []
    _, out = run_timer(sound=lambda last: plays.append(last) or True, bell=False)
    assert plays == [] and "\a" not in out


# ------------------------------------------------------------ config and CLI


def test_sound_config_key_is_a_path_defaulting_empty():
    assert config.DEFAULTS["sound"] == ""
    assert config.validate("sound", "  ~/ding.wav ") == "~/ding.wav"
    with pytest.raises(config.ConfigError, match="sound must be a single-line path"):
        config.validate("sound", "a\nb")


def test_cli_sound_flag_plays_file(tmp_path):
    wav = make_wav(tmp_path / "ding.wav")
    player = FakePlayer()
    code, out, err = run_cli(tmp_path / "home", *SHORT_RUN, "--sound", str(wav), player=player)
    assert code == 0, err
    assert player.paths == [wav]
    assert player.plays == [False, True]
    assert "\a" not in out and err == ""


def test_cli_without_sound_never_builds_player(tmp_path):
    player = FakePlayer()
    code, out, _ = run_cli(tmp_path / "home", *SHORT_RUN, player=player)
    assert code == 0
    assert player.paths == [] and out.count("\a") == 2


def test_cli_bad_sound_flag_is_a_usage_error(tmp_path):
    bad = tmp_path / "song.mp3"
    bad.write_bytes(b"ID3\x04" + b"\0" * 40)
    code, out, err = run_cli(tmp_path / "home", *SHORT_RUN, "--sound", str(bad))
    assert code == 2
    assert "not a WAV file" in err
    assert "Work 1/1" not in out  # refused before the timer starts
    code, _, err = run_cli(tmp_path / "home", *SHORT_RUN, "--sound", str(tmp_path / "gone.wav"))
    assert code == 2 and "sound file not found" in err


def test_cli_sound_from_config_and_no_sound_override(tmp_path):
    home = tmp_path / "home"
    wav = make_wav(tmp_path / "ding.wav")
    assert run_cli(home, "config", "set", "sound", str(wav))[0] == 0
    player = FakePlayer()
    run_cli(home, *SHORT_RUN, player=player)
    assert len(player.plays) == 2
    player = FakePlayer()
    _, out, _ = run_cli(home, *SHORT_RUN, "--no-sound", player=player)
    assert player.paths == [] and out.count("\a") == 2


def test_cli_missing_configured_sound_warns_and_rings_bell(tmp_path):
    home = tmp_path / "home"
    assert run_cli(home, "config", "set", "sound", str(tmp_path / "moved.wav"))[0] == 0
    code, out, err = run_cli(home, *SHORT_RUN)
    assert code == 0
    assert "sound file not found" in err and "using the terminal bell" in err
    assert out.count("\a") == 2


def test_cli_no_player_available_warns_and_rings_bell(tmp_path):
    wav = make_wav(tmp_path / "ding.wav")
    code, out, err = run_cli(tmp_path / "home", *SHORT_RUN, "--sound", str(wav),
                             player=FakePlayer(available=False))
    assert code == 0
    assert "no WAV player found" in err
    assert out.count("\a") == 2


def test_cli_failing_player_falls_back_to_bell(tmp_path):
    wav = make_wav(tmp_path / "ding.wav")
    _, out, err = run_cli(tmp_path / "home", *SHORT_RUN, "--sound", str(wav),
                          player=FakePlayer(works=False))
    assert out.count("\a") == 2 and err == ""


def test_cli_sound_with_no_bell_warns_and_stays_silent(tmp_path):
    wav = make_wav(tmp_path / "ding.wav")
    player = FakePlayer()
    code, out, err = run_cli(tmp_path / "home", *SHORT_RUN, "--sound", str(wav), "--no-bell",
                             player=player)
    assert code == 0
    assert "--sound has no effect" in err
    assert player.paths == [] and "\a" not in out


def test_cli_sound_and_no_sound_are_exclusive(tmp_path, capsys):
    code, _, _ = run_cli(tmp_path / "home", *SHORT_RUN, "--sound", "x.wav", "--no-sound")
    assert code == 2
