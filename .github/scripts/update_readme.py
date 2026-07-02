#!/usr/bin/env python3
"""Regenerate README.md + assets/hero-terminal.svg with live GitHub data.

Two live layers:
  - shields.io star badges refresh on every page view
  - this script (GitHub Actions, every 6h) refreshes which repos appear in the
    highlights grid AND re-renders the animated terminal hero with current
    star counts / follower count baked in
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

USER = "fivetaku"
TOP_N = 8
PLUGIN_COUNT = 14  # plugins in the gptaku_plugins marketplace
INSANE_PREFIX = "insane-"  # showcased in their own section, excluded from grid

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / ".github" / "README.template.md"
OUTPUT = ROOT / "README.md"
HERO = ROOT / "assets" / "hero-terminal.svg"
TILES = ROOT / "assets" / "stat-tiles.svg"


def fmt_stars(n: int) -> str:
    if n >= 1000:
        return f"{n / 1000:.1f}k".replace(".0k", "k")
    return str(n)


def static_badge(count: int, style: str) -> str:
    # Static badge: no GitHub API call behind it, so it can never come back
    # as "invalid" when shields' API quota is rate-limited. The count itself
    # is refreshed every 6h by this script (URL change also busts camo cache).
    return (
        f"https://img.shields.io/badge/stars-{fmt_stars(count)}-F97316"
        f"?style={style}&labelColor=0D1117&logo=github&logoColor=white"
    )

# ---------------------------------------------------------------- GitHub API

def _gh(args: list[str]) -> str:
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        sys.exit("GH_TOKEN or GITHUB_TOKEN env var is required")
    env = {**os.environ, "GH_TOKEN": token}
    return subprocess.check_output(["gh", "api", *args], env=env, text=True)


def fetch_repos() -> list[dict]:
    out = _gh(["--paginate", f"users/{USER}/repos?per_page=100"])
    # --paginate concatenates JSON arrays: "[...][...]" -> normalize
    repos: list[dict] = []
    decoder = json.JSONDecoder()
    idx = 0
    while idx < len(out):
        chunk, end = decoder.raw_decode(out, idx)
        repos.extend(chunk)
        idx = end
        while idx < len(out) and out[idx] in " \n\r\t":
            idx += 1
    return [r for r in repos if not r.get("fork") and not r.get("private") and r["name"] != USER]


def fetch_followers() -> int:
    return int(json.loads(_gh([f"users/{USER}"])).get("followers", 0))


# ---------------------------------------------------------- highlights table

def render_highlights(repos: list[dict]) -> str:
    rows: list[str] = ["<table>"]
    for i in range(0, len(repos), 2):
        pair = repos[i:i + 2]
        rows.append("  <tr>")
        for repo in pair:
            name = repo["name"]
            desc = (repo.get("description") or "").replace("|", "&#124;").strip()
            badge = static_badge(repo.get("stargazers_count", 0), "flat")
            rows.append("    <td width=\"50%\" valign=\"top\">")
            rows.append(
                f"      <a href=\"https://github.com/{USER}/{name}\"><b>{name}</b></a>"
                f"&nbsp;<a href=\"https://github.com/{USER}/{name}/stargazers\">"
                f"<img src=\"{badge}\" alt=\"stars\" /></a><br/>"
            )
            if desc:
                rows.append(f"      <sub>{desc}</sub>")
            rows.append("    </td>")
        if len(pair) == 1:
            rows.append("    <td width=\"50%\"></td>")
        rows.append("  </tr>")
    rows.append("</table>")
    return "\n".join(rows)


# ------------------------------------------------------------- hero terminal
# Animated SVG that replays a Claude Code session. SMIL only (works through
# GitHub's camo proxy). Typed lines reveal via discrete clip-path steps,
# output lines fade in, final cursor blinks forever.

W = 880
MARGIN_X = 28
BODY_TOP = 62
LINE_H = 25
CHAR_W = 9.05  # 15px monospace advance (Menlo/SF Mono)

ORANGE = "#F97316"
INDIGO = "#818CF8"
TEXT = "#E6EDF3"
MUTED = "#8B949E"
GREEN = "#3FB950"


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def tspans(segments: list[tuple[str, str]]) -> str:
    parts = []
    for txt, fill in segments:
        bold = ' font-weight="700"' if fill.startswith("url(") else ""
        parts.append(f'<tspan fill="{fill}"{bold}>{esc(txt)}</tspan>')
    return "".join(parts)


def render_hero(lines: list[tuple], total_dur_out: list[float]) -> str:
    defs: list[str] = []
    body: list[str] = []
    t = 0.6
    y = BODY_TOP
    last_chars = 0

    for i, line in enumerate(lines):
        kind = line[0]
        if kind == "blank":
            y += LINE_H - 8
            continue
        segments = line[1]
        plain = "".join(s for s, _ in segments)
        if kind == "typed":
            chars = len(plain)
            dur = max(0.5, chars * 0.045)
            max_w = chars * CHAR_W + 14
            steps = min(chars, 60)
            values = ";".join(f"{max_w * k / steps:.1f}" for k in range(steps + 1))
            key_times = ";".join(f"{k / steps:.4f}" for k in range(steps + 1))
            defs.append(
                f'<clipPath id="tc{i}"><rect x="{MARGIN_X}" y="{y - 17}" width="0" height="23">'
                f'<animate attributeName="width" begin="{t:.2f}s" dur="{dur:.2f}s" fill="freeze" '
                f'calcMode="discrete" values="{values}" keyTimes="{key_times}"/>'
                f"</rect></clipPath>"
            )
            body.append(
                f'<text x="{MARGIN_X}" y="{y}" clip-path="url(#tc{i})">{tspans(segments)}</text>'
            )
            t += dur + 0.12
        else:  # out
            body.append(
                f'<text x="{MARGIN_X}" y="{y}" opacity="0">{tspans(segments)}'
                f'<animate attributeName="opacity" begin="{t:.2f}s" dur="0.4s" values="0;1" fill="freeze"/>'
                f"</text>"
            )
            t += 0.5
        last_chars = len(plain)
        y += LINE_H

    total_dur_out.append(t)
    height = y - LINE_H + 26

    # blinking block cursor after the last line (rect: SMIL-safe everywhere)
    cursor_x = MARGIN_X + last_chars * 8.9 + 4
    cursor_y = y - LINE_H - 14
    body.append(
        f'<rect x="{cursor_x:.0f}" y="{cursor_y}" width="9" height="17" fill="{ORANGE}" opacity="0">'
        f'<animate attributeName="opacity" begin="{t:.2f}s" dur="1.1s" '
        f'calcMode="discrete" values="1;0" repeatCount="indefinite"/></rect>'
    )
    defs_s = "\n    ".join(defs)
    body_s = "\n  ".join(body)

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{height}" viewBox="0 0 {W} {height}" role="img" aria-label="GPTaku — live Claude Code session">
  <style>
    text {{ font-family: 'SF Mono', SFMono-Regular, Menlo, Consolas, 'Liberation Mono', monospace; font-size: 15px; }}
    .title {{ font-size: 12.5px; }}
  </style>
  <defs>
    <linearGradient id="brand" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="{ORANGE}"/>
      <stop offset="1" stop-color="{INDIGO}"/>
    </linearGradient>
    {defs_s}
  </defs>

  <rect x="0.5" y="0.5" width="{W - 1}" height="{height - 1}" rx="12" fill="#0D1117" stroke="#30363D"/>
  <path d="M 0.5 12 A 12 12 0 0 1 12 0.5 H {W - 12} A 12 12 0 0 1 {W - 0.5} 12 V 38 H 0.5 Z" fill="#161B22"/>
  <rect x="0.5" y="38" width="{W - 1}" height="1.5" fill="url(#brand)"/>
  <circle cx="26" cy="19.5" r="6" fill="#FF5F56"/>
  <circle cx="46" cy="19.5" r="6" fill="#FFBD2E"/>
  <circle cx="66" cy="19.5" r="6" fill="#27C93F"/>
  <text x="{W // 2}" y="24" text-anchor="middle" class="title" fill="{MUTED}">gptaku @ claude-code — ~/gptaku_plugins</text>

  {body_s}
</svg>
"""


