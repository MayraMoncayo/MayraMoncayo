#!/usr/bin/env python3
"""Render the profile cards from profile.json + stats.json + ascii.json.

  dark_mode.svg / light_mode.svg   neofetch card: boot log -> typed prompt -> card printed line by line
  top_dark.svg  / top_light.svg    `top` card: what is running on Mayra right now

Everything that moves is CSS inside the SVG; GitHub renders the SVG as an <img> and browsers
play the animation. `prefers-reduced-motion` turns it off and shows the finished card.

profile.json "lines" mini-format:
  "Key: value"          -> "- Key: ........ value"  (dots right-align the value)
  "  Key: value"        -> same, indented one level (2 spaces per level)
  "Section"             -> "- Section" header (no ": ")
  ""                    -> blank line
  "Uptime: {uptime}"    -> live uptime
  "{stats}"             -> the GitHub Stats block (live numbers from stats.json)
"""
from __future__ import annotations

import datetime as dt
import html
import json
import re
from pathlib import Path

from dateutil.relativedelta import relativedelta

ROOT = Path(__file__).resolve().parent


def load(name, default=None):
    path = ROOT / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


PROFILE = load("profile.json")
STATS = load("stats.json") or {}
ART = load("ascii.json") or {"cols": 0, "dark": [], "light": []}

# ---- grid ---------------------------------------------------------------------------
FONT_SIZE, LINE_H, CHAR_W = 13, 17, 7.8      # textLength pins every line to CHAR_W per character
PAD_X, PAD_Y, GAP = 22, 22, 26
INFO_WIDTH = int(PROFILE.get("info_width", 64))
STATS_SPLIT = 38
BAR_BLOCKS = 36
FONT = "Consolas, Menlo, 'DejaVu Sans Mono', 'Courier New', monospace"

# ---- timeline (seconds) ---------------------------------------------------------------
BOOT_GAP, BOOT_HOLD = 0.13, 0.7    # per boot line / pause before the log clears
TYPE_CHAR, LINE_GAP = 0.04, 0.045  # per typed character / per printed line

THEMES = {
    "dark": {
        "bg": "#0d1117", "border": "#30363d", "art": "#c9d1d9", "fg": "#e6edf3", "cc": "#8b949e",
        "key": "#ffa657", "value": "#58a6ff", "add": "#3fb950", "del": "#f85149", "user": "#3fb950",
    },
    "light": {
        "bg": "#ffffff", "border": "#d0d7de", "art": "#24292f", "fg": "#1f2328", "cc": "#6e7781",
        "key": "#bc4c00", "value": "#0969da", "add": "#1a7f37", "del": "#cf222e", "user": "#1a7f37",
    },
}

esc = lambda s: html.escape(s, quote=False)
fmt = lambda n: f"{n:,}"
DOTS = object()  # sentinel: "fill this slot with dots"


# ---- text model: a line is a list of parts (class, text[, fill]) ------------------------

def plain(parts):
    return "".join(p[1] for p in parts)


def fill(parts, width):
    """Replace the DOTS sentinel so the run of parts is exactly `width` characters."""
    used = sum(len(p[1]) for p in parts if p[1] is not DOTS)
    n = max(1, width - used)
    return [("cc", "." * n) if p[1] is DOTS else p for p in parts]


def kv(indent, key, value):
    return fill([("cc", "  " * indent + "- "), ("key", key + ":"), ("cc", " "), ("cc", DOTS), ("cc", " "),
                 ("value", value)], INFO_WIDTH)


def section(indent, text):
    return [("cc", "  " * indent + "- "), ("fg", text)]


def prompt(command=""):
    parts = [("user", f"{PROFILE['user']}@{PROFILE['host']}"), ("fg", ":"), ("value", "~"), ("fg", "$ ")]
    return parts + ([("fg", command)] if command else [])


def uptime_text(today=None):
    today = today or dt.date.today()
    since = PROFILE.get("uptime_since") or STATS.get("created_at", "2010-01-01")[:10]
    since = dt.date.fromisoformat(since)
    d = relativedelta(today, since)
    unit = lambda n, w: f"{n} {w}{'' if n == 1 else 's'}"
    text = f"{unit(d.years, 'year')}, {unit(d.months, 'month')}, {unit(d.days, 'day')}"
    return text + (" 🎂" if (today.month, today.day) == (since.month, since.day) else "")


def sparkline(values):
    blocks = "▁▂▃▄▅▆▇█"
    top = max(values) if values else 0
    return "".join(blocks[round(v / top * 7)] if top else blocks[0] for v in values)


