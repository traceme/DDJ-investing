#!/usr/bin/env python3
"""Build 《投资心法100条精选》 as a self-contained EPUB 3 book."""

from __future__ import annotations

import html
import posixpath
import re
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from io import BytesIO
from math import cos, radians, sin
from pathlib import Path
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree as ET

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "投资心法100条精选版.md"
OUTPUT = ROOT / "投资心法100条精选版.epub"
BOOK_TITLE = "投资心法100条精选"
BOOK_ID = "ddj-investing-100-selection"
LANGUAGE = "zh-CN"
BOOK_DATE = "2026-08-23"
EBOOK_LINE_PREFIX = "📘 电子书："
SIBLING_MD = "./投资心法313条全量版.md"
SIBLING_URL = "https://traceme.github.io/DDJ-investing/#/投资心法313条全量版"

XHTML_HEADER = """<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="zh-CN" xml:lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <title>{title}</title>
  <link href="style/book.css" rel="stylesheet" type="text/css" />
</head>
<body{body_class}>
"""


@dataclass(frozen=True)
class Quote:
    text: str
    source: str


@dataclass(frozen=True)
class Entry:
    number: int
    title: str
    body: str
    quotes: tuple[Quote, ...]
    part_name: str

    @property
    def href(self) -> str:
        return f"e{self.number:03d}.xhtml"


@dataclass
class Part:
    index: int
    title: str
    span: str = ""
    entries: list[Entry] = field(default_factory=list)

    @property
    def href(self) -> str:
        return f"part{self.index}.xhtml"

    @property
    def name(self) -> str:
        return self.title.split(" · ", 1)[0]

    @property
    def summary(self) -> str:
        parts = self.title.split(" · ", 1)
        return parts[1] if len(parts) > 1 else ""

    @property
    def short_name(self) -> str:
        return self.name.split("、", 1)[-1]


@dataclass(frozen=True)
class Book:
    title: str
    declared_count: int
    intro: tuple[str, ...]
    parts: tuple[Part, ...]
    disclaimer: str

    @property
    def entries(self) -> list[Entry]:
        return [entry for part in self.parts for entry in part.entries]


# --------------------------------------------------------------------------- #
# Markdown → XHTML helpers
# --------------------------------------------------------------------------- #


def xhtml_document(title: str, body: str, body_class: str = "") -> str:
    class_attr = f' class="{body_class}"' if body_class else ""
    return (
        XHTML_HEADER.format(title=html.escape(title), body_class=class_attr)
        + body
        + "\n</body>\n</html>\n"
    )


def inline_markdown(text: str) -> str:
    escaped = html.escape(text.strip(), quote=True)

    def replace_link(match: re.Match[str]) -> str:
        label, href = match.groups()
        if href == SIBLING_MD:
            href = SIBLING_URL
        return f'<a href="{html.escape(href, quote=True)}">{label}</a>'

    escaped = re.sub(r"\[([^]]+)]\(([^)]+)\)", replace_link, escaped)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    return escaped


# --------------------------------------------------------------------------- #
# Source parsing
# --------------------------------------------------------------------------- #


def split_quote(line: str) -> Quote:
    """Attribution is the last 　——《…》 marker; quote bodies may contain ——."""
    match = re.fullmatch(r"(.*)　——(《.+)", line)
    if not match:
        return Quote(line.strip(), "")
    return Quote(match.group(1).strip(), "——" + match.group(2).strip())


