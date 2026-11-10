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
                [--label TEXT | --task N] [--todo-file PATH] [--tally | --no-tally]
                [--no-bell] [--sound PATH | --no-sound]
                [--sound-break PATH] [--sound-work PATH]
                [--notify | --no-notify] [--seconds] [--color auto|always|never]
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

### Labels from todo.txt

If you keep a [todo.txt](http://todotxt.org) list, `--task N` uses line N of
it as the label, numbered the same way `todo.sh` numbers tasks. The priority,
creation date and `key:value` tags such as `due:2026-11-20` are dropped so the
label stays stable as those change; `+project` and `@context` words are kept.
Completed (`x ...`) and empty lines are refused with exit status 2 before the
timer starts. The todo file is only read, unless you ask for a tally (below).

Point focusbell at the file once with `focusbell config set todo_file PATH`
(stored as an absolute path, `~` allowed) or per run with `--todo-file PATH`,
which wins over the config key. `--task` and `--label` cannot be combined.

Real output with a three-line todo.txt whose third task is done:

```text
$ cat todo.txt
(A) 2026-11-01 Write chapter 2 +thesis @desk due:2026-11-20
Reply to Sam about the budget @email
x 2026-11-05 File expenses
$ focusbell start --seconds --work 3 --short 2 --long 2 --cycles 1 --task 1 --todo-file todo.txt --no-bell
focusbell: 1 x 3s work, 2s short breaks, 2s long break after every 1. p to pause, s to skip a break, Ctrl+C to stop.
Task 1: (A) 2026-11-01 Write chapter 2 +thesis @desk due:2026-11-20
Work 1/1: 00:03 left  [Write chapter 2 +thesis @desk]
Work block 1 done. Long break next.
Long break: 00:02 left  [Write chapter 2 +thesis @desk]
All done. Nice work.
Focused 3s: 1 of 1 work block(s) completed.
$ focusbell start --task 3 --todo-file todo.txt
focusbell: error: task 3 is already done: x 2026-11-05 File expenses
$ focusbell start --task 1
focusbell: error: --task needs a todo.txt: pass --todo-file PATH or run `focusbell config set todo_file PATH`
```

The logged record is the usual one, with the cleaned text as its label:

```json
{"start": "2026-11-10T03:13:13+00:00", "end": "2026-11-10T03:13:16+00:00", "minutes": 0.05, "planned_minutes": 0.05, "label": "Write chapter 2 +thesis @desk", "status": "completed"}
```

#### Counting pomodoros on the task

With `--tally` (or `focusbell config set tally true`; `--no-tally` turns it
off for one run), each completed work block adds one to a `pomodoros:N` tag
on the `--task` line, appending `pomodoros:1` if the line has none. Only that
tag changes: every other line, tag, line ending (LF or CRLF), a UTF-8 BOM and
a missing final newline are kept byte for byte, and the file is replaced
atomically through a temp file in the same folder, so an editor or sync tool
never sees half a file. The count is written after each block, so a block
you stop with Ctrl+C is not counted but the ones before it are. The label
ignores `key:value` tags, so it, the session log and `stats --by task` stay
the same as the count grows.

If the task line changed while the timer ran, focusbell looks for the exact
original line elsewhere in the file (for example after a new task was added
above it); if it is gone or appears more than once, the file is left alone
and one warning is printed after the timer. A `pomodoros:` tag that is not a
whole number is also left alone with a warning.

Real output with a todo.txt whose second task already has a counter:

```text
$ cat todo.txt
(A) 2026-11-01 Write chapter 2 +thesis @desk due:2026-11-20
Review PR 42 +focusbell pomodoros:2
x 2026-11-05 File expenses
$ focusbell start --seconds --work 3 --short 2 --long 2 --cycles 2 --task 2 --todo-file todo.txt --tally --no-bell
focusbell: 2 x 3s work, 2s short breaks, 2s long break after every 2. p to pause, s to skip a break, Ctrl+C to stop.
Task 2: Review PR 42 +focusbell pomodoros:2
Work 1/2: 00:03 left  [Review PR 42 +focusbell]
Work block 1 done. Short break next.
Short break: 00:02 left  [Review PR 42 +focusbell]
Short break over. Back to work.
Work 2/2: 00:03 left  [Review PR 42 +focusbell]
Work block 2 done. Long break next.
Long break: 00:02 left  [Review PR 42 +focusbell]
All done. Nice work.
Focused 6s: 2 of 2 work block(s) completed.
Task 2: pomodoros:4 (+2) in todo.txt
$ focusbell start --seconds --work 3 --short 2 --long 2 --cycles 1 --task 1 --todo-file todo.txt --tally --no-bell
focusbell: 1 x 3s work, 2s short breaks, 2s long break after every 1. p to pause, s to skip a break, Ctrl+C to stop.
Task 1: (A) 2026-11-01 Write chapter 2 +thesis @desk due:2026-11-20
Work 1/1: 00:03 left  [Write chapter 2 +thesis @desk]
Work block 1 done. Long break next.
Long break: 00:02 left  [Write chapter 2 +thesis @desk]
All done. Nice work.
Focused 3s: 1 of 1 work block(s) completed.
Task 1: pomodoros:1 (+1) in todo.txt
$ cat todo.txt
(A) 2026-11-01 Write chapter 2 +thesis @desk due:2026-11-20 pomodoros:1
Review PR 42 +focusbell pomodoros:4
x 2026-11-05 File expenses
$ focusbell stats --by task --todo-file todo.txt --days 1
Focus time by task, last 1 day(s) (2026-11-09 to 2026-11-09)

#  Task                           Completed  Focus  Share  Last
-  -----------------------------  ---------  -----  -----  ----------
2  Review PR 42 +focusbell              2/2     0m    67%  2026-11-09
1  Write chapter 2 +thesis @desk        1/1     0m    33%  2026-11-09

Total       0m in 3 session(s) across 2 label(s)
```

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

### Sound files

`--sound PATH` plays a WAV file at every transition instead of the terminal
bell, again with no extra Python packages:

| Platform | Player |
| --- | --- |
| Windows | `winsound` (standard library) |
| macOS | `afplay` |
| Linux | `paplay` (PulseAudio/PipeWire), else `aplay` (ALSA) |

The file is checked before the timer starts: a missing file or anything that
is not a RIFF/WAVE file is refused with exit code 2. Sounds play in the
background so the countdown never waits for them; on Windows the last one
(after the final phase) plays to the end before focusbell exits. If no player
is installed or playback fails, focusbell rings the terminal bell instead, so
a transition is never silent by accident. Real output from this Windows PC
(the WAV played; there are no bell characters in the output):

```text
$ focusbell start --seconds --work 2 --short 1 --long 1 --cycles 1 --label demo --sound ding.wav | cat
focusbell: 1 x 2s work, 1s short breaks, 1s long break after every 1. p to pause, s to skip a break, Ctrl+C to stop.
Work 1/1: 00:02 left  [demo]
Work block 1 done. Long break next.
Long break: 00:01 left  [demo]
All done. Nice work.
Focused 2s: 1 of 1 work block(s) completed.
$ focusbell start --sound notes.wav
focusbell: error: not a WAV file: notes.wav (only RIFF/WAVE files are supported)
```

Make it the default with `focusbell config set sound PATH` (an absolute path
is safest, since a relative one is read from the current directory).
`--no-sound` goes back to the bell for one run, and `--no-bell` silences both.
A configured file that has gone missing does not block a session: focusbell
warns and uses the bell:

```text
$ focusbell config set sound moved.wav
sound = "moved.wav"
$ focusbell start --seconds --work 1 --short 1 --long 1 --cycles 1
focusbell: warning: sound file not found: moved.wav (from the sound config key); using the terminal bell
```

#### Different sounds for breaks and work

`--sound-break PATH` plays when a break starts and when the whole session
ends; `--sound-work PATH` plays when a break ends and it is time to work
again. Each falls back to `--sound` (and then the bell), so you can set just
one of them. The config keys are `sound_break` and `sound_work`. Real output
from this Windows PC (break.wav played three times, work.wav once, and the
bell never rang):

```text
$ focusbell start --seconds --work 2 --short 1 --long 1 --cycles 2 --sound-break break.wav --sound-work work.wav | cat
focusbell: 2 x 2s work, 1s short breaks, 1s long break after every 2. p to pause, s to skip a break, Ctrl+C to stop.
Work 1/2: 00:02 left
Work block 1 done. Short break next.
Short break: 00:01 left
Short break over. Back to work.
Work 2/2: 00:02 left
Work block 2 done. Long break next.
Long break: 00:01 left
All done. Nice work.
Focused 4s: 2 of 2 work block(s) completed.
$ focusbell start --sound-work work.wav --no-sound
focusbell: error: --sound-work cannot be combined with --no-sound
```

The same rules as `--sound` apply: a bad file given on the command line is
refused, a missing configured `sound_break` or `sound_work` file is skipped
with a warning, and `--no-sound` ignores all three config keys.

### Pause and resume

When stdin is a terminal, press **p** to pause the current phase and **p**
again to resume. On a terminal the countdown freezes and shows
`paused, p to resume`; time spent paused pushes the end of the phase back and
is not counted as focus time. Keys are read without blocking (`msvcrt` on
Windows, `termios` cbreak mode on Linux/macOS, restored on exit), so nothing
needs Enter and nothing is echoed. When stdin is not a terminal the timer runs
exactly as before and the banner only mentions Ctrl+C.

Real output from a demo where `p` was typed into the console about 2 s into
the work block and again 5 s later (stdout redirected to a file, so the plain
line format is used):

```text
$ focusbell start --seconds --work 8 --short 2 --long 2 --cycles 1 --label demo --no-bell
focusbell: 1 x 8s work, 2s short breaks, 2s long break after every 1. p to pause, s to skip a break, Ctrl+C to stop.
Work 1/1: 00:08 left  [demo]
Work 1/1: paused at 00:06 left  [demo]. Press p to resume.
Work 1/1: resumed, 00:06 left  [demo]
Work 1/1: 00:05 left  [demo]
Work block 1 done. Long break next.
Long break: 00:02 left  [demo]
All done. Nice work.
Focused 8s: 1 of 1 work block(s) completed. Paused 1 time(s), 5s in total.
```

The logged block keeps its 8 s of focus in `minutes`, while `end` is the real
wall-clock end, and the pause is recorded alongside it:

```json
{"start": "2026-11-10T02:27:25+00:00", "end": "2026-11-10T02:27:38+00:00", "minutes": 0.13, "planned_minutes": 0.13, "label": "demo", "status": "completed", "pauses": 1, "paused_minutes": 0.08}
```

`focusbell log` then adds a note to its footer, e.g.
`1 session(s), 0m focused. 1 pause(s) in 1 session(s), 0m on hold (not counted).`
Pressing Ctrl+C while paused logs only the time actually worked.

### Skip a break

When stdin is a terminal, press **s** during a short or long break to end it
right away and start the next work block (or finish, if it was the last
break). It works while the break is paused too; `s` during a work block is
ignored. A skipped break rings no bell and sends no desktop notification,
since you are evidently at the keyboard. Skipping adds nothing to the session
log, which only records work blocks; the end-of-session summary counts the
skipped breaks.

Real output from a demo where `s` was typed into the console a few seconds
into the short break and again a few seconds into the long break (stdout
redirected to a file):

```text
$ focusbell start --seconds --work 3 --short 30 --long 30 --cycles 2 --label demo --no-bell
focusbell: 2 x 3s work, 30s short breaks, 30s long break after every 2. p to pause, s to skip a break, Ctrl+C to stop.
Work 1/2: 00:03 left  [demo]
Work block 1 done. Short break next.
Short break: 00:30 left  [demo]
Short break skipped. Back to work.
Work 2/2: 00:03 left  [demo]
Work block 2 done. Long break next.
Long break: 00:30 left  [demo]
Long break skipped. All done. Nice work.
Focused 6s: 2 of 2 work block(s) completed. Skipped 2 break(s).
```

The whole session took about 13 s instead of 66 s. On a terminal the
countdown line stops at the time that was left and is marked `skipped`.

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
you have not started today yet. Below it come two all-time records over the
whole log, whatever the window (see [Longest streak and best
week](#longest-streak-and-best-week); the examples above were captured
before those rows existed).

If the terminal cannot encode the block characters (for example output
redirected on Windows with code page 1252), the bars fall back to ASCII:

```text
$ focusbell stats --days 3
Focus time, last 3 day(s) (2026-11-07 to 2026-11-09)

Sat 11-07  ##############################   1h 40m
Sun 11-08  ######################........   1h 15m
Mon 11-09  ##################............   1h 02m
```

### Longest streak and best week

After `Streak`, `focusbell stats` shows the longest run of consecutive active
days and the Monday-to-Sunday week with the most focus time, searched over the
whole log rather than the `--days` window. Real output from a temporary
`FOCUSBELL_HOME` with a few made-up sessions (a busy week in October, then
quieter ones), run on Tuesday 2026-11-10:

```text
$ focusbell stats --days 3
Focus time, last 3 day(s) (2026-11-08 to 2026-11-10)

Sun 11-08  ..............................       0m
Mon 11-09  ##############################      50m
Tue 11-10  ###############...............      25m

Total       1h 15m in 2 session(s), avg 25m/day
Completed   2 of 2 (100%), 0 interrupted
Top labels  thesis (1h 15m)
Streak      2 day(s)
Best streak 5 day(s), 2026-10-19 to 2026-10-23
Best week   6h 40m, week of 2026-10-19
```

Days and weeks are local and split at midnight like the daily chart; days
after today are ignored. On a tie the more recent streak or week wins. When
the best streak is the one still running it is marked `(current)`, and the
best week gets `(this week)` if it is the current week (counted so far). With
an empty log the rows read `0 day(s)` and `-`. `stats --by task` does not show
them.

### Weekly goal

Set a target for focus time per week, in minutes:

```text
$ focusbell config set weekly_goal 600
weekly_goal = 600
$ focusbell config set weekly_goal 20000
focusbell: error: weekly_goal must be between 0 and 10080, got 20000
```

Weeks run Monday to Sunday in local time, and minutes are split at midnight
the same way as the daily chart, so a block that starts late on Sunday counts
partly toward each week. Interrupted blocks count with the minutes actually
worked. `focusbell config set weekly_goal 0` turns the goal off again.

With a goal set, `focusbell stats` adds a progress bar for the current week
(whatever `--days` window the chart shows), and `focusbell start` ends with a
one-line summary that already includes the blocks just finished. Real output
from a temporary `FOCUSBELL_HOME` with a few made-up sessions, run on Tuesday
2026-11-10 with output redirected (hence the ASCII bars):

```text
$ focusbell stats --days 3
Focus time, last 3 day(s) (2026-11-08 to 2026-11-10)

Sun 11-08  ####################..........      50m
Mon 11-09  ####################..........      50m
Tue 11-10  ##############################   1h 15m

Total       2h 55m in 5 session(s), avg 58m/day
Completed   5 of 5 (100%), 0 interrupted
Top labels  thesis (2h 05m), code review (25m), email (25m)
Streak      3 day(s)
Week goal   ####................  2h 05m of 10h 00m (20%), 7h 55m to go, 6 day(s) left
$ focusbell start --seconds --work 3 --short 2 --long 2 --cycles 1 --label demo --no-bell
focusbell: 1 x 3s work, 2s short breaks, 2s long break after every 1. Ctrl+C to stop.
Work 1/1: 00:03 left  [demo]
Work block 1 done. Long break next.
Long break: 00:02 left  [demo]
All done. Nice work.
Focused 3s: 1 of 1 work block(s) completed.
This week: 2h 05m of 10h 00m goal (20%), 7h 55m to go, 6 day(s) left.
```

The 50 minutes on Sunday belong to the previous week. "Days left" counts
today. The percentage is rounded down, so 100% only shows once the goal is
met; after that the line says `goal met` instead of what is left (shown in
green when color is on) and the percentage keeps going past 100.

### Stats by task

`focusbell stats --by task` swaps the daily chart for a table of focus time
per label over the same `--days` window: completed/logged blocks, focus
minutes, share of the total and the last day worked. Sessions are counted on
the local day they started; unlabelled sessions are grouped as `(no label)`
at the bottom.

When a todo.txt is known (`--todo-file PATH`, or the `todo_file` config key),
each row whose label matches a task gets that task's line number in a `#`
column, so you can go straight back to it with `start --task N`. Done tasks
match too and are shown as `x3`; if the same task appears both open and done,
the open line wins. Open tasks with no focus time in the window are listed
underneath. Labels that are not in the file show `-`. An explicit
`--todo-file` that cannot be read is an error (exit 2); a stale `todo_file`
config key only warns and the table is shown without numbers.

Real output from a temporary `FOCUSBELL_HOME` holding a made-up week of
sessions, plus one real `--seconds` block started with `--task 5` (which is
why "Plan next sprint" shows 0m), run on 2026-11-09:

```text
$ cat todo.txt
(A) 2026-11-01 Write chapter 2 +thesis @desk due:2026-11-20
Reply to Sam about the budget @email
x 2026-11-06 2026-11-02 File expenses
(B) Review PR 42 +focusbell
Plan next sprint
$ focusbell stats --by task --todo-file todo.txt
Focus time by task, last 7 day(s) (2026-11-03 to 2026-11-09)

#   Task                           Completed   Focus  Share  Last
--  -----------------------------  ---------  ------  -----  ----------
1   Write chapter 2 +thesis @desk        3/4  1h 27m    42%  2026-11-07
4   Review PR 42 +focusbell              2/2     50m    24%  2026-11-08
x3  File expenses                        1/1     25m    12%  2026-11-04
-   standup notes                        1/1     25m    12%  2026-11-09
5   Plan next sprint                     1/1      0m     0%  2026-11-09
-   (no label)                           0/1     18m     9%  2026-11-09

Total       3h 25m in 10 session(s) across 6 label(s)
No focus time yet on open task(s) 2
```

Without a todo file the `#` column is left out:

```text
$ focusbell stats --by task --days 1
Focus time by task, last 1 day(s) (2026-11-09 to 2026-11-09)

Task              Completed  Focus  Share  Last
----------------  ---------  -----  -----  ----------
standup notes           1/1    25m    58%  2026-11-09
Plan next sprint        1/1     0m     0%  2026-11-09
(no label)              0/1    18m    42%  2026-11-09

Total       43m in 3 session(s) across 3 label(s)
```

Labels longer than 48 characters are shortened with `...`.

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

### Notes

```text
$ focusbell note stuck on the proof of lemma 2
Noted the 2026-11-09 10:00 session (thesis): stuck on the proof of lemma 2
$ focusbell log
Date        Start  End    Minutes  Status       Label   Note
----------  -----  -----  -------  -----------  ------  -----------------------------
2026-11-09  09:00  09:25     25.0  completed    thesis  -
2026-11-09  09:30  09:41     11.5  interrupted  email   -
2026-11-09  10:00  10:25     25.0  completed    thesis  stuck on the proof of lemma 2

3 session(s), 1h 02m focused.
```

`focusbell note TEXT` attaches a note to the most recent session (by start
time). A second note replaces the first. The log is rewritten atomically and
every other line is left untouched. `log` shows a Note column once any session
has a note; `export` adds it to CSV (a trailing `note` column) and JSON (a
`note` key, only on noted sessions). The HTML report gets a Note column when
any listed session has a note, and the ics export appends the note to the
event description.

To note an earlier session, pass the local start time shown by `log`
(output from a real run):

```text
$ focusbell note --start "2026-11-09 09:00" outline done
Noted the 2026-11-09 09:00 session (thesis): outline done
$ focusbell note --start "2026-11-09 09:01" x
focusbell: error: no session started at 2026-11-09 09:01 (see `focusbell log`)
```

### Relabel

Fix a typo or rename a label after the fact (output from a real run):

```text
$ focusbell relabel email
Relabelled the 2026-11-09 10:00 session: emial -> email
$ focusbell relabel --start "2026-11-09 09:00" thesis ch2
Relabelled the 2026-11-09 09:00 session: thesis -> thesis ch2
$ focusbell relabel --start "2026-11-09 09:01" x
focusbell: error: no session started at 2026-11-09 09:01 (see `focusbell log`)
```

Like `note`, it targets the latest session unless `--start` picks one, and the
log is rewritten atomically with every other line left byte for byte.

### Export

```text
$ focusbell export --format csv
start,end,minutes,planned_minutes,label,status,note
2026-11-04T09:00:00-08:00,2026-11-04T09:25:00-08:00,25.0,25.0,thesis,completed,
2026-11-05T10:00:00-08:00,2026-11-05T10:25:00-08:00,25.0,25.0,email,completed,
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

```text
$ focusbell export --format ics --output focus.ics
Exported 2 session(s) to focus.ics
$ focusbell export --format ics
BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//focusbell//focus sessions//EN
CALSCALE:GREGORIAN
BEGIN:VEVENT
UID:20261109T090000Z@focusbell
DTSTAMP:20261109T092500Z
DTSTART:20261109T090000Z
DTEND:20261109T092500Z
SUMMARY:Focus: thesis\, ch.2
DESCRIPTION:Completed: 25 min focused of 25 planned
END:VEVENT
...
```

`--format ics` writes one event per session (interrupted ones included, marked
in the description) with UTC times, CRLF line endings and escaped, folded text,
ready to import into any calendar app.

Add `--skip-interrupted` (any format) to leave interrupted sessions out. With
three logged sessions, one of them interrupted (output from a real run):

```text
$ focusbell export --skip-interrupted
start,end,minutes,planned_minutes,label,status,note
2026-11-09T09:00:00+00:00,2026-11-09T09:25:00+00:00,25.0,25.0,thesis,completed,
2026-11-09T10:00:00+00:00,2026-11-09T10:25:00+00:00,25.0,25.0,thesis,completed,
```

The CSV and JSON exports carry the session note (see below) when there is one.

### HTML report

```text
$ focusbell report --html focus.html
Wrote report for 182 day(s) to focus.html
```

Writes one self-contained page (inline CSS, no scripts, fonts or links, so it
works offline and can be mailed as a single file) with:

- totals for the period: focus time, sessions, completed blocks, active days
- a calendar heat map, one column per Monday-to-Sunday week, shaded in four
  steps relative to the busiest day; hover a cell for its date and minutes
- a per-label breakdown: sessions, completed, focus time, share, last day
- the session table, newest first, with interrupted blocks highlighted

`--days N` sets the period (ending today, default 182, at most 3660) and
`--html -` prints the page to stdout. Days are local calendar days, split at
midnight like `stats`. The page follows the system light/dark setting.

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
todo_file = ""
tally = false
weekly_goal = 0
sound = ""
sound_break = ""
sound_work = ""
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
| `todo_file` | path to a todo.txt for `--task` (empty = unset) | empty |
| `tally` | true/false: bump `pomodoros:N` on the `--task` line per completed block | false |
| `weekly_goal` | whole minutes 0 to 10080 of focus per week (0 = no goal) | 0 |
| `sound` | path to a WAV played instead of the bell (empty = bell) | empty |
| `sound_break` | WAV for "break starts" and "all done" (empty = use `sound`) | empty |
| `sound_work` | WAV for "back to work" (empty = use `sound`) | empty |

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
The desktop notifier and the sound player are injected the same way, so tests
never pop up real notifications or play sounds.
Tests point `FOCUSBELL_HOME` at a temporary directory and never touch your real
log. CI runs the suite on Ubuntu and Windows with Python 3.10, 3.12 and 3.13.

See [ROADMAP.md](ROADMAP.md) for what is planned next.

## License

MIT, see [LICENSE](LICENSE).
