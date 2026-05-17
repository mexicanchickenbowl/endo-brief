#!/usr/bin/env python3
"""Generate article-card MP4 videos for the most recent Endo Morning Brief episodes."""

import os
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from textwrap import wrap

from PIL import Image, ImageDraw, ImageFilter, ImageFont

REPO_DIR = Path("/tmp/endo-brief")
EPISODES_DIR = REPO_DIR / "episodes"
OUTPUT_DIR = Path("/Users/nathan/Nightly Podcasts/episode-videos")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

W, H = 1280, 720
BG = (15, 23, 42)        # slate-900 navy
PANEL = (23, 35, 60)
GOLD = (212, 175, 55)
WHITE = (245, 245, 245)
MUTED = (160, 174, 192)
ACCENT = (94, 234, 212)

FONT_BOLD = "/System/Library/Fonts/HelveticaNeue.ttc"
FONT_REG = "/System/Library/Fonts/HelveticaNeue.ttc"


def font(size, bold=False):
    path = FONT_BOLD if bold else FONT_REG
    # HelveticaNeue.ttc — index 1 = Bold, 0 = Regular
    return ImageFont.truetype(path, size, index=1 if bold else 0)


def slugify(s: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s[:80]


def parse_feed():
    """Tolerant regex parser — feed has bare '&' which breaks strict XML."""
    raw = (REPO_DIR / "feed.rss").read_text(encoding="utf-8")
    items = []
    for m in re.finditer(r"<item>(.*?)</item>", raw, re.DOTALL):
        block = m.group(1)
        def field(tag):
            mm = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", block, re.DOTALL)
            return (mm.group(1).strip() if mm else "")
        title = field("title")
        desc = field("description")
        guid = field("guid")
        pub = field("pubDate")
        url, length = "", 0
        um = re.search(r'<enclosure[^>]*\burl="([^"]+)"', block)
        lm = re.search(r'<enclosure[^>]*\blength="(\d+)"', block)
        if um:
            url = um.group(1)
        if lm:
            length = int(lm.group(1))
        # unescape HTML entities for display text
        for ent, ch in [("&amp;", "&"), ("&quot;", '"'), ("&apos;", "'"),
                        ("&lt;", "<"), ("&gt;", ">")]:
            title = title.replace(ent, ch)
            desc = desc.replace(ent, ch)
        fname = url.rsplit("/", 1)[-1] if url else ""
        items.append({
            "title": title,
            "description": desc,
            "guid": guid,
            "pub": pub,
            "url": url,
            "length": length,
            "audio_path": EPISODES_DIR / fname if fname else None,
        })
    return items


def split_title(title: str):
    """Split 'ABE Board Review — Vital Pulp Therapy — 2026-05-15' into series, topic, date."""
    parts = [p.strip() for p in title.split("—")]
    if len(parts) >= 3:
        return parts[0], " — ".join(parts[1:-1]), parts[-1]
    if len(parts) == 2:
        return parts[0], "", parts[1]
    return title, "", ""


def episode_kind(title: str) -> str:
    t = title.lower()
    if "endo lit brief" in t:
        return "lit-brief"
    if "recent literature spotlight" in t:
        return "recent-lit"
    if "abe board review" in t:
        return "abe-review"
    return "general"


def topic_bullets(description: str) -> list[str]:
    """Extract topical bullets from a description by splitting on commas after a colon."""
    bullets = []
    # find content after "covering" or "Covers" or after the first sentence with topics
    m = re.search(r"(?:covering|Covers|across|on)\s+([^.]+)", description)
    if m:
        chunk = m.group(1)
        parts = re.split(r",| and ", chunk)
        for p in parts:
            p = p.strip().rstrip(".")
            if p and len(p) > 2 and len(p) < 80:
                bullets.append(p.capitalize())
    # fallback: split full description
    if not bullets:
        parts = re.split(r"\.\s+", description)
        for p in parts:
            p = p.strip()
            if p and len(p) > 4:
                bullets.append(p[:120])
    return bullets[:5]


def draw_text_block(draw, xy, text, fnt, fill, max_width, line_h, max_lines=None):
    """Draw wrapped text; returns y coordinate after last line."""
    x, y = xy
    words = text.split()
    line, lines = "", []
    for w in words:
        test = (line + " " + w).strip()
        bbox = draw.textbbox((0, 0), test, font=fnt)
        if bbox[2] - bbox[0] <= max_width:
            line = test
        else:
            if line:
                lines.append(line)
            line = w
    if line:
        lines.append(line)
    if max_lines:
        lines = lines[:max_lines]
    for ln in lines:
        draw.text((x, y), ln, font=fnt, fill=fill)
        y += line_h
    return y


def gradient_bg() -> Image.Image:
    """Dark navy gradient with subtle radial vignette."""
    img = Image.new("RGB", (W, H), BG)
    # subtle diagonal gradient
    top = (18, 28, 50)
    bot = (10, 16, 32)
    for y in range(H):
        t = y / H
        r = int(top[0] * (1 - t) + bot[0] * t)
        g = int(top[1] * (1 - t) + bot[1] * t)
        b = int(top[2] * (1 - t) + bot[2] * t)
        ImageDraw.Draw(img).line([(0, y), (W, y)], fill=(r, g, b))
    # soft golden glow on left edge
    overlay = Image.new("RGB", (W, H), (0, 0, 0))
    od = ImageDraw.Draw(overlay)
    od.ellipse((-300, 100, 500, 900), fill=(40, 32, 12))
    overlay = overlay.filter(ImageFilter.GaussianBlur(120))
    img = Image.blend(img, overlay, 0.35)
    return img


def card_title(ep) -> Image.Image:
    img = gradient_bg()
    d = ImageDraw.Draw(img)
    series, topic, date = split_title(ep["title"])
    # series label
    d.text((80, 90), series.upper(), font=font(22, bold=True), fill=GOLD)
    # gold underline
    d.rectangle((80, 130, 180, 134), fill=GOLD)
    # main title
    fnt = font(56, bold=True)
    title_text = topic or ep["title"]
    draw_text_block(d, (80, 170), title_text, fnt, WHITE, max_width=W - 160, line_h=72, max_lines=4)
    # date footer
    d.text((80, H - 90), date, font=font(28, bold=False), fill=MUTED)
    # cover thumb-style mark in corner
    d.rectangle((W - 200, H - 90, W - 80, H - 70), fill=ACCENT)
    d.text((W - 200, H - 130), "ENDO MORNING BRIEF", font=font(16, bold=True), fill=ACCENT)
    return img


def card_overview(ep) -> Image.Image:
    img = gradient_bg()
    d = ImageDraw.Draw(img)
    d.text((80, 90), "EPISODE OVERVIEW", font=font(22, bold=True), fill=GOLD)
    d.rectangle((80, 130, 180, 134), fill=GOLD)
    draw_text_block(d, (80, 180), ep["description"], font(30, bold=False), WHITE,
                    max_width=W - 160, line_h=46, max_lines=10)
    series, topic, date = split_title(ep["title"])
    d.text((80, H - 60), f"{series} · {date}", font=font(20, bold=True), fill=MUTED)
    return img


def card_topics(ep) -> Image.Image:
    img = gradient_bg()
    d = ImageDraw.Draw(img)
    d.text((80, 90), "TOPICS COVERED", font=font(22, bold=True), fill=GOLD)
    d.rectangle((80, 130, 180, 134), fill=GOLD)
    bullets = topic_bullets(ep["description"])
    y = 200
    for i, b in enumerate(bullets[:6]):
        d.ellipse((80, y + 18, 96, y + 34), outline=GOLD, width=2)
        d.ellipse((84, y + 22, 92, y + 30), fill=GOLD)
        y = draw_text_block(d, (120, y + 8), b, font(28, bold=False), WHITE,
                            max_width=W - 200, line_h=42, max_lines=2)
        y += 14
    series, topic, date = split_title(ep["title"])
    d.text((80, H - 60), f"{series} · {date}", font=font(20, bold=True), fill=MUTED)
    return img


def card_outro(ep) -> Image.Image:
    img = gradient_bg()
    d = ImageDraw.Draw(img)
    kind = episode_kind(ep["title"])
    if kind == "abe-review":
        label = "ABE BOARD PREP"
        msg = "Classic landmark literature, distilled for the oral and written board exam."
    elif kind == "lit-brief":
        label = "DAILY LITERATURE SCAN"
        msg = "Curated PubMed picks. Clinical takeaways for the working endodontist."
    elif kind == "recent-lit":
        label = "RECENT LITERATURE SPOTLIGHT"
        msg = "Five landmark recent papers (2015–2025), synthesized for boards and clinic."
    else:
        label = "ENDO MORNING BRIEF"
        msg = "Daily endodontic literature, distilled for residents."

    d.text((80, 120), label, font=font(26, bold=True), fill=GOLD)
    d.rectangle((80, 165, 220, 169), fill=GOLD)
    draw_text_block(d, (80, 220), msg, font(40, bold=True), WHITE,
                    max_width=W - 160, line_h=58, max_lines=4)
    d.text((80, H - 140), "Subscribe", font=font(22, bold=True), fill=ACCENT)
    d.text((80, H - 100), "mexicanchickenbowl.github.io/endo-brief", font=font(28, bold=False), fill=WHITE)
    return img


def get_audio_duration(path: Path) -> float:
    out = subprocess.run(
        ["/opt/homebrew/bin/ffprobe", "-v", "error", "-show_entries",
         "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


def build_video(ep):
    audio = ep["audio_path"]
    if not audio.exists() or ep["length"] == 0:
        print(f"  skip — audio missing or length=0 ({audio.name})")
        return None

    duration = get_audio_duration(audio)
    cards = [card_title(ep), card_overview(ep), card_topics(ep), card_outro(ep)]
    n = len(cards)
    per = duration / n  # seconds each card is shown
    fade = 0.6  # crossfade duration in seconds

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        img_paths = []
        for i, c in enumerate(cards):
            p = td / f"card_{i:02d}.png"
            c.save(p)
            img_paths.append(p)

        # Build a concat list approach: each image as input with -loop 1 -t per
        # then use xfade between them in a filter_complex.
        inputs = []
        for p in img_paths:
            inputs += ["-loop", "1", "-t", f"{per:.3f}", "-i", str(p)]
        inputs += ["-i", str(audio)]

        # filter_complex: chain xfade between [0:v]..[n-1:v]
        # xfade offset is cumulative: t0 = per - fade ; t1 = 2*per - 2*fade ; ...
        filt = []
        prev = "[0:v]"
        for i in range(1, n):
            offset = i * per - i * fade
            label = f"v{i}" if i < n - 1 else "vout"
            filt.append(f"{prev}[{i}:v]xfade=transition=fade:duration={fade}:offset={offset:.3f}[{label}]")
            prev = f"[{label}]"
        # also scale to 1280x720 just in case
        filter_str = ";".join(filt) + f";[vout]format=yuv420p[v]"

        slug = ep["guid"] or slugify(ep["title"])
        out_path = OUTPUT_DIR / f"episode_{slug}.mp4"

        cmd = [
            "/opt/homebrew/bin/ffmpeg", "-y",
            *inputs,
            "-filter_complex", filter_str,
            "-map", "[v]",
            "-map", f"{n}:a",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k",
            "-shortest", "-movflags", "+faststart",
            "-preset", "medium", "-crf", "22",
            str(out_path),
        ]
        print(f"  encoding -> {out_path.name} ({duration:.1f}s)")
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            print("FFMPEG ERROR:\n" + r.stderr[-2000:])
            return None
        return out_path


def main():
    items = parse_feed()
    # filter usable + take most recent 6
    usable = [i for i in items if i["length"] > 0 and i["audio_path"].exists()]
    targets = usable[:6]
    print(f"Building {len(targets)} videos:")
    for i, ep in enumerate(targets, 1):
        print(f"\n[{i}/{len(targets)}] {ep['title']}")
        out = build_video(ep)
        if out:
            print(f"  done: {out}")


if __name__ == "__main__":
    main()
