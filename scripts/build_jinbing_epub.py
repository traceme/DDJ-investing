#!/usr/bin/env python3
"""Build the《人生悟道 渡人渡己·投资篇》reading-notes edition as an EPUB 3 book."""

from __future__ import annotations

import html
import json
import posixpath
import re
import tempfile
import unicodedata
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree as ET

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
NOTES_DIR = ROOT / "jinbing-drdj"
SOURCE_PDF = NOTES_DIR / "人生悟道-渡人渡己-投资篇-纪念版.pdf"
OUTPUT = ROOT / "人生悟道渡人渡己投资篇读书心法.epub"
BOOK_TITLE = "人生悟道渡人渡己·投资篇 读书心法"
BOOK_ID = "jinbing-drdj-investing-notes-72"
LANGUAGE = "zh-CN"
BOOK_DATE = "2026-08-25"
SOURCE_BOOK = "《人生悟道 渡人渡己·投资篇（纪念版）》金冰 著"

ARTICLE_COUNT = 72
MIN_ESSAY_CHARS = 500
MAX_ESSAY_CHARS = 1800
MIN_IDEA_CHARS = 120
MAX_IDEA_CHARS = 420
MAX_ADVICE_CHARS = 100
MAX_MARKS = 2
MAX_MARK_CHARS = 30
MAX_SHARED_RUN = 30  # 超出此长度的连续原文雷同（<mark> 之外）视为抄袭

PARTS = (
    ("基础篇", "打破直觉：重塑投资决策的基础", 1, 25,
     "复利、风险、概率、耐心、能力圈——先把决策的地基从直觉换成常识，再谈别的。"),
    ("进阶篇", "融会贯通：培养充满生命力的投资思维", 26, 48,
     "从生意的眼光看股票，从人的处境看仓位：散户真正的优势在哪里，又该在哪里认输。"),
    ("哲思篇", "穿越波澜：投资如人生，人生亦投资", 49, 72,
     "钱、判断力、婚姻、创业、中年——把投资放回一整个人生里，才知道什么值得等。"),
)

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
class Article:
    number: int
    title: str
    core_line: str
    attribution: str
    idea: str
    essay: str
    advice: str

    @property
    def href(self) -> str:
        return f"a{self.number:02d}.xhtml"

    @property
    def part(self) -> str:
        for name, _sub, lo, hi, _summary in PARTS:
            if lo <= self.number <= hi:
                return name
        raise ValueError(f"第{self.number}篇不属于任何分部")


# --------------------------------------------------------------------------
# 原书文本（仅用于校验引文，不进入成书）
# --------------------------------------------------------------------------

def _cjk_normalize(text: str) -> str:
    """把康熙部首/兼容汉字折叠成常规汉字，但保留全角标点。"""
    out = []
    for char in text:
        code = ord(char)
        if 0x2E80 <= code <= 0x2FDF or 0xF900 <= code <= 0xFAFF:
            out.append(unicodedata.normalize("NFKC", char))
        else:
            out.append(char)
    return "".join(out)


def load_source_articles() -> dict[int, str] | None:
    """从原书 PDF 按目录切出 72 篇正文；PDF 不在时返回 None（引文校验跳过）。"""
    if not SOURCE_PDF.exists():
        return None
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return None

    document = fitz.open(SOURCE_PDF)
    pages = [_cjk_normalize(document[index].get_text()) for index in range(document.page_count)]
    toc = document.get_toc()
    if len(toc) != 74:
        raise ValueError(f"原书目录条目数异常：{len(toc)}")

    articles: dict[int, str] = {}
    number = 0
    for index, (_level, _title, page) in enumerate(toc):
        if index < 2:  # 寄语、自序属前言，不计入正文
            continue
        number += 1
        start = page - 1
        end = toc[index + 1][2] - 1 if index + 1 < len(toc) else document.page_count
        body = "\n".join(pages[start:end])
        lines = []
        for line in body.split("\n"):
            stripped = line.strip().replace(" ", " ")
            if re.fullmatch(r"\d{1,3}", stripped):
                continue
            if stripped in ("致谢", "FAQ"):
                break
            lines.append(stripped)
        articles[number] = "".join(lines)
    if len(articles) != ARTICLE_COUNT:
        raise ValueError(f"原书正文篇数异常：{len(articles)}")
    return articles


def squeeze(text: str) -> str:
    return re.sub(r"\s+", "", text)


