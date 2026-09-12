#!/usr/bin/env python3
"""Build the single-file books as self-contained EPUB 3 files.

与 build_codex/selection/jinbing 三个构建器不同，这些书的正文是通用 Markdown
（含表格、ASCII 表单代码块、勾选清单、多级标题），因此这里带一个小而完整的
Markdown → XHTML 转换器，而不是针对固定条目结构的解析器。

用法：
    python3 scripts/build_system_epub.py            # 所有已登记版本
    python3 scripts/build_system_epub.py rules32    # 只构建《投资三十二条军规》

EPUB 样式约束：表格与 <pre> 不得使用 overflow——带 overflow 的盒子在分页阅读器里是
不可分割的整体，超过一屏的内容会整段渲染成空白页。
"""

from __future__ import annotations

import html
import re
import sys
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
LANGUAGE = "zh-CN"
BOOK_DATE = "2026-08-26"


@dataclass(frozen=True)
class Edition:
    key: str
    source: Path
    output: Path
    title: str
    subtitle: str
    book_id: str
    eyebrow: str
    cover_motif: str          # "tablet" | "twelve" | "eight"
    cover_caption: str
    split_h3: tuple = ()      # ((H2 前缀, 页面短前缀), …)：该 H2 之下的 H3 各自成页
    intro_title: str = ""     # 非空＝首个 H2 之前的引言（H1 除外）自成一页，以此为页题
    publication_date: str = BOOK_DATE


EDITIONS = {
    "playbook": Edition(
        key="playbook",
        source=ROOT / "道德经投资打法手册.md",
        output=ROOT / "道德经投资打法手册.epub",
        title="道德经投资打法手册",
        subtitle="八个决策点 · 四类生意 · 一套参数",
        book_id="ddj-investing-playbook",
        eyebrow="从 心 法 到 打 法",
        cover_motif="eight",
        cover_caption="把《道德经》投资心法换算成可执行的决策规则",
    ),
    "catalog": Edition(
        key="catalog",
        source=ROOT / "投资纪律总表.md",
        output=ROOT / "投资纪律总表.epub",
        title="投资纪律总表",
        subtitle="三百六十条 · 逐字核对来源",
        book_id="ddj-investing-discipline-catalog",
        eyebrow="十 八 类 · 四 种 形 态",
        cover_motif="tablet",
        cover_caption="五部心法语料中的每一条行为纪律",
        split_h3=(("第二部分", "纪律一览"), ("第四部分", "数字口径"), ("附录 A", "来源与引文")),
    ),
    "system": Edition(
        key="system",
        source=ROOT / "道德经投资系统.md",
        output=ROOT / "道德经投资系统.epub",
        title="道德经投资系统",
        subtitle="宪法 · 状态机 · 权限引擎",
        book_id="ddj-investing-system",
        eyebrow="三 百 六 十 条 纪 律 · 一 台 机 器",
        cover_motif="twelve",
        cover_caption="一台让你在最坏的日子也只能做对的事的机器",
    ),
    "quant": Edition(
        key="quant",
        source=ROOT / "股票量化投资系统.md",
        output=ROOT / "股票量化投资系统.epub",
        title="股票量化投资系统",
        subtitle="道德经 · 价值主线 · 程序守纪律",
        book_id="ddj-investing-quant-system",
        eyebrow="设 计 规 格 · 从 心 法 到 代 码",
        cover_motif="three",
        cover_caption="向外增加对企业的认识，向内减少无根据的行动",
        intro_title="卷首",
    ),
    "mind": Edition(
        key="mind",
        source=ROOT / "成功投资者心性养成指南.md",
        output=ROOT / "成功投资者心性养成指南.epub",
        title="成功投资者心性养成指南",
        subtitle="戒掉一把梭 · 练成守得住",
        book_id="ddj-investing-mindset",
        eyebrow="自 胜 者 强 · 一 年 训 练 手 册",
        cover_motif="ripple",
        cover_caption="把《道德经》的心性换算成可计数的日常练习",
    ),
    "rules32": Edition(
        key="rules32",
        source=ROOT / "投资三十二条军规.md",
        output=ROOT / "投资三十二条军规.epub",
        title="投资三十二条军规",
        subtitle="守住本金 · 管好下注 · 长久执行",
        book_id="ddj-investing-rules32",
        eyebrow="三 百 六 十 条 纪 律 · 凝 为 三 十 二 条",
        cover_motif="thirtytwo",
        cover_caption="每条有判断标准，每条有操作指南",
        publication_date="2026-09-12",
    ),
}

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

CONTAINER_XML = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="EPUB/content.opf" media-type="application/oebps-package+xml" />
  </rootfiles>