def parse_book() -> Book:
    lines = SOURCE.read_text(encoding="utf-8").split("\n")
    title = ""
    intro: list[str] = []
    parts: list[Part] = []
    tail: list[str] = []
    index = 0

    while index < len(lines):
        line = lines[index].rstrip()
        if not line or line == "---":
            index += 1
            continue
        if line.startswith("# ") and not title:
            title = line[2:].strip()
            index += 1
            continue
        if line.startswith("## "):
            parts.append(Part(index=len(parts) + 1, title=line[3:].strip()))
            index += 1
            continue
        if re.fullmatch(r"\*第 .+ 条\*", line):
            if not parts:
                raise ValueError(f"条数范围出现在分部之前：{line}")
            parts[-1].span = line.strip("*").strip()
            index += 1
            continue
        if line.startswith("### "):
            heading = re.fullmatch(r"###\s+(\d+)\.\s*(.+)", line)
            if not heading:
                raise ValueError(f"无法解析条目标题：{line}")
            if not parts:
                raise ValueError(f"条目出现在分部之前：{line}")
            index += 1
            body_lines: list[str] = []
            quotes: list[Quote] = []
            while index < len(lines):
                current = lines[index].rstrip()
                if current.startswith("#") or current == "---":
                    break
                if not current:
                    index += 1
                    continue
                if current.startswith(">"):
                    content = current[1:].strip()
                    if content:
                        quotes.append(split_quote(content))
                    index += 1
                    continue
                if re.fullmatch(r"\*第 .+ 条\*", current):
                    break
                body_lines.append(current)
                index += 1
            if len(body_lines) != 1:
                raise ValueError(
                    f"第{heading.group(1)}条正文应为单段，实际 {len(body_lines)} 段"
                )
            if not quotes:
                raise ValueError(f"第{heading.group(1)}条缺少原文摘录")
            parts[-1].entries.append(
                Entry(
                    number=int(heading.group(1)),
                    title=heading.group(2).strip(),
                    body=body_lines[0],
                    quotes=tuple(quotes),
                    part_name=parts[-1].short_name,
                )
            )
            continue
        if line.startswith(">"):
            content = line[1:].strip()
            if content:
                intro.append(content)
            index += 1
            continue
        if line.startswith(EBOOK_LINE_PREFIX):
            index += 1
            continue
        tail.append(line)
        index += 1

    declared = re.search(r"(\d+)\s*条", title)
    if not declared:
        raise ValueError(f"书名中未声明条数：{title}")
    disclaimer = " ".join(item for item in tail if "免责声明" in item)
    if not disclaimer:
        raise ValueError("未找到免责声明")

    book = Book(
        title=title,
        declared_count=int(declared.group(1)),
        intro=tuple(intro),
        parts=tuple(parts),
        disclaimer=disclaimer,
    )
    audit_book(book)
    return book


def audit_book(book: Book) -> None:
    entries = book.entries
    numbers = [entry.number for entry in entries]
    if numbers != list(range(1, len(entries) + 1)):
        raise ValueError("条目编号不连续或未从 1 开始")
    if len(entries) != book.declared_count:
        raise ValueError(f"条目数 {len(entries)} 与书名声明的 {book.declared_count} 不符")
    for part in book.parts:
        span = re.fullmatch(r"第 (\d+)—(\d+) 条", part.span)
        if not span:
            raise ValueError(f"分部缺少条数范围：{part.title}")
        first, last = int(span.group(1)), int(span.group(2))
        actual = [entry.number for entry in part.entries]
        if actual != list(range(first, last + 1)):
            raise ValueError(
                f"{part.title} 实际条目 {actual[:2]}…{actual[-1:]} 与声明范围 {part.span} 不符"
            )
    parsed_quotes = sum(len(entry.quotes) for entry in entries)
    source_quotes = sum(
        1 for line in SOURCE.read_text(encoding="utf-8").split("\n") if "　——《" in line
    )
    if parsed_quotes != source_quotes:
        raise ValueError(f"引文条数不符：解析 {parsed_quotes}，源文件 {source_quotes}")
    missing = [entry.number for entry in entries for q in entry.quotes if not q.source]
    if missing:
        raise ValueError(f"以下条目存在无出处引文：{sorted(set(missing))}")


# --------------------------------------------------------------------------- #
# Cover
# --------------------------------------------------------------------------- #


def get_font(size: int) -> ImageFont.FreeTypeFont:
    candidates = (
        "/System/Library/Fonts/Supplemental/Songti.ttc",
        "/System/Library/Fonts/PingFang.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
        "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    )
    for candidate in candidates:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size=size)
    raise FileNotFoundError("未找到可渲染中文的宋体或苹方字体")


