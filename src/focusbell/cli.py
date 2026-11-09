"""Command-line interface for focusbell."""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from datetime import date, datetime, tzinfo
from pathlib import Path
from typing import Callable, Mapping, Optional, Sequence, TextIO

from . import __version__, config, timer
from .log import Session, append_record, data_dir, log_path, read_sessions
from .render import (
    BLOCK_EMPTY,
    BLOCK_FULL,
    Painter,
    bar_chart,
    can_encode,
    fmt_minutes,
    isatty,
    table,
    use_color,
)
from .stats import compute_stats, to_local

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
    ):
        self.stdout = stdout
        self.stderr = stderr
        self.environ = environ
        self.clock = clock
        self.sleep = sleep
        self.now = now
        self.tz = tz

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
    p.add_argument("--label", help="what you are working on, stored with each session")
    p.add_argument("--no-bell", action="store_true", help="do not ring the terminal bell")
    p.add_argument("--seconds", action="store_true",
                   help="treat durations as seconds instead of minutes (for quick demos)")

    p = sub.add_parser("log", parents=[color], help="show logged sessions as a table")
    p.add_argument("--since", type=_since, help="only sessions on or after DATE (YYYY-MM-DD)")
    p.add_argument("--limit", type=_positive_int, help="show only the last N sessions")

    p = sub.add_parser("stats", parents=[color], help="focus minutes per day, totals, streak")
    p.add_argument("--days", type=_positive_int, default=7,
                   help="how many days to chart, ending today (default 7, max 366)")

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
    painter = ctx.painter(args, cfg)
    path = log_path(ctx.environ)

    def on_record(record: dict) -> None:
        try:
            append_record(path, record)
        except OSError as exc:
            ctx.warn(f"could not write session log {path}: {exc}")

    blocks = values["cycles"] * args.sets
    ctx.out(
        f"focusbell: {blocks} x {_fmt_span(values['work'] * unit, args.seconds)} work, "
        f"{_fmt_span(values['short'] * unit, args.seconds)} short breaks, "
        f"{_fmt_span(values['long'] * unit, args.seconds)} long break"
        f" after every {values['cycles']}. Ctrl+C to stop."
    )
    result = timer.run(
        schedule,
        clock=ctx.clock,
        sleep=ctx.sleep,
        out=ctx.stdout,
        label=label,
        bell=bool(cfg["bell"]) and not args.no_bell,
        tty=isatty(ctx.stdout),
        on_record=on_record,
        report_every=5.0 if args.seconds else 60.0,
        paint=painter,
    )
    focused = (
        f"{result.focus_seconds:.0f}s" if args.seconds else fmt_minutes(result.focus_seconds / 60)
    )
    summary = f"Focused {focused}: {result.completed} of {blocks} work block(s) completed"
    if result.interrupted:
        partial = any(r["status"] == timer.INTERRUPTED for r in result.records)
        ctx.out(summary + (", 1 interrupted." if partial else ".") + " Stopped.")
        return EXIT_INTERRUPTED
    ctx.out(summary + ".")
    return EXIT_OK


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
    ctx.out()
    ctx.out(f"{len(sessions)} session(s), {fmt_minutes(total)} focused.")
    return EXIT_OK


def cmd_stats(ctx: _Ctx, args: argparse.Namespace) -> int:
    if args.days > 366:
        ctx.error(f"--days must be between 1 and 366, got {args.days}")
        return EXIT_USAGE
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
    return EXIT_OK


def cmd_config(ctx: _Ctx, args: argparse.Namespace) -> int:
    path = ctx.config_path
    if args.action == "set":
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
        ctx.out(json.dumps(cfg[key]).strip('"'))
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


COMMANDS = {
    "start": cmd_start,
    "log": cmd_log,
    "stats": cmd_stats,
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
    )
    try:
        return COMMANDS[args.command](ctx, args)
    except KeyboardInterrupt:
        stderr.write("\nInterrupted.\n")
        return EXIT_INTERRUPTED
    except BrokenPipeError:  # pragma: no cover - e.g. `focusbell log | head`
        return EXIT_OK
