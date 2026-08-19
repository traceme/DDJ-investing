#!/usr/bin/env python3
"""Build the Codex edition as a self-contained EPUB 3 book."""

from __future__ import annotations

import html
import posixpath
import re
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from io import BytesIO
from pathlib import Path
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree as ET

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
CODEX_DIR = ROOT / "codex"
MAIN_DIR = ROOT / "chapters"
SOURCE_TEXT = ROOT / "原文" / "道德经-王弼本.md"
OUTPUT = ROOT / "道德经81章投资心法Codex版本.epub"
BOOK_TITLE = "道德经81章投资心法Codex版本"
BOOK_ID = "ddj-investing-81-codex"
LANGUAGE = "zh-CN"
MIN_ESSAY_CHARS = 380
MAX_ESSAY_CHARS = 800
SIMILARITY_LIMIT = 0.30
MIN_SHARED_PARAGRAPH_CHARS = 50

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
class Chapter:
    number: int
    title: str
    original: str
    essay: str
    advice: str

    @property
    def href(self) -> str:
        return f"ch{self.number:02d}.xhtml"


def xhtml_document(title: str, body: str, body_class: str = "") -> str:
    class_attr = f' class="{body_class}"' if body_class else ""
    return (
        XHTML_HEADER.format(title=html.escape(title), body_class=class_attr)
        + body
        + "\n</body>\n</html>\n"
    )


def inline_markdown(text: str) -> str:
    allowed_tags = {
        "<mark>": "\ue000",
        "</mark>": "\ue001",
        "<u>": "\ue002",
        "</u>": "\ue003",
    }
    protected = text.strip()
    for tag, placeholder in allowed_tags.items():
        protected = protected.replace(tag, placeholder)
    escaped = html.escape(protected, quote=True)

    def replace_link(match: re.Match[str]) -> str:
        label, href = match.groups()
        if href in {"/原文/道德经-王弼本.md", "原文/道德经-王弼本.md"}:
            href = "appendix.xhtml"
        return f'<a href="{html.escape(href, quote=True)}">{label}</a>'

    escaped = re.sub(r"\[([^]]+)]\(([^)]+)\)", replace_link, escaped)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    for tag, placeholder in allowed_tags.items():
        escaped = escaped.replace(placeholder, tag)
    return escaped


def paragraphs(text: str, css_class: str | None = None) -> str:
    class_attr = f' class="{css_class}"' if css_class else ""
    blocks = [block.strip() for block in re.split(r"\n\s*\n", text) if block.strip()]
    rendered = []
    for block in blocks:
        rendered_lines = [inline_markdown(line) for line in block.splitlines()]
        rendered.append(f"<p{class_attr}>{'<br />'.join(rendered_lines)}</p>")
    return "\n".join(rendered)