def centered_text(
    draw: ImageDraw.ImageDraw,
    y: int,
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: tuple[int, int, int],
    spacing: int = 0,
) -> None:
    if spacing <= 0:
        box = draw.textbbox((0, 0), text, font=font)
        draw.text(((1600 - (box[2] - box[0])) / 2, y), text, font=font, fill=fill)
        return
    widths = [draw.textlength(char, font=font) for char in text]
    total = sum(widths) + spacing * (len(text) - 1)
    x = (1600 - total) / 2
    for char, width in zip(text, widths):
        draw.text((x, y), char, font=font, fill=fill)
        x += width + spacing


def build_cover(path: Path) -> None:
    background = (246, 242, 231)
    ink = (57, 48, 35)
    green = (48, 101, 78)
    gold = (181, 153, 88)
    pale_gold = (214, 198, 157)
    image = Image.new("RGB", (1600, 2400), background)
    draw = ImageDraw.Draw(image)

    draw.rounded_rectangle((70, 70, 1530, 2330), radius=4, outline=gold, width=7)
    draw.rectangle((95, 95, 1505, 2305), outline=pale_gold, width=2)
    centered_text(draw, 160, "三 书 · 三百一十三 章", get_font(50), gold, spacing=8)

    # 三本书提炼成一条主线：三环相交，交点是共同的那个「道」。
    cx, cy, radius, offset = 800, 600, 150, 82
    for angle in (90, 210, 330):
        ox = cx + offset * cos(radians(angle))
        oy = cy - offset * sin(radians(angle))
        draw.ellipse(
            (ox - radius, oy - radius, ox + radius, oy + radius),
            outline=green,
            width=6,
        )
    draw.ellipse((cx - 26, cy - 26, cx + 26, cy + 26), fill=gold)

    centered_text(draw, 940, "投资心法", get_font(220), ink, spacing=12)
    centered_text(draw, 1215, "100 条精选", get_font(132), ink, spacing=6)
    draw.line((560, 1435, 1040, 1435), fill=gold, width=4)

    badge_text = "按重要程度排序"
    badge_font = get_font(60)
    badge_box = draw.textbbox((0, 0), badge_text, font=badge_font)
    badge_width = badge_box[2] - badge_box[0] + 110
    badge_left = (1600 - badge_width) / 2
    draw.rounded_rectangle(
        (badge_left, 1515, badge_left + badge_width, 1625), radius=14, fill=green
    )
    centered_text(draw, 1533, badge_text, badge_font, background, spacing=6)

    centered_text(draw, 1760, "先活下来，再谈看得准", get_font(64), green, spacing=3)
    centered_text(draw, 1870, "最后才谈学得快", get_font(64), green, spacing=3)
    centered_text(
        draw, 2020, "生存 · 认知 · 市场观 · 纪律 · 心性 · 长期", get_font(44), ink, spacing=2
    )
    centered_text(draw, 2180, "traceme  ·  三书合编", get_font(40), gold, spacing=2)
    image.save(path, format="PNG", optimize=True)


# --------------------------------------------------------------------------- #
# Pages
# --------------------------------------------------------------------------- #


def cover_xhtml() -> str:
    body = f"""<section epub:type="cover" class="cover-page">
  <img src="cover.png" alt="{BOOK_TITLE}封面" />
</section>"""
    return xhtml_document(BOOK_TITLE, body, "cover-body")


def title_xhtml(book: Book) -> str:
    body = f"""<section epub:type="titlepage" class="title-page">
  <p class="eyebrow">三书合编 · 三百一十三章提炼</p>
  <h1>投资心法<br /><span>{book.declared_count} 条精选</span></h1>
  <p class="subtitle">先活下来，再谈看得准，最后才谈学得快</p>
  <p class="author">traceme</p>
</section>"""
    return xhtml_document(BOOK_TITLE, body, "title-body")