def build_hero(repos: list[dict], followers: int) -> str:
    stars = {r["name"]: r.get("stargazers_count", 0) for r in repos}
    total = sum(stars.values())

    def n(name: str) -> str:
        return f"{stars.get(name, 0):,}"

    grad = "url(#brand)"
    lines: list[tuple] = [
        ("typed", [("$ ", ORANGE), ("claude", TEXT)]),
        ("out", [("✻ ", ORANGE), ("Welcome back, ", TEXT), ("GPTaku", grad), (".", TEXT)]),
        ("blank",),
        ("typed", [("> ", INDIGO), ("/insane-search", TEXT), ("  reddit.com — blocked, 403", MUTED)]),
        ("out", [("  ● ", INDIGO), ("WAF profiled → TLS impersonation → in. ", MUTED), ("✓", GREEN), (f"  {n('insane-search')} ★", ORANGE)]),
        ("blank",),
        ("typed", [("> ", INDIGO), ("/fablize", TEXT), ("  make Opus ship like Fable", MUTED)]),
        ("out", [("  ● ", INDIGO), ("completion · evidence · verification — enforced ", MUTED), ("✓", GREEN), (f"  {n('fablize')} ★", ORANGE)]),
        ("blank",),
        ("typed", [("> ", INDIGO), ("/pumasi", TEXT), ("  build the whole marketplace in parallel", MUTED)]),
        ("out", [("  ● ", INDIGO), (f"{PLUGIN_COUNT} plugins shipped → gptaku_plugins ", MUTED), ("✓", GREEN), (f"  {n('gptaku_plugins')} ★", ORANGE)]),
        ("blank",),
        ("typed", [("> ", INDIGO), ("whoami", TEXT)]),
        ("out", [("  ", TEXT), ("GPTaku", grad), (" — building the Claude Code plugin ecosystem", TEXT)]),
        ("out", [(f"  ★ {total:,} stars shipped", ORANGE), (f" · {followers:,} followers · next plugin loading", MUTED)]),
    ]

    total_dur: list[float] = []
    return render_hero(lines, total_dur)