def audit_against_source(article: Article, source: str) -> None:
    """<mark> 内必须逐字出自原书；<mark> 外不得有长段雷同。"""
    bare_source = squeeze(source)
    marks = re.findall(r"<mark>(.*?)</mark>", f"{article.idea}\n{article.essay}", re.DOTALL)
    if len(marks) > MAX_MARKS:
        raise ValueError(f"第{article.number}篇 <mark> 引文超过{MAX_MARKS}处：{len(marks)}")
    for quote in marks:
        squeezed = squeeze(quote)
        if len(squeezed) > MAX_MARK_CHARS:
            raise ValueError(f"第{article.number}篇引文过长（{len(squeezed)}字）：{quote}")
        if squeezed not in bare_source:
            raise ValueError(f"第{article.number}篇 <mark> 引文无法在原书本篇逐字定位：{quote}")

    own = re.sub(r"<mark>.*?</mark>", "　", f"{article.idea}\n{article.essay}", flags=re.DOTALL)
    own = squeeze(re.sub(r"</?u>", "", own))
    for start in range(0, max(0, len(own) - MAX_SHARED_RUN) + 1):
        window = own[start : start + MAX_SHARED_RUN]
        if "　" in window:
            continue
        if window in bare_source:
            raise ValueError(
                f"第{article.number}篇存在与原书连续{MAX_SHARED_RUN}字以上雷同：{window}"
            )


# --------------------------------------------------------------------------
# 解析读书笔记
# --------------------------------------------------------------------------

def parse_article(number: int) -> Article:
    path = NOTES_DIR / f"第{number:02d}篇.md"
    if not path.exists():
        raise FileNotFoundError(f"缺少 {path}")
    text = path.read_text(encoding="utf-8")
    text = text.split("<!-- jinbing-nav -->", 1)[0].rstrip()

    lines = text.splitlines()
    if not lines or not lines[0].startswith("# "):
        raise ValueError(f"第{number}篇缺少 H1 标题")
    title = lines[0][2:].strip()
    expected_prefix = f"第{chinese_number(number)}篇 · "
    if not title.startswith(expected_prefix):
        raise ValueError(f"第{number}篇标题格式错误：{title}")
    core_line = title[len(expected_prefix):].strip()
    if not 4 <= len(squeeze(core_line)) <= 20:
        raise ValueError(f"第{number}篇核心句长度异常（{len(squeeze(core_line))}字）：{core_line}")

    attribution = ""
    body_start = 1
    for index in range(1, len(lines)):
        stripped = lines[index].strip()
        if not stripped:
            continue
        if stripped.startswith("> 原书出处：") and not attribution:
            attribution = stripped[2:].strip()
            body_start = index + 1
            continue
        break
    if not attribution:
        raise ValueError(f"第{number}篇缺少出处行")
    if SOURCE_BOOK not in attribution:
        raise ValueError(f"第{number}篇出处行未标明原书：{attribution}")

    sections: dict[str, str] = {}
    order: list[str] = []
    current: str | None = None
    buffer: list[str] = []
    for line in lines[body_start:]:
        if line.startswith("## "):
            if current:
                sections[current] = "\n".join(buffer).strip()
            current = line[3:].strip()
            order.append(current)
            buffer = []
            continue
        if current:
            buffer.append(line)
    if current:
        sections[current] = "\n".join(buffer).strip()

    if order != ["中心思想", "投资心法", "实操建议"]:
        raise ValueError(f"第{number}篇小节结构错误：{order}")

    idea = sections["中心思想"].strip()
    essay = sections["投资心法"].strip()
    advice = re.sub(r"\n?-{3,}\s*$", "", sections["实操建议"]).strip()

    idea_len = len(squeeze(idea))
    if not MIN_IDEA_CHARS <= idea_len <= MAX_IDEA_CHARS:
        raise ValueError(f"第{number}篇中心思想{idea_len}字，应在{MIN_IDEA_CHARS}–{MAX_IDEA_CHARS}字之间")
    essay_len = len(squeeze(re.sub(r"</?(mark|u)>", "", essay)))
    if not MIN_ESSAY_CHARS <= essay_len <= MAX_ESSAY_CHARS:
        raise ValueError(f"第{number}篇心法{essay_len}字，应在{MIN_ESSAY_CHARS}–{MAX_ESSAY_CHARS}字之间")
    advice_len = len(squeeze(advice))
    if advice_len > MAX_ADVICE_CHARS:
        raise ValueError(f"第{number}篇实操建议{advice_len}字，超过{MAX_ADVICE_CHARS}字上限")
    if "<mark>" in advice or "<u>" in advice:
        raise ValueError(f"第{number}篇实操建议不应含标记标签")
    if essay.count("<u>") != 2 or essay.count("</u>") != 2:
        raise ValueError(f"第{number}篇应恰好含两处 <u> 心法")
    for tag in ("mark", "u"):
        if essay.count(f"<{tag}>") != essay.count(f"</{tag}>"):
            raise ValueError(f"第{number}篇 <{tag}> 标签未闭合")

    return Article(number, title, core_line, attribution, idea, essay, advice)