def intro_xhtml(book: Book) -> str:
    notes = "\n".join(
        f"  <p>{inline_markdown(item)}</p>" for item in book.intro
    )
    parts = "\n".join(
        f"    <li><strong>{html.escape(part.name)}</strong>"
        f"（{html.escape(part.span)}）：{html.escape(part.summary)}</li>"
        for part in book.parts
    )
    body = f"""<section epub:type="preface">
  <h1>编选说明</h1>
  <blockquote class="notice">
{notes}
  </blockquote>
  <h2>九个分部</h2>
  <ol class="parts">
{parts}
  </ol>
  <blockquote class="disclaimer"><p>{inline_markdown(book.disclaimer)}</p></blockquote>
</section>"""
    return xhtml_document("编选说明", body)


def part_xhtml(part: Part) -> str:
    body = f"""<section epub:type="part" class="part-page">
  <p class="eyebrow">{html.escape(part.span)}</p>
  <h1>{html.escape(part.name)}</h1>
  <p class="part-summary">{html.escape(part.summary)}</p>
</section>"""
    return xhtml_document(part.name, body, "part-body")


def entry_xhtml(entry: Entry, previous_href: str, next_href: str) -> str:
    quotes = "\n".join(
        f"      <p>{inline_markdown(quote.text)}"
        f'<span class="src">{inline_markdown(quote.source)}</span></p>'
        for quote in entry.quotes
    )
    body = f"""<article epub:type="chapter">
  <p class="entry-no">第 {entry.number} 条 · {html.escape(entry.part_name)}</p>
  <h1>{html.escape(entry.title)}</h1>
  <p class="entry-body">{inline_markdown(entry.body)}</p>
  <section class="quotes">
    <h2>书中原文</h2>
    <blockquote>
{quotes}
    </blockquote>
  </section>
  <nav class="entry-nav" aria-label="条目导航">
    <a href="{previous_href}">← 上一条</a>
    <a href="nav.xhtml">目录</a>
    <a href="{next_href}">下一条 →</a>
  </nav>
</article>"""
    return xhtml_document(f"{entry.number}. {entry.title}", body)


def nav_xhtml(book: Book) -> str:
    items = []
    for part in book.parts:
        entries = "\n".join(
            f'        <li><a href="{entry.href}">{entry.number}. '
            f"{html.escape(entry.title)}</a></li>"
            for entry in part.entries
        )
        items.append(
            f'    <li><a href="{part.href}">{html.escape(part.title)}</a>\n'
            f"      <ol>\n{entries}\n      </ol>\n    </li>"
        )
    body = """<nav epub:type="toc" id="toc" aria-labelledby="toc-title">
  <h1 id="toc-title">目录</h1>
  <ol>
    <li><a href="title.xhtml">扉页</a></li>
    <li><a href="intro.xhtml">编选说明</a></li>
""" + "\n".join(items) + """
  </ol>
</nav>
<nav epub:type="landmarks" class="landmarks" aria-label="导览">
  <h2>导览</h2>
  <ol>
    <li><a epub:type="cover" href="cover.xhtml">封面</a></li>
    <li><a epub:type="toc" href="nav.xhtml">目录</a></li>
    <li><a epub:type="bodymatter" href="e001.xhtml">正文</a></li>
  </ol>
</nav>"""
    return xhtml_document("目录", body, "toc-body")