# ---------------------------------------------------------------- stat tiles
# Self-rendered 2x2 stat card (replaces github-readme-stats, whose public
# instance is chronically rate-limited). Data comes from the same API pull.

def render_stat_tiles(total_stars: int, followers: int, repo_count: int) -> str:
    stats = [
        (f"{total_stars:,}", "stars shipped"),
        (str(PLUGIN_COUNT), "plugins in the marketplace"),
        (f"{followers:,}", "followers"),
        (str(repo_count), "open-source repos"),
    ]
    tw, th, gap = 207, 79, 12
    tiles = []
    for i, (num, label) in enumerate(stats):
        col, row = i % 2, i // 2
        x, y = col * (tw + gap), row * (th + gap)
        cx = x + tw / 2
        begin = 0.15 + i * 0.18
        tiles.append(
            f'<g opacity="0">'
            f'<animate attributeName="opacity" begin="{begin:.2f}s" dur="0.5s" values="0;1" fill="freeze"/>'
            f'<rect x="{x + 0.5}" y="{y + 0.5}" width="{tw - 1}" height="{th - 1}" rx="10" fill="#0D1117" stroke="#30363D"/>'
            f'<text x="{cx}" y="{y + 38}" text-anchor="middle" class="num" fill="url(#brand)">{esc(num)}</text>'
            f'<text x="{cx}" y="{y + 60}" text-anchor="middle" class="lbl" fill="{MUTED}">{esc(label)}</text>'
            f"</g>"
        )
    w = tw * 2 + gap
    h = th * 2 + gap
    tiles_s = "\n  ".join(tiles)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" aria-label="GPTaku stats">
  <style>
    .num {{ font-family: -apple-system, 'Segoe UI', Helvetica, Arial, sans-serif; font-size: 27px; font-weight: 800; }}
    .lbl {{ font-family: 'SF Mono', SFMono-Regular, Menlo, Consolas, monospace; font-size: 11.5px; }}
  </style>
  <defs>
    <linearGradient id="brand" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="{ORANGE}"/>
      <stop offset="1" stop-color="{INDIGO}"/>
    </linearGradient>
  </defs>
  {tiles_s}
</svg>
"""


# ----------------------------------------------------------------------- main

def main() -> None:
    repos = fetch_repos()
    followers = fetch_followers()
    if not repos:
        sys.exit("No repos returned from API")

    grid = [r for r in repos if not r["name"].startswith(INSANE_PREFIX)]
    top = sorted(grid, key=lambda r: r.get("stargazers_count", 0), reverse=True)[:TOP_N]
    stars = {r["name"]: r.get("stargazers_count", 0) for r in repos}
    total_stars = sum(stars.values())

    HERO.parent.mkdir(parents=True, exist_ok=True)
    HERO.write_text(build_hero(repos, followers), encoding="utf-8")
    TILES.write_text(render_stat_tiles(total_stars, followers, len(repos)), encoding="utf-8")

    template = TEMPLATE.read_text(encoding="utf-8")
    rendered = (
        template
        .replace("{{HIGHLIGHTS}}", render_highlights(top))
        .replace("{{LAST_SYNC}}", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    )
    # {{STARS:<repo>}} -> static badge count for that repo
    rendered = re.sub(
        r"\{\{STARS:([A-Za-z0-9._-]+)\}\}",
        lambda m: fmt_stars(stars.get(m.group(1), 0)),
        rendered,
    )
    OUTPUT.write_text(rendered, encoding="utf-8")
    print(f"Wrote {OUTPUT} with {len(top)} repos: {[r['name'] for r in top]}")
    print(f"Wrote {HERO} and {TILES}")


if __name__ == "__main__":
    main()