def stats_lines():
    s = STATS
    right = INFO_WIDTH - STATS_SPLIT - 3
    repos = fill([("cc", "  - "), ("key", "Repos:"), ("cc", " "), ("cc", DOTS), ("cc", " "),
                  ("value", fmt(s.get("repos", 0))), ("cc", " {"), ("key", "Contributed:"), ("cc", " "),
                  ("value", fmt(s.get("contributed", 0))), ("cc", "}")], STATS_SPLIT)
    stars = fill([("key", "Stars:"), ("cc", " "), ("cc", DOTS), ("cc", " "), ("value", fmt(s.get("stars", 0)))], right)
    commits = fill([("cc", "  - "), ("key", "Commits:"), ("cc", " "), ("cc", DOTS), ("cc", " "),
                    ("value", fmt(s.get("commits", 0)))], STATS_SPLIT)
    followers = fill([("key", "Followers:"), ("cc", " "), ("cc", DOTS), ("cc", " "),
                      ("value", fmt(s.get("followers", 0)))], right)
    add, dele = s.get("additions", 0), s.get("deletions", 0)
    loc = fill([("cc", "  - "), ("key", "Lines of Code on GitHub:"), ("cc", " "), ("cc", DOTS), ("cc", " "),
                ("value", fmt(add - dele)), ("cc", " ( "), ("add", fmt(add) + "++"), ("cc", ", "),
                ("del", fmt(dele) + "--"), ("cc", " )")], INFO_WIDTH)
    activity = fill([("cc", "  - "), ("key", "Activity (30d):"), ("cc", " "), ("cc", DOTS), ("cc", " "),
                     ("value", sparkline(s.get("activity", [0] * 30)))], INFO_WIDTH)
    sep = [("cc", " | ")]
    return [repos + sep + stars, commits + sep + followers, loc, activity]


KV_RE = re.compile(r"^ *(.+?): (.+)$")


def info_rows():
    """Right column of the neofetch card. Each row: ("typed"|"line", parts) or None for a blank."""
    rows = [("typed", prompt("neofetch"))]
    head = f"{PROFILE['user']}@{PROFILE['host']}"
    rows.append(("line", [("hdr", head), ("cc", " " + "─" * max(0, INFO_WIDTH - len(head) - 4))]))
    for raw in PROFILE["lines"]:
        stripped, indent = raw.strip(), (len(raw) - len(raw.lstrip(" "))) // 2
        m = KV_RE.match(raw.rstrip())
        if stripped == "":
            rows.append(None)
        elif stripped == "{stats}":
            rows.extend(("line", p) for p in stats_lines())
        elif m and m.group(2).strip() == "{uptime}":
            rows.append(("line", kv(indent, m.group(1).strip(), uptime_text())))
        elif m:
            rows.append(("line", kv(indent, m.group(1).strip(), m.group(2).strip())))
        else:
            rows.append(("line", section(indent, stripped)))
    rows += [None, ("line", prompt() + [("cursor", "▌")])]
    return rows


def language_bar():
    cfg = PROFILE.get("languages", {})
    langs = [l for l in STATS.get("languages", []) if l["name"] not in set(cfg.get("exclude", []))]
    total = sum(l["bytes"] for l in langs) or 1
    shown, parts = langs[: cfg.get("max", 5)], []
    for l in shown:
        pct = l["bytes"] / total
        parts += [("bar", "█" * max(1, round(pct * BAR_BLOCKS)), l.get("color") or None),
                  ("fg", f" {l['name']} {pct * 100:.0f}%  ")]
    rest = 1 - sum(l["bytes"] for l in shown) / total
    if rest > 0.005:
        parts += [("cc", "█" * max(1, round(rest * BAR_BLOCKS))), ("cc", f" other {rest * 100:.0f}%")]
    return parts


# ---- SVG helpers ------------------------------------------------------------------------

def tspan(part, delay=None):
    cls, text = part[0], part[1]
    # inline style, not a fill attribute: class rules in <style> would override a presentation attribute
    styles = ([f"fill:{part[2]}"] if len(part) > 2 and part[2] else []) + \
             ([f"animation-delay:{delay:.2f}s"] if delay is not None else [])
    style = f' style="{";".join(styles)}"' if styles else ""
    return f'<tspan class="{cls}"{style}>{esc(text)}</tspan>'


