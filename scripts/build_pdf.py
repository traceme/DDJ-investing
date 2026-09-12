#!/usr/bin/env python3
"""把本仓库的 Markdown 书稿做成阅读友好的 A4 PDF。

主要书目：
  规则层三本   playbook 道德经投资打法手册 ／ catalog 投资纪律总表 ／ system 道德经投资系统
  心法层五本   ddj 道德经81章投资心法 ／ codex Codex 重悟版 ／ selection 投资心法100条精选
               jinbing 渡人渡己读书心法 ／ thirdeye 第三只眼观投资心法
  指南两本     effort 普通投资者的努力方向与时间分配 ／ research 专业投资研究指南

分工：
- Chrome headless 负责排版（宋体正文／黑体标题、表格跨页自动重复表头、行不跨页、
  标题不孤行），并用 --generate-pdf-document-outline 生成带页码的书签；
  标题用 Hiragino Sans GB 而非 PingFang：后者会被 Chrome 逐页以 Type 3 字形嵌入，体积膨胀十倍。
- PyMuPDF 负责装订：封面页（复用 EPUB 封面或系列封面模板）、扉页与目录（目录页码来自 Chrome 书签）、每页页眉
  （左书名、右当前章节）与页脚页码、PDF 页码标签（前言罗马数字、正文阿拉伯数字）、字体子集合并。
  盖章前每页先 wrap_contents()：Chrome 的内容流不闭合坐标变换，否则追加的文字会被压扁挪位。
  Chrome 在 macOS 上打印完常不退出，脚本在输出文件停止增长后结束进程。

页眉页脚用宋体：构建时用 fontTools 从系统 Songti.ttc 抽出「Songti SC Regular」一个字面到
临时目录（PyMuPDF 不能直接用 TTC），随后以子集嵌入 PDF；仓库不含任何字体文件。

用法：
    python3 scripts/build_pdf.py                 # 所有已登记书目
    python3 scripts/build_pdf.py catalog ddj     # 只构建指定的几本
    python3 scripts/build_pdf.py rules32         # 《投资三十二条军规》
    python3 scripts/build_pdf.py effort research # 两本投资指南

依赖：Google Chrome、PyMuPDF (fitz)、fontTools、Pillow（规则层封面）。
"""

from __future__ import annotations

import datetime as dt
import html
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import fitz  # PyMuPDF
from fontTools.ttLib import TTCollection

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_system_epub as B  # noqa: E402  复用 Markdown→XHTML 转换器、版本表与封面

ROOT = Path(__file__).resolve().parent.parent
CHROME = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
SONGTI_TTC = Path("/System/Library/Fonts/Supplemental/Songti.ttc")

A4_W, A4_H = 595.276, 841.890            # pt
MARGIN_X = 56.7                          # 20mm
HEADER_Y, RULE_Y, FOOTER_Y = 44.0, 50.0, A4_H - 34.0
INK, GOLD, PALE = (0.21, 0.18, 0.15), (0.69, 0.56, 0.26), (0.87, 0.82, 0.72)
COVER_BG = (246 / 255, 242 / 255, 231 / 255)


# --------------------------------------------------------------------------- #
# 书籍登记表
# --------------------------------------------------------------------------- #

@dataclass
class Book:
    key: str
    title: str
    subtitle: str
    eyebrow: str
    caption: str
    meta: str                                   # 扉页末行：性质与免责
    out: Path
    sections: Callable[[], list[B.Section]]     # 章节装载器
    cover: Callable[[Path], None]               # 把封面 PNG 写到给定路径
    probes: tuple = ()                          # 自检：成书正文必含
    rich_marks: bool = False                    # 还原 <mark>/<u>（心法随笔用）
    source: Path | None = None                  # 单文件指南：逐行核验原稿与成书、核对全部标题书签
    title_lines: tuple[str, ...] = ()           # 长书名在封面及扉页的自然分行


def demote(lines: list[str]) -> list[str]:
    """章文件里的 `## ` → `### `（章标题本身是 H1，节标题在书里是三级）。"""
    out, code = [], False
    for ln in lines:
        if ln.startswith("```"):
            code = not code
        if not code and re.match(r"^\s*<!--.*-->\s*$", ln):
            continue                                   # HTML 注释（如导航标记）不是正文
        out.append(("#" + ln) if (not code and re.match(r"^#{2,4} ", ln)) else ln)
    return out