</container>
"""


# --------------------------------------------------------------------------- #
# 解析：按 H2 切成书页
# --------------------------------------------------------------------------- #

@dataclass
class Section:
    index: int
    title: str
    lines: list[str] = field(default_factory=list)
    subheads: list[tuple[str, str]] = field(default_factory=list)  # (anchor, text)

    @property
    def href(self) -> str:
        return f"s{self.index:02d}.xhtml"

    @property
    def is_part(self) -> bool:
        """扉页：标题像分部标题，且正文只有一小段导语——没有表格、没有小节、不长。"""
        if not re.match(r"^第[一二三]部分[^·]*$|^第[一二三]部分 · [^·]+$|^附录$", self.title.strip()):
            return False
        body = "\n".join(self.lines)
        if re.search(r"^\s*\|", body, flags=re.M) or re.search(r"^###", body, flags=re.M):
            return False
        return len(re.sub(r"\s", "", body)) < 400


def parse_document(source: Path, split_h3: tuple = (), intro_title: str = "") -> list[Section]:
    text = source.read_text(encoding="utf-8")
    sections: list[Section] = []
    current: Section | None = None
    index = 0
    if intro_title:
        head = text.split("\n## ", 1)[0].split("\n")
        intro = [l for l in head if not l.startswith("# ")]
        if any(l.strip() for l in intro):
            index += 1
            sections.append(Section(index=index, title=intro_title, lines=intro))
    in_split = ""               # 非空＝当前 H2 之下的 H3 各自成页，值为页面短前缀
    for line in text.split("\n"):
        m3 = re.match(r"^### (.+?)\s*$", line)
        if m3 and in_split:
            index += 1
            current = Section(index=index, title=f"{in_split} · {m3.group(1).strip()}")
            sections.append(current)
            continue
        m = re.match(r"^## (.+?)\s*$", line)
        if m:
            title = m.group(1).strip()
            if title == "目录":          # EPUB 自带导航，跳过正文目录
                current = None
                in_split = ""
                continue
            in_split = next((lbl for pfx, lbl in split_h3 if title.startswith(pfx)), "")
            index += 1
            current = Section(index=index, title=title)
            sections.append(current)
            continue
        if current is not None:
            current.lines.append(line)
    if not sections:
        raise ValueError(f"{source.name}：未解析到任何 H2 章节")
    return sections


# --------------------------------------------------------------------------- #
# Markdown → XHTML
# --------------------------------------------------------------------------- #

ANNOT_FULL = re.compile(r"^[　 ]*▍《道德经》第([一二三四五六七八九十]+)章[：:]\s*(.+?)\s*$")
ANNOT_COMPACT = re.compile(r"[ 　]*▍([一二三四五六七八九十]+)章「([^」]+)」")


def esc(s: str) -> str:
    return html.escape(s, quote=False)


def inline(text: str) -> str:
    """行内标记：代码 → 加粗 → 链接 → 原文紧凑式标注。顺序保证不互相破坏。"""
    placeholders: list[str] = []

    def stash(payload: str) -> str:
        placeholders.append(payload)
        return f"{len(placeholders) - 1}"

    # 行内代码优先，内部不再解析其他标记
    text = re.sub(r"`([^`]+)`", lambda m: stash(f"<code>{esc(m.group(1))}</code>"), text)
    # 紧凑式原文标注
    text = ANNOT_COMPACT.sub(
        lambda m: stash(
            '<span class="ddj-inline">▍'
            f'<span class="ddj-ch">{esc(m.group(1))}章</span>'
            f'<span class="ddj-q">「{esc(m.group(2))}」</span></span>'
        ),
        text,
    )
    # 链接：站内路径（仓库文件、docsify 路由）在离线成书里无处可去，只留链接文字
    text = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        lambda m: stash(f'<a href="{esc(m.group(2))}">{esc(m.group(1))}</a>'
                        if re.match(r"^(https?:|mailto:|#)", m.group(2)) else esc(m.group(1))),
        text,
    )
    text = esc(text)
    # 加粗在前、斜体在后；加粗用非贪婪，才容得下内嵌的 *斜体*
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text, flags=re.S)
    text = re.sub(r"(?<![*\w])\*([^*\n]+)\*(?![*\w])", r"<em>\1</em>", text)
    for i, payload in enumerate(placeholders):
        text = text.replace(f"{i}", payload)
    return text


def render_table(rows: list[str]) -> str:
    def cells(row: str) -> list[str]:
        return [c.strip() for c in row.strip().strip("|").split("|")]

    if len(rows) < 2:
        return ""
    head = cells(rows[0])
    body = [cells(r) for r in rows[2:]]
    out = ['<div class="tablewrap"><table>', "<thead><tr>"]
    out += [f"<th>{inline(c)}</th>" for c in head]
    out.append("</tr></thead><tbody>")
    for row in body:
        row = (row + [""] * len(head))[: len(head)]
        out.append("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in row) + "</tr>")
    out.append("</tbody></table></div>")
    return "".join(out)


def render_blocks(lines: list[str]) -> str:
    out: list[str] = []
    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            i += 1
            continue

        # 代码块（ASCII 表单）—— 原样保留
        if stripped.startswith("```"):
            i += 1
            buf: list[str] = []
            while i < n and not lines[i].strip().startswith("```"):
                buf.append(lines[i])
                i += 1
            i += 1
            out.append("<pre>" + esc("\n".join(buf)) + "</pre>")
            continue

        # 分隔线
        if re.fullmatch(r"-{3,}", stripped):
            out.append('<hr class="rule" />')
            i += 1
            continue

        # 标题
        m = re.match(r"^(#{3,4}) (.+?)\s*$", stripped)
        if m:
            level = len(m.group(1))
            tag = "h2" if level == 3 else "h3"
            anchor = f"h{i}"
            out.append(f'<{tag} id="{anchor}">{inline(m.group(2))}</{tag}>')
            i += 1
            continue

        # 完整式原文标注
        m = ANNOT_FULL.match(line)
        if m:
            out.append(
                '<p class="ddj-full">▍<span class="ddj-src">《道德经》第'
                f'{esc(m.group(1))}章</span>：<span class="ddj-text">{esc(m.group(2))}</span></p>'
            )
            i += 1
            continue

        # 表格
        if stripped.startswith("|"):
            rows = []
            while i < n and lines[i].strip().startswith("|"):
                rows.append(lines[i])
                i += 1
            out.append(render_table(rows))
            continue

        # 引用块
        if stripped.startswith("> "):
            buf = []
            while i < n and lines[i].strip().startswith(">"):
                buf.append(re.sub(r"^\s*>\s?", "", lines[i]))
                i += 1
            inner = "".join(f"<p>{inline(b)}</p>" for b in buf if b.strip())
            out.append(f"<blockquote>{inner}</blockquote>")
            continue

        # 勾选清单
        if re.match(r"^[-*] \[ \] ", stripped):
            buf = []
            while i < n and re.match(r"^[-*] \[ \] ", lines[i].strip()):
                buf.append(re.sub(r"^[-*] \[ \] ", "", lines[i].strip()))
                i += 1
            items = "".join(f"<li>{inline(b)}</li>" for b in buf)
            out.append(f'<ul class="checklist">{items}</ul>')
            continue

        # 有序列表（保留原编号）
        m = re.match(r"^(\d+)\. (.+)$", stripped)
        if m:
            start = m.group(1)
            buf = []
            while i < n:
                mm = re.match(r"^(\d+)\. (.+)$", lines[i].strip())
                if not mm:
                    # 续行（缩进的补充说明或完整式标注）并入当前条目
                    if buf and lines[i].strip() and lines[i][:1] in (" ", "　"):
                        ann = ANNOT_FULL.match(lines[i])
                        if ann:
                            buf[-1] += (
                                '<span class="ddj-full inlineblock">▍<span class="ddj-src">《道德经》第'
                                f'{esc(ann.group(1))}章</span>：<span class="ddj-text">{esc(ann.group(2))}</span></span>'
                            )
                        else:
                            buf[-1] += "<br />" + inline(lines[i].strip())
                        i += 1
                        continue
                    break
                buf.append(inline(mm.group(2)))
                i += 1
            items = "".join(f"<li>{b}</li>" for b in buf)
            out.append(f'<ol start="{start}">{items}</ol>')
            continue

        # 无序列表
        if re.match(r"^[-*] ", stripped):
            buf = []
            while i < n and re.match(r"^[-*] ", lines[i].strip()):
                buf.append(inline(re.sub(r"^[-*] ", "", lines[i].strip())))
                i += 1
            items = "".join(f"<li>{b}</li>" for b in buf)
            out.append(f"<ul>{items}</ul>")
            continue

        # 普通段落
        buf = [stripped]
        i += 1
        while i < n and lines[i].strip() and not re.match(
            r"^(#{2,4} |\||```|-{3,}$|> |[-*] |\d+\. |[　 ]*▍)", lines[i].strip()
        ) and not ANNOT_FULL.match(lines[i]):
            buf.append(lines[i].strip())
            i += 1
        out.append(f"<p>{inline(''.join(buf))}</p>")
    return "\n".join(out)


def collect_subheads(lines: list[str]) -> list[tuple[str, str]]:
    heads = []
    for i, line in enumerate(lines):
        m = re.match(r"^### (.+?)\s*$", line.strip())
        if m:
            heads.append((f"h{i}", m.group(1).strip()))
    return heads


# --------------------------------------------------------------------------- #
# 页面
# --------------------------------------------------------------------------- #

def xhtml_document(title: str, body: str, body_class: str = "") -> str:
    cls = f' class="{body_class}"' if body_class else ""
    return XHTML_HEADER.format(title=esc(title), body_class=cls) + body + "\n</body>\n</html>\n"


def cover_xhtml() -> str:
    body = '<div class="cover-page"><img src="cover.png" alt="封面" /></div>'
    return xhtml_document("封面", body, "cover-body")


def title_xhtml(ed: Edition) -> str:
    body = (
        '<div class="title-page">'
        f'<p class="eyebrow">{esc(ed.eyebrow)}</p>'
        f"<h1>{esc(ed.title)}<span><br />{esc(ed.subtitle)}</span></h1>"
        f'<p class="subtitle">{esc(ed.cover_caption)}</p>'
        '<p class="author">从五部心法穷举、合并、结构化而成<br />'
        "每条原则与数字均标出处，可回原书复核</p>"
        "</div>"
    )
    return xhtml_document(f"{ed.title}·{ed.subtitle}", body, "title-body")


def section_xhtml(sec: Section, prev_href: str, next_href: str) -> str:
    if sec.is_part:
        body = (
            f'<div class="part-page"><h1>{inline(sec.title)}</h1>'
            + render_blocks(sec.lines).replace("<p>", '<p class="part-summary">')
            + "</div>"
        )
        return xhtml_document(sec.title, body, "part-body")
    nav = (
        '<nav class="entry-nav" epub:type="page-list">'
        f'<a href="{prev_href}">← 上一章</a>'
        '<a href="nav.xhtml">目录</a>'
        f'<a href="{next_href}">下一章 →</a></nav>'
    )
    body = f"<h1>{inline(sec.title)}</h1>\n" + render_blocks(sec.lines) + "\n" + nav
    return xhtml_document(sec.title, body)


def nav_xhtml(ed: Edition, sections: list[Section]) -> str:
    items = []
    for sec in sections:
        sub = ""
        if sec.subheads and not sec.is_part:
            sub = (
                "<ol>"
                + "".join(
                    f'<li><a href="{sec.href}#{a}">{esc(t)}</a></li>' for a, t in sec.subheads
                )
                + "</ol>"
            )
        items.append(f'<li><a href="{sec.href}">{esc(sec.title)}</a>{sub}</li>')
    body = (
        f"<h1>{esc(ed.title)}·{esc(ed.subtitle)}</h1>"
        '<nav epub:type="toc" id="toc"><h2>目录</h2><ol>' + "".join(items) + "</ol></nav>"
        '<nav epub:type="landmarks" class="landmarks" hidden="hidden"><h2>地标</h2><ol>'
        '<li><a epub:type="cover" href="cover.xhtml">封面</a></li>'
        '<li><a epub:type="titlepage" href="title.xhtml">书名页</a></li>'
        f'<li><a epub:type="bodymatter" href="{sections[0].href}">正文</a></li>'
        "</ol></nav>"
    )
    return xhtml_document("目录", body, "toc-body")


def toc_ncx(ed: Edition, sections: list[Section]) -> str:
    order = [0]

    def nxt() -> int:
        order[0] += 1
        return order[0]

    def leaf(nav_id: str, label: str, src: str) -> str:
        return (
            f'<navPoint id="{nav_id}" playOrder="{nxt()}">'
            f"<navLabel><text>{esc(label)}</text></navLabel>"
            f'<content src="{src}" /></navPoint>'
        )

    points = [leaf("nav-cover", "封面", "cover.xhtml"), leaf("nav-title", "书名页", "title.xhtml")]
    for sec in sections:
        pid = f"nav-s{sec.index:02d}"
        head = (
            f'<navPoint id="{pid}" playOrder="{nxt()}">'
            f"<navLabel><text>{esc(sec.title)}</text></navLabel>"
            f'<content src="{sec.href}" />'
        )
        kids = "".join(
            leaf(f"{pid}-{k}", t, f"{sec.href}#{a}")
            for k, (a, t) in enumerate(sec.subheads if not sec.is_part else [])
        )
        points.append(head + kids + "</navPoint>")
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">\n'
        f'<head><meta name="dtb:uid" content="urn:uuid:{ed.book_id}" />'
        '<meta name="dtb:depth" content="2" />'
        '<meta name="dtb:totalPageCount" content="0" />'
        '<meta name="dtb:maxPageNumber" content="0" /></head>\n'
        f"<docTitle><text>{esc(ed.title)}·{esc(ed.subtitle)}</text></docTitle>\n"
        "<navMap>" + "".join(points) + "</navMap>\n</ncx>\n"
    )


def content_opf(ed: Edition, sections: list[Section], modified: str) -> str:
    manifest = [
        '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav" />',
        '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml" />',
        '<item id="css" href="style/book.css" media-type="text/css" />',
        '<item id="cover-image" href="cover.png" media-type="image/png" properties="cover-image" />',
        '<item id="cover" href="cover.xhtml" media-type="application/xhtml+xml" />',
        '<item id="title" href="title.xhtml" media-type="application/xhtml+xml" />',
    ]
    spine = ['<itemref idref="cover" />', '<itemref idref="title" />']
    for sec in sections:
        manifest.append(
            f'<item id="s{sec.index:02d}" href="{sec.href}" media-type="application/xhtml+xml" />'
        )
        spine.append(f'<itemref idref="s{sec.index:02d}" />')
    spine.append('<itemref idref="nav" />')
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="pub-id" '
        'xml:lang="zh-CN" prefix="rendition: http://www.idpf.org/vocab/rendition/#">\n'
        '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
        f'    <dc:identifier id="pub-id">urn:uuid:{ed.book_id}</dc:identifier>\n'
        f"    <dc:title>{esc(ed.title)}·{esc(ed.subtitle)}</dc:title>\n"
        f"    <dc:language>{LANGUAGE}</dc:language>\n"
        f"    <dc:date>{ed.publication_date}</dc:date>\n"
        "    <dc:creator>渡人渡己 · 道德经投资心法项目</dc:creator>\n"
        f"    <dc:description>{esc(ed.cover_caption)}</dc:description>\n"
        f'    <meta property="dcterms:modified">{modified}</meta>\n'
        '    <meta name="cover" content="cover-image" />\n'
        "  </metadata>\n  <manifest>\n    "
        + "\n    ".join(manifest)
        + '\n  </manifest>\n  <spine toc="ncx">\n    '
        + "\n    ".join(spine)
        + "\n  </spine>\n</package>\n"
    )


# --------------------------------------------------------------------------- #
# 封面
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


def centered_text(draw, y, text, font, fill, spacing=0):
    if spacing <= 0:
        box = draw.textbbox((0, 0), text, font=font)
        draw.text(((1600 - (box[2] - box[0])) / 2, y), text, font=font, fill=fill)
        return
    widths = [draw.textlength(ch, font=font) for ch in text]
    total = sum(widths) + spacing * (len(text) - 1)
    x = (1600 - total) / 2
    for ch, w in zip(text, widths):
        draw.text((x, y), ch, font=font, fill=fill)
        x += w + spacing


def build_cover(path: Path, ed: Edition) -> None:
    background = (246, 242, 231)
    ink = (57, 48, 35)
    green = (48, 101, 78)
    gold = (181, 153, 88)
    pale_gold = (214, 198, 157)
    image = Image.new("RGB", (1600, 2400), background)
    draw = ImageDraw.Draw(image)

    draw.rounded_rectangle((70, 70, 1530, 2330), radius=4, outline=gold, width=7)
    draw.rectangle((95, 95, 1505, 2305), outline=pale_gold, width=2)
    centered_text(draw, 160, ed.eyebrow, get_font(48), gold, spacing=6)

    cx, cy = 800, 640
    if ed.cover_motif == "tablet":
        # 律碑：一方碑石，碑面十八道横线＝十八类；碑首一枚朱印
        draw.rounded_rectangle((cx - 178, cy - 250, cx + 178, cy + 250), radius=14,
                               outline=green, width=6)
        draw.rounded_rectangle((cx - 150, cy - 222, cx + 150, cy + 222), radius=8,
                               outline=pale_gold, width=2)
        for k in range(18):
            y = cy - 186 + k * 22
            w = 112 if k % 6 == 0 else 78
            draw.line((cx - w, y, cx + w, y), fill=gold if k % 6 == 0 else pale_gold,
                      width=5 if k % 6 == 0 else 3)
        draw.ellipse((cx - 26, cy + 176, cx + 26, cy + 228), outline=gold, width=5)
        draw.ellipse((cx - 11, cy + 191, cx + 11, cy + 213), fill=gold)
    elif ed.cover_motif == "twelve":
        # 十二条宪法：外环十二格刻度；内方是法（不可修改的四条为实心）
        from math import cos, radians, sin
        draw.ellipse((cx - 250, cy - 250, cx + 250, cy + 250), outline=green, width=6)
        for k in range(12):
            ang = radians(90 - k * 30)
            x1, y1 = cx + 214 * cos(ang), cy - 214 * sin(ang)
            x2, y2 = cx + 246 * cos(ang), cy - 246 * sin(ang)
            draw.line((x1, y1, x2, y2), fill=gold if k in (0, 3, 4, 11) else pale_gold, width=8 if k in (0, 3, 4, 11) else 4)
        draw.rounded_rectangle((cx - 110, cy - 110, cx + 110, cy + 110), radius=6, outline=gold, width=5)
        draw.rounded_rectangle((cx - 62, cy - 62, cx + 62, cy + 62), radius=4, outline=pale_gold, width=3)
        draw.ellipse((cx - 14, cy - 14, cx + 14, cy + 14), fill=gold)
    elif ed.cover_motif == "eight":
        # 八个决策点：环上八个节点首尾相连，是一笔交易的顺序，也是复利的一圈
        from math import cos, radians, sin
        draw.ellipse((cx - 250, cy - 250, cx + 250, cy + 250), outline=green, width=6)
        pts = []
        for k in range(8):
            ang = radians(90 - k * 45)
            pts.append((cx + 250 * cos(ang), cy - 250 * sin(ang)))
        for k, (x, y) in enumerate(pts):
            r = 22 if k == 0 else 16
            draw.ellipse((x - r, y - r, x + r, y + r), fill=gold if k == 0 else background,
                         outline=gold, width=4)
        for k in range(8):
            (x1, y1), (x2, y2) = pts[k], pts[(k + 1) % 8]
            draw.line((x1, y1, x2, y2), fill=pale_gold, width=3)
        draw.ellipse((cx - 96, cy - 96, cx + 96, cy + 96), outline=gold, width=4)
        draw.ellipse((cx - 16, cy - 16, cx + 16, cy + 16), fill=gold)
    elif ed.cover_motif == "three":
        # 三情景估值：环内一枚正三角，三个顶点是熊／基／牛，重心一点是可执行买价
        from math import cos, radians, sin
        draw.ellipse((cx - 250, cy - 250, cx + 250, cy + 250), outline=green, width=6)
        pts = [(cx + 190 * cos(radians(90 + k * 120)), cy - 190 * sin(radians(90 + k * 120))) for k in range(3)]
        draw.polygon(pts, outline=gold, width=5)
        for k, (x, y) in enumerate(pts):
            r = 22 if k == 0 else 16
            draw.ellipse((x - r, y - r, x + r, y + r), fill=gold if k == 0 else background, outline=gold, width=4)
        draw.line((cx - 250, cy + 95, cx + 250, cy + 95), fill=pale_gold, width=3)
        draw.ellipse((cx - 16, cy - 16 + 30, cx + 16, cy + 16 + 30), fill=gold)
    elif ed.cover_motif == "thirtytwo":
        # 八行四枚令牌，对应八组、每组四条，与本系列几何封面同源。
        for row in range(8):
            for col in range(4):
                x = cx - 208 + col * 112
                y = cy - 245 + row * 65
                draw.rounded_rectangle((x, y, x + 80, y + 43), radius=4,
                                       outline=green if col == 0 else gold, width=3)
                draw.line((x + 20, y + 21, x + 60, y + 21),
                          fill=gold if col == 0 else pale_gold, width=3)
    elif ed.cover_motif == "ripple":
        # 守静：一枚石子落进静水，涟漪一圈圈散开——冲动会来，也会退
        for k, r in enumerate((250, 190, 130, 72)):
            draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline=green if k == 0 else pale_gold,
                         width=6 if k == 0 else 3)
        draw.ellipse((cx - 16, cy - 16, cx + 16, cy + 16), fill=gold)
        draw.line((cx - 250, cy + 300, cx + 250, cy + 300), fill=pale_gold, width=3)
    size = 150
    while size > 90 and draw.textlength(ed.title, font=get_font(size)) > 1380:
        size -= 10
    centered_text(draw, 1060 + (150 - size) // 2, ed.title, get_font(size), ink)
    centered_text(draw, 1265, ed.subtitle, get_font(76), green, spacing=6)
    draw.line((520, 1420, 1080, 1420), fill=pale_gold, width=3)
    centered_text(draw, 1480, ed.cover_caption, get_font(46), (101, 90, 70))
    centered_text(draw, 2140, "渡人渡己 · 道德经投资心法项目", get_font(40), gold, spacing=4)

    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="PNG", optimize=True)


# --------------------------------------------------------------------------- #
# CSS
# --------------------------------------------------------------------------- #

BOOK_CSS = """@charset "UTF-8";
@namespace epub "http://www.idpf.org/2007/ops";