def text_el(x, y, parts, cls="", delay=None):
    n = len(plain(parts))
    if n == 0:
        return ""
    style = f' style="animation-delay:{delay:.2f}s"' if delay is not None else ""
    return (f'  <text class="{cls}" x="{x:.1f}" y="{y}" textLength="{n * CHAR_W:.1f}" lengthAdjust="spacing" '
            f'xml:space="preserve"{style}>{"".join(tspan(p) for p in parts)}</text>')


def typed_el(x, y, parts, t0):
    """One <tspan> per character, each appearing TYPE_CHAR seconds after the previous one."""
    spans, i = [], 0
    for cls, text in parts:
        for ch in text:
            spans.append(tspan((cls, ch), delay=t0 + i * TYPE_CHAR))
            i += 1
    return (f'  <text class="typed" x="{x:.1f}" y="{y}" textLength="{i * CHAR_W:.1f}" lengthAdjust="spacing" '
            f'xml:space="preserve">{"".join(spans)}</text>'), i


def cursor_el(x, y, n_chars, t0):
    """Block cursor that steps along the prompt while it is being typed, then disappears."""
    t1 = t0 + n_chars * TYPE_CHAR
    return (f'  <rect class="typing-cursor" x="{x:.1f}" y="{y - FONT_SIZE + 1}" width="{CHAR_W:.1f}" height="{LINE_H - 2}" '
            f'style="animation-delay:{t0:.2f}s,{t0:.2f}s,{t1 + 0.15:.2f}s;'
            f'animation-duration:0.01s,{n_chars * TYPE_CHAR:.2f}s,0.01s;'
            f'animation-timing-function:linear,steps({n_chars},end),linear;--travel:{n_chars * CHAR_W:.1f}px"/>')


