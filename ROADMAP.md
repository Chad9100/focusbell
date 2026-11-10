# Roadmap

Estimates are rough working hours for one person.

## v0.1 (done)

- [x] `focusbell start` with work / short break / long break cycles and `--sets`
- [x] Live single-line countdown on a TTY, plain periodic lines otherwise
- [x] Terminal bell at each transition, `--no-bell`
- [x] Ctrl+C stops cleanly and logs the partial block as interrupted
- [x] JSON Lines session log in a per-user data dir, `FOCUSBELL_HOME` override
- [x] Corrupt log lines skipped with a warning
- [x] `focusbell log`, `stats` (daily bar chart, totals, completion rate, top labels, streak)
- [x] `focusbell config get|set` with range validation
- [x] `focusbell export --format csv|json`
- [x] `--color auto|always|never`, `NO_COLOR`, ASCII fallback for bars
- [x] Injectable clock/sleep; pytest suite; CI on Ubuntu and Windows

## v0.2: desktop notifications (about 4 h, done)

- [x] Notify at each transition: `notify-send` on Linux, `osascript` on macOS,
      a PowerShell toast on Windows (no new Python dependencies)
- [x] `--notify` flag and `notify` config key; silent fallback when unavailable
- [x] Tests with the notifier injected like the clock

## v0.3: pause and resume (about 4 h, done)

- [x] Press `p` to pause and resume when stdin is a terminal
- [x] Paused time excluded from logged minutes; pauses counted in the record
      (`pauses` and `paused_minutes`, written only for paused blocks)
- [x] Non-blocking key reading on Windows (`msvcrt`) and POSIX (`termios`)
- [x] Press `s` to skip the rest of a break (paused or not); ignored during
      work, no bell or notification for a skipped break, counted in the summary

## v0.4: todo.txt integration (about 3 h, done)

- [x] `--task N` picks the label from line N of a todo.txt file (priority,
      creation date and `key:value` tags stripped; done/empty lines refused)
- [x] `todo_file` config key and a `--todo-file PATH` override
- [x] `focusbell stats --by task`: focus time, completed blocks, share and
      last day per label, numbered from todo.txt (done tasks as `x3`), plus
      open tasks with no focus time
- [x] Optionally append a `pomodoros:N` tag to the task when a block completes
      (`--tally` / `tally` config key; atomic, byte-preserving write-back)

## v0.5: weekly goals (about 3 h, done)

- [x] `config set weekly_goal 600` (minutes, Monday-to-Sunday local weeks)
- [x] Goal progress bar in `stats` and a one-line summary after each session
- [x] Longest streak and best week in `stats` (all-time, whatever `--days`)

## v0.6: HTML report (about 3 h, done)

- [x] `focusbell report --html out.html`: self-contained page with a calendar
      heat map, per-label breakdown and the session table
- [x] No external assets, works offline

## v0.7: sound files (about 2 h, done)

- [x] `--sound PATH` plays a WAV at transitions (`winsound` on Windows,
      `afplay` on macOS, `paplay`/`aplay` on Linux), falling back to the
      terminal bell when no player works; `sound` config key, `--no-sound`
- [x] WAV header checked before the timer starts; a missing configured file
      only warns, so it never costs a session

## v0.8: richer sounds and notes (about 5 h)

- [x] Separate sounds for "break starts" and "back to work"
      (`--sound-break`, `--sound-work`, falling back to `--sound`;
      `sound_break` / `sound_work` config keys) (about 1 h)
- [ ] `focusbell note TEXT` attaches a note to the most recent session; notes
      shown in `log`, exported to CSV/JSON and listed in the HTML report
      (about 2 h)
- [ ] `focusbell relabel` to fix the label of the last session (or one picked
      by `--start`), rewriting the log atomically (about 2 h)

## v0.9: calendar export (about 3 h, export done)

- [x] `focusbell export --format ics`: one VEVENT per session (label as the
      summary, status in the description) for import into a calendar app
- [x] `export --skip-interrupted` drops interrupted sessions from any format
      (about 0.5 h)
- [ ] Break events in the ics export (needs break records in the log; about 1 h)

## v1.0: release (about 3 h)

- [ ] Publish to PyPI with a trusted-publishing GitHub workflow
- [ ] Stable log format documented with a version field and migration notes
- [ ] Shell completion scripts; man-page style `--help` review

**Total for v0.4 to v1.0: about 24 hours.**
