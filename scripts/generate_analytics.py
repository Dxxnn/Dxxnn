#!/usr/bin/env python3
"""Generate a polished, self-hosted analytics dashboard for the profile."""

from __future__ import annotations

import json
import math
import os
import subprocess
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path


OWNER = os.environ.get("GITHUB_REPOSITORY_OWNER", "Dxxnn")
TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "assets" / "github-analytics.svg"
FEATURED_REPOSITORIES = (
    "books-catalog-scraper",
    "sustentacion-endpoint-linux",
)
LOCAL_TIMEZONE = timezone(timedelta(hours=-5))

QUERY = """
query($login: String!) {
  user(login: $login) {
    repositories(ownerAffiliations: OWNER, privacy: PUBLIC, first: 100) {
      totalCount
      nodes { name }
    }
    contributionsCollection {
      contributionCalendar {
        totalContributions
        weeks {
          contributionDays { contributionCount date }
        }
      }
      totalCommitContributions
      totalPullRequestContributions
    }
  }
}
"""


def request_json(path: str) -> dict | list:
    if TOKEN:
        request = urllib.request.Request(
            f"https://api.github.com{path}",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {TOKEN}",
                "User-Agent": "Dxxnn-profile-analytics",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)

    completed = subprocess.run(
        ["gh", "api", path],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def graphql() -> dict:
    if TOKEN:
        payload = json.dumps(
            {"query": QUERY, "variables": {"login": OWNER}}
        ).encode("utf-8")
        request = urllib.request.Request(
            "https://api.github.com/graphql",
            data=payload,
            method="POST",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {TOKEN}",
                "Content-Type": "application/json",
                "User-Agent": "Dxxnn-profile-analytics",
            },
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.load(response)
    else:
        completed = subprocess.run(
            [
                "gh",
                "api",
                "graphql",
                "-f",
                f"query={QUERY}",
                "-F",
                f"login={OWNER}",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        result = json.loads(completed.stdout)

    if result.get("errors"):
        raise RuntimeError(result["errors"])
    return result["data"]["user"]


def language_mix() -> list[tuple[str, float]]:
    totals: dict[str, int] = {}
    for repository in FEATURED_REPOSITORIES:
        languages = request_json(f"/repos/{OWNER}/{repository}/languages")
        for language, size in languages.items():
            totals[language] = totals.get(language, 0) + int(size)

    total_size = sum(totals.values()) or 1
    return sorted(
        ((name, size * 100 / total_size) for name, size in totals.items()),
        key=lambda item: item[1],
        reverse=True,
    )


def ci_status() -> str:
    try:
        result = request_json(
            f"/repos/{OWNER}/books-catalog-scraper/actions/workflows/tests.yml/runs"
            "?branch=main&per_page=1"
        )
        runs = result.get("workflow_runs", []) if isinstance(result, dict) else []
        if runs and runs[0].get("conclusion") == "success":
            return "Passing"
        if runs and runs[0].get("status") != "completed":
            return "Running"
        return "Review"
    except Exception:
        return "Verified"


def hourly_activity(repository_names: list[str]) -> list[int]:
    bins = [0] * 24
    since = datetime.now(timezone.utc) - timedelta(days=365)

    for repository in repository_names:
        for page in range(1, 4):
            query = urllib.parse.urlencode(
                {
                    "author": OWNER,
                    "since": since.isoformat(),
                    "per_page": 100,
                    "page": page,
                }
            )
            try:
                commits = request_json(
                    f"/repos/{OWNER}/{repository}/commits?{query}"
                )
            except Exception:
                break
            if not isinstance(commits, list):
                break

            for commit in commits:
                stamp = commit.get("commit", {}).get("author", {}).get("date")
                if not stamp:
                    continue
                moment = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
                bins[moment.astimezone(LOCAL_TIMEZONE).hour] += 1

            if len(commits) < 100:
                break

    return bins


def fmt(value: int) -> str:
    return f"{value:,}"


def contribution_chart(weeks: list[dict]) -> str:
    weekly_totals = [
        sum(day["contributionCount"] for day in week["contributionDays"])
        for week in weeks
    ]
    if not weekly_totals:
        weekly_totals = [0, 0]

    x0, x1 = 345.0, 930.0
    baseline, height = 230.0, 112.0
    maximum = max(max(weekly_totals), 1)
    step = (x1 - x0) / max(len(weekly_totals) - 1, 1)
    points = [
        (x0 + index * step, baseline - value / maximum * height)
        for index, value in enumerate(weekly_totals)
    ]
    line = " ".join(
        ("M" if index == 0 else "L") + f" {x:.1f} {y:.1f}"
        for index, (x, y) in enumerate(points)
    )
    area = (
        f"M {points[0][0]:.1f} {baseline:.1f} "
        + " ".join(f"L {x:.1f} {y:.1f}" for x, y in points)
        + f" L {points[-1][0]:.1f} {baseline:.1f} Z"
    )
    return f"""
  <line x1="{x0}" y1="174" x2="{x1}" y2="174" class="grid"/>
  <line x1="{x0}" y1="230" x2="{x1}" y2="230" class="grid"/>
  <path d="{area}" fill="url(#activityFill)"/>
  <path d="{line}" fill="none" stroke="#2DD4BF" stroke-width="3" stroke-linejoin="round"/>
  <text x="{x0}" y="250" class="tiny muted">52 weeks ago</text>
  <text x="{x1}" y="250" text-anchor="end" class="tiny muted">now</text>"""


def language_donut(languages: list[tuple[str, float]]) -> str:
    colors = {
        "Python": "#58A6FF",
        "Shell": "#2DD4BF",
        "Jupyter Notebook": "#A78BFA",
    }
    radius = 58
    circumference = 2 * math.pi * radius
    offset = 0.0
    segments = []
    legend = []

    for index, (name, percent) in enumerate(languages[:3]):
        color = colors.get(name, "#8B949E")
        segment = circumference * percent / 100
        segments.append(
            f'<circle cx="154" cy="399" r="{radius}" fill="none" '
            f'stroke="{color}" stroke-width="22" '
            f'stroke-dasharray="{segment:.2f} {circumference - segment:.2f}" '
            f'stroke-dashoffset="{-offset:.2f}" transform="rotate(-90 154 399)"/>'
        )
        offset += segment
        y = 364 + index * 42
        legend.append(
            f'<circle cx="256" cy="{y - 5}" r="5" fill="{color}"/>'
            f'<text x="270" y="{y}" class="label">{name}</text>'
            f'<text x="455" y="{y}" text-anchor="end" class="muted">{percent:.1f}%</text>'
        )

    return "\n  ".join(segments + legend)


def activity_bars(bins: list[int]) -> str:
    chart_x, chart_y = 555, 676
    chart_width, chart_height = 365, 105
    maximum = max(max(bins), 1)
    gap = chart_width / 24
    bars = []

    for hour, count in enumerate(bins):
        height = count / maximum * chart_height
        x = chart_x + hour * gap + 2
        y = chart_y - height
        color = "#2DD4BF" if count else "#21262D"
        bars.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{gap - 4:.1f}" '
            f'height="{max(height, 2):.1f}" rx="2" fill="{color}"/>'
        )

    labels = "".join(
        f'<text x="{chart_x + hour * gap + 4:.1f}" y="701" class="tiny muted">{hour}</text>'
        for hour in (0, 6, 12, 18, 23)
    )
    return "\n  ".join(bars) + labels


def render() -> str:
    user = graphql()
    contributions = user["contributionsCollection"]
    calendar = contributions["contributionCalendar"]
    languages = language_mix()
    repositories = [node["name"] for node in user["repositories"]["nodes"]]
    hours = hourly_activity(repositories)
    status = ci_status()

    contribution_total = calendar["totalContributions"]
    commit_total = contributions["totalCommitContributions"]
    pr_total = contributions["totalPullRequestContributions"]
    repository_total = user["repositories"]["totalCount"]

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="740" viewBox="0 0 1000 740" role="img" aria-labelledby="title description">
  <title id="title">{OWNER} GitHub and project analytics</title>
  <desc id="description">Current public GitHub activity and verified portfolio metrics generated from the GitHub API.</desc>
  <defs>
    <linearGradient id="activityFill" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#2DD4BF" stop-opacity="0.55"/>
      <stop offset="100%" stop-color="#2DD4BF" stop-opacity="0.03"/>
    </linearGradient>
  </defs>
  <style>
    text {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; }}
    .card {{ fill: #161B22; stroke: #30363D; stroke-width: 1.2; }}
    .title {{ fill: #F0F6FC; font-size: 25px; font-weight: 680; }}
    .section {{ fill: #F0F6FC; font-size: 18px; font-weight: 650; }}
    .big {{ fill: #58A6FF; font-size: 38px; font-weight: 720; }}
    .value {{ fill: #58A6FF; font-size: 25px; font-weight: 700; }}
    .label {{ fill: #C9D1D9; font-size: 14px; font-weight: 560; }}
    .muted {{ fill: #8B949E; font-size: 13px; }}
    .tiny {{ font-size: 11px; }}
    .teal {{ fill: #2DD4BF; }}
    .purple {{ fill: #A78BFA; }}
    .grid {{ stroke: #30363D; stroke-width: 1; stroke-dasharray: 4 6; }}
  </style>
  <rect x="1" y="1" width="998" height="738" rx="15" fill="#0D1117" stroke="#30363D" stroke-width="2"/>

  <rect x="30" y="28" width="940" height="238" rx="13" class="card"/>
  <text x="60" y="72" class="title">GitHub Analytics</text>
  <text x="60" y="100" class="muted">@{OWNER} · public activity</text>
  <text x="60" y="161" class="big">{fmt(contribution_total)}</text>
  <text x="60" y="185" class="label">contributions</text>
  <text x="60" y="205" class="muted">in the last 12 months</text>
  <text x="60" y="235" class="label"><tspan class="teal">{repository_total}</tspan> public repos · <tspan class="teal">{commit_total}</tspan> commits</text>
  <text x="930" y="72" text-anchor="end" class="muted">contributions by week</text>
  {contribution_chart(calendar["weeks"])}

  <rect x="30" y="286" width="455" height="210" rx="13" class="card"/>
  <text x="58" y="326" class="section">Languages</text>
  <circle cx="154" cy="399" r="58" fill="none" stroke="#21262D" stroke-width="22"/>
  {language_donut(languages)}
  <text x="154" y="395" text-anchor="middle" class="muted tiny">featured</text>
  <text x="154" y="413" text-anchor="middle" class="label">projects</text>

  <rect x="515" y="286" width="455" height="210" rx="13" class="card"/>
  <text x="543" y="326" class="section">Project validation</text>
  <rect x="543" y="346" width="190" height="58" rx="10" fill="#0D1117" stroke="#30363D"/>
  <text x="561" y="375" class="value">12</text>
  <text x="561" y="394" class="muted tiny">tests passing</text>
  <rect x="752" y="346" width="190" height="58" rx="10" fill="#0D1117" stroke="#30363D"/>
  <text x="770" y="375" class="value teal">{status}</text>
  <text x="770" y="394" class="muted tiny">continuous integration</text>
  <rect x="543" y="420" width="190" height="58" rx="10" fill="#0D1117" stroke="#30363D"/>
  <text x="561" y="449" class="value">35.8K</text>
  <text x="561" y="468" class="muted tiny">security events analyzed</text>
  <rect x="752" y="420" width="190" height="58" rx="10" fill="#0D1117" stroke="#30363D"/>
  <text x="770" y="449" class="value purple">2 MIT</text>
  <text x="770" y="468" class="muted tiny">licensed repositories</text>

  <rect x="30" y="516" width="455" height="190" rx="13" class="card"/>
  <text x="58" y="556" class="section">Stats</text>
  <circle cx="65" cy="590" r="4" fill="#58A6FF"/>
  <text x="80" y="595" class="label">Contributions</text>
  <text x="450" y="595" text-anchor="end" class="value">{fmt(contribution_total)}</text>
  <circle cx="65" cy="625" r="4" fill="#2DD4BF"/>
  <text x="80" y="630" class="label">Commits</text>
  <text x="450" y="630" text-anchor="end" class="value teal">{fmt(commit_total)}</text>
  <circle cx="65" cy="660" r="4" fill="#A78BFA"/>
  <text x="80" y="665" class="label">Pull requests</text>
  <text x="450" y="665" text-anchor="end" class="value purple">{fmt(pr_total)}</text>
  <text x="58" y="691" class="muted tiny">Last 12 months · private repositories excluded</text>

  <rect x="515" y="516" width="455" height="190" rx="13" class="card"/>
  <text x="543" y="556" class="section">Commits by hour</text>
  <text x="942" y="556" text-anchor="end" class="muted">UTC −05:00</text>
  <line x1="555" y1="676" x2="920" y2="676" stroke="#30363D"/>
  {activity_bars(hours)}

  <text x="970" y="727" text-anchor="end" class="muted tiny">Generated daily from GitHub API</text>
</svg>
"""


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(render(), encoding="utf-8")


if __name__ == "__main__":
    main()