def strip_nav(lines: list[str]) -> list[str]:
    """去掉章末导航：结尾的分隔线与「[← 上一章] · [全书目录] · [下一章 →]」。"""
    while lines and not lines[-1].strip():
        lines.pop()
    if lines and re.match(r"^\[[^\]]*(目录|上一|下一)[^\]]*\]", lines[-1].strip()):
        lines.pop()
    while lines and not lines[-1].strip():
        lines.pop()
    if lines and lines[-1].strip() == "---":
        lines.pop()
    return lines


def chapter_files(pattern: str) -> Callable[[], list[B.Section]]:
    """逐章文件 → 每章一节：H1 为章题，正文降级、去导航。"""
    def load() -> list[B.Section]:
        secs = []
        for i, path in enumerate(sorted(ROOT.glob(pattern)), 1):
            lines = path.read_text(encoding="utf-8").split("\n")
            title = next(l[2:].strip() for l in lines if l.startswith("# "))
            body = [l for l in lines if not l.startswith("# ")]
            secs.append(B.Section(index=i, title=title, lines=strip_nav(demote(body))))
        return secs
    return load


def with_parts(loader: Callable[[], list[B.Section]],
               parts: list[tuple[int, str, str]]) -> Callable[[], list[B.Section]]:
    """在指定章序号之前插入分部扉页：parts = [(起始章序号(1 起), 扉页标题, 一句说明)]。"""
    def load() -> list[B.Section]:
        secs, out, at = loader(), [], {n: (t, s) for n, t, s in parts}
        for i, sec in enumerate(secs, 1):
            if i in at:
                t, s = at[i]
                out.append(B.Section(index=0, title=t, lines=["", s, ""]))
            out.append(sec)
        for k, sec in enumerate(out, 1):
            sec.index = k
        return out
    return load


def single_file(path: Path, split_h3: tuple = (), intro_title: str = "卷首") -> Callable[[], list[B.Section]]:
    """单文件书：第一个 `## ` 之前的引言成为「卷首」一节，其余按 H2 分节。"""
    def load() -> list[B.Section]:
        text = path.read_text(encoding="utf-8")
        head = text.split("\n## ", 1)[0].split("\n")
        intro = [l for l in head if not l.startswith("📘") and not l.startswith("# ")]
        secs = B.parse_document(path, split_h3)
        if any(l.strip() for l in intro):
            secs.insert(0, B.Section(index=0, title=intro_title, lines=intro))
        for k, sec in enumerate(secs, 1):
            sec.index = k
        return secs
    return load


def cover_from_edition(ed: B.Edition) -> Callable[[Path], None]:
    return lambda png: B.build_cover(png, ed)


def cover_from_epub(epub: Path) -> Callable[[Path], None]:
    def extract(png: Path) -> None:
        with zipfile.ZipFile(epub) as z:
            name = next(n for n in z.namelist() if n.lower().endswith("cover.png"))
            png.write_bytes(z.read(name))
    return extract


ESSAY_META = "哲学随笔与投资常识的融合，不构成任何具体投资建议；行业、指数与历史行情均为示例或史实复盘"
NOTES_META = "第三方著作的逐篇读书笔记，不含原书正文；不构成任何具体投资建议"
RULES_META = "本书是方法论，不是荐股；示例参数来自归一为 100 单位的案例账户"

E = B.EDITIONS


QUANT_META = "设计规格：程序、回测与模拟交易尚未实施，不可据此启用实盘；不构成任何具体投资建议"
MIND_META = "训练手册，不是荐股，也不是医疗建议；示例数字来自归一为 100 单位的案例账户"


def rules_book(key: str, out: str, probes: tuple, meta: str = RULES_META) -> Book:
    ed = E[key]
    return Book(key, ed.title, ed.subtitle, ed.eyebrow, ed.cover_caption, meta, ROOT / out,
                lambda: B.parse_document(ed.source, ed.split_h3, ed.intro_title),
                cover_from_edition(ed), probes)


def guide_book(key: str, title: str, subtitle: str, eyebrow: str, caption: str,
               motif: str, probes: tuple, title_lines: tuple[str, ...] = ()) -> Book:
    """仅登记 PDF 的单文件指南；复用系列封面，不依赖预先生成的 EPUB。"""
    source, output = ROOT / f"{title}.md", ROOT / f"{title}.pdf"
    cover = B.Edition(key=key, source=source, output=output, title=title, subtitle=subtitle,
                      book_id=f"ddj-investing-{key}", eyebrow=eyebrow,
                      cover_motif=motif, cover_caption=caption, cover_title_lines=title_lines)
    return Book(key, title, subtitle, eyebrow, caption,
                "投资方法说明，不构成具体证券买卖建议，也不保证收益或最大回撤",
                output, single_file(source), cover_from_edition(cover), probes,
                source=source, title_lines=title_lines)


