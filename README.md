# focusbell

A Pomodoro-style focus timer for the terminal. It runs work/break cycles with a
live countdown, rings the terminal bell (and optionally shows a desktop
notification) when a phase ends, and logs every work
block so you can see how much focused time you actually put in.

**Who it is for:** people who live in a terminal and want a small timer that
writes a log they own (plain JSON Lines), without an app, an account, or a
browser tab.

**Built with:** Python 3.10+ and the standard library only (no runtime
dependencies). Tests use pytest.

## Install

```sh
git clone https://github.com/Chad9100/focusbell.git
cd focusbell
python -m pip install .
```

That puts a `focusbell` command on your PATH. `python -m focusbell` works too.

## Usage

### Run a session

```sh
focusbell start [--work 25] [--short 5] [--long 15] [--cycles 4] [--sets 1]
                [--label TEXT] [--no-bell] [--notify | --no-notify] [--seconds]
                [--color auto|always|never]
```

Work blocks are separated by short breaks, and every `--cycles`-th block is
followed by a long break. `--sets 2` runs two such rounds. Durations are
minutes (fractions allowed); `--seconds` reads them as seconds, which is handy
for trying it out.

In a terminal the countdown is a single line that updates in place, e.g.
`Work 2/4  17:42  [thesis]`. When output is not a terminal (piped, redirected,
CI) it prints a plain line at the start of each phase and once a minute (every
5 s with `--seconds`). This is real output from a short demo session, captured
through a pipe:

```text
$ focusbell start --seconds --work 3 --short 2 --long 2 --cycles 2 --label demo
focusbell: 2 x 3s work, 2s short breaks, 2s long break after every 2. Ctrl+C to stop.
Work 1/2: 00:03 left  [demo]
Work block 1 done. Short break next.
Short break: 00:02 left  [demo]
Short break over. Back to work.
Work 2/2: 00:03 left  [demo]
Work block 2 done. Long break next.
Long break: 00:02 left  [demo]
All done. Nice work.
Focused 6s: 2 of 2 work block(s) completed.
```

(The four bell characters, one per transition, are invisible here; `--no-bell`
turns them off.)

### Desktop notifications

`--notify` also pops up a desktop notification at every transition, so you
notice the end of a block even when the terminal is hidden. It uses tools the
OS already has, with no extra Python packages:

| Platform | Tool |
| --- | --- |
| Linux | `notify-send` (libnotify) |
| macOS | `osascript` (`display notification`) |
| Windows | a PowerShell toast (Windows PowerShell or `pwsh`) |

The notification title is `focusbell` (plus `: LABEL` when you pass
`--label`) and the text is the same line the terminal prints, e.g. `Work
block 1 done. Short break next.` The helper is started in the background and
not waited for, so it never delays the countdown. If the tool is missing or
fails, focusbell carries on silently with the bell and terminal output.
Turn it on permanently with `focusbell config set notify true`; `--no-notify`
turns it off for one run.

### Pause and resume

When stdin is a terminal, press **p** to pause the current phase and **p**
again to resume. On a terminal the countdown freezes and shows
`paused, p to resume`; time spent paused pushes the end of the phase back and
is not counted as focus time. Keys are read without blocking (`msvcrt` on
Windows, `termios` cbreak mode on Linux/macOS, restored on exit), so nothing
needs Enter and nothing is echoed. When stdin is not a terminal the timer runs
exactly as before and the banner only mentions Ctrl+C.

Real output from a demo where `p` was typed into the console about 3 s into
the work block and again 4 s later (stdout redirected to a file, so the plain
line format is used):

```text
$ focusbell start --seconds --work 8 --short 2 --long 2 --cycles 1 --label demo --no-bell
focusbell: 1 x 8s work, 2s short breaks, 2s long break after every 1. p to pause, Ctrl+C to stop.
Work 1/1: 00:08 left  [demo]
Work 1/1: 00:05 left  [demo]
Work 1/1: paused at 00:05 left  [demo]. Press p to resume.
Work 1/1: resumed, 00:05 left  [demo]
Work block 1 done. Long break next.
Long break: 00:02 left  [demo]
All done. Nice work.
Focused 8s: 1 of 1 work block(s) completed. Paused 1 time(s), 4s in total.
```

The logged block keeps its 8 s of focus in `minutes`, while `end` is the real
wall-clock end, and the pause is recorded alongside it:

```json
{"start": "2026-11-10T01:24:36+00:00", "end": "2026-11-10T01:24:48+00:00", "minutes": 0.13, "planned_minutes": 0.13, "label": "demo", "status": "completed", "pauses": 1, "paused_minutes": 0.07}
```

`focusbell log` then adds a note to its footer, e.g.
`1 session(s), 0m focused. 1 pause(s) in 1 session(s), 0m on hold (not counted).`
Pressing Ctrl+C while paused logs only the time actually worked.

### Stopping

Press **Ctrl+C** at any time to stop. A work block in progress is saved as
`interrupted` with the minutes you actually worked, and the command exits with
status 130.

### Where the log lives

Each completed or interrupted work block is appended as one JSON line to
`sessions.jsonl` in:

| Platform | Directory |
| --- | --- |
| Windows | `%APPDATA%\focusbell` |
| Linux / macOS | `$XDG_DATA_HOME/focusbell`, else `~/.local/share/focusbell` |
| Any | `$FOCUSBELL_HOME` if set (overrides the above) |

A line looks like:

```json
{"start": "2026-11-09T17:10:00+00:00", "end": "2026-11-09T17:35:00+00:00", "minutes": 25.0, "planned_minutes": 25.0, "label": "thesis", "status": "completed"}
```