def markdown_fragment(markdown: str) -> str:
    """Render the small Markdown subset used by the Codex introduction."""
    lines = markdown.splitlines()
    output: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index].rstrip()
        if not line:
            index += 1
            continue
        if line.startswith("# "):
            index += 1
            continue
        if line.startswith("## "):
            output.append(f"<h2>{inline_markdown(line[3:])}</h2>")
            index += 1
            continue
        if line.startswith("> "):
            quote_lines: list[str] = []
            while index < len(lines) and lines[index].startswith("> "):
                quote_lines.append(lines[index][2:].strip())
                index += 1
            output.append(
                '<blockquote class="notice"><p>'
                + "<br />".join(inline_markdown(item) for item in quote_lines)
                + "</p></blockquote>"
            )
            continue
        if line.startswith("- "):
            items: list[str] = []
            while index < len(lines) and lines[index].startswith("- "):
                items.append(f"<li>{inline_markdown(lines[index][2:])}</li>")
                index += 1
            output.append("<ul>" + "".join(items) + "</ul>")
            continue
        if (
            line.startswith("|")
            and index + 1 < len(lines)
            and re.match(r"^\|[\s:|-]+\|$", lines[index + 1])
        ):
            rows: list[list[str]] = []
            while index < len(lines) and lines[index].startswith("|"):
                cells = [cell.strip() for cell in lines[index].strip("|").split("|")]
                rows.append(cells)
                index += 1
            header, data_rows = rows[0], rows[2:]
            table = ["<table><thead><tr>"]
            table.extend(f"<th>{inline_markdown(cell)}</th>" for cell in header)
            table.append("</tr></thead><tbody>")
            for row in data_rows:
                table.append("<tr>")
                table.extend(f"<td>{inline_markdown(cell)}</td>" for cell in row)
                table.append("</tr>")
            table.append("</tbody></table>")
            output.append("".join(table))
            continue

        paragraph_lines = [line]
        index += 1
        while index < len(lines) and lines[index].strip():
            candidate = lines[index]
            if candidate.startswith(("#", "> ", "- ", "|")):
                break
            paragraph_lines.append(candidate.strip())
            index += 1
        output.append("<p>" + inline_markdown(" ".join(paragraph_lines)) + "</p>")
    return "\n".join(output)


def parse_source_text() -> tuple[str, dict[int, str]]:
    text = SOURCE_TEXT.read_text(encoding="utf-8")
    first_heading = re.search(r"^## 第1章\s*$", text, re.MULTILINE)
    if not first_heading:
        raise ValueError(f"无法解析底本：{SOURCE_TEXT}")
    introduction = text[: first_heading.start()].strip()
    matches = list(re.finditer(r"^## 第(\d+)章\s*$", text, re.MULTILINE))
    chapters: dict[int, str] = {}
    for pos, match in enumerate(matches):
        end = matches[pos + 1].start() if pos + 1 < len(matches) else len(text)
        chapters[int(match.group(1))] = text[match.end() : end].strip()
    if set(chapters) != set(range(1, 82)):
        raise ValueError("底本必须完整包含第1至81章")
    return introduction, chapters


