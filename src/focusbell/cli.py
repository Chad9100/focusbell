"""Command-line interface for focusbell."""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from datetime import date, datetime, timedelta, tzinfo
from pathlib import Path
from typing import Callable, ContextManager, Mapping, Optional, Sequence, TextIO

from . import __version__, config, keys, notify, report, sound, timer, todo
from .log import Session, append_record, data_dir, log_path, read_sessions
from .render import (
    BLOCK_EMPTY,
    BLOCK_FULL,
    Painter,
    bar,
    bar_chart,
    can_encode,
    fmt_minutes,
    isatty,
    table,
    use_color,
)
from .stats import GoalProgress, by_label, compute_stats, goal_progress, records, to_local

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_INTERRUPTED = 130

EXPORT_FIELDS = ["start", "end", "minutes", "planned_minutes", "label", "status"]


class _Ctx:
    def __init__(
        self,
        stdout: TextIO,
        stderr: TextIO,
        environ: Mapping[str, str],
        clock: Callable[[], float],
        sleep: Callable[[float], None],
        now: Callable[[], datetime],
        tz: Optional[tzinfo],
        notifier: Optional[Callable[[], Optional[notify.Notifier]]] = None,
        key_reader: Optional[Callable[[], ContextManager[Optional[keys.Poll]]]] = None,
        player: Optional[Callable[[Path], Optional[sound.Player]]] = None,
    ):
        self.stdout = stdout
        self.stderr = stderr
        self.environ = environ
        self.clock = clock
        self.sleep = sleep
        self.now = now
        self.tz = tz
        self.notifier = notifier or (lambda: notify.system_notifier(environ=environ))
        self.key_reader = key_reader or keys.key_reader
        self.player = player or sound.system_player

    def out(self, text: str = "") -> None:
        self.stdout.write(text + "\n")

    def warn(self, message: str) -> None:
        self.stderr.write(f"focusbell: warning: {message}\n")

    def error(self, message: str) -> None:
        self.stderr.write(f"focusbell: error: {message}\n")

    @property
    def config_path(self) -> Path:
        return data_dir(self.environ) / config.CONFIG_NAME

    def load_config(self) -> dict:
        return config.load(self.config_path, self.warn)

    def painter(self, args: argparse.Namespace, cfg: Optional[dict] = None) -> Painter:
        mode = getattr(args, "color", None)
        if mode is None:
            mode = (cfg or self.load_config())["color"]
        return Painter(use_color(mode, self.stdout, self.environ))


def _since(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"invalid date {value!r} (expected YYYY-MM-DD)"
        ) from None


def _positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected a whole number, got {value!r}") from None
    if number < 1:
        raise argparse.ArgumentTypeError(f"must be at least 1, got {number}")
    return number