BOOKS: dict[str, Book] = {
    "playbook": rules_book("playbook", "道德经投资打法手册.pdf", ("R4.6", "案例账户", "附录 B")),
    "catalog": rules_book("catalog", "投资纪律总表.pdf", ("C01-001", "C18-022", "铁律")),
    "system": rules_book("system", "道德经投资系统.pdf", ("宪十二", "C01-001", "R18.20")),
    "quant": rules_book("quant", "股票量化投资系统.pdf",
                        ("设计规格 v1.0", "十三、实施交付", "legacy_playbook", "第48章"), QUANT_META),
    "mind": rules_book("mind", "成功投资者心性养成指南.pdf",
                       ("卷首", "案例账户", "附录 A", "T1.1"), MIND_META),
    "rules32": rules_book("rules32", "投资三十二条军规.pdf",
                          ("第01条", "第32条", "附录A", "C01-001", "C18-022", "0.6575"),
                          "三十二条操作军规；虚构案例归一为100单位，示例参数不构成具体投资建议"),
    "effort": guide_book("effort", "普通投资者的努力方向与时间分配", "让时间服务于长期目标",
                         "职 业 · 资 金 · 学 习 · 研 究", "把有限注意力用在真正影响长期结果的事情上",
                         "ripple", ("合计 240 分钟", "66,465", "为学日益", "只解决一个重要问题"),
                         title_lines=("普通投资者的", "努力方向与时间分配")),
    "research": guide_book("research", "专业投资研究指南", "证据 · 估值 · 风险 · 组合",
                           "从 公 司 筛 选 到 可 复 核 的 决 策", "九个研究维度，三个决策层次，一份可复核结论",
                           "three", ("真正需要研究的九件事", "55 单位", "关键假设", "QQQ")),
    "ddj": Book("ddj", "道德经81章投资心法", "八十一章 · 逐章投资随笔", "以 王 弼 通 行 本 为 底 本",
                "把章句引申为投资世界里的常识与纪律", ESSAY_META, ROOT / "道德经81章投资心法.pdf",
                chapter_files("chapters/第*章.md"), cover_from_epub(ROOT / "道德经81章投资心法.epub"),
                ("第一章", "第八十一章", "实操建议"), rich_marks=True),
    "codex": Book("codex", "道德经81章投资心法", "Codex 重悟版 · 大白话讲透章句与投资方法",
                  "八 十 一 章 · 各 附 实 操 建 议", "从生活与市场场景切入的独立重写", ESSAY_META,
                  ROOT / "道德经81章投资心法Codex版本.pdf",
                  chapter_files("codex/第*章.md"), cover_from_epub(ROOT / "道德经81章投资心法Codex版本.epub"),
                  ("第一章", "第八十一章", "实操建议"), rich_marks=True),
    "selection": Book("selection", "投资心法 100 条精选", "三书提炼 · 按重要程度排序",
                      "生 存 性 · 根 本 性 · 三 书 共 振", "313 章合并为 100 条，每条附三书原文摘录", ESSAY_META,
                      ROOT / "投资心法100条精选版.pdf",
                      single_file(ROOT / "投资心法100条精选版.md", intro_title="怎么读这一百条"),
                      cover_from_epub(ROOT / "投资心法100条精选版.epub"), ("1. ", "100. ", "《道德经》")),
    "jinbing": Book("jinbing", "人生悟道 渡人渡己 · 投资篇读书心法", "七十二篇 · 中心思想 · 投资心法 · 实操建议",
                    "基 础 篇 · 进 阶 篇 · 哲 思 篇", "金冰《人生悟道 渡人渡己·投资篇（纪念版）》逐篇读书笔记",
                    NOTES_META, ROOT / "人生悟道渡人渡己投资篇读书心法.pdf",
                    with_parts(chapter_files("jinbing-drdj/第*篇.md"), [
                        (1, "第一部分 · 基础篇", "第一至二十五篇：把时间、本金与自己看清楚，先立生存层。"),
                        (26, "第二部分 · 进阶篇", "第二十六至四十八篇：研究、估值、仓位与卖出的手艺。"),
                        (49, "第三部分 · 哲思篇", "第四十九至七十二篇：周期、心力与修炼，投资之外的投资。")]),
                    cover_from_epub(ROOT / "人生悟道渡人渡己投资篇读书心法.epub"),
                    ("第一篇", "第七十二篇", "实操建议"), rich_marks=True),
    "thirdeye": Book("thirdeye", "第三只眼观 · 投资心法", "一百五十一篇 · 中心思想与投资随笔", "读 书 笔 记",
                     "《第三只眼观》151 篇文章的逐篇读书笔记", NOTES_META, ROOT / "第三只眼观投资心法.pdf",
                     chapter_files("thethirdeye/第*章.md"), cover_from_epub(ROOT / "第三只眼观投资心法.epub"),
                     ("第一章", "中心思想", "投资心法"), rich_marks=True),
}


