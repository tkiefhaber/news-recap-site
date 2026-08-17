#!/usr/bin/env python3
"""
Build feed.xml for news-recap-site.

Derives a full-text RSS 2.0 feed from the dated pages in archive/, newest first.
Run from anywhere; paths are resolved relative to this file's parent repo.

Also injects the <link rel="alternate" type="application/rss+xml"> autodiscovery
tag into index.html and archive/index.html if it isn't already there, so RSS
readers and browser extensions can find the feed from the site itself.

Invoked by scripts/push.sh before the commit, so the feed regenerates every time
the Cowork scheduled task writes a new recap.
"""

import html
import re
import sys
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

REPO = Path(__file__).resolve().parent.parent
ARCHIVE = REPO / "archive"
FEED_PATH = REPO / "feed.xml"

SITE_URL = "https://news-recap-site.pages.dev"
FEED_URL = f"{SITE_URL}/feed.xml"
FEED_TITLE = "Daily News Recap"
FEED_DESC = (
    "A balanced daily brief: the day's top stories with straight facts, "
    "left and right framings, and expert read on downstream effects. "
    "Plus markets and a sports watercooler."
)

MAX_ITEMS = 30
ET = ZoneInfo("America/New_York")

AUTODISCOVERY = (
    f'<link rel="alternate" type="application/rss+xml" '
    f'title="{FEED_TITLE}" href="{{href}}">'
)

DATED = re.compile(r"^(\d{4})-(\d{2})-(\d{2})\.html$")


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def extract_body(doc: str) -> str:
    """Pull the article content out of a recap page: everything between the
    closing </header> and the opening <footer>."""
    start = doc.find("</header>")
    end = doc.find("<footer")
    if start == -1 or end == -1:
        return ""
    return doc[start + len("</header>") : end].strip()


def extract_headline(doc: str) -> str:
    """First story headline on the page, used as the item title suffix."""
    m = re.search(r"<h3[^>]*>(.*?)</h3>", doc, re.S)
    if not m:
        return ""
    return re.sub(r"<[^>]+>", "", m.group(1)).strip()


def extract_all_headlines(doc: str) -> list[str]:
    return [
        re.sub(r"<[^>]+>", "", h).strip()
        for h in re.findall(r"<h3[^>]*>(.*?)</h3>", doc, re.S)
    ]


def absolutize(fragment: str) -> str:
    """Rewrite root-relative and bare-relative hrefs to absolute URLs so links
    still work inside a reader."""
    return re.sub(
        r'href="(?!https?://|mailto:|#)([^"]+)"',
        lambda m: f'href="{SITE_URL}/{m.group(1).lstrip("/")}"',
        fragment,
    )


def style_for_readers(fragment: str) -> str:
    """RSS readers strip the stylesheet, so the colored .label paragraphs lose
    all visual distinction. Convert them to bold text with a trailing colon so
    the Facts / Left view / Right view / Watch for structure survives."""
    fragment = re.sub(
        r'<p class="label[^"]*">(.*?)</p>',
        r"<p><strong>\1</strong></p>",
        fragment,
        flags=re.S,
    )
    fragment = re.sub(
        r'<h2 class="section">(.*?)</h2>',
        r"<h2>\1</h2>",
        fragment,
        flags=re.S,
    )
    fragment = re.sub(r'<p class="sources">', "<p><em>Sources:</em> ", fragment)
    fragment = re.sub(r'<(ul|article|li) class="[^"]*"', r"<\1", fragment)
    return fragment


def rfc822(d: datetime) -> str:
    return d.strftime("%a, %d %b %Y %H:%M:%S %z")


def build_items() -> list[dict]:
    items = []
    for path in sorted(ARCHIVE.glob("*.html"), reverse=True):
        m = DATED.match(path.name)
        if not m:
            continue  # skips archive/index.html
        year, month, day = (int(x) for x in m.groups())
        doc = read(path)
        body = extract_body(doc)
        if not body:
            print(f"  ! {path.name}: could not locate body, skipping", file=sys.stderr)
            continue

        # Recaps are generated first thing in the morning; stamp 07:00 ET so
        # readers order them sensibly and DST is handled correctly.
        published = datetime.combine(
            datetime(year, month, day).date(), time(7, 0), tzinfo=ET
        )
        headlines = extract_all_headlines(doc)
        top = headlines[0] if headlines else ""
        pretty = published.strftime("%a %b %-d, %Y")

        summary = " · ".join(headlines[:4]) if headlines else FEED_DESC

        items.append(
            {
                "title": f"{pretty} — {top}" if top else pretty,
                "link": f"{SITE_URL}/archive/{path.name}",
                "date": published,
                "summary": summary,
                "content": style_for_readers(absolutize(body)),
            }
        )
        if len(items) >= MAX_ITEMS:
            break
    return items


def build_feed(items: list[dict]) -> str:
    now = datetime.now(ET)
    built = rfc822(items[0]["date"]) if items else rfc822(now)

    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom" '
        'xmlns:content="http://purl.org/rss/1.0/modules/content/">',
        "<channel>",
        f"<title>{html.escape(FEED_TITLE)}</title>",
        f"<link>{SITE_URL}/</link>",
        f"<description>{html.escape(FEED_DESC)}</description>",
        "<language>en-us</language>",
        f'<atom:link href="{FEED_URL}" rel="self" type="application/rss+xml" />',
        f"<lastBuildDate>{built}</lastBuildDate>",
        "<ttl>720</ttl>",
    ]

    for it in items:
        parts += [
            "<item>",
            f"<title>{html.escape(it['title'])}</title>",
            f"<link>{it['link']}</link>",
            f'<guid isPermaLink="true">{it["link"]}</guid>',
            f"<pubDate>{rfc822(it['date'])}</pubDate>",
            f"<description>{html.escape(it['summary'])}</description>",
            f"<content:encoded><![CDATA[{it['content']}]]></content:encoded>",
            "</item>",
        ]

    parts += ["</channel>", "</rss>", ""]
    return "\n".join(parts)


def inject_autodiscovery(path: Path, href: str) -> bool:
    """Add the feed <link> to a page's <head> if absent. Returns True if changed."""
    if not path.exists():
        return False
    doc = read(path)
    if "application/rss+xml" in doc:
        return False
    tag = AUTODISCOVERY.format(href=href)
    if "</head>" not in doc:
        return False
    doc = doc.replace("</head>", f"{tag}\n</head>", 1)
    path.write_text(doc, encoding="utf-8")
    return True


def main() -> int:
    if not ARCHIVE.is_dir():
        print(f"No archive directory at {ARCHIVE}", file=sys.stderr)
        return 1

    items = build_items()
    if not items:
        print("No dated archive pages found; feed not written.", file=sys.stderr)
        return 1

    FEED_PATH.write_text(build_feed(items), encoding="utf-8")
    print(f"feed.xml: {len(items)} items, newest {items[0]['date']:%Y-%m-%d}")

    for page, href in ((REPO / "index.html", "feed.xml"),
                       (ARCHIVE / "index.html", "../feed.xml")):
        if inject_autodiscovery(page, href):
            print(f"autodiscovery tag added to {page.relative_to(REPO)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