html { color: #352f25; background: #fffdf8; }
body {
  margin: 5%;
  font-family: "Songti SC", "Noto Serif CJK SC", serif;
  font-size: 1em;
  line-height: 1.85;
  text-align: justify;
}
h1 {
  margin: 0.6em 0 1.1em;
  padding-bottom: 0.5em;
  border-bottom: 2px solid #b79a58;
  color: #2f624d;
  font-size: 1.45em;
  font-weight: 600;
  line-height: 1.5;
  text-align: center;
}
h2 {
  margin: 1.8em 0 0.6em;
  padding-left: 0.55em;
  border-left: 0.28em solid #3d6b56;
  color: #3d6b56;
  font-size: 1.08em;
  font-weight: 600;
  line-height: 1.5;
}
h3 {
  margin: 1.3em 0 0.4em;
  color: #8c7950;
  font-size: 0.98em;
  font-weight: 600;
}
p { margin: 0.6em 0; text-indent: 2em; }
a { color: #3d6b56; text-decoration: none; }
strong { color: #2f624d; }
code {
  padding: 0 0.2em;
  background: #f4efe2;
  color: #6b5c3e;
  font-family: "Menlo", "Courier New", monospace;
  font-size: 0.9em;
}
blockquote {
  margin: 1em 0.2em;
  padding: 0.8em 1em;
  border-left: 0.3em solid #b79a58;
  background: #faf6eb;
  color: #493f2c;
}
blockquote p { margin: 0.3em 0; text-indent: 0; }
ol, ul { padding-left: 1.6em; }
li { margin: 0.55em 0; text-indent: 0; }
hr.rule {
  height: 0;
  margin: 1.8em 12%;
  border: 0;
  border-top: 1px solid #ddd2b8;
}
pre {
  /* 同表格：不用 overflow，改为折行，避免超过一屏的表单在分页阅读器里整段空白 */
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  page-break-inside: auto;
  break-inside: auto;
  margin: 1em 0;
  padding: 0.9em 1em;
  border: 1px solid #e2d8c0;
  border-radius: 3px;
  background: #fbf8f0;
  color: #4a412f;
  font-family: "Menlo", "Courier New", monospace;
  font-size: 0.72em;
  line-height: 1.5;
  text-align: left;
}
/* 不给表格加 overflow：带 overflow 的盒子在分页阅读器里是不可分割的整体，
   超过一屏的表会整段渲染成空白页；改为允许表格与行跨页断开、单元格内任意折行 */
.tablewrap { margin: 1em 0; }
table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.86em;
  page-break-inside: auto;
  break-inside: auto;
}
tr { page-break-inside: auto; break-inside: auto; }
th, td {
  padding: 0.45em 0.6em;
  border: 1px solid #ddd2b8;
  line-height: 1.65;
  text-align: left;
  vertical-align: top;
  overflow-wrap: anywhere;
  word-break: break-word;
}
th { background: #f4efe2; color: #2f624d; font-weight: 600; }
ul.checklist { list-style: none; padding-left: 0.4em; }
ul.checklist li { position: relative; padding-left: 1.5em; }
ul.checklist li:before {
  position: absolute;
  left: 0;
  color: #b18f43;
  content: "\\25A1";
}
.ddj-full {
  margin: 0.45em 0 1.1em 1.6em;
  color: #7a6a45;
  font-size: 0.9em;
  text-indent: 0;
}
.ddj-full .ddj-src { color: #b18f43; letter-spacing: 0.04em; }
.ddj-full .ddj-text { color: #5d5238; }
.inlineblock { display: block; margin: 0.4em 0 0 0; }
.ddj-inline {
  color: #a08a55;
  font-size: 0.88em;
  white-space: nowrap;
}
.ddj-inline .ddj-q { color: #7a6a45; }
.entry-nav {
  display: flex;
  justify-content: space-between;
  margin-top: 2.6em;
  padding-top: 0.8em;
  border-top: 1px solid #d8ccb0;
  font-size: 0.88em;
  text-indent: 0;
}
.cover-body { margin: 0; padding: 0; background: #f6f2e7; text-align: center; }
.cover-page { margin: 0; padding: 0; }
.cover-page img { width: 100%; height: auto; max-height: 100%; object-fit: contain; }
.title-body, .part-body { margin: 0; padding: 0; }
.title-page, .part-page {
  min-height: 85vh;
  padding: 16% 8% 8%;
  box-sizing: border-box;
  text-align: center;
}
.title-page h1 { margin: 1em 0 0.5em; border: 0; font-size: 2.1em; color: #352f25; }
.title-page h1 span { color: #3d6b56; font-size: 0.5em; }
.eyebrow { color: #b18f43; text-indent: 0; text-align: center; letter-spacing: 0.16em; }
.subtitle, .author, .part-summary { text-indent: 0; text-align: center; }
.subtitle { color: #3d6b56; font-size: 1.05em; }
.author { margin-top: 7em; color: #8c7950; font-size: 0.9em; }
.part-page h1 { margin-top: 1.4em; border: 0; font-size: 1.9em; }
.part-summary { max-width: 30em; margin: 1.6em auto; color: #655a46; }
.toc-body { text-align: left; }
.toc-body h1 { text-align: center; }
.toc-body ol { padding-left: 1.4em; }
.toc-body ol ol { margin: 0.4em 0 0.9em; font-size: 0.92em; }
.toc-body li { margin: 0.32em 0; }
.landmarks { margin-top: 2em; border-top: 1px solid #d8ccb0; }
"""


# --------------------------------------------------------------------------- #
# 打包与校验
# --------------------------------------------------------------------------- #

def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def assemble_epub(build_dir: Path, ed: Edition, sections: list[Section]) -> None:
    epub_dir = build_dir / "EPUB"
    write_text(build_dir / "mimetype", "application/epub+zip")
    write_text(build_dir / "META-INF" / "container.xml", CONTAINER_XML)
    write_text(epub_dir / "style" / "book.css", BOOK_CSS)
    build_cover(epub_dir / "cover.png", ed)
    write_text(epub_dir / "cover.xhtml", cover_xhtml())
    write_text(epub_dir / "title.xhtml", title_xhtml(ed))
    for pos, sec in enumerate(sections):
        prev_href = "title.xhtml" if pos == 0 else sections[pos - 1].href
        next_href = "nav.xhtml" if pos == len(sections) - 1 else sections[pos + 1].href
        write_text(epub_dir / sec.href, section_xhtml(sec, prev_href, next_href))
    write_text(epub_dir / "nav.xhtml", nav_xhtml(ed, sections))
    write_text(epub_dir / "toc.ncx", toc_ncx(ed, sections))
    modified = (
        datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    )
    write_text(epub_dir / "content.opf", content_opf(ed, sections, modified))


def package_epub(build_dir: Path, output: Path) -> None:
    tmp = output.with_suffix(output.suffix + ".tmp")
    with zipfile.ZipFile(tmp, "w") as archive:
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
    tmp.replace(output)


def validate_epub(output: Path, ed: Edition, sections: list[Section]) -> None:
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
            "EPUB/cover.xhtml",
            "EPUB/title.xhtml",
            "EPUB/style/book.css",
        } | {f"EPUB/{sec.href}" for sec in sections}
        missing = sorted(required - set(names))
        if missing:
            raise ValueError(f"EPUB 缺少文件：{missing}")

        # 每个 XHTML 必须能作为 XML 解析
        for name in names:
            if name.endswith((".xhtml", ".opf", ".ncx")) or name.endswith("container.xml"):
                try:
                    ET.fromstring(archive.read(name))
                except ET.ParseError as exc:  # pragma: no cover
                    raise ValueError(f"{name} 不是良构 XML：{exc}") from exc

        # NCX playOrder 必须按文档顺序递增
        ncx = archive.read("EPUB/toc.ncx").decode("utf-8")
        orders = [int(x) for x in re.findall(r'playOrder="(\d+)"', ncx)]
        if orders != sorted(orders) or orders != list(range(1, len(orders) + 1)):
            raise ValueError("toc.ncx 的 playOrder 未按文档顺序连续递增")

        # spine 覆盖全部章节
        opf = archive.read("EPUB/content.opf").decode("utf-8")
        for sec in sections:
            if f'idref="s{sec.index:02d}"' not in opf:
                raise ValueError(f"spine 缺少 {sec.title}")

        # 正文完整性：源文中的关键锚点必须出现在成书里
        joined = "".join(
            archive.read(f"EPUB/{sec.href}").decode("utf-8") for sec in sections
        )
        probes = {
            "playbook": ("附录 A", "免责声明", "第十七章", "R4.6", "案例账户", "《道德经》第"),
            "system": ("附录 A", "免责声明", "第七章", "宪十二", "C01-001", "《道德经》第"),
            "catalog": ("附录 A", "第一部分", "第五部分", "C01-001", "C18-022", "铁律"),
            "quant": ("卷首", "设计规格 v1.0", "十三、实施交付", "legacy_playbook", "第48章", "MOS"),
            "mind": ("卷首", "第一章", "附录 A", "免责声明", "案例账户", "《道德经》第", "T1.1"),
            "rules32": ("第01条", "第32条", "附录A", "C01-001", "C18-022", "操作指南", "案例账户"),
        }.get(ed.key, ("附录A", "免责声明", "第十二章"))
        for probe in probes:
            if probe not in joined:
                raise ValueError(f"成书正文缺少「{probe}」")
        if ed.key == "catalog":
            n_id = len(set(re.findall(r"C\d\d-\d{3}", joined)))
            if n_id < 360:
                raise ValueError(f"纪律总表只剩 {n_id} 个编号（应为 360），疑似转换丢失")
        if ed.key == "rules32":
            import json
            catalog = json.loads((ROOT / "system/data/纪律总表.json").read_text(encoding="utf-8"))
            if set(re.findall(r"C\d{2}-\d{3}", joined)) != {d["id"] for d in catalog}:
                raise ValueError("三十二条军规的360条来源编号有遗漏或多余")
            if sum(bool(re.match(r"第\d{2}条 · ", s.title)) for s in sections) != 32:
                raise ValueError("三十二条军规的正文条目数量错误")
        if ed.key in ("playbook", "system", "catalog", "quant", "mind", "rules32"):
            for bad in ("150万", "1.5M", "traceme", "discovery-invest"):
                if bad in joined:
                    raise ValueError(f"{ed.title}正文含不应出现的字符串「{bad}」")
            if re.search(r"<a href=\"/", joined):
                raise ValueError(f"{ed.title}成书里残留站内链接")
        if ed.key in ("playbook", "system", "catalog", "mind"):
            nq = joined.count("《道德经》第")
            floor = {"playbook": 30, "system": 15, "catalog": 0, "mind": 20}.get(ed.key, 15)
            if nq < floor:
                raise ValueError(f"{ed.title}的《道德经》引文只剩 {nq} 处（下限 {floor}），疑似转换丢失")
        if ed.key == "system":
            nrow = joined.count("C0") + joined.count("C1")
            if nrow < 360:
                raise ValueError(f"系统的矩阵编号只剩 {nrow} 处，疑似转换丢失")
        else:
            if "▍" in joined:
                raise ValueError("无标注版不应含 ▍ 原文标注")
    return None


def build_edition(ed: Edition) -> None:
    if not ed.source.exists():
        raise FileNotFoundError(f"缺少源文件：{ed.source}")
    sections = parse_document(ed.source, ed.split_h3, ed.intro_title)
    for sec in sections:
        sec.subheads = collect_subheads(sec.lines)
    with tempfile.TemporaryDirectory() as tmp:
        build_dir = Path(tmp)
        assemble_epub(build_dir, ed, sections)
        package_epub(build_dir, ed.output)
    validate_epub(ed.output, ed, sections)
    size = ed.output.stat().st_size
    subs = sum(len(s.subheads) for s in sections)
    print(
        f"✅ {ed.output.name}：{size:,} 字节｜{len(sections)} 章｜{subs} 小节｜"
        f"校验通过（XML 良构、playOrder 连续、spine 完整、正文抽检）"
    )


def main() -> None:
    keys = sys.argv[1:] or list(EDITIONS)
    for key in keys:
        if key not in EDITIONS:
            raise SystemExit(f"未知版本：{key}（可选 {', '.join(EDITIONS)}）")
        build_edition(EDITIONS[key])


if __name__ == "__main__":
    main()