# --------------------------------------------------------------------------- #
# 版式
# --------------------------------------------------------------------------- #

CSS = """
@page { size: A4; margin: 26mm 20mm 24mm 20mm; }
html { font-size: 10.8pt; }
body { font-family: "Songti SC", "STSong", serif; line-height: 1.9; color: #352f25; margin: 0;
       text-align: justify; }
h1, h2, h3, h4 { font-family: "Hiragino Sans GB", "PingFang SC", sans-serif; font-weight: 600;
                 color: #2f624d; line-height: 1.4; break-after: avoid; page-break-after: avoid; }
section.chapter { break-before: page; page-break-before: always; }
section.chapter:first-child { break-before: auto; page-break-before: auto; }
h1 { font-size: 20pt; margin: 0 0 1em; padding-bottom: 0.35em; border-bottom: 1.2pt solid #b18f43; }
h2 { font-size: 15pt; margin: 1.6em 0 0.6em; }
h3 { font-size: 13pt; margin: 1.6em 0 0.5em; }
h4 { font-size: 11.5pt; margin: 1.3em 0 0.4em; color: #3d6b56; }
p { margin: 0 0 0.75em; orphans: 2; widows: 2; }
strong { color: #2b2620; }
mark { background: none; color: #b18f43; font-weight: 600; }
u { text-decoration: underline; text-decoration-color: #3d6b56; text-decoration-thickness: 1.2pt;
    text-underline-offset: 2.5pt; }
blockquote { margin: 0.9em 0 1.1em; padding: 0.55em 1em; border-left: 2.5pt solid #b18f43;
             background: #faf6eb; color: #5d5238; break-inside: avoid; page-break-inside: avoid; }
blockquote p { margin: 0.25em 0; }
ul, ol { margin: 0.3em 0 0.9em; padding-left: 1.7em; }
li { margin: 0.15em 0; }
hr.rule { border: 0; border-top: 0.6pt solid #ddd2b8; margin: 1.3em 0; }
.tablewrap { margin: 0.8em 0 1.1em; }
table { width: 100%; border-collapse: collapse; font-size: 9pt; line-height: 1.55;
        break-inside: auto; page-break-inside: auto; }
thead { display: table-header-group; }
tr { break-inside: avoid; page-break-inside: avoid; }
th, td { border: 0.5pt solid #ddd2b8; padding: 3.5pt 5pt; vertical-align: top; text-align: left;
         overflow-wrap: anywhere; word-break: break-word; }
th { background: #f4efe2; color: #2f624d; font-family: "Hiragino Sans GB", "PingFang SC", sans-serif;
     font-weight: 600; }
tbody tr:nth-child(even) td { background: #fcfaf4; }
table.wide { font-size: 8.2pt; line-height: 1.45; }
table.wide th, table.wide td { padding: 2.5pt 3.5pt; }
td.nw, th.nw, th:last-child { white-space: nowrap; }     /* 短首列（编号、序号）与末列表头不折行 */
table.c5 td:nth-child(2), table.c5 th:nth-child(2) { min-width: 8.5em; }
table.c5 td:nth-child(3), table.c5 th:nth-child(3) { min-width: 4.5em; }
pre { font-family: Menlo, "SF Mono", monospace; font-size: 8.3pt; line-height: 1.5; background: #fbf8f0;
      border: 0.5pt solid #e6dcc4; padding: 0.7em 0.9em; white-space: pre-wrap; overflow-wrap: anywhere;
      break-inside: avoid; page-break-inside: avoid; margin: 0.8em 0 1em; }
code { font-family: Menlo, "SF Mono", monospace; font-size: 0.9em; background: #f4efe2; padding: 0 0.25em; }
td.nw code { white-space: nowrap; overflow-wrap: normal; word-break: keep-all; }
ul.checklist { list-style: none; padding-left: 0.3em; }
ul.checklist li:before { content: "\\2610\\00a0"; color: #b18f43; }
section.part { text-align: center; padding-top: 34%; }
section.part h1 { border: 0; font-size: 24pt; }
section.part p { max-width: 28em; margin: 1.5em auto; color: #655a46; text-align: justify; }

/* 扉页与目录 */
.title { text-align: center; padding-top: 22%; }
.title .eyebrow { color: #b18f43; letter-spacing: 0.35em; font-size: 10pt; margin-bottom: 3em; }
.title h1 { border: 0; font-size: 34pt; margin: 0 0 0.4em; color: #352f25; }
.title .sub { font-family: "Hiragino Sans GB", "PingFang SC", sans-serif; color: #2f624d; font-size: 15pt;
              letter-spacing: 0.1em; margin-bottom: 2.4em; }
.title .cap { color: #655a46; font-size: 11pt; margin-bottom: 8em; }
.title .meta { color: #8a7d62; font-size: 9.5pt; line-height: 1.9; }
.toc { break-before: page; page-break-before: always; }
.toc h1 { border-bottom: 1.2pt solid #b18f43; }
.toc ol { list-style: none; padding: 0; margin: 0.6em 0 0; }
.toc li { display: flex; align-items: baseline; margin: 0.28em 0; font-size: 10.5pt; }
.toc.dense li { margin: 0.12em 0; font-size: 9.8pt; }
.toc li .t { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 84%; }
.toc li .d { flex: 1; border-bottom: 0.6pt dotted #b9ad8f; margin: 0 0.5em; min-width: 1.2em;
             transform: translateY(-0.3em); }
.toc li .n { font-family: "Hiragino Sans GB", "PingFang SC", sans-serif; color: #2f624d;
             font-variant-numeric: tabular-nums; }
.toc li.part { margin-top: 0.9em; }
.toc li.part .t { font-family: "Hiragino Sans GB", "PingFang SC", sans-serif; font-weight: 600; color: #2f624d; }
.toc .hint { color: #8a7d62; font-size: 9.5pt; margin-top: 2em; }
"""


