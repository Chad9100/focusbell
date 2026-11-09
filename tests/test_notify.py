import io
import subprocess

import pytest

from focusbell import config, notify, timer
from focusbell.timer import build_schedule

ALL_TOOLS = {
    "powershell": r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
    "osascript": "/usr/bin/osascript",
    "notify-send": "/usr/bin/notify-send",
}


def which_from(tools):
    return lambda name: tools.get(name)


class Clock:
    def __init__(self):
        self.t = 1_793_000_000.0

    def __call__(self):
        return self.t

    def sleep(self, seconds):
        self.t += seconds


# ------------------------------------------------------------ commands per OS


def test_linux_uses_notify_send_with_separator():
    argv, env = notify.notifier_command("focusbell", "-rf done", "linux", which_from(ALL_TOOLS))
    assert argv == ["/usr/bin/notify-send", "--app-name=focusbell", "--", "focusbell", "-rf done"]
    assert env == {}


def test_macos_passes_text_as_osascript_arguments():
    argv, env = notify.notifier_command('a "quoted" title', "msg", "darwin", which_from(ALL_TOOLS))
    assert argv[0] == "/usr/bin/osascript"
    assert argv[-2:] == ['a "quoted" title', "msg"]
    script = " ".join(argv[1:-2])
    assert "quoted" not in script  # user text is never spliced into AppleScript
    assert env == {}


def test_windows_passes_text_through_environment():
    argv, env = notify.notifier_command("focusbell: it's", "Back to work.", "win32",
                                        which_from(ALL_TOOLS))
    assert argv[0].endswith("powershell.exe")
    assert "-NoProfile" in argv and "-Command" in argv
    script = argv[-1]
    assert "it's" not in script and "Back to work." not in script
    assert "ToastNotificationManager" in script
    assert env == {"FOCUSBELL_NOTIFY_TITLE": "focusbell: it's",
                   "FOCUSBELL_NOTIFY_MESSAGE": "Back to work."}


def test_windows_falls_back_to_pwsh():
    argv, _ = notify.notifier_command("t", "m", "win32", which_from({"pwsh": "C:/pwsh.exe"}))
    assert argv[0] == "C:/pwsh.exe"


@pytest.mark.parametrize("platform", ["linux", "darwin", "win32", "freebsd13"])
def test_no_tool_means_no_command(platform):
    assert notify.notifier_command("t", "m", platform, which_from({})) is None
    assert notify.system_notifier(platform, which_from({})) is None


# ------------------------------------------------------------ system_notifier


def test_system_notifier_starts_process_without_waiting():
    calls = []

    def popen(argv, **kwargs):
        calls.append((argv, kwargs))

    send = notify.system_notifier("win32", which_from(ALL_TOOLS), popen, environ={"PATH": "x"})
    send("focusbell", "Work block 1 done. Short break next.")
    (argv, kwargs), = calls
    assert argv[0].endswith("powershell.exe")
    assert kwargs["stdout"] is subprocess.DEVNULL and kwargs["stderr"] is subprocess.DEVNULL
    assert kwargs["env"]["PATH"] == "x"
    assert kwargs["env"]["FOCUSBELL_NOTIFY_MESSAGE"] == "Work block 1 done. Short break next."


def test_system_notifier_swallows_launch_errors():
    def popen(argv, **kwargs):
        raise FileNotFoundError(argv[0])

    send = notify.system_notifier("linux", which_from(ALL_TOOLS), popen, environ={})
    send("t", "m")  # must not raise


# ------------------------------------------------------------ timer hook


def run_timer(**kw):
    clock = Clock()
    out = io.StringIO()
    result = timer.run(build_schedule(3, 1, 2, cycles=2), clock=clock, sleep=clock.sleep,
                       out=out, tty=False, bell=False, **kw)
    return result, out.getvalue()


def test_timer_notifies_at_every_transition_with_the_printed_message():
    seen = []
    _, out = run_timer(notify=lambda title, msg: seen.append((title, msg)), label="thesis")
    assert [msg for _, msg in seen] == [
        "Work block 1 done. Short break next.",
        "Short break over. Back to work.",
        "Work block 2 done. Long break next.",
        "All done. Nice work.",
    ]
    assert {title for title, _ in seen} == {"focusbell: thesis"}
    for _, msg in seen:
        assert msg in out


def test_timer_title_without_label():
    seen = []
    run_timer(notify=lambda title, msg: seen.append(title))
    assert set(seen) == {"focusbell"}


def test_failing_notifier_does_not_stop_the_timer():
    def boom(title, msg):
        raise RuntimeError("no display")

    result, _ = run_timer(notify=boom)
    assert result.completed == 2 and not result.interrupted


# ------------------------------------------------------------ config and CLI


def test_notify_config_key_is_a_boolean_defaulting_off():
    assert config.DEFAULTS["notify"] is False
    assert config.validate("notify", "on") is True
    with pytest.raises(config.ConfigError, match="notify must be true or false"):
        config.validate("notify", "sometimes")


SHORT_RUN = ("start", "--seconds", "--work", "1", "--short", "1", "--long", "1", "--cycles", "1")


def recorder():
    seen = []
    factory_calls = []

    def factory():
        factory_calls.append(1)
        return lambda title, msg: seen.append(msg)

    return factory, seen, factory_calls


def test_cli_does_not_notify_by_default(run):
    factory, seen, made = recorder()
    assert run(*SHORT_RUN, notifier=factory)[0] == 0
    assert seen == [] and made == []


def test_cli_notify_flag_sends_notifications(run):
    factory, seen, _ = recorder()
    code, _, err = run(*SHORT_RUN, "--notify", notifier=factory)
    assert code == 0, err
    assert seen == ["Work block 1 done. Long break next.", "All done. Nice work."]


def test_cli_notify_config_and_no_notify_override(run):
    assert run("config", "set", "notify", "true")[0] == 0
    factory, seen, _ = recorder()
    run(*SHORT_RUN, notifier=factory)
    assert len(seen) == 2
    factory, seen, made = recorder()
    run(*SHORT_RUN, "--no-notify", notifier=factory)
    assert seen == [] and made == []


def test_cli_notify_without_any_tool_is_silent(run):
    code, out, err = run(*SHORT_RUN, "--notify", notifier=lambda: None)
    assert code == 0
    assert err == ""
    assert "All done. Nice work." in out