def extract_investment_essay(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    heading = re.search(r"^## 投资心法\s*$", text, re.MULTILINE)
    if not heading:
        raise ValueError(f"缺少投资心法：{path}")
    remainder = text[heading.end() :]
    next_heading = re.search(r"^##\s+", remainder, re.MULTILINE)
    return remainder[: next_heading.start() if next_heading else None].strip()


def normalized_prose(text: str) -> str:
    without_tags = re.sub(r"</?(?:mark|u)>", "", text)
    return re.sub(r"[\W_]+", "", without_tags)


def audit_independent_prose(chapters: list[Chapter]) -> tuple[int, int, float]:
    """Reject copied prose, including copying from a different main-book chapter."""
    main_essays = {
        number: extract_investment_essay(MAIN_DIR / f"第{number:02d}章.md")
        for number in range(1, 82)
    }
    normalized_main = {
        number: normalized_prose(essay) for number, essay in main_essays.items()
    }
    main_paragraphs: dict[str, int] = {}
    for number, essay in main_essays.items():
        for paragraph in re.split(r"\n\s*\n", essay):
            normalized = normalized_prose(paragraph)
            if len(normalized) >= MIN_SHARED_PARAGRAPH_CHARS:
                main_paragraphs.setdefault(normalized, number)

    highest_similarity = (0, 0, 0.0)
    for chapter in chapters:
        normalized = normalized_prose(chapter.essay)
        best_ratio, best_number = max(
            (
                SequenceMatcher(
                    None,
                    normalized,
                    main_text,
                    autojunk=False,
                ).ratio(),
                main_number,
            )
            for main_number, main_text in normalized_main.items()
        )
        if best_ratio >= SIMILARITY_LIMIT:
            raise ValueError(
                f"第{chapter.number}章与主书第{best_number}章文本相似度"
                f"为{best_ratio:.1%}，必须低于{SIMILARITY_LIMIT:.0%}"
            )
        if best_ratio > highest_similarity[2]:
            highest_similarity = (chapter.number, best_number, best_ratio)
        for paragraph in re.split(r"\n\s*\n", chapter.essay):
            normalized_paragraph = normalized_prose(paragraph)
            copied_from = main_paragraphs.get(normalized_paragraph)
            if copied_from is not None:
                raise ValueError(
                    f"第{chapter.number}章复用了主书第{copied_from}章的完整长段落"
                )
    return highest_similarity


def parse_chapter(number: int) -> Chapter:
    path = CODEX_DIR / f"第{number:02d}章.md"
    text = path.read_text(encoding="utf-8")
    text = text.split("<!-- codex-nav -->", 1)[0].strip()
    title_match = re.search(r"^# (.+)$", text, re.MULTILINE)
    if not title_match:
        raise ValueError(f"缺少章节标题：{path}")

    section_matches = list(
        re.finditer(r"^## (原文|投资心法|实操建议)\s*$", text, re.MULTILINE)
    )
    sections: dict[str, str] = {}
    for pos, match in enumerate(section_matches):
        end = (
            section_matches[pos + 1].start()
            if pos + 1 < len(section_matches)
            else len(text)
        )
        sections[match.group(1)] = text[match.end() : end].strip()
    expected = {"原文", "投资心法", "实操建议"}
    if set(sections) != expected:
        raise ValueError(f"章节结构不完整：{path}")

    original = "\n".join(
        line[2:] if line.startswith("> ") else line.lstrip(">")
        for line in sections["原文"].splitlines()
    ).strip()
    essay = sections["投资心法"].strip()
    plain_essay = re.sub(r"\s+", "", re.sub(r"</?(?:mark|u)>", "", essay))
    if not MIN_ESSAY_CHARS <= len(plain_essay) <= MAX_ESSAY_CHARS:
        raise ValueError(
            f"第{number}章投资心法为{len(plain_essay)}字，应保持在"
            f"{MIN_ESSAY_CHARS}至{MAX_ESSAY_CHARS}字"
        )
    if essay.count("<u>") != 2 or essay.count("</u>") != 2:
        raise ValueError(f"第{number}章投资心法必须恰有两处下划线心法")
    if essay.count("<mark>") < 2 or essay.count("<mark>") != essay.count("</mark>"):
        raise ValueError(f"第{number}章原文回扣标记不完整")
    advice = sections["实操建议"].strip()
    plain_advice = re.sub(r"\s+", "", advice)
    if len(plain_advice) >= 100:
        raise ValueError(f"第{number}章实操建议达到{len(plain_advice)}字，应少于100字")
    if re.search(r"</?(?:mark|u)>", advice):
        raise ValueError(f"第{number}章实操建议不得包含mark或u标记")
    return Chapter(
        number=number,
        title=title_match.group(1).strip(),
        original=original,
        essay=essay,
        advice=advice,
    )


def load_book() -> tuple[list[Chapter], str, dict[int, str], tuple[int, int, float]]:
    source_intro, source_chapters = parse_source_text()
    chapters = [parse_chapter(number) for number in range(1, 82)]
    for chapter in chapters:
        if chapter.original != source_chapters[chapter.number]:
            raise ValueError(f"第{chapter.number}章原文与王弼底本不一致")
        source_without_space = re.sub(r"\s+", "", source_chapters[chapter.number])
        for quote in re.findall(r"<mark>(.*?)</mark>", chapter.essay, re.DOTALL):
            if re.sub(r"\s+", "", quote) not in source_without_space:
                raise ValueError(
                    f"第{chapter.number}章mark引文无法在本章王弼底本中逐字定位：{quote}"
                )
    independence_audit = audit_independent_prose(chapters)
    return chapters, source_intro, source_chapters, independence_audit


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
    centered_text(draw, 160, "道 · 德 · 经", get_font(50), gold, spacing=10)

    cx, cy, radius = 800, 600, 210
    circle = (cx - radius, cy - radius, cx + radius, cy + radius)
    draw.ellipse(circle, fill=background, outline=green, width=8)
    draw.pieslice(circle, 90, 270, fill=green)
    draw.ellipse((cx - radius // 2, cy - radius, cx + radius // 2, cy), fill=green)
    draw.ellipse((cx - radius // 2, cy, cx + radius // 2, cy + radius), fill=background)
    dot = 30
    draw.ellipse(
        (cx - dot, cy - radius // 2 - dot, cx + dot, cy - radius // 2 + dot),
        fill=background,
    )
    draw.ellipse(
        (cx - dot, cy + radius // 2 - dot, cx + dot, cy + radius // 2 + dot), fill=green
    )
    draw.ellipse(circle, outline=green, width=8)

    centered_text(draw, 940, "道德经", get_font(220), ink, spacing=12)
    centered_text(draw, 1210, "81章投资心法", get_font(132), ink, spacing=4)
    draw.line((560, 1430, 1040, 1430), fill=gold, width=4)

    badge_text = "CODEX 版本"
    badge_font = get_font(64)
    badge_box = draw.textbbox((0, 0), badge_text, font=badge_font)
    badge_width = badge_box[2] - badge_box[0] + 100
    badge_left = (1600 - badge_width) / 2
    draw.rounded_rectangle(
        (badge_left, 1510, badge_left + badge_width, 1620),
        radius=14,
        fill=green,
    )
    centered_text(draw, 1525, badge_text, badge_font, background, spacing=4)

    centered_text(draw, 1750, "从章句到投资日常", get_font(66), green, spacing=3)
    centered_text(
        draw, 1870, "生活入道 · 市场见心 · 知行合一", get_font(46), ink, spacing=2
    )
    centered_text(draw, 2180, "traceme  ·  Codex", get_font(40), gold, spacing=2)
    image.save(path, format="PNG", optimize=True)


def cover_xhtml() -> str:
    body = """<section epub:type="cover" class="cover-page">
  <img src="cover.png" alt="道德经81章投资心法Codex版本封面" />
</section>"""
    return xhtml_document(BOOK_TITLE, body, "cover-body")


def title_xhtml() -> str:
    body = """<section epub:type="titlepage" class="title-page">
  <p class="eyebrow">道德经 · 八十一章</p>
  <h1>道德经81章投资心法<br /><span>Codex版本</span></h1>
  <p class="subtitle">从章句到投资日常</p>
  <p class="author">traceme · Codex</p>
</section>"""
    return xhtml_document(BOOK_TITLE, body, "title-body")


def intro_xhtml() -> str:
    readme = (CODEX_DIR / "README.md").read_text(encoding="utf-8")
    introduction = readme.split("## 全书目录", 1)[0].strip()
    introduction = "\n".join(
        line for line in introduction.splitlines() if not line.startswith("📘 电子书：")
    )
    body = '<section epub:type="preface">\n<h1>阅读说明</h1>\n'
    body += markdown_fragment(introduction)
    body += "\n</section>"
    return xhtml_document("阅读说明", body)


def part_xhtml(title: str, subtitle: str, summary: str) -> str:
    body = f"""<section epub:type="part" class="part-page">
  <p class="eyebrow">{html.escape(subtitle)}</p>
  <h1>{html.escape(title)}</h1>
  <p class="part-summary">{html.escape(summary)}</p>
</section>"""
    return xhtml_document(title, body, "part-body")


def chapter_xhtml(chapter: Chapter) -> str:
    previous_href = (
        "intro.xhtml" if chapter.number == 1 else f"ch{chapter.number - 1:02d}.xhtml"
    )
    next_href = (
        "appendix.xhtml"
        if chapter.number == 81
        else f"ch{chapter.number + 1:02d}.xhtml"
    )
    body = f"""<article epub:type="chapter">
  <h1>{html.escape(chapter.title)}</h1>
  <section class="original" epub:type="epigraph">
    <h2>原文</h2>
    <blockquote><p>{inline_markdown(chapter.original)}</p></blockquote>
  </section>
  <section>
    <h2>投资心法</h2>
    {paragraphs(chapter.essay)}
  </section>
  <section class="advice">
    <h2>实操建议</h2>
    {paragraphs(chapter.advice)}
  </section>
  <nav class="chapter-nav" aria-label="章节导航">
    <a href="{previous_href}">← 上一章</a>
    <a href="nav.xhtml">目录</a>
    <a href="{next_href}">下一章 →</a>
  </nav>
</article>"""
    return xhtml_document(chapter.title, body)


def appendix_xhtml(source_intro: str, source_chapters: dict[int, str]) -> str:
    notes = []
    for line in source_intro.splitlines():
        if line.startswith("> "):
            notes.append(f"<p>{inline_markdown(line[2:])}</p>")
    body = [
        '<section epub:type="appendix">',
        "<h1>附录 · 道德经王弼本</h1>",
        '<blockquote class="source-note">' + "".join(notes) + "</blockquote>",
    ]
    for number in range(1, 82):
        body.append(f'<h2 id="source-{number}">第{number}章</h2>')
        body.append(f"<p>{inline_markdown(source_chapters[number])}</p>")
    body.append("</section>")
    return xhtml_document("附录 · 道德经王弼本", "\n".join(body))


def nav_xhtml(chapters: list[Chapter]) -> str:
    def chapter_items(start: int, end: int) -> str:
        return "\n".join(
            f'        <li><a href="{chapter.href}">{html.escape(chapter.title)}</a></li>'
            for chapter in chapters[start - 1 : end]
        )

    body = f"""<nav epub:type="toc" id="toc" aria-labelledby="toc-title">
  <h1 id="toc-title">目录</h1>
  <ol>
    <li><a href="title.xhtml">扉页</a></li>
    <li><a href="intro.xhtml">阅读说明</a></li>
    <li><a href="part1.xhtml">道经 · 上篇（第一至三十七章）</a>
      <ol>
{chapter_items(1, 37)}
      </ol>
    </li>
    <li><a href="part2.xhtml">德经 · 下篇（第三十八至八十一章）</a>
      <ol>
{chapter_items(38, 81)}
      </ol>
    </li>
    <li><a href="appendix.xhtml">附录 · 道德经王弼本</a></li>
  </ol>
</nav>
<nav epub:type="landmarks" class="landmarks" aria-label="导览">
  <h2>导览</h2>
  <ol>
    <li><a epub:type="cover" href="cover.xhtml">封面</a></li>
    <li><a epub:type="toc" href="nav.xhtml">目录</a></li>
    <li><a epub:type="bodymatter" href="ch01.xhtml">正文</a></li>
  </ol>
</nav>"""
    return xhtml_document("目录", body, "toc-body")


def toc_ncx(chapters: list[Chapter]) -> str:
    play_order = 1

    def point(identifier: str, label: str, href: str) -> str:
        nonlocal play_order
        order = play_order
        play_order += 1
        return f"""    <navPoint id="{identifier}" playOrder="{order}">
      <navLabel><text>{html.escape(label)}</text></navLabel>
      <content src="{href}" />
    </navPoint>
"""

    points = point("title", "扉页", "title.xhtml")
    points += point("intro", "阅读说明", "intro.xhtml")
    points += point("part1", "道经 · 上篇", "part1.xhtml")
    points += "".join(
        point(f"ch{chapter.number:02d}", chapter.title, chapter.href)
        for chapter in chapters[:37]
    )
    points += point("part2", "德经 · 下篇", "part2.xhtml")
    points += "".join(
        point(f"ch{chapter.number:02d}", chapter.title, chapter.href)
        for chapter in chapters[37:]
    )
    points += point("appendix", "附录 · 道德经王弼本", "appendix.xhtml")
    return f"""<?xml version="1.0" encoding="utf-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1" xml:lang="zh-CN">
  <head>
    <meta name="dtb:uid" content="{BOOK_ID}" />
    <meta name="dtb:depth" content="1" />
    <meta name="dtb:totalPageCount" content="0" />
    <meta name="dtb:maxPageNumber" content="0" />
  </head>
  <docTitle><text>{BOOK_TITLE}</text></docTitle>
  <docAuthor><text>traceme · Codex</text></docAuthor>
  <navMap>
{points}  </navMap>
</ncx>
"""


def content_opf(chapters: list[Chapter], modified: str) -> str:
    chapter_manifest = "\n".join(
        f'    <item id="ch{chapter.number:02d}" href="{chapter.href}" media-type="application/xhtml+xml" />'
        for chapter in chapters
    )
    chapter_spine = "\n".join(
        f'    <itemref idref="ch{chapter.number:02d}" />' for chapter in chapters
    )
    spine_lines = chapter_spine.splitlines()
    upper_spine = "\n".join(spine_lines[:37])
    lower_spine = "\n".join(spine_lines[37:])
    return f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="book-id" xml:lang="zh-CN" prefix="dcterms: http://purl.org/dc/terms/">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="book-id">{BOOK_ID}</dc:identifier>
    <dc:title>{BOOK_TITLE}</dc:title>
    <dc:language>{LANGUAGE}</dc:language>
    <dc:creator id="creator">traceme</dc:creator>
    <dc:contributor>Codex</dc:contributor>
    <dc:publisher>DDJ-investing</dc:publisher>
    <dc:date>2026-08-19</dc:date>
    <dc:description>以王弼通行本为底本，从生活经验和市场场景切入，用通俗语言讲清八十一章与投资方法、人性修炼及长期复利的关系，并为每章提供实操建议。</dc:description>
    <dc:subject>道德经</dc:subject>
    <dc:subject>投资</dc:subject>
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
    <item id="part1" href="part1.xhtml" media-type="application/xhtml+xml" />
    <item id="part2" href="part2.xhtml" media-type="application/xhtml+xml" />
{chapter_manifest}
    <item id="appendix" href="appendix.xhtml" media-type="application/xhtml+xml" />
    <item id="css" href="style/book.css" media-type="text/css" />
    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml" />
  </manifest>
  <spine toc="ncx" page-progression-direction="ltr">
    <itemref idref="cover" linear="no" />
    <itemref idref="title" />
    <itemref idref="nav" />
    <itemref idref="intro" />
    <itemref idref="part1" />
{upper_spine}
    <itemref idref="part2" />
{lower_spine}
    <itemref idref="appendix" />
  </spine>
  <guide>
    <reference type="cover" title="封面" href="cover.xhtml" />
    <reference type="toc" title="目录" href="nav.xhtml" />
    <reference type="text" title="正文" href="ch01.xhtml" />
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
  margin: 1.2em 0 1.3em;
  color: #2f624d;
  font-size: 1.65em;
  font-weight: 600;
  line-height: 1.5;
  text-align: center;
}
h2 {
  margin: 1.7em 0 0.7em;
  color: #3d6b56;
  font-size: 1.18em;
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
ul { padding-left: 1.5em; }
li { margin: 0.45em 0; }
code { font-family: monospace; font-size: 0.9em; }
mark {
  padding: 0 0.12em;
  background: #f3e7bf;
  color: #7a5819;
  font-weight: 600;
}
u {
  text-decoration-color: #4d806a;
  text-decoration-thickness: 0.1em;
  text-underline-offset: 0.18em;
}
table { width: 100%; border-collapse: collapse; font-size: 0.88em; }
th, td { padding: 0.55em 0.45em; border: 1px solid #d8ccb0; vertical-align: top; }
th { background: #f2ecdd; color: #3d6b56; }
.original blockquote { font-family: "STKaiti", "Kaiti SC", serif; line-height: 2; }
.advice {
  margin-top: 1.8em;
  padding: 0.1em 1em 0.8em;
  border: 1px solid #d8ccb0;
  border-radius: 0.35em;
  background: #f7f3e7;
}
.advice h2 { margin-top: 0.75em; color: #8a651d; }
.advice p { text-indent: 0; font-weight: 600; }
.chapter-nav {
  display: flex;
  justify-content: space-between;
  margin-top: 2.5em;
  padding-top: 0.8em;
  border-top: 1px solid #d8ccb0;
  font-size: 0.88em;
}
.chapter-nav a { margin: 0 0.35em; }
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
.source-note { font-size: 0.88em; }
"""


CONTAINER_XML = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="EPUB/content.opf" media-type="application/oebps-package+xml" />
  </rootfiles>
</container>
"""


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def assemble_epub(
    build_dir: Path,
    chapters: list[Chapter],
    source_intro: str,
    source_chapters: dict[int, str],
) -> None:
    epub_dir = build_dir / "EPUB"
    write_text(build_dir / "mimetype", "application/epub+zip")
    write_text(build_dir / "META-INF" / "container.xml", CONTAINER_XML)
    write_text(epub_dir / "style" / "book.css", BOOK_CSS)
    build_cover(epub_dir / "cover.png")
    write_text(epub_dir / "cover.xhtml", cover_xhtml())
    write_text(epub_dir / "title.xhtml", title_xhtml())
    write_text(epub_dir / "intro.xhtml", intro_xhtml())
    write_text(
        epub_dir / "part1.xhtml",
        part_xhtml(
            "道经 · 上篇",
            "第一至三十七章",
            "从名与实、有与无讲起，在欲望、得失与等待中，看见投资者最先要管住的是自己的心。",
        ),
    )
    write_text(
        epub_dir / "part2.xhtml",
        part_xhtml(
            "德经 · 下篇",
            "第三十八至八十一章",
            "从德与势、反与复讲起，在周期、仓位与取舍中，学会不争一时而守住长久。",
        ),
    )
    for chapter in chapters:
        write_text(epub_dir / chapter.href, chapter_xhtml(chapter))
    write_text(
        epub_dir / "appendix.xhtml", appendix_xhtml(source_intro, source_chapters)
    )
    write_text(epub_dir / "nav.xhtml", nav_xhtml(chapters))
    write_text(epub_dir / "toc.ncx", toc_ncx(chapters))
    modified = (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
    write_text(epub_dir / "content.opf", content_opf(chapters, modified))


def package_epub(build_dir: Path, output: Path) -> None:
    temporary_output = output.with_suffix(output.suffix + ".tmp")
    with zipfile.ZipFile(temporary_output, "w") as archive:
        archive.write(
            build_dir / "mimetype",
            "mimetype",
            compress_type=zipfile.ZIP_STORED,
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


def validate_epub(output: Path) -> None:
    with zipfile.ZipFile(output) as archive:
        names = archive.namelist()
        if names[0] != "mimetype":
            raise ValueError("mimetype 必须是 EPUB 中的首个文件")
        mimetype = archive.getinfo("mimetype")
        if mimetype.compress_type != zipfile.ZIP_STORED:
            raise ValueError("mimetype 不得压缩")
        if archive.read("mimetype") != b"application/epub+zip":
            raise ValueError("mimetype 内容错误")
        required = {
            "META-INF/container.xml",
            "EPUB/content.opf",
            "EPUB/nav.xhtml",
            "EPUB/toc.ncx",
            "EPUB/cover.png",
            "EPUB/appendix.xhtml",
            *(f"EPUB/ch{number:02d}.xhtml" for number in range(1, 82)),
        }
        missing = required - set(names)
        if missing:
            raise ValueError(f"EPUB 缺少文件：{sorted(missing)}")
        parsed_xml: dict[str, ET.Element] = {}
        for name in names:
            if name.endswith((".xml", ".xhtml", ".opf", ".ncx")):
                parsed_xml[name] = ET.fromstring(archive.read(name))

        opf_ns = {
            "opf": "http://www.idpf.org/2007/opf",
            "dc": "http://purl.org/dc/elements/1.1/",
        }
        opf = parsed_xml["EPUB/content.opf"]
        title = opf.findtext("opf:metadata/dc:title", namespaces=opf_ns)
        if title != BOOK_TITLE:
            raise ValueError(f"EPUB 书名错误：{title}")
        manifest_items = opf.findall("opf:manifest/opf:item", opf_ns)
        manifest = {item.attrib["id"]: item.attrib["href"] for item in manifest_items}
        if len(manifest) != len(manifest_items):
            raise ValueError("manifest 中存在重复 id")
        for href in manifest.values():
            target = posixpath.normpath(posixpath.join("EPUB", unquote(href)))
            if target not in names:
                raise ValueError(f"manifest 指向不存在的文件：{href}")
        for itemref in opf.findall("opf:spine/opf:itemref", opf_ns):
            if itemref.attrib.get("idref") not in manifest:
                raise ValueError(
                    f"spine idref 无对应 manifest 项：{itemref.attrib.get('idref')}"
                )

        local_targets: set[str] = set()
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
                    local_targets.add(target)
                    if target not in names:
                        raise ValueError(f"{name} 含无效内部链接：{value}")

        xhtml_ns = {"xhtml": "http://www.w3.org/1999/xhtml"}
        nav = parsed_xml["EPUB/nav.xhtml"]
        chapter_links = {
            anchor.attrib["href"]
            for anchor in nav.findall(".//xhtml:a", xhtml_ns)
            if re.fullmatch(r"ch\d{2}\.xhtml", anchor.attrib.get("href", ""))
        }
        if chapter_links != {f"ch{number:02d}.xhtml" for number in range(1, 82)}:
            raise ValueError("导航目录未完整覆盖81章")

        for number in range(1, 82):
            chapter_page = parsed_xml[f"EPUB/ch{number:02d}.xhtml"]
            headings = [
                "".join(heading.itertext())
                for heading in chapter_page.findall(".//xhtml:h2", xhtml_ns)
            ]
            if headings != ["原文", "投资心法", "实操建议"]:
                raise ValueError(f"第{number}章 EPUB 章节结构错误：{headings}")
            if len(chapter_page.findall(".//xhtml:u", xhtml_ns)) != 2:
                raise ValueError(f"第{number}章 EPUB 应包含两处下划线心法")
            if len(chapter_page.findall(".//xhtml:mark", xhtml_ns)) < 2:
                raise ValueError(f"第{number}章 EPUB 缺少原文回扣标记")

        with Image.open(BytesIO(archive.read("EPUB/cover.png"))) as cover:
            if cover.size != (1600, 2400) or cover.format != "PNG":
                raise ValueError("封面必须为1600×2400 PNG")


def main() -> None:
    chapters, source_intro, source_chapters, independence_audit = load_book()
    with tempfile.TemporaryDirectory(prefix="ddj-codex-epub-") as temporary:
        build_dir = Path(temporary)
        assemble_epub(build_dir, chapters, source_intro, source_chapters)
        package_epub(build_dir, OUTPUT)
    validate_epub(OUTPUT)
    codex_number, main_number, similarity = independence_audit
    print(f"已生成：{OUTPUT}")
    print(f"章节：{len(chapters)}；文件大小：{OUTPUT.stat().st_size:,} bytes")
    print(
        f"文本差异审计：最高为Codex第{codex_number}章与主书第{main_number}章"
        f"的{similarity:.1%}"
    )


if __name__ == "__main__":
    main()