def html_head(title: str) -> str:
    return ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"/>'
            f'<title>{html.escape(title)}</title><style>{CSS}</style></head><body>')


# --------------------------------------------------------------------------- #
# Chrome：排版 → PDF
# --------------------------------------------------------------------------- #

def chrome_pdf(html_path: Path, pdf_path: Path, timeout: float = 300) -> None:
    if not CHROME.exists():
        raise SystemExit(f"未找到 Chrome：{CHROME}")
    pdf_path.unlink(missing_ok=True)
    profile = Path(tempfile.mkdtemp(prefix="ddj-chrome-"))
    args = [str(CHROME), "--headless=new", "--disable-gpu", "--no-sandbox", "--no-first-run",
            "--no-default-browser-check", "--disable-extensions", "--hide-scrollbars",
            f"--user-data-dir={profile}", "--no-pdf-header-footer",
            "--generate-pdf-document-outline", "--virtual-time-budget=10000",
            f"--print-to-pdf={pdf_path}", html_path.resolve().as_uri()]
    proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    t0, last, stable = time.time(), -1, 0
    try:
        while time.time() - t0 < timeout:
            if proc.poll() is not None:
                break
            if pdf_path.exists():
                size = pdf_path.stat().st_size
                stable = stable + 1 if size > 0 and size == last else 0
                last = size
                if stable >= 4:            # 2 秒内文件未再变化：已写完
                    break
            time.sleep(0.5)
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(5)
            except subprocess.TimeoutExpired:
                proc.kill()
        shutil.rmtree(profile, ignore_errors=True)
    if not pdf_path.exists() or pdf_path.stat().st_size == 0:
        raise RuntimeError(f"Chrome 未生成 {pdf_path.name}")
    fitz.open(pdf_path).close()   # 能打开才算写完整


# --------------------------------------------------------------------------- #
# HTML 装配
# --------------------------------------------------------------------------- #

def mark_wide_tables(doc: str) -> str:
    """按列数给表加类：≥6 列用更小字号（矩阵表），≥5 列给前几列最小宽度；短首列不折行。"""
    def first_cell(m):
        tag, attrs, inner = m.group(1), m.group(2), m.group(3)
        plain = re.sub(r"<[^>]+>", "", inner)
        width = sum(1 if ord(c) > 0x2E7F else 0.55 for c in plain)   # 按字宽估：西文约半个汉字宽
        if width <= 14 and " " not in plain.strip():
            return f'<tr><{tag} class="nw"{attrs}>{inner}</{tag}>'
        return m.group(0)
    def fix(m):
        t = m.group(0)
        ncol = len(re.findall(r"<th\b", t.split("</tr>", 1)[0]))
        cls = "wide c5" if ncol >= 6 else "c5" if ncol == 5 else ""
        if cls:
            t = t.replace("<table>", f'<table class="{cls}">', 1)
        return re.sub(r"<tr><(t[dh])((?:\s[^>]*)?)>(.*?)</\1>", first_cell, t, flags=re.S)
    return re.sub(r"<table>.*?</table>", fix, doc, flags=re.S)