def toc_ncx(book: Book) -> str:
    play_order = 1

    def next_order() -> int:
        nonlocal play_order
        order = play_order
        play_order += 1
        return order

    def leaf(identifier: str, label: str, href: str, indent: str = "    ") -> str:
        return (
            f'{indent}<navPoint id="{identifier}" playOrder="{next_order()}">\n'
            f"{indent}  <navLabel><text>{html.escape(label)}</text></navLabel>\n"
            f'{indent}  <content src="{href}" />\n'
            f"{indent}</navPoint>\n"
        )

    points = leaf("title", "扉页", "title.xhtml")
    points += leaf("intro", "编选说明", "intro.xhtml")
    for part in book.parts:
        # playOrder 必须与阅读顺序一致：父节点先取号，再生成子节点。
        head = (
            f'    <navPoint id="part{part.index}" playOrder="{next_order()}">\n'
            f"      <navLabel><text>{html.escape(part.title)}</text></navLabel>\n"
            f'      <content src="{part.href}" />\n'
        )
        children = "".join(
            leaf(
                f"e{entry.number:03d}",
                f"{entry.number}. {entry.title}",
                entry.href,
                indent="      ",
            )
            for entry in part.entries
        )
        points += head + children + "    </navPoint>\n"
    return f"""<?xml version="1.0" encoding="utf-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1" xml:lang="zh-CN">
  <head>
    <meta name="dtb:uid" content="{BOOK_ID}" />
    <meta name="dtb:depth" content="2" />
    <meta name="dtb:totalPageCount" content="0" />
    <meta name="dtb:maxPageNumber" content="0" />
  </head>
  <docTitle><text>{BOOK_TITLE}</text></docTitle>
  <docAuthor><text>traceme</text></docAuthor>
  <navMap>
{points}  </navMap>
</ncx>
"""


def content_opf(book: Book, modified: str) -> str:
    manifest = "\n".join(
        f'    <item id="part{part.index}" href="{part.href}" media-type="application/xhtml+xml" />'
        for part in book.parts
    )
    manifest += "\n" + "\n".join(
        f'    <item id="e{entry.number:03d}" href="{entry.href}" media-type="application/xhtml+xml" />'
        for entry in book.entries
    )
    spine_lines: list[str] = []
    for part in book.parts:
        spine_lines.append(f'    <itemref idref="part{part.index}" />')
        spine_lines.extend(
            f'    <itemref idref="e{entry.number:03d}" />' for entry in part.entries
        )
    spine = "\n".join(spine_lines)
    return f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="book-id" xml:lang="zh-CN" prefix="dcterms: http://purl.org/dc/terms/">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="book-id">{BOOK_ID}</dc:identifier>
    <dc:title>{BOOK_TITLE}</dc:title>
    <dc:language>{LANGUAGE}</dc:language>
    <dc:creator id="creator">traceme</dc:creator>
    <dc:publisher>DDJ-investing</dc:publisher>
    <dc:date>{BOOK_DATE}</dc:date>
    <dc:description>从《第三只眼观投资心法》《道德经81章投资心法》《道德经81章投资心法·Codex版本》共313章中提炼合并的{book.declared_count}条投资心法，按生存性、根本性与三书共振度排序，每条附三书原文摘录并标明出处。</dc:description>
    <dc:subject>投资</dc:subject>
    <dc:subject>道德经</dc:subject>
    <dc:subject>价值投资</dc:subject>
    <meta property="dcterms:modified">{modified}</meta>
    <meta name="cover" content="cover-image" />
  </metadata>
  <manifest>
    <item id="cover-image" href="cover.png" media-type="image/png" properties="cover-image" />
    <item id="cover" href="cover.xhtml" media-type="application/xhtml+xml" />
    <item id="title" href="title.xhtml" media-type="application/xhtml+xml" />
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav" />
    <item id="intro" href="intro.xhtml" media-type="application/xhtml+xml" />
{manifest}
    <item id="css" href="style/book.css" media-type="text/css" />
    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml" />
  </manifest>
  <spine toc="ncx" page-progression-direction="ltr">
    <itemref idref="cover" linear="no" />
    <itemref idref="title" />
    <itemref idref="nav" />
    <itemref idref="intro" />
{spine}
  </spine>
  <guide>
    <reference type="cover" title="封面" href="cover.xhtml" />
    <reference type="toc" title="目录" href="nav.xhtml" />
    <reference type="text" title="正文" href="e001.xhtml" />
  </guide>
</package>
"""


BOOK_CSS = """@charset "UTF-8";
@namespace epub "http://www.idpf.org/2007/ops";

