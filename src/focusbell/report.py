"""A self-contained HTML report: calendar heat map, per-label breakdown, sessions.

The page has inline CSS only (no scripts, fonts or images), so it opens
offline and can be mailed or archived as a single file.
"""

from __future__ import annotations

import math
from datetime import date, timedelta, tzinfo
from html import escape
from typing import Optional

from . import __version__
from .log import Session
from .render import fmt_minutes
from .stats import by_label, minutes_by_day, to_local, week_start

LEVELS = 4  # heat map shades above "nothing logged"
DAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

CSS = """
:root { --bg: #ffffff; --fg: #1f2328; --muted: #656d76; --line: #d0d7de;
  --l0: #ebedf0; --l1: #c6e48b; --l2: #7bc96f; --l3: #239a3b; --l4: #196127;
  --bar: #2da44e; --warn: #bf8700; }
@media (prefers-color-scheme: dark) {
  :root { --bg: #0d1117; --fg: #e6edf3; --muted: #8d96a0; --line: #30363d;
    --l0: #161b22; --l1: #0e4429; --l2: #006d32; --l3: #26a641; --l4: #39d353;
    --bar: #3fb950; --warn: #d29922; }
}
* { box-sizing: border-box; }
body { margin: 0; padding: 24px 16px; background: var(--bg); color: var(--fg);
  font: 14px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width: 960px; margin: 0 auto; }
h1 { font-size: 22px; margin: 0 0 4px; }
h2 { font-size: 16px; margin: 28px 0 8px; }
.muted { color: var(--muted); }
.totals { display: flex; flex-wrap: wrap; gap: 8px 24px; margin: 16px 0 0; padding: 0; list-style: none; }
.totals b { display: block; font-size: 18px; }
.scroll { overflow-x: auto; }
.heat { border-collapse: separate; border-spacing: 3px; }
.heat th { font-weight: normal; font-size: 11px; color: var(--muted); text-align: left; white-space: nowrap; }
.heat td { width: 12px; height: 12px; min-width: 12px; padding: 0; border-radius: 2px; }
.l0 { background: var(--l0); } .l1 { background: var(--l1); } .l2 { background: var(--l2); }
.l3 { background: var(--l3); } .l4 { background: var(--l4); }
.heat td.out { background: transparent; }
.legend { display: inline-flex; gap: 3px; vertical-align: middle; }
.legend span { width: 12px; height: 12px; border-radius: 2px; display: inline-block; }
table.data { border-collapse: collapse; width: 100%; }
table.data th, table.data td { padding: 4px 8px; border-bottom: 1px solid var(--line); text-align: left; }
table.data td.num, table.data th.num { text-align: right; font-variant-numeric: tabular-nums; }
.share { display: inline-block; height: 8px; background: var(--bar); border-radius: 2px; vertical-align: middle; }
.interrupted { color: var(--warn); }
"""


def _level(minutes: float, maximum: float) -> int:
    """0 for an empty day, otherwise 1..LEVELS relative to the busiest day."""
    if minutes <= 0 or maximum <= 0:
        return 0
    return max(1, min(LEVELS, math.ceil(round(minutes / maximum * LEVELS, 9))))


def _heat_map(per_day: dict[date, float], first: date, last: date) -> list[str]:
    """Rows Monday..Sunday, one column per week, days outside the range blank."""
    monday = week_start(first)
    weeks = (week_start(last) - monday).days // 7 + 1
    maximum = max((m for d, m in per_day.items() if first <= d <= last), default=0.0)
    out = ['<div class="scroll"><table class="heat" aria-label="Focus minutes per day">']
    # Month labels over the first column of each new month.
    cells = ["<th></th>"]
    prev_month = None
    for w in range(weeks):
        col_monday = monday + timedelta(weeks=w)
        start_day = max(col_monday, first)
        label = ""
        if start_day.month != prev_month:
            label = start_day.strftime("%b")
            prev_month = start_day.month
        cells.append(f"<th>{label}</th>")
    out.append("<tr>" + "".join(cells) + "</tr>")
    for row in range(7):
        name = DAY_NAMES[row] if row % 2 == 0 else ""
        cells = [f"<th>{name}</th>"]
        for w in range(weeks):
            day = monday + timedelta(weeks=w, days=row)
            if not first <= day <= last:
                cells.append('<td class="out"></td>')
                continue
            minutes = per_day.get(day, 0.0)
            tip = f"{day.isoformat()} {DAY_NAMES[row]}: {fmt_minutes(minutes)}"
            cells.append(f'<td class="l{_level(minutes, maximum)}" title="{tip}"></td>')
        out.append("<tr>" + "".join(cells) + "</tr>")
    out.append("</table></div>")
    legend = "".join(f'<span class="l{i}"></span>' for i in range(LEVELS + 1))
    out.append(f'<p class="muted">Less <span class="legend">{legend}</span> More'
               f" (busiest day {fmt_minutes(maximum)})</p>")
    return out


