import io
import json
import os
import subprocess
import sys
from datetime import timedelta, timezone

import pytest

from conftest import TTY, FakeClock, rec, write_log
from focusbell.log import read_sessions


def logged(home):
    return read_sessions(home / "sessions.jsonl")


DEMO = [
    rec("2026-11-09T09:00:00+00:00", 25, "thesis"),
    rec("2026-11-09T10:00:00+00:00", 12, "thesis", "interrupted"),
    rec("2026-11-08T09:00:00+00:00", 25, "email"),
    rec("2026-11-07T09:00:00+00:00", 50, "code"),
    rec("2026-11-01T09:00:00+00:00", 25, "old"),
]


# ------------------------------------------------------------ start


def test_start_seconds_mode_runs_and_logs(run, isolated_home):
    code, out, err = run("start", "--seconds", "--work", "3", "--short", "1", "--long", "2", "--cycles", "2")
    assert code == 0, err
    assert "2 x 3s work" in out
    assert "Focused 6s: 2 of 2 work block(s) completed." in out
    sessions = logged(isolated_home)
    assert [s.status for s in sessions] == ["completed", "completed"]
    assert sessions[0].minutes == 0.05


def test_start_uses_config_defaults(run, isolated_home):
    assert run("config", "set", "work", "2")[0] == 0
    assert run("config", "set", "cycles", "3")[0] == 0
    code, out, _ = run("start", "--seconds", "--short", "1", "--long", "1")
    assert code == 0
    assert "3 x 2s work" in out
    assert len(logged(isolated_home)) == 3


def test_start_flags_override_config(run, isolated_home):
    run("config", "set", "cycles", "5")
    code, _, _ = run("start", "--seconds", "--work", "1", "--short", "1", "--long", "1", "--cycles", "1")
    assert code == 0
    assert len(logged(isolated_home)) == 1


def test_start_minutes_mode_full_pomodoro_with_fake_clock(run, isolated_home):
    clock = FakeClock()
    t0 = clock()
    code, out, _ = run("start", "--label", "thesis", clock=clock)
    assert code == 0
    assert clock() - t0 == 4 * 25 * 60 + 3 * 5 * 60 + 15 * 60
    sessions = logged(isolated_home)
    assert [s.minutes for s in sessions] == [25.0] * 4
    assert {s.label for s in sessions} == {"thesis"}


def test_ctrl_c_mid_work_exits_130_and_logs_interrupted(run, isolated_home):
    clock = FakeClock()
    clock.interrupt_at = clock() + 25 * 60 + 5 * 60 + 8 * 60  # 8 minutes into block 2
    code, out, _ = run("start", "--label", "write", clock=clock)
    assert code == 130
    assert "1 of 4 work block(s) completed, 1 interrupted. Stopped." in out
    sessions = logged(isolated_home)
    assert [(s.status, s.minutes) for s in sessions] == [("completed", 25.0), ("interrupted", 8.0)]
    assert sessions[1].planned_minutes == 25.0


def test_bell_rings_by_default_and_not_with_no_bell(run):
    _, out, _ = run("start", "--seconds", "--work", "1", "--short", "1", "--long", "1", "--cycles", "2")
    assert out.count("\a") == 4
    _, out, _ = run("start", "--seconds", "--work", "1", "--short", "1", "--long", "1", "--cycles", "2", "--no-bell")
    assert "\a" not in out


def test_bell_can_be_disabled_in_config(run):
    run("config", "set", "bell", "false")
    _, out, _ = run("start", "--seconds", "--work", "1", "--short", "1", "--long", "1", "--cycles", "1")
    assert "\a" not in out


def test_start_non_tty_prints_plain_lines(run):
    _, out, _ = run("start", "--seconds", "--work", "12", "--short", "1", "--long", "1", "--cycles", "1", "--no-bell")
    assert "\r" not in out
    assert "Work 1/1: 00:12 left" in out
    assert "Work 1/1: 00:10 left" in out and "Work 1/1: 00:05 left" in out


def test_start_tty_uses_carriage_returns_and_color(run):
    out = TTY()
    code, text, _ = run("start", "--seconds", "--work", "2", "--short", "1", "--long", "1", "--cycles", "1", stdout=out)
    assert code == 0
    assert "\r" in text and "\x1b[" in text