def svg_doc(theme, width, height, body):
    t = THEMES[theme]
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" font-family="{FONT}" font-size="{FONT_SIZE}">
  <style>
    .art {{ fill: {t["art"]}; }}   .hdr {{ fill: {t["fg"]}; font-weight: bold; }}   .fg {{ fill: {t["fg"]}; }}
    .cc {{ fill: {t["cc"]}; }}     .key {{ fill: {t["key"]}; }}   .value {{ fill: {t["value"]}; }}
    .add {{ fill: {t["add"]}; }}   .del {{ fill: {t["del"]}; }}   .user {{ fill: {t["user"]}; font-weight: bold; }}
    .inv {{ fill: {t["bg"]}; }}    .bar {{ fill: {t["cc"]}; }}    .typing-cursor {{ fill: {t["fg"]}; opacity: 0; }}
    @keyframes appear {{ from {{ opacity: 0; }} to {{ opacity: 1; }} }}
    @keyframes vanish {{ from {{ opacity: 1; }} to {{ opacity: 0; }} }}
    @keyframes ink    {{ from {{ fill-opacity: 0; }} to {{ fill-opacity: 1; }} }}   /* tspans: opacity does not apply, fill-opacity does */
    @keyframes blink  {{ 0%, 55% {{ fill-opacity: 1; }} 56%, 100% {{ fill-opacity: 0; }} }}
    @keyframes travel {{ from {{ transform: translateX(0); }} to {{ transform: translateX(var(--travel)); }} }}
    .boot          {{ animation: vanish 0.25s linear forwards; }}
    .boot text     {{ opacity: 0; animation: appear 0.05s linear forwards; }}
    .typed tspan   {{ animation: ink 0.01s linear both; }}
    .typing-cursor {{ animation-name: appear, travel, vanish; animation-fill-mode: forwards, forwards, forwards; }}
    .line          {{ animation: appear 0.12s ease-out both; }}
    .cursor        {{ animation: blink 1s step-end infinite; }}
    @media (prefers-reduced-motion: reduce) {{
      * {{ animation: none !important; }}
      .boot {{ display: none; }}
    }}
  </style>
  <rect x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" rx="6" fill="{t["bg"]}" stroke="{t["border"]}"/>
{chr(10).join(b for b in body if b)}
</svg>
'''


# ---- cards -------------------------------------------------------------------------------

def neofetch_card(theme):
    art = ART.get(theme) or ART.get("dark") or []
    art_cols = ART.get("cols") or max((sum(len(t) for t, _ in r) for r in art), default=0)
    rows = info_rows()
    boot = PROFILE.get("boot", [])

    info_x = PAD_X + art_cols * CHAR_W + GAP
    width = round(info_x + INFO_WIDTH * CHAR_W + PAD_X)
    n_rows = max(len(rows), len(art)) + 2               # + blank + language bar
    height = round(PAD_Y + (n_rows - 1) * LINE_H + FONT_SIZE + PAD_Y)
    y = lambda i: PAD_Y + FONT_SIZE + i * LINE_H

    boot_end = len(boot) * BOOT_GAP + BOOT_HOLD
    t_type = boot_end + 0.35
    n_prompt = len(plain(rows[0][1]))
    t_print = t_type + n_prompt * TYPE_CHAR + 0.3

    body = [f'  <g class="boot" style="animation-delay:{boot_end:.2f}s">']
    for i, line in enumerate(boot):
        body.append(text_el(info_x, y(i), [("cc", "["), ("add", "  OK  "), ("cc", "] "), ("fg", line)],
                            delay=i * BOOT_GAP))
    body.append("  </g>")

    typed, n = typed_el(info_x, y(0), rows[0][1], t_type)
    body += [typed, cursor_el(info_x, y(0), n, t_type)]

    for i, row in enumerate(rows[1:], start=1):
        if row:
            body.append(text_el(info_x, y(i), row[1], cls="line", delay=t_print + (i - 1) * LINE_GAP))
    for i, runs in enumerate(art):
        parts = [("art", text, colour) for text, colour in runs]
        body.append(text_el(PAD_X, y(i), parts, cls="art line", delay=t_print + i * LINE_GAP))

    bar_delay = t_print + (n_rows - 2) * LINE_GAP + 0.1
    body.append(text_el(PAD_X, y(n_rows - 1), language_bar(), cls="line", delay=bar_delay))
    return svg_doc(theme, width, height, body), width


def top_card(theme, width):
    procs = PROFILE.get("top", [])
    user = PROFILE["user"]
    user = user if len(user) <= 9 else user[:8] + "+"   # top truncates long user names like this
    now = dt.datetime.now().strftime("%H:%M:%S")
    load = ", ".join(str(v) for v in STATS.get("load", [0, 0, 0]))
    running = sum(1 for p in procs if p["stat"] == "R")

    rows = [("typed", prompt("top -o cpu")),
            ("line", [("fg", f"top - {now} up {uptime_text()},  1 user,  load average: {load}")]),
            ("line", [("fg", "Tasks: "), ("hdr", str(len(procs))), ("fg", " total, "), ("hdr", str(running)),
                      ("fg", " running, "), ("hdr", str(len(procs) - running)), ("fg", " sleeping")]),
            None,
            ("header", [("inv", f"{'PID':>5} {'USER':<10} {'STAT':^4} {'%CPU':>5} {'TIME+':>6}  COMMAND")])]
    for i, p in enumerate(procs, start=1):
        rows.append(("line", [("cc", f"{i:>5} "), ("fg", f"{user:<10} "),
                              ("add" if p["stat"] == "R" else "cc", f"{p['stat']:^4} "),
                              ("value", f"{p['cpu']:>5} "), ("key", f"{p['time']:>6}  "), ("fg", p["cmd"])]))

    height = round(PAD_Y + (len(rows) - 1) * LINE_H + FONT_SIZE + PAD_Y)
    y = lambda i: PAD_Y + FONT_SIZE + i * LINE_H
    t_print = 0.2 + len(plain(rows[0][1])) * TYPE_CHAR + 0.3

    typed, n = typed_el(PAD_X, y(0), rows[0][1], 0.2)
    body = [typed, cursor_el(PAD_X, y(0), n, 0.2)]
    for i, row in enumerate(rows[1:], start=1):
        if not row:
            continue
        delay = t_print + (i - 1) * LINE_GAP
        if row[0] == "header":
            n_chars = len(plain(row[1]))
            body.append(f'  <rect class="line" x="{PAD_X - 4}" y="{y(i) - FONT_SIZE}" width="{width - 2 * PAD_X + 8}" '
                        f'height="{LINE_H}" fill="{THEMES[theme]["cc"]}" style="animation-delay:{delay:.2f}s"/>')
        body.append(text_el(PAD_X, y(i), row[1], cls="line", delay=delay))
    return svg_doc(theme, width, height, body)


if __name__ == "__main__":
    if STATS.get("sample"):
        print("note: stats.json holds sample numbers; the workflow replaces it on its first run")
    for theme, name, top_name in (("dark", "dark_mode.svg", "top_dark.svg"), ("light", "light_mode.svg", "top_light.svg")):
        svg, width = neofetch_card(theme)
        (ROOT / name).write_text(svg, encoding="utf-8")
        (ROOT / top_name).write_text(top_card(theme, width), encoding="utf-8")
        print(f"{name} + {top_name}: {width}px wide")