def render_html(
    sessions: list[Session],
    today: date,
    days: int,
    tz: Optional[tzinfo] = None,
    generated: Optional[str] = None,
) -> str:
    """The whole report page for the ``days`` local days ending ``today``."""
    if days < 1:
        raise ValueError("days must be at least 1")
    first = today - timedelta(days=days - 1)
    per_day = minutes_by_day(sessions, tz)
    in_range = [s for s in sessions if first <= to_local(s.start, tz).date() <= today]
    total = sum(m for d, m in per_day.items() if first <= d <= today)
    completed = sum(1 for s in in_range if s.status == "completed")
    active = sum(1 for d, m in per_day.items() if first <= d <= today and m > 0)

    h: list[str] = [
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        "<title>focusbell report</title>",
        f"<style>{CSS}</style>",
        "</head>",
        "<body><main>",
        "<h1>focusbell report</h1>",
        f'<p class="muted">{first.isoformat()} to {today.isoformat()} ({days} day(s))'
        + (f", generated {escape(generated)}" if generated else "")
        + f" by focusbell {escape(__version__)}</p>",
        '<ul class="totals">',
        f"<li><b>{fmt_minutes(total)}</b><span class=\"muted\">focused</span></li>",
        f"<li><b>{len(in_range)}</b><span class=\"muted\">session(s)</span></li>",
        f"<li><b>{completed}</b><span class=\"muted\">completed</span></li>",
        f"<li><b>{active}</b><span class=\"muted\">active day(s)</span></li>",
        "</ul>",
        "<h2>Calendar</h2>",
    ]
    h += _heat_map(per_day, first, today)

    h.append("<h2>By label</h2>")
    groups = by_label(sessions, first, today, tz)
    if not groups:
        h.append('<p class="muted">No sessions in this period.</p>')
    else:
        label_total = sum(g.minutes for g in groups) or 1.0
        h.append('<div class="scroll"><table class="data"><thead><tr><th>Label</th>'
                 '<th class="num">Sessions</th><th class="num">Completed</th>'
                 '<th class="num">Focus</th><th>Share</th><th>Last</th></tr></thead><tbody>')
        for g in groups:
            share = g.minutes / label_total
            name = escape(g.label) if g.label else '<span class="muted">(no label)</span>'
            h.append(
                f"<tr><td>{name}</td><td class=\"num\">{g.sessions}</td>"
                f"<td class=\"num\">{g.completed}</td><td class=\"num\">{fmt_minutes(g.minutes)}</td>"
                f'<td><span class="share" style="width:{share * 120:.0f}px"></span> {share:.0%}</td>'
                f"<td>{g.last_day.isoformat()}</td></tr>"
            )
        h.append("</tbody></table></div>")

    h.append("<h2>Sessions</h2>")
    if not in_range:
        h.append('<p class="muted">No sessions in this period.</p>')
    else:
        h.append('<div class="scroll"><table class="data"><thead><tr><th>Date</th><th>Start</th>'
                 '<th>End</th><th class="num">Minutes</th><th>Status</th><th>Label</th>'
                 "</tr></thead><tbody>")
        for s in sorted(in_range, key=lambda s: s.start, reverse=True):
            start = to_local(s.start, tz)
            end = to_local(s.end, tz)
            status = escape(s.status)
            if s.status != "completed":
                status = f'<span class="interrupted">{status}</span>'
            h.append(
                f"<tr><td>{start:%Y-%m-%d}</td><td>{start:%H:%M}</td><td>{end:%H:%M}</td>"
                f'<td class="num">{s.minutes:.1f}</td><td>{status}</td>'
                f"<td>{escape(s.label) if s.label else '-'}</td></tr>"
            )
        h.append("</tbody></table></div>")
    h.append("</main></body>")
    h.append("</html>")
    return "\n".join(h) + "\n"