html { color: #352f25; background: #fffdf8; }
body {
  margin: 5%;
  font-family: "Songti SC", "Noto Serif CJK SC", serif;
  font-size: 1em;
  line-height: 1.9;
  text-align: justify;
}
h1 {
  margin: 0.9em 0 1.1em;
  color: #2f624d;
  font-size: 1.5em;
  font-weight: 600;
  line-height: 1.55;
  text-align: center;
}
h2 {
  margin: 1.7em 0 0.7em;
  color: #3d6b56;
  font-size: 1.1em;
  font-weight: 600;
}
p { margin: 0.55em 0; text-indent: 2em; }
a { color: #3d6b56; text-decoration: none; }
blockquote {
  margin: 1em 0.25em;
  padding: 0.9em 1.1em;
  border-left: 0.3em solid #b79a58;
  background: #faf6eb;
  color: #493f2c;
}
blockquote p { margin: 0.3em 0; text-indent: 0; }
ol, ul { padding-left: 1.5em; }
li { margin: 0.5em 0; }
.entry-no {
  margin-bottom: 0;
  color: #b18f43;
  font-size: 0.86em;
  letter-spacing: 0.16em;
  text-align: center;
  text-indent: 0;
}
.entry-body { margin: 0.6em 0 1.4em; }
.quotes h2 {
  margin: 1.6em 0 0.4em;
  color: #8c7950;
  font-size: 0.92em;
  font-weight: normal;
  letter-spacing: 0.2em;
  text-align: center;
}
.quotes blockquote { font-size: 0.94em; }
.quotes blockquote p { margin: 0.85em 0; line-height: 1.85; }
.src {
  display: block;
  margin-top: 0.1em;
  color: #8c7950;
  font-size: 0.85em;
  text-align: right;
}
.notice, .disclaimer { font-size: 0.92em; }
.disclaimer { border-left-color: #a8543f; background: #f9f0ea; }
.parts li { text-align: justify; }
.entry-nav {
  display: flex;
  justify-content: space-between;
  margin-top: 2.5em;
  padding-top: 0.8em;
  border-top: 1px solid #d8ccb0;
  font-size: 0.88em;
}
.entry-nav a { margin: 0 0.35em; }
.cover-body { margin: 0; padding: 0; background: #f6f2e7; text-align: center; }
.cover-page { margin: 0; padding: 0; }
.cover-page img { width: 100%; height: auto; max-height: 100%; object-fit: contain; }
.title-body, .part-body { margin: 0; padding: 0; }
.title-page, .part-page {
  min-height: 85vh;
  padding: 18% 8% 8%;
  box-sizing: border-box;
  text-align: center;
}
.title-page h1 { margin: 1.1em 0 0.5em; font-size: 2.2em; color: #352f25; }
.title-page h1 span { color: #3d6b56; font-size: 0.68em; }
.eyebrow { color: #b18f43; text-indent: 0; text-align: center; letter-spacing: 0.18em; }
.subtitle, .author, .part-summary { text-indent: 0; text-align: center; }
.subtitle { color: #3d6b56; font-size: 1.1em; }
.author { margin-top: 8em; color: #8c7950; }
.part-page h1 { margin-top: 1.5em; font-size: 2em; }
.part-summary { max-width: 28em; margin: 2em auto; color: #655a46; }
.toc-body { text-align: left; }
.toc-body h1 { text-align: center; }
.toc-body ol { padding-left: 1.4em; }
.toc-body ol ol { margin: 0.5em 0 1em; }
.landmarks { margin-top: 2em; border-top: 1px solid #d8ccb0; }
"""


CONTAINER_XML = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="EPUB/content.opf" media-type="application/oebps-package+xml" />
  </rootfiles>
</container>
"""


# --------------------------------------------------------------------------- #
# Packaging
# --------------------------------------------------------------------------- #


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def assemble_epub(build_dir: Path, book: Book) -> None:
    epub_dir = build_dir / "EPUB"
    write_text(build_dir / "mimetype", "application/epub+zip")
    write_text(build_dir / "META-INF" / "container.xml", CONTAINER_XML)
    write_text(epub_dir / "style" / "book.css", BOOK_CSS)
    build_cover(epub_dir / "cover.png")
    write_text(epub_dir / "cover.xhtml", cover_xhtml())
    write_text(epub_dir / "title.xhtml", title_xhtml(book))
    write_text(epub_dir / "intro.xhtml", intro_xhtml(book))
    for part in book.parts:
        write_text(epub_dir / part.href, part_xhtml(part))
    entries = book.entries
    for position, entry in enumerate(entries):
        previous_href = "intro.xhtml" if position == 0 else entries[position - 1].href
        next_href = (
            "nav.xhtml" if position == len(entries) - 1 else entries[position + 1].href
        )
        write_text(epub_dir / entry.href, entry_xhtml(entry, previous_href, next_href))
    write_text(epub_dir / "nav.xhtml", nav_xhtml(book))
    write_text(epub_dir / "toc.ncx", toc_ncx(book))
    modified = (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
    write_text(epub_dir / "content.opf", content_opf(book, modified))


def package_epub(build_dir: Path, output: Path) -> None:
    temporary_output = output.with_suffix(output.suffix + ".tmp")
    with zipfile.ZipFile(temporary_output, "w") as archive:
        archive.write(
            build_dir / "mimetype", "mimetype", compress_type=zipfile.ZIP_STORED
        )
        for path in sorted(build_dir.rglob("*")):
            if not path.is_file() or path.name == "mimetype":
                continue
            archive.write(
                path,
                path.relative_to(build_dir).as_posix(),
                compress_type=zipfile.ZIP_DEFLATED,
                compresslevel=9,
            )
    temporary_output.replace(output)


def validate_epub(output: Path, book: Book) -> None:
    entries = book.entries
    with zipfile.ZipFile(output) as archive:
        names = archive.namelist()
        if names[0] != "mimetype":
            raise ValueError("mimetype 必须是 EPUB 中的首个文件")
        if archive.getinfo("mimetype").compress_type != zipfile.ZIP_STORED:
            raise ValueError("mimetype 不得压缩")
        if archive.read("mimetype") != b"application/epub+zip":
            raise ValueError("mimetype 内容错误")

        required = {
            "META-INF/container.xml",
            "EPUB/content.opf",
            "EPUB/nav.xhtml",
            "EPUB/toc.ncx",
            "EPUB/cover.png",
            "EPUB/intro.xhtml",
            *(f"EPUB/{part.href}" for part in book.parts),
            *(f"EPUB/{entry.href}" for entry in entries),
        }
        missing = required - set(names)
        if missing:
            raise ValueError(f"EPUB 缺少文件：{sorted(missing)}")

        parsed_xml: dict[str, ET.Element] = {
            name: ET.fromstring(archive.read(name))
            for name in names
            if name.endswith((".xml", ".xhtml", ".opf", ".ncx"))
        }

        opf_ns = {
            "opf": "http://www.idpf.org/2007/opf",
            "dc": "http://purl.org/dc/elements/1.1/",
        }
        opf = parsed_xml["EPUB/content.opf"]
        if opf.findtext("opf:metadata/dc:title", namespaces=opf_ns) != BOOK_TITLE:
            raise ValueError("EPUB 书名错误")
        manifest_items = opf.findall("opf:manifest/opf:item", opf_ns)
        manifest = {item.attrib["id"]: item.attrib["href"] for item in manifest_items}
        if len(manifest) != len(manifest_items):
            raise ValueError("manifest 中存在重复 id")
        for href in manifest.values():
            target = posixpath.normpath(posixpath.join("EPUB", unquote(href)))
            if target not in names:
                raise ValueError(f"manifest 指向不存在的文件：{href}")
        spine = [
            itemref.attrib.get("idref")
            for itemref in opf.findall("opf:spine/opf:itemref", opf_ns)
        ]
        for idref in spine:
            if idref not in manifest:
                raise ValueError(f"spine idref 无对应 manifest 项：{idref}")
        if len(spine) != len(set(spine)):
            raise ValueError("spine 中存在重复条目")

        for name, root in parsed_xml.items():
            if not name.startswith("EPUB/"):
                continue
            for element in root.iter():
                for attribute in ("href", "src"):
                    value = element.attrib.get(attribute)
                    if not value:
                        continue
                    parsed = urlsplit(value)
                    if parsed.scheme or not parsed.path:
                        continue
                    target = posixpath.normpath(
                        posixpath.join(posixpath.dirname(name), unquote(parsed.path))
                    )
                    if target not in names:
                        raise ValueError(f"{name} 含无效内部链接：{value}")

        xhtml_ns = {"xhtml": "http://www.w3.org/1999/xhtml"}
        nav = parsed_xml["EPUB/nav.xhtml"]
        nav_links = {
            anchor.attrib.get("href", "")
            for anchor in nav.findall(".//xhtml:a", xhtml_ns)
        }
        expected_links = {entry.href for entry in entries} | {
            part.href for part in book.parts
        }
        if not expected_links <= nav_links:
            raise ValueError("导航目录未覆盖全部分部与条目")

        ncx_ns = {"ncx": "http://www.daisy.org/z3986/2005/ncx/"}
        ncx_points = parsed_xml["EPUB/toc.ncx"].findall(".//ncx:content", ncx_ns)
        if len({point.attrib["src"] for point in ncx_points}) != len(ncx_points):
            raise ValueError("toc.ncx 中存在重复目标")

        total_quotes = 0
        for entry in entries:
            page = parsed_xml[f"EPUB/{entry.href}"]
            bodies = [
                element
                for element in page.findall(".//xhtml:p", xhtml_ns)
                if element.attrib.get("class") == "entry-body"
            ]
            if len(bodies) != 1:
                raise ValueError(f"第{entry.number}条正文段落数错误：{len(bodies)}")
            quote_paragraphs = page.findall(
                ".//xhtml:blockquote/xhtml:p", xhtml_ns
            )
            if len(quote_paragraphs) != len(entry.quotes):
                raise ValueError(
                    f"第{entry.number}条引文数不符："
                    f"{len(quote_paragraphs)} ≠ {len(entry.quotes)}"
                )
            for paragraph in quote_paragraphs:
                sources = [
                    span
                    for span in paragraph.findall("xhtml:span", xhtml_ns)
                    if span.attrib.get("class") == "src"
                ]
                if len(sources) != 1 or not (sources[0].text or "").startswith("——《"):
                    raise ValueError(f"第{entry.number}条存在缺失出处的引文")
            total_quotes += len(quote_paragraphs)
        source_quotes = sum(
            1 for line in SOURCE.read_text(encoding="utf-8").split("\n") if "　——《" in line
        )
        if total_quotes != source_quotes:
            raise ValueError(f"EPUB 引文总数 {total_quotes} ≠ 源文件 {source_quotes}")

        with Image.open(BytesIO(archive.read("EPUB/cover.png"))) as cover:
            if cover.size != (1600, 2400) or cover.format != "PNG":
                raise ValueError("封面必须为1600×2400 PNG")


def main() -> None:
    book = parse_book()
    with tempfile.TemporaryDirectory(prefix="ddj-selection-epub-") as temporary:
        build_dir = Path(temporary)
        assemble_epub(build_dir, book)
        package_epub(build_dir, OUTPUT)
    validate_epub(OUTPUT, book)
    quotes = sum(len(entry.quotes) for entry in book.entries)
    print(f"已生成：{OUTPUT}")
    print(
        f"条目：{len(book.entries)}；分部：{len(book.parts)}；"
        f"引文：{quotes}；文件大小：{OUTPUT.stat().st_size:,} bytes"
    )
    for part in book.parts:
        print(f"  {part.name}（{part.span}）：{len(part.entries)} 条")


if __name__ == "__main__":
    main()