def chinese_number(value: int) -> str:
    digits = "零一二三四五六七八九"
    if value < 10:
        return digits[value]
    if value < 20:
        return "十" + (digits[value % 10] if value % 10 else "")
    return digits[value // 10] + "十" + (digits[value % 10] if value % 10 else "")


def load_book() -> tuple[list[Article], dict[int, str] | None]:
    articles = [parse_article(number) for number in range(1, ARTICLE_COUNT + 1)]
    source = load_source_articles()
    if source:
        for article in articles:
            audit_against_source(article, source[article.number])
    return articles, source


# --------------------------------------------------------------------------
# 渲染
# --------------------------------------------------------------------------

def xhtml_document(title: str, body: str, body_class: str = "") -> str:
    class_attr = f' class="{body_class}"' if body_class else ""
    return (
        XHTML_HEADER.format(title=html.escape(title), body_class=class_attr)
        + body
        + "\n</body>\n</html>\n"
    )


def inline_markdown(text: str) -> str:
    allowed = {"<mark>": "", "</mark>": "", "<u>": "", "</u>": ""}
    protected = text.strip()
    for tag, placeholder in allowed.items():
        protected = protected.replace(tag, placeholder)
    escaped = html.escape(protected, quote=True)

    def replace_link(match: re.Match[str]) -> str:
        label, href = match.groups()
        if href.startswith("/jinbing-drdj/") or href.startswith("jinbing-drdj/"):
            name = href.rsplit("/", 1)[-1]
            match_number = re.fullmatch(r"第(\d{2})篇\.md", name)
            href = f"a{match_number.group(1)}.xhtml" if match_number else "nav.xhtml"
        return f'<a href="{html.escape(href, quote=True)}">{label}</a>'

    escaped = re.sub(r"\[([^]]+)]\(([^)]+)\)", replace_link, escaped)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    for tag, placeholder in allowed.items():
        escaped = escaped.replace(placeholder, tag)
    return escaped


def paragraphs(text: str, css_class: str | None = None) -> str:
    class_attr = f' class="{css_class}"' if css_class else ""
    blocks = [block.strip() for block in re.split(r"\n\s*\n", text) if block.strip()]
    return "\n".join(
        f"<p{class_attr}>{'<br />'.join(inline_markdown(line) for line in block.splitlines())}</p>"
        for block in blocks
    )


def markdown_fragment(markdown: str) -> str:
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
        if line.startswith("### "):
            output.append(f"<h3>{inline_markdown(line[4:])}</h3>")
            index += 1
            continue
        if line.startswith("> "):
            quote = []
            while index < len(lines) and lines[index].startswith("> "):
                quote.append(f"<p>{inline_markdown(lines[index][2:])}</p>")
                index += 1
            output.append("<blockquote>" + "".join(quote) + "</blockquote>")
            continue
        if re.match(r"^[-*] ", line):
            items = []
            while index < len(lines) and re.match(r"^[-*] ", lines[index].rstrip()):
                items.append(f"<li>{inline_markdown(lines[index].rstrip()[2:])}</li>")
                index += 1
            output.append("<ul>" + "".join(items) + "</ul>")
            continue
        if re.match(r"^\|", line) or re.fullmatch(r"-{3,}", line):
            index += 1
            continue
        paragraph = []
        while index < len(lines) and lines[index].strip() and not lines[index].startswith(("#", ">", "- ", "* ", "|")):
            paragraph.append(inline_markdown(lines[index].strip()))
            index += 1
        if paragraph:
            output.append(f"<p>{''.join(paragraph)}</p>")
    return "\n".join(output)


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


def centered_text(draw, y, text, font, fill, spacing=0) -> None:
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
    centered_text(draw, 160, "读 · 书 · 心 · 法", get_font(50), gold, spacing=10)

    # 渡：水面、月与涟漪
    cx, cy, radius = 800, 620, 215
    circle = (cx - radius, cy - radius, cx + radius, cy + radius)
    draw.ellipse(circle, outline=green, width=8)
    waterline = cy + 46
    draw.line((cx - radius + 22, waterline, cx + radius - 22, waterline), fill=gold, width=5)
    draw.ellipse((cx - 62, cy - 138, cx + 62, cy - 14), outline=green, width=6)
    draw.ellipse((cx - 20, cy - 96, cx + 20, cy - 56), fill=gold)
    for index, spread in enumerate((80, 134, 188)):
        drop = waterline + 16 * index
        box = (cx - spread, drop - spread // 4, cx + spread, drop + spread // 4)
        draw.arc(box, 22, 158, fill=gold if index == 0 else pale_gold, width=4)

    centered_text(draw, 980, "读书心法", get_font(216), ink, spacing=14)
    centered_text(draw, 1265, "人生悟道 · 渡人渡己 · 投资篇", get_font(74), ink, spacing=3)
    draw.line((520, 1420, 1080, 1420), fill=gold, width=4)

    badge_text = "七十二篇精读"
    badge_font = get_font(62)
    badge_box = draw.textbbox((0, 0), badge_text, font=badge_font)
    badge_width = badge_box[2] - badge_box[0] + 110
    badge_left = (1600 - badge_width) / 2
    draw.rounded_rectangle((badge_left, 1500, badge_left + badge_width, 1610), radius=14, fill=green)
    centered_text(draw, 1516, badge_text, badge_font, background, spacing=4)

    centered_text(draw, 1760, "中心思想 · 投资心法 · 实操建议", get_font(60), green, spacing=3)
    centered_text(draw, 1885, "把别人的悟，读成自己的纪律", get_font(46), ink, spacing=2)
    centered_text(draw, 2170, "金冰 原著  ·  traceme 提炼", get_font(40), gold, spacing=2)
    image.save(path, format="PNG", optimize=True)


def cover_xhtml() -> str:
    body = """<section epub:type="cover" class="cover-page">
  <img src="cover.png" alt="人生悟道渡人渡己投资篇读书心法封面" />
</section>"""
    return xhtml_document(BOOK_TITLE, body, "cover-body")


def title_xhtml() -> str:
    body = """<section epub:type="titlepage" class="title-page">
  <p class="eyebrow">人生悟道 · 渡人渡己 · 投资篇</p>
  <h1>读书心法<br /><span>七十二篇</span></h1>
  <p class="subtitle">中心思想 · 投资心法 · 实操建议</p>
  <p class="author">金冰 原著 · traceme 提炼</p>
</section>"""
    return xhtml_document(BOOK_TITLE, body, "title-body")


def intro_xhtml() -> str:
    readme = (NOTES_DIR / "README.md").read_text(encoding="utf-8")
    introduction = readme.split("## 全书目录", 1)[0].strip()
    introduction = "\n".join(
        line for line in introduction.splitlines() if not line.startswith("📘 电子书：")
    )
    body = '<section epub:type="preface">\n<h1>阅读说明</h1>\n' + markdown_fragment(introduction) + "\n</section>"
    return xhtml_document("阅读说明", body)


def source_xhtml() -> str:
    body = f"""<section epub:type="afterword">
  <h1>关于原书</h1>
  <p>本书是读书笔记，不是原著。所有中心思想、心法随笔与实操建议均为重新撰写；除少量注明出处的短引文外，不含原书文字。</p>
  <h2>原书</h2>
  <p>{html.escape(SOURCE_BOOK)}。全书正文七十二篇，分「基础篇 · 打破直觉」「进阶篇 · 融会贯通」「哲思篇 · 穿越波澜」三部，选自「人生悟道 渡人渡己」系列中约九百集投资主题节目。</p>
  <h2>原书出处与获取</h2>
  <p>「人生悟道 渡人渡己」是金冰先生发起的免费公开分享项目，音频、视频与文字稿见其官方网站 drdj.net，另在喜马拉雅与 YouTube 同名分享。原书电子版由该项目免费开放，欢迎读者直接阅读原著。</p>
  <h2>致谢</h2>
  <p>感谢金冰先生与「人生悟道 渡人渡己」的志愿者们，把两千余集口述整理成可读的文字。没有他们的工作，这本笔记无从谈起。</p>
  <h2>免责声明</h2>
  <p>本书为读书笔记与个人心得，讨论的是投资中的思维方式与行为纪律，<strong>不构成任何投资建议</strong>。文中提到的行业、公司、历史行情与资产类别，一律只作行为的例证，不是推荐。投资有风险，决策请独立判断并自负盈亏。</p>
</section>"""
    return xhtml_document("关于原书", body)


def part_xhtml(title: str, subtitle: str, summary: str) -> str:
    body = f"""<section epub:type="part" class="part-page">
  <p class="eyebrow">{html.escape(subtitle)}</p>
  <h1>{html.escape(title)}</h1>
  <p class="part-summary">{html.escape(summary)}</p>
</section>"""
    return xhtml_document(title, body, "part-body")


def article_xhtml(article: Article) -> str:
    previous_href = "intro.xhtml" if article.number == 1 else f"a{article.number - 1:02d}.xhtml"
    next_href = "source.xhtml" if article.number == ARTICLE_COUNT else f"a{article.number + 1:02d}.xhtml"
    body = f"""<article epub:type="chapter">
  <h1>{html.escape(article.title)}</h1>
  <p class="attribution">{inline_markdown(article.attribution)}</p>
  <section class="idea">
    <h2>中心思想</h2>
    {paragraphs(article.idea)}
  </section>
  <section>
    <h2>投资心法</h2>
    {paragraphs(article.essay)}
  </section>
  <section class="advice">
    <h2>实操建议</h2>
    {paragraphs(article.advice)}
  </section>
  <nav class="chapter-nav" aria-label="篇目导航">
    <a href="{previous_href}">← 上一篇</a>
    <a href="nav.xhtml">目录</a>
    <a href="{next_href}">下一篇 →</a>
  </nav>
</article>"""
    return xhtml_document(article.title, body)


def nav_xhtml(articles: list[Article]) -> str:
    blocks = []
    for index, (name, subtitle, lo, hi, _summary) in enumerate(PARTS, start=1):
        items = "\n".join(
            f'        <li><a href="{article.href}">{html.escape(article.title)}</a></li>'
            for article in articles[lo - 1 : hi]
        )
        blocks.append(
            f'    <li><a href="part{index}.xhtml">{html.escape(name)} · {html.escape(subtitle)}</a>\n'
            f"      <ol>\n{items}\n      </ol>\n    </li>"
        )
    body = f"""<nav epub:type="toc" id="toc" aria-labelledby="toc-title">
  <h1 id="toc-title">目录</h1>
  <ol>
    <li><a href="title.xhtml">扉页</a></li>
    <li><a href="intro.xhtml">阅读说明</a></li>
{chr(10).join(blocks)}
    <li><a href="source.xhtml">关于原书</a></li>
  </ol>
</nav>
<nav epub:type="landmarks" class="landmarks" aria-label="导览">
  <h2>导览</h2>
  <ol>
    <li><a epub:type="cover" href="cover.xhtml">封面</a></li>
    <li><a epub:type="toc" href="nav.xhtml">目录</a></li>
    <li><a epub:type="bodymatter" href="a01.xhtml">正文</a></li>
  </ol>
</nav>"""
    return xhtml_document("目录", body, "toc-body")


def toc_ncx(articles: list[Article]) -> str:
    order = 0

    def next_order() -> int:
        nonlocal order
        order += 1
        return order

    def leaf(identifier: str, label: str, href: str, indent: str = "    ") -> str:
        return (
            f'{indent}<navPoint id="{identifier}" playOrder="{next_order()}">\n'
            f"{indent}  <navLabel><text>{html.escape(label)}</text></navLabel>\n"
            f'{indent}  <content src="{href}" />\n'
            f"{indent}</navPoint>\n"
        )

    points = leaf("title", "扉页", "title.xhtml")
    points += leaf("intro", "阅读说明", "intro.xhtml")
    for index, (name, subtitle, lo, hi, _summary) in enumerate(PARTS, start=1):
        head = (
            f'    <navPoint id="part{index}" playOrder="{next_order()}">\n'
            f"      <navLabel><text>{html.escape(name + ' · ' + subtitle)}</text></navLabel>\n"
            f'      <content src="part{index}.xhtml" />\n'
        )
        children = "".join(
            leaf(f"a{article.number:02d}", article.title, article.href, indent="      ")
            for article in articles[lo - 1 : hi]
        )
        points += head + children + "    </navPoint>\n"
    points += leaf("source", "关于原书", "source.xhtml")
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


def content_opf(articles: list[Article], modified: str) -> str:
    manifest = "\n".join(
        f'    <item id="a{article.number:02d}" href="{article.href}" media-type="application/xhtml+xml" />'
        for article in articles
    )
    spine_blocks = []
    for index, (_name, _subtitle, lo, hi, _summary) in enumerate(PARTS, start=1):
        spine_blocks.append(f'    <itemref idref="part{index}" />')
        spine_blocks.extend(
            f'    <itemref idref="a{article.number:02d}" />' for article in articles[lo - 1 : hi]
        )
    parts_manifest = "\n".join(
        f'    <item id="part{index}" href="part{index}.xhtml" media-type="application/xhtml+xml" />'
        for index in range(1, len(PARTS) + 1)
    )
    return f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="book-id" xml:lang="zh-CN" prefix="dcterms: http://purl.org/dc/terms/">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="book-id">{BOOK_ID}</dc:identifier>
    <dc:title>{BOOK_TITLE}</dc:title>
    <dc:language>{LANGUAGE}</dc:language>
    <dc:creator id="creator">traceme</dc:creator>
    <dc:contributor>金冰（原著）</dc:contributor>
    <dc:source>{SOURCE_BOOK}</dc:source>
    <dc:publisher>DDJ-investing</dc:publisher>
    <dc:date>{BOOK_DATE}</dc:date>
    <dc:description>金冰《人生悟道 渡人渡己·投资篇（纪念版）》七十二篇的读书心法：每篇先提炼原文中心思想，再写成一篇独立的投资心法随笔，并给出百字以内的实操纪律。读书笔记，不构成投资建议。</dc:description>
    <dc:subject>投资</dc:subject>
    <dc:subject>价值投资</dc:subject>
    <dc:subject>读书笔记</dc:subject>
    <meta property="dcterms:modified">{modified}</meta>
    <meta name="cover" content="cover-image" />
  </metadata>
  <manifest>
    <item id="cover-image" href="cover.png" media-type="image/png" properties="cover-image" />
    <item id="cover" href="cover.xhtml" media-type="application/xhtml+xml" />
    <item id="title" href="title.xhtml" media-type="application/xhtml+xml" />
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav" />
    <item id="intro" href="intro.xhtml" media-type="application/xhtml+xml" />
{parts_manifest}
{manifest}
    <item id="source" href="source.xhtml" media-type="application/xhtml+xml" />
    <item id="css" href="style/book.css" media-type="text/css" />
    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml" />
  </manifest>
  <spine toc="ncx" page-progression-direction="ltr">
    <itemref idref="cover" linear="no" />
    <itemref idref="title" />
    <itemref idref="nav" />
    <itemref idref="intro" />
{chr(10).join(spine_blocks)}
    <itemref idref="source" />
  </spine>
  <guide>
    <reference type="cover" title="封面" href="cover.xhtml" />
    <reference type="toc" title="目录" href="nav.xhtml" />
    <reference type="text" title="正文" href="a01.xhtml" />
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
  margin: 1.2em 0 0.9em;
  color: #2f624d;
  font-size: 1.6em;
  font-weight: 600;
  line-height: 1.5;
  text-align: center;
}
h2 {
  margin: 1.7em 0 0.7em;
  color: #3d6b56;
  font-size: 1.16em;
  font-weight: 600;
}
h3 { margin: 1.3em 0 0.5em; color: #6b5a33; font-size: 1.02em; }
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
.attribution {
  margin: -0.4em 0 1.6em;
  color: #8c7950;
  font-size: 0.84em;
  text-indent: 0;
  text-align: center;
}
.idea {
  padding: 0.1em 1em 0.8em;
  border-left: 0.25em solid #b79a58;
  background: #faf6eb;
}
.idea h2 { margin-top: 0.75em; color: #8a651d; }
.idea p { text-indent: 0; }
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
.title-page h1 span { color: #3d6b56; font-size: 0.62em; }
.eyebrow { color: #b18f43; text-indent: 0; text-align: center; letter-spacing: 0.18em; }
.subtitle, .author, .part-summary { text-indent: 0; text-align: center; }
.subtitle { color: #3d6b56; font-size: 1.05em; }
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


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def assemble_epub(build_dir: Path, articles: list[Article]) -> None:
    epub_dir = build_dir / "EPUB"
    write_text(build_dir / "mimetype", "application/epub+zip")
    write_text(build_dir / "META-INF" / "container.xml", CONTAINER_XML)
    write_text(epub_dir / "style" / "book.css", BOOK_CSS)
    build_cover(epub_dir / "cover.png")
    write_text(epub_dir / "cover.xhtml", cover_xhtml())
    write_text(epub_dir / "title.xhtml", title_xhtml())
    write_text(epub_dir / "intro.xhtml", intro_xhtml())
    for index, (name, subtitle, _lo, _hi, summary) in enumerate(PARTS, start=1):
        write_text(epub_dir / f"part{index}.xhtml", part_xhtml(name, subtitle, summary))
    for article in articles:
        write_text(epub_dir / article.href, article_xhtml(article))
    write_text(epub_dir / "source.xhtml", source_xhtml())
    write_text(epub_dir / "nav.xhtml", nav_xhtml(articles))
    write_text(epub_dir / "toc.ncx", toc_ncx(articles))
    modified = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    write_text(epub_dir / "content.opf", content_opf(articles, modified))


def package_epub(build_dir: Path, output: Path) -> None:
    temporary_output = output.with_suffix(output.suffix + ".tmp")
    with zipfile.ZipFile(temporary_output, "w") as archive:
        archive.write(build_dir / "mimetype", "mimetype", compress_type=zipfile.ZIP_STORED)
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


def validate_epub(output: Path, articles: list[Article]) -> None:
    xhtml_ns = {"xhtml": "http://www.w3.org/1999/xhtml"}
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
            "EPUB/source.xhtml",
            *(f"EPUB/part{index}.xhtml" for index in range(1, len(PARTS) + 1)),
            *(f"EPUB/a{number:02d}.xhtml" for number in range(1, ARTICLE_COUNT + 1)),
        }
        missing = required - set(names)
        if missing:
            raise ValueError(f"EPUB 缺少文件：{sorted(missing)}")

        parsed: dict[str, ET.Element] = {}
        for name in names:
            if name.endswith((".xml", ".xhtml", ".opf", ".ncx")):
                parsed[name] = ET.fromstring(archive.read(name))

        opf_ns = {"opf": "http://www.idpf.org/2007/opf", "dc": "http://purl.org/dc/elements/1.1/"}
        opf = parsed["EPUB/content.opf"]
        if opf.findtext("opf:metadata/dc:title", namespaces=opf_ns) != BOOK_TITLE:
            raise ValueError("EPUB 书名错误")
        if SOURCE_BOOK not in (opf.findtext("opf:metadata/dc:source", namespaces=opf_ns) or ""):
            raise ValueError("EPUB 元数据缺少原书出处")
        items = opf.findall("opf:manifest/opf:item", opf_ns)
        manifest = {item.attrib["id"]: item.attrib["href"] for item in items}
        if len(manifest) != len(items):
            raise ValueError("manifest 中存在重复 id")
        for href in manifest.values():
            target = posixpath.normpath(posixpath.join("EPUB", unquote(href)))
            if target not in names:
                raise ValueError(f"manifest 指向不存在的文件：{href}")
        spine = [ref.attrib.get("idref") for ref in opf.findall("opf:spine/opf:itemref", opf_ns)]
        if len(spine) != len(set(spine)):
            raise ValueError("spine 中存在重复条目")
        for idref in spine:
            if idref not in manifest:
                raise ValueError(f"spine idref 无对应 manifest 项：{idref}")

        for name, root in parsed.items():
            if not name.startswith("EPUB/"):
                continue
            for element in root.iter():
                for attribute in ("href", "src"):
                    value = element.attrib.get(attribute)
                    if not value:
                        continue
                    parsed_url = urlsplit(value)
                    if parsed_url.scheme or not parsed_url.path:
                        continue
                    target = posixpath.normpath(
                        posixpath.join(posixpath.dirname(name), unquote(parsed_url.path))
                    )
                    if target not in names:
                        raise ValueError(f"{name} 含无效内部链接：{value}")

        nav = parsed["EPUB/nav.xhtml"]
        nav_links = {
            anchor.attrib["href"]
            for anchor in nav.findall(".//xhtml:a", xhtml_ns)
            if re.fullmatch(r"a\d{2}\.xhtml", anchor.attrib.get("href", ""))
        }
        if nav_links != {f"a{number:02d}.xhtml" for number in range(1, ARTICLE_COUNT + 1)}:
            raise ValueError("导航目录未完整覆盖72篇")
        part_links = {
            anchor.attrib["href"]
            for anchor in nav.findall(".//xhtml:a", xhtml_ns)
            if re.fullmatch(r"part\d\.xhtml", anchor.attrib.get("href", ""))
        }
        if part_links != {f"part{index}.xhtml" for index in range(1, len(PARTS) + 1)}:
            raise ValueError("导航目录未覆盖三个分部")

        ncx_ns = {"ncx": "http://www.daisy.org/z3986/2005/ncx/"}
        ncx = parsed["EPUB/toc.ncx"]
        orders = [int(point.attrib["playOrder"]) for point in ncx.findall(".//ncx:navPoint", ncx_ns)]
        if orders != sorted(orders) or len(orders) != len(set(orders)):
            raise ValueError("toc.ncx 的 playOrder 必须按文档顺序且不重复")
        targets = [
            point.find("ncx:content", ncx_ns).attrib["src"]
            for point in ncx.findall(".//ncx:navPoint", ncx_ns)
        ]
        if len(targets) != len(set(targets)):
            raise ValueError("toc.ncx 存在重复目标")

        for article in articles:
            page = parsed[f"EPUB/a{article.number:02d}.xhtml"]
            headings = ["".join(node.itertext()) for node in page.findall(".//xhtml:h2", xhtml_ns)]
            if headings != ["中心思想", "投资心法", "实操建议"]:
                raise ValueError(f"第{article.number}篇 EPUB 结构错误：{headings}")
            if len(page.findall(".//xhtml:u", xhtml_ns)) != 2:
                raise ValueError(f"第{article.number}篇 EPUB 应含两处心法下划线")
            if len(page.findall(".//xhtml:mark", xhtml_ns)) > MAX_MARKS:
                raise ValueError(f"第{article.number}篇 EPUB 引文超过{MAX_MARKS}处")
            attribution = page.find(".//xhtml:p[@class='attribution']", xhtml_ns)
            if attribution is None or "金冰" not in "".join(attribution.itertext()):
                raise ValueError(f"第{article.number}篇 EPUB 缺少原书出处标注")
            advice_section = page.find(".//xhtml:section[@class='advice']", xhtml_ns)
            advice_text = squeeze("".join(advice_section.itertext()).replace("实操建议", "", 1))
            if len(advice_text) > MAX_ADVICE_CHARS:
                raise ValueError(f"第{article.number}篇 EPUB 实操建议超过{MAX_ADVICE_CHARS}字")

        with Image.open(BytesIO(archive.read("EPUB/cover.png"))) as cover:
            if cover.size != (1600, 2400) or cover.format != "PNG":
                raise ValueError("封面必须为1600×2400 PNG")


def main() -> None:
    articles, source = load_book()
    with tempfile.TemporaryDirectory(prefix="jinbing-epub-") as temporary:
        build_dir = Path(temporary)
        assemble_epub(build_dir, articles)
        package_epub(build_dir, OUTPUT)
    validate_epub(OUTPUT, articles)

    essay_lengths = [len(squeeze(re.sub(r"</?(mark|u)>", "", a.essay))) for a in articles]
    advice_lengths = [len(squeeze(a.advice)) for a in articles]
    marks = sum(len(re.findall(r"<mark>", f"{a.idea}{a.essay}")) for a in articles)
    print(f"已生成：{OUTPUT}")
    print(f"篇目：{len(articles)}；分部：{len(PARTS)}；引文：{marks} 处；文件大小：{OUTPUT.stat().st_size:,} bytes")
    print(f"心法字数：{min(essay_lengths)}–{max(essay_lengths)}（均值 {sum(essay_lengths)//len(essay_lengths)}）")
    print(f"实操建议字数：{min(advice_lengths)}–{max(advice_lengths)}（上限 {MAX_ADVICE_CHARS}）")
    if source:
        print(f"原书校验：{ARTICLE_COUNT} 篇引文逐字核对通过，正文无连续{MAX_SHARED_RUN}字以上雷同")
    else:
        print("原书 PDF 不在本地，已跳过引文逐字核对（仅结构与字数校验）")


if __name__ == "__main__":
    main()