def test_start_tty_respects_no_color(run, isolated_home):
    env = {"FOCUSBELL_HOME": str(isolated_home), "NO_COLOR": "1"}
    _, text, _ = run("start", "--seconds", "--work", "2", "--short", "1", "--long", "1", "--cycles", "1",
                     stdout=TTY(), environ=env)
    assert "\x1b[" not in text


@pytest.mark.parametrize(
    "flags",
    [["--work", "0"], ["--work", "abc"], ["--cycles", "2.5"], ["--short", "999"], ["--sets", "0"], ["--sets", "20"]],
)
def test_start_rejects_bad_values_with_exit_2(run, isolated_home, flags):
    code, _, _ = run("start", *flags)
    assert code == 2
    assert not (isolated_home / "sessions.jsonl").exists()


def test_start_survives_unwritable_log(run, tmp_path):
    blocker = tmp_path / "file-not-dir"
    blocker.write_text("x")
    env = {"FOCUSBELL_HOME": str(blocker)}
    code, _, err = run("start", "--seconds", "--work", "1", "--short", "1", "--long", "1", "--cycles", "1", environ=env)
    assert code == 0
    assert "could not write session log" in err


# ------------------------------------------------------------ log


def test_log_table(run, isolated_home):
    write_log(isolated_home, DEMO)
    code, out, _ = run("log")
    assert code == 0
    lines = out.splitlines()
    assert lines[0].split() == ["Date", "Start", "End", "Minutes", "Status", "Label"]
    assert "2026-11-09  10:00  10:12     12.0  interrupted  thesis" in out
    assert "5 session(s), 2h 17m focused." in out


def test_log_since_and_limit(run, isolated_home):
    write_log(isolated_home, DEMO)
    _, out, _ = run("log", "--since", "2026-11-08")
    assert "2026-11-01" not in out and "2026-11-07" not in out
    assert "3 session(s)" in out
    _, out, _ = run("log", "--limit", "1")
    assert "1 session(s)" in out and "10:00" in out


def test_log_uses_display_time_zone(run, isolated_home):
    write_log(isolated_home, [rec("2026-11-09T02:00:00+00:00")])
    _, out, _ = run("log", tz=timezone(timedelta(hours=-5)))
    assert "2026-11-08  21:00  21:25" in out


def test_log_empty(run):
    code, out, _ = run("log")
    assert code == 0 and "No sessions logged yet." in out


def test_log_bad_since_exits_2(run, capsys):
    assert run("log", "--since", "last tuesday")[0] == 2
    assert "invalid date" in capsys.readouterr().err


def test_corrupt_log_lines_warn_but_do_not_crash(run, isolated_home):
    write_log(isolated_home, DEMO[:1], extra_lines=["garbage", '{"start": 5}'])
    code, out, err = run("log")
    assert code == 0
    assert "1 session(s)" in out
    assert err.count("warning: skipping corrupt line") == 2


# ------------------------------------------------------------ stats


def test_stats_report(run, isolated_home):
    write_log(isolated_home, DEMO)
    code, out, _ = run("stats")
    assert code == 0
    assert "last 7 day(s) (2026-11-03 to 2026-11-09)" in out
    assert "Mon 11-09" in out and "Tue 11-03" in out
    assert "█" in out
    assert "Total       1h 52m in 4 session(s), avg 16m/day" in out
    assert "Completed   3 of 4 (75%), 1 interrupted" in out
    assert "Top labels  code (50m), thesis (37m), email (25m)" in out
    assert "Streak      3 day(s)" in out


def test_stats_days_option(run, isolated_home):
    write_log(isolated_home, DEMO)
    _, out, _ = run("stats", "--days", "14")
    assert "last 14 day(s)" in out and "Sun 11-01" in out


def test_stats_ascii_fallback_when_stdout_cannot_encode_blocks(run, isolated_home):
    write_log(isolated_home, DEMO)
    buf = io.BytesIO()
    stream = io.TextIOWrapper(buf, encoding="ascii")
    code, _, _ = run("stats", stdout=_Capture(stream))
    assert code == 0
    stream.flush()
    text = buf.getvalue().decode("ascii")
    assert "#" in text and "█" not in text


class _Capture:
    """Wraps a TextIOWrapper so the test helper can call getvalue()."""

    def __init__(self, stream):
        self._s = stream
        self.encoding = stream.encoding

    def write(self, text):
        return self._s.write(text)

    def flush(self):
        self._s.flush()

    def isatty(self):
        return False

    def getvalue(self):
        return ""


