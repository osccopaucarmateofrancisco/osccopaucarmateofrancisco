#!/usr/bin/env python3
"""Dependency-free SVG radar ("spider") chart generator.

Two data sources:
  --data assets/skills.json        self-rated values, straight from a JSON file you edit by hand
  --github USERNAME                real values, computed from language bytes across your public repos

Usage:
  python3 scripts/radar.py --data assets/skills.json -o assets/radar --values
  python3 scripts/radar.py --github USERNAME -o assets/radar-langs --limit 7 --curve 0.4 \
      --exclude "Shell,Makefile,Dockerfile,Batchfile,Procfile" --values

Each run writes two files: <out>-light.svg and <out>-dark.svg.
"""
import argparse
import json
import math
import sys
import urllib.request

W, H = 520, 400
CX, CY = W / 2, 210
R = 115
RINGS = 4

THEMES = {
    "light": {"grid": "#d0d7de", "axis": "#8b949e", "text": "#24292f", "fill": "#39d353", "stroke": "#2ea043", "bg": "none"},
    "dark":  {"grid": "#30363d", "axis": "#484f58", "text": "#c9d1d9", "fill": "#39d353", "stroke": "#56d364", "bg": "none"},
}


def fetch_json(url, token=None):
    req = urllib.request.Request(url, headers={"User-Agent": "radar-script", "Accept": "application/vnd.github+json"})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def load_self_rated(path):
    data = json.load(open(path, encoding="utf-8"))
    title = data.get("title", "Skill Radar")
    axes = [(a["label"], float(a["value"])) for a in data["axes"]]
    return title, axes, None


def load_from_github(user, limit, curve, exclude, token=None):
    exclude = {e.strip().lower() for e in exclude.split(",")} if exclude else set()
    repos = []
    page = 1
    while True:
        batch = fetch_json(f"https://api.github.com/users/{user}/repos?per_page=100&page={page}&type=owner", token)
        if not batch:
            break
        repos.extend(batch)
        if len(batch) < 100:
            break
        page += 1

    totals = {}
    for repo in repos:
        if repo.get("fork"):
            continue
        try:
            langs = fetch_json(repo["languages_url"], token)
        except Exception:
            continue
        for lang, nbytes in langs.items():
            if lang.lower() in exclude:
                continue
            totals[lang] = totals.get(lang, 0) + nbytes

    if not totals:
        raise SystemExit(f"No language data found for {user} (repos private or empty?)")

    ranked = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)[:limit]
    max_bytes = ranked[0][1]
    axes = [(lang, 100.0 * (nbytes / max_bytes) ** curve) for lang, nbytes in ranked]
    raw = {lang: nbytes for lang, nbytes in ranked}
    return f"{user} · language mix", axes, raw


def point(cx, cy, r, angle):
    return cx + r * math.sin(angle), cy - r * math.cos(angle)


def render(title, axes, theme_name, show_values=True, raw_bytes=None):
    t = THEMES[theme_name]
    n = len(axes)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
        f'font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif">'
    ]
    if title:
        parts.append(
            f'<text x="{W/2}" y="24" text-anchor="middle" font-size="16" font-weight="600" '
            f'fill="{t["text"]}">{title}</text>'
        )

    # grid rings
    for ring in range(1, RINGS + 1):
        rr = R * ring / RINGS
        pts = " ".join(f"{x:.2f},{y:.2f}" for x, y in (point(CX, CY, rr, 2 * math.pi * i / n) for i in range(n)))
        parts.append(f'<polygon points="{pts}" fill="none" stroke="{t["grid"]}" stroke-width="1"/>')

    # axis spokes + labels
    for i, (label, _value) in enumerate(axes):
        angle = 2 * math.pi * i / n
        x, y = point(CX, CY, R, angle)
        parts.append(f'<line x1="{CX}" y1="{CY}" x2="{x:.2f}" y2="{y:.2f}" stroke="{t["axis"]}" stroke-width="1"/>')
        lx, ly = point(CX, CY, R + 26, angle)
        anchor = "middle"
        if lx < CX - 5:
            anchor = "end"
        elif lx > CX + 5:
            anchor = "start"
        parts.append(
            f'<text x="{lx:.2f}" y="{ly:.2f}" text-anchor="{anchor}" dominant-baseline="middle" '
            f'font-size="12" font-weight="600" fill="{t["text"]}">{label}</text>'
        )
        if show_values:
            vy = ly + 14
            label_val = raw_bytes[label] if raw_bytes else axes[i][1]
            vtext = f"{label_val/1024:.1f} KB" if raw_bytes else f"{axes[i][1]:.0f}"
            parts.append(
                f'<text x="{lx:.2f}" y="{vy:.2f}" text-anchor="{anchor}" font-size="10" '
                f'fill="{t["axis"]}">{vtext}</text>'
            )

    # data polygon
    pts = []
    for i, (_label, value) in enumerate(axes):
        angle = 2 * math.pi * i / n
        rr = R * max(0.0, min(100.0, value)) / 100.0
        pts.append(point(CX, CY, rr, angle))
    poly = " ".join(f"{x:.2f},{y:.2f}" for x, y in pts)
    parts.append(f'<polygon points="{poly}" fill="{t["fill"]}" fill-opacity="0.35" stroke="{t["stroke"]}" stroke-width="2"/>')
    for x, y in pts:
        parts.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="3" fill="{t["stroke"]}"/>')

    parts.append("</svg>")
    return "".join(parts)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--data", help="path to a self-rated JSON file")
    p.add_argument("--github", help="GitHub username to compute a real language radar for")
    p.add_argument("--token", help="GitHub token (increases API rate limit / sees private repos with repo scope)")
    p.add_argument("--limit", type=int, default=7)
    p.add_argument("--curve", type=float, default=0.4)
    p.add_argument("--exclude", default="")
    p.add_argument("--values", action="store_true", help="print the value/byte-count next to each label")
    p.add_argument("-o", "--out", required=True, help="output path prefix (writes <out>-light.svg / <out>-dark.svg)")
    args = p.parse_args()

    if args.data:
        title, axes, raw = load_self_rated(args.data)
    elif args.github:
        title, axes, raw = load_from_github(args.github, args.limit, args.curve, args.exclude, args.token)
    else:
        sys.exit("pass either --data <file.json> or --github <username>")

    for theme in ("light", "dark"):
        svg = render(title, axes, theme, show_values=args.values, raw_bytes=raw)
        path = f"{args.out}-{theme}.svg"
        open(path, "w", encoding="utf-8").write(svg)
        print("wrote", path)


if __name__ == "__main__":
    main()
