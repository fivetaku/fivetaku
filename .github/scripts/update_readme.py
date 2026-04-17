#!/usr/bin/env python3
"""Regenerate README.md from template with the latest top repos.

Star counts in output use shields.io badges, so they stay live on every view.
The list of *which* repos appear is refreshed daily by GitHub Actions.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

USER = "fivetaku"
TOP_N = 6
ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / ".github" / "README.template.md"
OUTPUT = ROOT / "README.md"

TYPING_LINES = ";".join([
    "Claude+Code+Plugin+Builder",
    "AI-Powered+Coding+for+Everyone",
    "Vibe+Coding+%C3%97+Korean+Dev+Community",
])


def fetch_repos() -> list[dict]:
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        sys.exit("GH_TOKEN or GITHUB_TOKEN env var is required")

    cmd = [
        "gh", "api",
        "-H", "Accept: application/vnd.github+json",
        f"users/{USER}/repos?per_page=100&sort=updated",
    ]
    env = {**os.environ, "GH_TOKEN": token}
    out = subprocess.check_output(cmd, env=env, text=True)
    repos = json.loads(out)
    return [r for r in repos if not r.get("fork") and not r.get("private") and r["name"] != USER]


def pick_top(repos: list[dict], n: int) -> list[dict]:
    return sorted(repos, key=lambda r: r.get("stargazers_count", 0), reverse=True)[:n]


def render_highlights(repos: list[dict]) -> str:
    rows: list[str] = ["<table>"]
    for i in range(0, len(repos), 2):
        pair = repos[i:i + 2]
        rows.append("  <tr>")
        for repo in pair:
            name = repo["name"]
            desc = (repo.get("description") or "").replace("|", "&#124;").strip()
            badge = (
                f"https://img.shields.io/github/stars/{USER}/{name}"
                f"?style=flat&color=F97316&labelColor=0D1117&logo=github&logoColor=white"
            )
            rows.append("    <td width=\"50%\" valign=\"top\">")
            rows.append(
                f"      <h3><a href=\"https://github.com/{USER}/{name}\">{name}</a> "
                f"<a href=\"https://github.com/{USER}/{name}/stargazers\">"
                f"<img src=\"{badge}\" alt=\"stars\" align=\"right\" /></a></h3>"
            )
            if desc:
                rows.append(f"      <p>{desc}</p>")
            rows.append("    </td>")
        if len(pair) == 1:
            rows.append("    <td width=\"50%\"></td>")
        rows.append("  </tr>")
    rows.append("</table>")
    return "\n".join(rows)


def main() -> None:
    repos = fetch_repos()
    top = pick_top(repos, TOP_N)
    if not top:
        sys.exit("No repos returned from API")

    template = TEMPLATE.read_text(encoding="utf-8")
    rendered = (
        template
        .replace("{{HIGHLIGHTS}}", render_highlights(top))
        .replace("{{TYPING_LINES}}", TYPING_LINES)
        .replace("{{LAST_SYNC}}", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    )
    OUTPUT.write_text(rendered, encoding="utf-8")
    print(f"Wrote {OUTPUT} with {len(top)} repos: {[r['name'] for r in top]}")


if __name__ == "__main__":
    main()