def build_parser() -> argparse.ArgumentParser:
    color = argparse.ArgumentParser(add_help=False)
    color.add_argument(
        "--color",
        choices=config.COLOR_MODES,
        default=argparse.SUPPRESS,
        help="colorize output (default: auto = only on a TTY with NO_COLOR unset)",
    )

    parser = argparse.ArgumentParser(
        prog="focusbell",
        description="Pomodoro-style focus timer for the terminal, with a session log and stats.",
        parents=[color],
    )
    parser.add_argument("--version", action="version", version=f"focusbell {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    p = sub.add_parser("start", parents=[color], help="run work/break cycles")
    p.add_argument("--work", help="work block length (minutes; default 25)")
    p.add_argument("--short", help="short break length (minutes; default 5)")
    p.add_argument("--long", help="long break length (minutes; default 15)")
    p.add_argument("--cycles", help="work blocks before a long break (default 4)")
    p.add_argument("--sets", type=_positive_int, default=1,
                   help="how many rounds of CYCLES work blocks to run (default 1)")
    what = p.add_mutually_exclusive_group()
    what.add_argument("--label", help="what you are working on, stored with each session")
    what.add_argument("--task", type=_positive_int, metavar="N",
                      help="use task N (line N) of your todo.txt as the label")
    p.add_argument("--todo-file", metavar="PATH",
                   help="todo.txt to read --task from (default: the todo_file config key)")
    p.add_argument("--tally", action=argparse.BooleanOptionalAction, default=None,
                   help="with --task, add or bump a pomodoros:N tag on that todo.txt "
                        "line after each completed work block (default: the tally "
                        "config key, off)")
    p.add_argument("--no-bell", action="store_true",
                   help="no audible signal at all: neither the terminal bell nor --sound")
    audio = p.add_mutually_exclusive_group()
    audio.add_argument("--sound", metavar="PATH",
                       help="play this WAV file at each transition instead of the terminal "
                            "bell (default: the sound config key)")
    audio.add_argument("--no-sound", action="store_true",
                       help="ignore the sound config key for this run and use the bell")
    p.add_argument("--notify", action=argparse.BooleanOptionalAction, default=None,
                   help="show a desktop notification at each transition "
                        "(default: the notify config key, off)")
    p.add_argument("--seconds", action="store_true",
                   help="treat durations as seconds instead of minutes (for quick demos)")

    p = sub.add_parser("log", parents=[color], help="show logged sessions as a table")
    p.add_argument("--since", type=_since, help="only sessions on or after DATE (YYYY-MM-DD)")
    p.add_argument("--limit", type=_positive_int, help="show only the last N sessions")

    p = sub.add_parser("stats", parents=[color], help="focus minutes per day, totals, streak")
    p.add_argument("--days", type=_positive_int, default=7,
                   help="how many days to chart, ending today (default 7, max 366)")
    p.add_argument("--by", choices=("day", "task"), default="day",
                   help="day: daily chart and totals (default); task: a table of "
                        "focus time per label, numbered from your todo.txt")
    p.add_argument("--todo-file", metavar="PATH",
                   help="todo.txt to number tasks from with --by task "
                        "(default: the todo_file config key)")

    p = sub.add_parser("report", parents=[color], help="write a self-contained HTML report")
    p.add_argument("--html", metavar="FILE", required=True,
                   help="write the report to FILE ('-' for stdout)")
    p.add_argument("--days", type=_positive_int, default=182,
                   help="days to cover, ending today (default 182, at most 3660)")

    p = sub.add_parser("config", parents=[color], help="get or set default settings")
    csub = p.add_subparsers(dest="action", metavar="ACTION")
    g = csub.add_parser("get", help="print one setting, or all of them")
    g.add_argument("key", nargs="?", help=", ".join(config.keys()))
    s = csub.add_parser("set", help="store a validated default")
    s.add_argument("key", help=", ".join(config.keys()))
    s.add_argument("value")

    p = sub.add_parser("export", parents=[color], help="export sessions as CSV or JSON")
    p.add_argument("--format", choices=("csv", "json"), default="csv")
    p.add_argument("--output", "-o", help="write to this file instead of stdout")
    p.add_argument("--since", type=_since, help="only sessions on or after DATE (YYYY-MM-DD)")
    return parser


# ----------------------------------------------------------------- commands


def _fmt_span(seconds: float, unit_seconds: bool) -> str:
    if unit_seconds:
        return f"{seconds:g}s"
    return f"{seconds / 60:g} min"


def cmd_start(ctx: _Ctx, args: argparse.Namespace) -> int:
    cfg = ctx.load_config()
    try:
        values = {
            key: config.validate(key, getattr(args, key)) if getattr(args, key) is not None
            else cfg[key]
            for key in ("work", "short", "long", "cycles")
        }
    except config.ConfigError as exc:
        ctx.error(str(exc))
        return EXIT_USAGE
    if args.sets > 12:
        ctx.error(f"sets must be between 1 and 12, got {args.sets}")
        return EXIT_USAGE
    unit = 1 if args.seconds else 60
    schedule = timer.build_schedule(
        values["work"] * unit, values["short"] * unit, values["long"] * unit,
        values["cycles"], args.sets,
    )
    label = (args.label or "").strip() or None
    task_line = None
    task: Optional[todo.TodoTask] = None
    todo_path: Optional[Path] = None
    want_tally = cfg["tally"] if args.tally is None else args.tally
    if args.task is not None:
        source = (args.todo_file or "").strip() or cfg["todo_file"]
        if not source:
            ctx.error("--task needs a todo.txt: pass --todo-file PATH or run "
                      "`focusbell config set todo_file PATH`")
            return EXIT_USAGE
        todo_path = Path(source).expanduser()
        try:
            task = todo.read_task(todo_path, args.task)
        except todo.TodoError as exc:
            ctx.error(str(exc))
            return EXIT_USAGE
        label = task.label
        task_line = f"Task {task.number}: {task.raw.strip()}"
    elif args.todo_file:
        ctx.warn("--todo-file has no effect without --task")
    if args.tally and task is None:
        ctx.warn("--tally has no effect without --task")
    tally = {"task": task, "added": 0, "count": None, "error": None}
    painter = ctx.painter(args, cfg)
    path = log_path(ctx.environ)

    def on_record(record: dict) -> None:
        try:
            append_record(path, record)
        except OSError as exc:
            ctx.warn(f"could not write session log {path}: {exc}")
        if (want_tally and tally["task"] is not None and tally["error"] is None
                and record["status"] == timer.COMPLETED):
            # Written after every block so a later Ctrl+C keeps the count.
            # Problems are reported once, after the timer, not mid-countdown.
            try:
                tally["task"], tally["count"] = todo.bump_tally(todo_path, tally["task"])
                tally["added"] += 1
            except todo.TodoError as exc:
                tally["error"] = str(exc)

    want_notify = cfg["notify"] if args.notify is None else args.notify
    notifier = ctx.notifier() if want_notify else None

    bell = bool(cfg["bell"]) and not args.no_bell
    player: Optional[sound.Player] = None
    sound_source = "" if args.no_sound else ((args.sound or "").strip() or cfg["sound"])
    if sound_source and not bell:
        if args.sound:
            ctx.warn("--sound has no effect with the bell turned off")
    elif sound_source:
        try:
            wav = sound.check_wav(Path(sound_source).expanduser())
        except sound.SoundError as exc:
            if args.sound:  # asked for on this run: refuse rather than surprise
                ctx.error(str(exc))
                return EXIT_USAGE
            # From the config: a moved file must not cost a focus session.
            ctx.warn(f"{exc} (from the sound config key); using the terminal bell")
        else:
            player = ctx.player(wav)
            if player is None:
                ctx.warn(f"no WAV player found ({sound.player_name()}); "
                         "using the terminal bell")

    blocks = values["cycles"] * args.sets

    def span(seconds: float) -> str:
        return f"{seconds:.0f}s" if args.seconds else fmt_minutes(seconds / 60)

    with ctx.key_reader() as poll:
        controls = ("p to pause, s to skip a break, Ctrl+C to stop." if poll is not None
                    else "Ctrl+C to stop.")
        ctx.out(
            f"focusbell: {blocks} x {_fmt_span(values['work'] * unit, args.seconds)} work, "
            f"{_fmt_span(values['short'] * unit, args.seconds)} short breaks, "
            f"{_fmt_span(values['long'] * unit, args.seconds)} long break"
            f" after every {values['cycles']}. {controls}"
        )
        if task_line:
            ctx.out(task_line)
        result = timer.run(
            schedule,
            clock=ctx.clock,
            sleep=ctx.sleep,
            out=ctx.stdout,
            label=label,
            bell=bell,
            tty=isatty(ctx.stdout),
            on_record=on_record,
            # Poll keys a few times a second so a pause or skip feels immediate.
            tick=0.25 if poll is not None else 1.0,
            report_every=5.0 if args.seconds else 60.0,
            paint=painter,
            notify=notifier,
            keys=poll,
            sound=player,
        )
    summary = (
        f"Focused {span(result.focus_seconds)}: "
        f"{result.completed} of {blocks} work block(s) completed"
    )
    pauses = ""
    if result.pauses:
        pauses = f" Paused {result.pauses} time(s), {span(result.paused_seconds)} in total."
    if result.skipped:
        pauses += f" Skipped {result.skipped} break(s)."
    if result.interrupted:
        partial = any(r["status"] == timer.INTERRUPTED for r in result.records)
        ctx.out(summary + (", 1 interrupted." if partial else ".") + pauses + " Stopped.")
    else:
        ctx.out(summary + "." + pauses)
    if tally["added"]:
        ctx.out(f"Task {tally['task'].number}: {todo.TALLY_KEY}:{tally['count']} "
                f"(+{tally['added']}) in {todo_path}")
    if tally["error"]:
        ctx.warn(tally["error"])
    if cfg["weekly_goal"]:
        # Re-read the log so the blocks just written count. Corrupt lines were
        # already reported by `stats`/`log`; don't repeat that after a session.
        sessions = read_sessions(path)
        today = to_local(ctx.now(), ctx.tz).date()
        ctx.out(_goal_summary(goal_progress(sessions, cfg["weekly_goal"], today, ctx.tz)))
    return EXIT_INTERRUPTED if result.interrupted else EXIT_OK


def _load_sessions(ctx: _Ctx, since: Optional[date]) -> list[Session]:
    sessions = read_sessions(log_path(ctx.environ), ctx.warn)
    if since is not None:
        sessions = [s for s in sessions if to_local(s.start, ctx.tz).date() >= since]
    return sessions


def cmd_log(ctx: _Ctx, args: argparse.Namespace) -> int:
    sessions = _load_sessions(ctx, args.since)
    if args.limit:
        sessions = sessions[-args.limit:]
    if not sessions:
        ctx.out("No sessions logged yet." if args.since is None else "No sessions since then.")
        return EXIT_OK
    rows = []
    for s in sessions:
        start = to_local(s.start, ctx.tz)
        end = to_local(s.end, ctx.tz)
        rows.append([
            start.strftime("%Y-%m-%d"),
            start.strftime("%H:%M"),
            end.strftime("%H:%M"),
            f"{s.minutes:.1f}",
            s.status,
            s.label or "-",
        ])
    paint = ctx.painter(args)
    lines = table(["Date", "Start", "End", "Minutes", "Status", "Label"], rows, right=(3,))
    ctx.out(paint("head", lines[0]))
    for line in lines[1:]:
        ctx.out(line)
    total = sum(s.minutes for s in sessions)
    paused = [s for s in sessions if s.pauses]
    note = ""
    if paused:
        held = sum(s.paused_minutes for s in paused)
        note = (f" {sum(s.pauses for s in paused)} pause(s) in {len(paused)} session(s),"
                f" {fmt_minutes(held)} on hold (not counted).")
    ctx.out()
    ctx.out(f"{len(sessions)} session(s), {fmt_minutes(total)} focused.{note}")
    return EXIT_OK


def cmd_stats(ctx: _Ctx, args: argparse.Namespace) -> int:
    if args.days > 366:
        ctx.error(f"--days must be between 1 and 366, got {args.days}")
        return EXIT_USAGE
    if args.by == "task":
        return _stats_by_task(ctx, args)
    if args.todo_file:
        ctx.warn("--todo-file has no effect without --by task")
    sessions = read_sessions(log_path(ctx.environ), ctx.warn)
    today = to_local(ctx.now(), ctx.tz).date()
    st = compute_stats(sessions, args.days, today, ctx.tz)
    paint = ctx.painter(args)
    unicode = can_encode(ctx.stdout, BLOCK_FULL + BLOCK_EMPTY)
    ctx.out(paint("head", f"Focus time, last {st.days} day(s) ({st.first_day} to {st.last_day})"))
    ctx.out()
    rows = [(d.strftime("%a %m-%d"), m) for d, m in st.per_day]
    for line in bar_chart(rows, width=30, unicode=unicode, paint=paint):
        ctx.out(line)
    ctx.out()
    avg = st.total_minutes / st.days
    ctx.out(f"Total       {fmt_minutes(st.total_minutes)} in {st.sessions} session(s), "
            f"avg {fmt_minutes(avg)}/day")
    if st.completion_rate is None:
        ctx.out("Completed   - (no sessions in this period)")
    else:
        ctx.out(f"Completed   {st.completed} of {st.sessions} ({st.completion_rate:.0%}), "
                f"{st.interrupted} interrupted")
    if st.top_labels:
        labels = ", ".join(f"{name} ({fmt_minutes(m)})" for name, m in st.top_labels)
    else:
        labels = "-"
    ctx.out(f"Top labels  {labels}")
    ctx.out(f"Streak      {st.streak} day(s)")
    for line in _record_lines(records(sessions, today, ctx.tz)):
        ctx.out(line)
    goal = ctx.load_config()["weekly_goal"]
    if goal:
        progress = goal_progress(sessions, goal, today, ctx.tz)
        ctx.out(_goal_line(progress, unicode, paint))
    return EXIT_OK


def _record_lines(rec) -> list[str]:
    """The all-time `Best streak` and `Best week` rows of `stats`."""
    if rec.streak_first is None:
        streak = "0 day(s)"
    else:
        span = (str(rec.streak_first) if rec.streak_days == 1
                else f"{rec.streak_first} to {rec.streak_last}")
        streak = f"{rec.streak_days} day(s), {span}"
        if rec.streak_current:
            streak += " (current)"
    if rec.week_first is None:
        week = "-"
    else:
        week = f"{fmt_minutes(rec.week_minutes)}, week of {rec.week_first}"
        if rec.week_current:
            week += " (this week)"
    return [f"Best streak {streak}", f"Best week   {week}"]


GOAL_BAR_WIDTH = 20


def _goal_status(progress: GoalProgress) -> str:
    if progress.met:
        return "goal met"
    return (f"{fmt_minutes(progress.remaining)} to go, "
            f"{progress.days_left} day(s) left")


def _goal_line(progress: GoalProgress, unicode: bool, paint: Painter) -> str:
    """The `Week goal` row of `stats`: bar, minutes, percent and what is left."""
    filled = bar(progress.done, progress.goal, GOAL_BAR_WIDTH, unicode)
    status = _goal_status(progress)
    return (f"Week goal   {paint('ok' if progress.met else 'bar', filled)}  "
            f"{fmt_minutes(progress.done)} of {fmt_minutes(progress.goal)} "
            f"({progress.percent}%), {paint('ok', status) if progress.met else status}")


def _goal_summary(progress: GoalProgress) -> str:
    """One line printed after a session when a weekly goal is set."""
    return (f"This week: {fmt_minutes(progress.done)} of {fmt_minutes(progress.goal)} "
            f"goal ({progress.percent}%), {_goal_status(progress)}.")


TASK_WIDTH = 48


def _shorten(text: str, width: int = TASK_WIDTH) -> str:
    return text if len(text) <= width else text[: width - 3].rstrip() + "..."


def _stats_by_task(ctx: _Ctx, args: argparse.Namespace) -> int:
    # Look up todo.txt numbers when a file is known. An explicit --todo-file
    # that cannot be read is an error; a stale config key only warns.
    tasks: Optional[list[todo.TodoTask]] = None
    source = (args.todo_file or "").strip()
    explicit = bool(source)
    if not explicit:
        source = ctx.load_config()["todo_file"]
    if source:
        try:
            tasks = todo.read_tasks(Path(source).expanduser())
        except todo.TodoError as exc:
            if explicit:
                ctx.error(str(exc))
                return EXIT_USAGE
            ctx.warn(f"{exc}; showing labels without task numbers")
    numbers: dict[str, todo.TodoTask] = {}
    for task in tasks or []:
        known = numbers.get(task.label)
        if known is None or (known.done and not task.done):
            numbers[task.label] = task  # first open line wins over a done one

    sessions = read_sessions(log_path(ctx.environ), ctx.warn)
    today = to_local(ctx.now(), ctx.tz).date()
    first = today - timedelta(days=args.days - 1)
    groups = by_label(sessions, first, today, ctx.tz)
    paint = ctx.painter(args)
    ctx.out(paint("head", f"Focus time by task, last {args.days} day(s) ({first} to {today})"))
    ctx.out()
    if not groups:
        ctx.out("No sessions in this period.")
    else:
        total = sum(g.minutes for g in groups)
        rows = []
        for g in groups:
            task = numbers.get(g.label) if g.label else None
            number = "-" if task is None else ("x" if task.done else "") + str(task.number)
            share = f"{g.minutes / total:.0%}" if total > 0 else "-"
            row = [_shorten(g.label or "(no label)"), f"{g.completed}/{g.sessions}",
                   fmt_minutes(g.minutes), share, g.last_day.isoformat()]
            rows.append([number] + row if tasks is not None else row)
        headers = ["Task", "Completed", "Focus", "Share", "Last"]
        right = (1, 2, 3)
        if tasks is not None:
            headers = ["#"] + headers
            right = tuple(i + 1 for i in right)
        lines = table(headers, rows, right=right)
        ctx.out(paint("head", lines[0]))
        for line in lines[1:]:
            ctx.out(line)
        ctx.out()
        sessions_n = sum(g.sessions for g in groups)
        ctx.out(f"Total       {fmt_minutes(total)} in {sessions_n} session(s) "
                f"across {len(groups)} label(s)")
    if tasks is not None:
        worked = {g.label for g in groups}
        idle = [t for t in tasks if not t.done and t.label not in worked
                and numbers[t.label] is t]
        if idle:
            listed = ", ".join(str(t.number) for t in idle)
            ctx.out(f"No focus time yet on open task(s) {listed}")
    return EXIT_OK


def cmd_config(ctx: _Ctx, args: argparse.Namespace) -> int:
    path = ctx.config_path
    if args.action == "set":
        if args.key == "todo_file" and args.value.strip():
            # Store an absolute path so --task works from any directory.
            args.value = str(Path(args.value.strip()).expanduser().absolute())
        try:
            value = config.save_value(path, args.key, args.value)
        except config.ConfigError as exc:
            ctx.error(str(exc))
            return EXIT_USAGE
        except OSError as exc:
            ctx.error(f"could not write {path}: {exc}")
            return EXIT_ERROR
        ctx.out(f"{args.key} = {json.dumps(value)}")
        return EXIT_OK
    cfg = ctx.load_config()
    key = getattr(args, "key", None)
    if key:
        if key not in cfg:
            ctx.error(f"unknown key {key!r} (known: {', '.join(config.keys())})")
            return EXIT_USAGE
        value = cfg[key]
        ctx.out(value if isinstance(value, str) else json.dumps(value))
        return EXIT_OK
    for k in config.keys():
        ctx.out(f"{k} = {json.dumps(cfg[k])}")
    return EXIT_OK


def _write_export(fh: TextIO, fmt: str, sessions: list[Session]) -> None:
    records = [s.to_dict() for s in sessions]
    if fmt == "json":
        fh.write(json.dumps(records, indent=2, ensure_ascii=False) + "\n")
        return
    writer = csv.DictWriter(fh, fieldnames=EXPORT_FIELDS, lineterminator="\n")
    writer.writeheader()
    for rec in records:
        writer.writerow({k: "" if rec[k] is None else rec[k] for k in EXPORT_FIELDS})


def cmd_export(ctx: _Ctx, args: argparse.Namespace) -> int:
    sessions = _load_sessions(ctx, args.since)
    if not args.output:
        _write_export(ctx.stdout, args.format, sessions)
        return EXIT_OK
    try:
        with open(args.output, "w", encoding="utf-8", newline="") as fh:
            _write_export(fh, args.format, sessions)
    except OSError as exc:
        ctx.error(f"could not write {args.output}: {exc}")
        return EXIT_ERROR
    ctx.stderr.write(f"Exported {len(sessions)} session(s) to {args.output}\n")
    return EXIT_OK


def cmd_report(ctx: _Ctx, args: argparse.Namespace) -> int:
    if args.days > 3660:
        ctx.error(f"--days must be between 1 and 3660, got {args.days}")
        return EXIT_USAGE
    sessions = read_sessions(log_path(ctx.environ), ctx.warn)
    now = to_local(ctx.now(), ctx.tz)
    page = report.render_html(sessions, now.date(), args.days, ctx.tz,
                              generated=now.strftime("%Y-%m-%d %H:%M"))
    if args.html == "-":
        ctx.stdout.write(page)
        return EXIT_OK
    try:
        with open(args.html, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(page)
    except OSError as exc:
        ctx.error(f"could not write {args.html}: {exc}")
        return EXIT_ERROR
    ctx.stderr.write(f"Wrote report for {args.days} day(s) to {args.html}\n")
    return EXIT_OK


COMMANDS = {
    "start": cmd_start,
    "log": cmd_log,
    "stats": cmd_stats,
    "report": cmd_report,
    "config": cmd_config,
    "export": cmd_export,
}


def main(
    argv: Optional[Sequence[str]] = None,
    *,
    stdout: Optional[TextIO] = None,
    stderr: Optional[TextIO] = None,
    environ: Optional[Mapping[str, str]] = None,
    clock: Optional[Callable[[], float]] = None,
    sleep: Optional[Callable[[float], None]] = None,
    now: Optional[Callable[[], datetime]] = None,
    tz: Optional[tzinfo] = None,
    notifier: Optional[Callable[[], Optional[notify.Notifier]]] = None,
    key_reader: Optional[Callable[[], ContextManager[Optional[keys.Poll]]]] = None,
    player: Optional[Callable[[Path], Optional[sound.Player]]] = None,
) -> int:
    if stdout is None:
        stdout = sys.stdout
        if hasattr(stdout, "reconfigure"):
            try:
                stdout.reconfigure(errors="replace")
            except (ValueError, OSError):  # pragma: no cover
                pass
    stderr = sys.stderr if stderr is None else stderr
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else EXIT_USAGE
    if args.command is None:
        parser.print_help(stdout)
        return EXIT_USAGE
    if args.command == "config" and args.action is None:
        args.action = "get"
        args.key = None
    ctx = _Ctx(
        stdout=stdout,
        stderr=stderr,
        environ=os.environ if environ is None else environ,
        clock=clock or time.time,
        sleep=sleep or time.sleep,
        now=now or (lambda: datetime.now().astimezone()),
        tz=tz,
        notifier=notifier,
        key_reader=key_reader,
        player=player,
    )
    try:
        return COMMANDS[args.command](ctx, args)
    except KeyboardInterrupt:
        stderr.write("\nInterrupted.\n")
        return EXIT_INTERRUPTED
    except BrokenPipeError:  # pragma: no cover - e.g. `focusbell log | head`
        return EXIT_OK