def test_stats_color_always_and_never(run, isolated_home):
    write_log(isolated_home, DEMO)
    assert "\x1b[" in run("stats", "--color", "always")[1]
    assert "\x1b[" not in run("--color", "never", "stats", stdout=TTY())[1]
    assert "\x1b[" in run("stats", stdout=TTY())[1]


def test_stats_with_no_sessions(run):
    code, out, _ = run("stats")
    assert code == 0
    assert "Completed   - (no sessions in this period)" in out
    assert "Streak      0 day(s)" in out


@pytest.mark.parametrize("days", ["0", "400", "x"])
def test_stats_bad_days_exit_2(run, days):
    assert run("stats", "--days", days)[0] == 2


# ------------------------------------------------------------ config


def test_config_get_all_and_one(run):
    run("config", "set", "work", "50")
    code, out, _ = run("config", "get")
    assert code == 0
    assert "work = 50" in out and "short = 5" in out and 'color = "auto"' in out
    assert run("config", "get", "work")[1] == "50\n"
    assert run("config")[1] == out


def test_config_set_invalid_exits_2(run, isolated_home):
    code, _, err = run("config", "set", "cycles", "40")
    assert code == 2 and "between 1 and 12" in err
    assert not (isolated_home / "config.json").exists()


def test_config_get_unknown_exits_2(run):
    code, _, err = run("config", "get", "volume")
    assert code == 2 and "unknown key" in err


def test_config_is_stored_in_focusbell_home(run, isolated_home):
    run("config", "set", "color", "never")
    assert json.loads((isolated_home / "config.json").read_text(encoding="utf-8")) == {"color": "never"}


# ------------------------------------------------------------ export


def test_export_csv(run, isolated_home):
    write_log(isolated_home, DEMO)
    code, out, _ = run("export", "--format", "csv")
    assert code == 0
    lines = out.splitlines()
    assert lines[0] == "start,end,minutes,planned_minutes,label,status"
    assert len(lines) == 6
    assert lines[1] == "2026-11-01T09:00:00+00:00,2026-11-01T09:25:00+00:00,25.0,25.0,old,completed"


def test_export_json_shape(run, isolated_home):
    write_log(isolated_home, DEMO)
    code, out, _ = run("export", "--format", "json", "--since", "2026-11-09")
    assert code == 0
    data = json.loads(out)
    assert isinstance(data, list) and len(data) == 2
    assert set(data[0]) == {"start", "end", "minutes", "planned_minutes", "label", "status"}
    assert data[1]["status"] == "interrupted" and data[1]["minutes"] == 12


def test_export_to_file(run, isolated_home, tmp_path):
    write_log(isolated_home, DEMO)
    target = tmp_path / "out.csv"
    code, out, err = run("export", "--output", str(target))
    assert code == 0 and out == ""
    assert "Exported 5 session(s)" in err
    assert target.read_bytes().count(b"\n") == 6 and b"\r" not in target.read_bytes()


def test_export_ics_to_file(run, isolated_home, tmp_path):
    write_log(isolated_home, DEMO)
    target = tmp_path / "out.ics"
    code, _, err = run("export", "--format", "ics", "--since", "2026-11-09", "--output", str(target))
    assert code == 0 and "Exported 2 session(s)" in err
    data = target.read_bytes()
    assert data.startswith(b"BEGIN:VCALENDAR\r\n") and data.count(b"BEGIN:VEVENT") == 2
    assert b"\r\r" not in data


def test_export_empty_log_json(run):
    assert json.loads(run("export", "--format", "json")[1]) == []


def test_export_unwritable_target_exits_1(run, tmp_path):
    code, _, err = run("export", "--output", str(tmp_path / "missing" / "dir" / "x.csv"))
    assert code == 1 and "could not write" in err


# ------------------------------------------------------------ misc


def test_no_command_prints_help_and_exits_2(run):
    code, out, _ = run()
    assert code == 2 and "usage: focusbell" in out


def test_unknown_command_exits_2(run):
    assert run("dance")[0] == 2


def test_version(run, capsys):
    assert run("--version")[0] == 0
    assert "focusbell 0.1.0" in capsys.readouterr().out


def test_python_dash_m_entry_point(isolated_home):
    env = dict(os.environ, FOCUSBELL_HOME=str(isolated_home))
    proc = subprocess.run(
        [sys.executable, "-m", "focusbell", "config", "get", "cycles"],
        capture_output=True, text=True, env=env, timeout=60,
    )
    assert proc.returncode == 0
    assert proc.stdout.strip() == "4"
