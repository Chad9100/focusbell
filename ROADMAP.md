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

## v0.6: HTML report (about 3 h)

- [ ] `focusbell report --html out.html`: self-contained page with a calendar
      heat map, per-label breakdown and the session table
- [ ] No external assets, works offline

## v0.7: sound files (about 2 h)

- [ ] `--sound PATH` plays a WAV at transitions (`winsound` on Windows,
      `aplay`/`afplay` elsewhere), falling back to the terminal bell

## v1.0: release (about 3 h)

- [ ] Publish to PyPI with a trusted-publishing GitHub workflow
- [ ] Stable log format documented with a version field and migration notes
- [ ] Shell completion scripts; man-page style `--help` review

**Total for v0.4 to v1.0: about 17 hours.**