def restore_marks(doc: str) -> str:
    """转换器把正文里的 <mark>/<u> 转义成了文字，这里还原成标签（心法随笔的引文与警句）。"""
    for tag in ("mark", "u"):
        doc = doc.replace(f"&lt;{tag}&gt;", f"<{tag}>").replace(f"&lt;/{tag}&gt;", f"</{tag}>")
    return doc


def body_html(book: Book, sections: list[B.Section]) -> str:
    head = html_head(book.title)
    if book.source:
        extra = """<style>
body.guide { line-height: 1.75; }
.guide section.chapter { break-before: auto; page-break-before: auto; }
.guide section.chapter + section.chapter { margin-top: 1.4em; }
.guide section.chapter:last-child { break-inside: avoid; page-break-inside: avoid; }
.guide h1 { font-size: 18pt; margin-bottom: 0.65em; }
.guide h2 { font-size: 13pt; margin: 0.9em 0 0.4em; }
.guide p { margin-bottom: 0.5em; }
.guide ul, .guide ol { margin-bottom: 0.6em; }
.guide li { margin: 0.1em 0; }
.guide .tablewrap { break-inside: avoid; page-break-inside: avoid; }
</style>"""
        head = head.replace("</head><body>", extra + '</head><body class="guide">')
    if book.key == "rules32":
        extra = """<style>
body.rules32 { line-height: 1.8; }
.rules32 h1 { margin-bottom: 0.65em; }
.rules32 h2 { font-size: 13pt; margin: 0.85em 0 0.4em; }
.rules32 p { margin-bottom: 0.5em; }
.rules32 ul, .rules32 ol { margin-bottom: 0.6em; }
.rules32 li { margin: 0.1em 0; }
.rules32 .source-note { font-size: 8.5pt; color: #76694f; line-height: 1.6; margin-top: 0.8em; }
.rules32 .source-group, .rules32 .rule-summary .tablewrap { break-inside: avoid; page-break-inside: avoid; }
</style>"""
        head = head.replace("</head><body>", extra + '</head><body class="rules32">')
    parts = [head]
    for sec in sections:
        cls = "chapter part" if sec.is_part else "chapter"
        content = B.render_blocks(sec.lines)
        if book.key == "rules32":
            content = content.replace("<p>本条归并", '<p class="source-note">本条归并')
            if sec.title == "三十二条速查":
                cls += " rule-summary"
            if sec.title.startswith(("附录A", "附录B")):
                content = re.sub(r"(<h2\b.*?)(?=<h2\b|\Z)",
                                 r'<div class="source-group">\1</div>', content, flags=re.S)
        parts.append(f'<section class="{cls}"><h1>{B.inline(sec.title)}</h1>{content}</section>')
    parts.append("</body></html>")
    doc = mark_wide_tables("".join(parts))
    return restore_marks(doc) if book.rich_marks else doc


def front_html(book: Book, toc: list[tuple[str, int, bool]], today: str) -> str:
    title = "<br/>".join(html.escape(line) for line in book.title_lines) if book.title_lines else html.escape(book.title)
    items = "".join(
        f'<li class="{"part" if is_part else ""}"><span class="t">{html.escape(t)}</span>'
        f'<span class="d"></span><span class="n">{p}</span></li>'
        for t, p, is_part in toc
    )
    dense = " dense" if len(toc) > 40 else ""
    return (html_head(book.title) +
            f'<section class="title"><div class="eyebrow">{html.escape(book.eyebrow)}</div>'
            f'<h1>{title}</h1><div class="sub">{html.escape(book.subtitle)}</div>'
            f'<div class="cap">{html.escape(book.caption)}</div>'
            f'<div class="meta">渡人渡己 · 道德经投资心法项目<br/>PDF 版　{today}　由仓库脚本从 Markdown 生成<br/>'
            f'{html.escape(book.meta)}</div></section>'
            f'<section class="toc{dense}"><h1>目录</h1><ol>{items}</ol>'
            f'<p class="hint">页码为正文页码（页脚所示）。阅读器侧栏的书签含各章之下的小节，可直接跳转；'
            f'每页页眉右侧为当前章节。</p></section></body></html>')