A block that was paused also has `"pauses"` (how many times) and
`"paused_minutes"` (time on hold, not included in `minutes`). Both are
optional: older logs without them read as zero pauses, and blocks that were
never paused are written exactly as above. JSON export includes them for
paused blocks; the CSV columns are unchanged.

Lines that are not valid JSON or are missing fields are skipped with a warning
on stderr; they never crash the tool.

### Stats

The examples below come from a made-up demo log written into a temporary
`FOCUSBELL_HOME` (13 sessions over six days, plus one deliberately truncated
line), run on Monday 2026-11-09:

```text
$ focusbell stats
focusbell: warning: skipping corrupt line 14 in ...\home\sessions.jsonl: Unterminated string starting at: line 1 column 11 (char 10)
Focus time, last 7 day(s) (2026-11-03 to 2026-11-09)

Tue 11-03  ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░       0m
Wed 11-04  ████████░░░░░░░░░░░░░░░░░░░░░░      25m
Thu 11-05  ██████████░░░░░░░░░░░░░░░░░░░░      32m
Fri 11-06  ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░       0m
Sat 11-07  ██████████████████████████████   1h 40m
Sun 11-08  ██████████████████████░░░░░░░░   1h 15m
Mon 11-09  ██████████████████░░░░░░░░░░░░   1h 02m

Total       4h 54m in 13 session(s), avg 42m/day
Completed   11 of 13 (85%), 2 interrupted
Top labels  thesis (2h 55m), code review (1h 15m), email (44m)
Streak      3 day(s)
```

`--days N` changes the window (1 to 366). Days are local calendar days; a
session that runs past midnight is split between the two days. The streak
counts consecutive days with focus time ending today, or ending yesterday if
you have not started today yet.

If the terminal cannot encode the block characters (for example output
redirected on Windows with code page 1252), the bars fall back to ASCII:

```text
$ focusbell stats --days 3
Focus time, last 3 day(s) (2026-11-07 to 2026-11-09)

Sat 11-07  ##############################   1h 40m
Sun 11-08  ######################........   1h 15m
Mon 11-09  ##################............   1h 02m
```

### Session log

```text
$ focusbell log --limit 4
Date        Start  End    Minutes  Status       Label
----------  -----  -----  -------  -----------  -----------
2026-11-08  14:00  14:25     25.0  completed    code review
2026-11-09  09:10  09:35     25.0  completed    thesis
2026-11-09  09:40  10:05     25.0  completed    thesis
2026-11-09  10:15  10:26     11.5  interrupted  email

4 session(s), 1h 26m focused.
```

`--since YYYY-MM-DD` shows only sessions from that day on.

### Export

```text
$ focusbell export --format csv
start,end,minutes,planned_minutes,label,status
2026-11-04T09:00:00-08:00,2026-11-04T09:25:00-08:00,25.0,25.0,thesis,completed
2026-11-05T10:00:00-08:00,2026-11-05T10:25:00-08:00,25.0,25.0,email,completed
...

$ focusbell export --format json
[
  {
    "start": "2026-11-04T09:00:00-08:00",
    "end": "2026-11-04T09:25:00-08:00",
    "minutes": 25.0,
    "planned_minutes": 25.0,
    "label": "thesis",
    "status": "completed"
  },
...
```

`--output FILE` writes to a file instead of stdout; `--since` filters as above.

### Config

Defaults live in `config.json` next to the log. Values are validated before
they are saved:

```text
$ focusbell config set work 50
work = 50
$ focusbell config set cycles 20
focusbell: error: cycles must be between 1 and 12, got 20
$ focusbell config set notify maybe
focusbell: error: notify must be true or false, got 'maybe'
$ focusbell config set notify on
notify = true
$ focusbell config get
work = 50
short = 5
long = 15
cycles = 4
bell = true
notify = true
color = "auto"
```

| Key | Allowed values | Default |
| --- | --- | --- |
| `work` | 1 to 180 (minutes) | 25 |
| `short` | 1 to 60 | 5 |
| `long` | 1 to 120 | 15 |
| `cycles` | whole number 1 to 12 | 4 |
| `bell` | true/false (also yes/no, on/off, 1/0) | true |
| `notify` | true/false, same spellings as `bell` | false |
| `color` | auto, always, never | auto |

Command-line flags always win over config values.

### Color

`--color auto` (the default) colors output only when stdout is a terminal and
the `NO_COLOR` environment variable is not set. `--color always` and
`--color never` force it either way. The option works before or after the
subcommand.

### Exit codes

| Code | Meaning |
| --- | --- |
| 0 | success |
| 1 | could not write an output file |
| 2 | usage error or invalid value |
| 130 | stopped with Ctrl+C |

## Development

```sh
git clone https://github.com/Chad9100/focusbell.git
cd focusbell
python -m venv .venv
. .venv/bin/activate          # Windows: .venv\Scripts\activate
python -m pip install -e ".[dev]"
pytest -q
```

The timer loop takes its `clock` and `sleep` functions as arguments, so the
tests drive a fake clock and a full four-block Pomodoro runs in milliseconds.
The desktop notifier is injected the same way, so tests never pop up real
notifications.
Tests point `FOCUSBELL_HOME` at a temporary directory and never touch your real
log. CI runs the suite on Ubuntu and Windows with Python 3.10, 3.12 and 3.13.

See [ROADMAP.md](ROADMAP.md) for what is planned next.

## License

MIT, see [LICENSE](LICENSE).