# --------------------------------------------------------------------------- #
# 装订
# --------------------------------------------------------------------------- #

def extract_songti(tmp: Path) -> Path:
    out = tmp / "SongtiSC-Regular.ttf"
    for face in TTCollection(str(SONGTI_TTC)).fonts:
        if (face["name"].getDebugName(4) or "") == "Songti SC Regular":
            face.save(str(out))
            return out
    raise SystemExit("Songti.ttc 中未找到 Songti SC Regular")


def add_cover(doc: fitz.Document, png: Path) -> None:
    pix = fitz.Pixmap(str(png))
    page = doc.new_page(pno=0, width=A4_W, height=A4_H)
    page.draw_rect(page.rect, color=None, fill=COVER_BG)
    scale = min(A4_W / pix.width, A4_H / pix.height)
    w, h = pix.width * scale, pix.height * scale
    x0, y0 = (A4_W - w) / 2, (A4_H - h) / 2
    page.insert_image(fitz.Rect(x0, y0, x0 + w, y0 + h), filename=str(png))


def stamp(doc: fitz.Document, first_body: int, chapter_of_page: dict[int, str],
          book_title: str, font: fitz.Font) -> None:
    for pno in range(first_body, doc.page_count):
        page = doc[pno]
        page.wrap_contents()      # Chrome 的内容流不以 Q 结尾，残留的变换矩阵会把追加的文字压扁挪位
        body_no = pno - first_body + 1
        tw = fitz.TextWriter(page.rect)
        tw.append(fitz.Point(MARGIN_X, HEADER_Y), book_title, font=font, fontsize=8.3)
        chap = chapter_of_page.get(pno, "")
        if chap:
            chap = chap if font.text_length(chap, fontsize=8.3) < 300 else chap[:34] + "…"
            tw.append(fitz.Point(A4_W - MARGIN_X - font.text_length(chap, fontsize=8.3), HEADER_Y),
                      chap, font=font, fontsize=8.3)
        tw.write_text(page, color=GOLD)
        page.draw_line(fitz.Point(MARGIN_X, RULE_Y), fitz.Point(A4_W - MARGIN_X, RULE_Y), color=PALE, width=0.4)
        num = str(body_no)
        tw2 = fitz.TextWriter(page.rect)
        tw2.append(fitz.Point((A4_W - font.text_length(num, fontsize=9.2)) / 2, FOOTER_Y), num, font=font, fontsize=9.2)
        tw2.write_text(page, color=INK)


def check_source_pdf(source: Path, doc: fitz.Document) -> None:
    """直接从原始 Markdown 提取文字核对，独立于 HTML 转换器。"""
    def compact(text: str) -> str:
        return re.sub(r"\s+", "", text)

    markdown = source.read_text(encoding="utf-8")
    content = compact("".join(page.get_text(clip=fitz.Rect(0, 55, page.rect.width, page.rect.height - 50))
                              for page in doc))
    missing = []
    for line in markdown.splitlines():
        if not line.strip() or re.fullmatch(r"[| :\-]+", line):
            continue
        line = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", line)
        line = re.sub(r"^#{1,6}\s+|^>\s*|^\d+\.\s+|^-\s+", "", line)
        line = compact(html.unescape(line.replace("**", "").replace(chr(96), "").replace("|", "")))
        if line and line not in content:
            missing.append(line[:90])
    if missing:
        raise RuntimeError(f"{source.name}: PDF 丢失正文：{missing[:5]}")
    headings = re.findall(r"^#{2,6} (.+)$", markdown, re.M)
    outline = doc.get_toc()
    actual = [t for _, t, _ in outline if t not in ("封面", "目录", "卷首")]
    if actual != headings:
        raise RuntimeError(f"{source.name}: PDF 书签与原稿标题不一致")
    for _, title, page in outline:
        if title != "封面" and compact(title) not in compact(doc[page - 1].get_text()):
            raise RuntimeError(f"{source.name}: 书签错页：{title}")
    expected_links = set(re.findall(r"\[[^\]]+\]\((https?://[^)]+)\)", markdown))
    pdf_links = {link["uri"] for page in doc for link in page.get_links() if link.get("uri")}
    if expected_links - pdf_links:
        raise RuntimeError(f"{source.name}: PDF 丢失外部引用链接：{expected_links - pdf_links}")
    print(f"   全文逐行保留，{len(headings)} 个原稿标题及目录书签定位正确，{len(expected_links)} 个外部引用链接保留")


def build(book: Book) -> None:
    sections = book.sections()
    if not sections:
        raise SystemExit(f"{book.key}: 未装载到任何章节")
    today = dt.date.today().isoformat()
    with tempfile.TemporaryDirectory(prefix="ddj-pdf-") as tmpdir:
        tmp = Path(tmpdir)
        (tmp / "body.html").write_text(body_html(book, sections), encoding="utf-8")
        chrome_pdf(tmp / "body.html", tmp / "body.pdf")
        body = fitz.open(tmp / "body.pdf")
        outline = body.get_toc()                     # [[level, title, page1], …]
        starts = [(t, p) for lvl, t, p in outline if lvl == 1]
        if len(starts) != len(sections):
            raise RuntimeError(f"{book.key}: 书签一级条目 {len(starts)} ≠ 章节数 {len(sections)}")
        toc = [(sec.title, p, sec.is_part) for sec, (_, p) in zip(sections, starts)]
        (tmp / "front.html").write_text(front_html(book, toc, today), encoding="utf-8")
        chrome_pdf(tmp / "front.html", tmp / "front.pdf")
        front = fitz.open(tmp / "front.pdf")
        cover_png = tmp / "cover.png"
        book.cover(cover_png)
        doc = fitz.open()
        doc.insert_pdf(front)
        doc.insert_pdf(body)
        add_cover(doc, cover_png)
        first_body = 1 + front.page_count
        font = fitz.Font(fontfile=str(extract_songti(tmp)))
        chapter_of_page: dict[int, str] = {}
        cur, bounds = "", {p - 1: t for t, p in starts}
        guide_starts: dict[int, list[str]] = {}
        for title, page in starts:
            guide_starts.setdefault(page - 1, []).append(title)
        for i in range(body.page_count):
            if book.source:
                # 连续排版时，同页可能开始多章；页眉标注页首正在阅读的章节。
                here = guide_starts.get(i, [])
                header = cur
                if here:
                    hits = body[i].search_for(here[0])
                    if not cur or (hits and hits[0].y0 < 105):
                        header = here[0]
                    cur = here[-1]
                chapter_of_page[first_body + i] = header
                continue
            cur = bounds.get(i, cur)
            chapter_of_page[first_body + i] = cur
        stamp(doc, first_body, chapter_of_page, book.title, font)
        toc_page = next(p for lvl, title, p in front.get_toc() if lvl == 1 and title == "目录")
        doc.set_toc([[1, "封面", 1], [1, "目录", toc_page + 1]] +
                    [[lvl, t, p + first_body] for lvl, t, p in outline])
        doc.set_page_labels([{"startpage": 0, "prefix": "", "style": "r", "firstpagenum": 1},
                             {"startpage": first_body, "prefix": "", "style": "D", "firstpagenum": 1}])
        doc.set_metadata({"title": book.title, "author": "渡人渡己 · 道德经投资心法项目", "subject": book.subtitle,
                          "creationDate": fitz.get_pdf_now(), "modDate": fitz.get_pdf_now()})
        doc.subset_fonts()                      # 合并各页的字体子集，只留用到的字形
        doc.save(book.out, garbage=4, deflate=True)
        n_body, n_front = body.page_count, front.page_count
        body.close(); front.close(); doc.close()
    check = fitz.open(book.out)
    text_all = "".join(check[i].get_text() for i in range(check.page_count))
    probes = tuple(book.probes) + (sections[0].title[:8], sections[-1].title[:8])
    missing = [p for p in probes if p not in text_all]
    if missing:
        raise RuntimeError(f"{book.key}: 成书缺少 {missing}")
    for bad in ("<!--", "&lt;mark", "&lt;u&gt;", "返回总目录", "下一章 →", "下一篇 →"):
        if bad in text_all:
            raise RuntimeError(f"{book.key}: 成书含不应出现的「{bad}」")
    if book.source:
        check_source_pdf(book.source, check)
    print(f"✅ {book.out.name}：{book.out.stat().st_size:,} 字节｜{check.page_count} 页"
          f"（封面 1 + 前言 {n_front} + 正文 {n_body}）｜{len(sections)} 章｜书签 {len(check.get_toc())} 条｜自检通过")
    check.close()


def main() -> None:
    keys = sys.argv[1:] or list(BOOKS)
    for key in keys:
        if key not in BOOKS:
            raise SystemExit(f"未知书目：{key}（可选 {', '.join(BOOKS)}）")
        build(BOOKS[key])


if __name__ == "__main__":
    main()
