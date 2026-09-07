#!/usr/bin/env python3
"""三本规则层书籍 → 阅读友好的 A4 PDF：
《道德经投资打法手册》(playbook)、《投资纪律总表》(catalog)、《道德经投资系统》(system)。

分工：
- Chrome headless 负责排版（宋体正文／黑体标题——标题用 Hiragino Sans GB 而非 PingFang：后者会被 Chrome 逐页以 Type 3 字形嵌入，体积膨胀十倍、表格跨页自动重复表头、行不跨页、
  标题不孤行），并用 --generate-pdf-document-outline 生成带页码的书签；
- PyMuPDF 负责装订：封面页、扉页与目录（目录页码来自 Chrome 书签）、每页页眉
  （左书名、右当前章节）与页脚页码、PDF 页码标签（前言罗马数字、正文阿拉伯数字）。

页眉页脚用宋体：构建时用 fontTools 从系统 Songti.ttc 抽出「Songti SC Regular」一个字面到
临时目录（PyMuPDF 不能直接用 TTC），随后以子集嵌入 PDF；仓库不含任何字体文件。

用法：
    python3 scripts/build_pdf.py                 # 三本都构建
    python3 scripts/build_pdf.py catalog         # 只构建一本（playbook / catalog / system）

依赖：Google Chrome、PyMuPDF (fitz)、fontTools、Pillow（封面）。
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
from pathlib import Path

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
INK, GREEN, GOLD, PALE = (0.21, 0.18, 0.15), (0.18, 0.38, 0.30), (0.69, 0.56, 0.26), (0.87, 0.82, 0.72)
COVER_BG = (246 / 255, 242 / 255, 231 / 255)

PDF_OUT = {
    "playbook": ROOT / "道德经投资打法手册.pdf",
    "catalog": ROOT / "投资纪律总表.pdf",
    "system": ROOT / "道德经投资系统.pdf",
}

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
.toc li .t { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 84%; }
.toc li .d { flex: 1; border-bottom: 0.6pt dotted #b9ad8f; margin: 0 0.5em; min-width: 1.2em;
             transform: translateY(-0.3em); }
.toc li .n { font-family: "Hiragino Sans GB", "PingFang SC", sans-serif; color: #2f624d; font-variant-numeric: tabular-nums; }
.toc li.part { margin-top: 0.9em; }
.toc li.part .t { font-family: "Hiragino Sans GB", "PingFang SC", sans-serif; font-weight: 600; color: #2f624d; }
.toc .hint { color: #8a7d62; font-size: 9.5pt; margin-top: 2em; }
"""

def html_head(title: str) -> str:
    return ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"/>'
            f'<title>{html.escape(title)}</title><style>{CSS}</style></head><body>')


# --------------------------------------------------------------------------- #
# Chrome：排版 → PDF（Chrome 打印完常常不退出，写完文件即结束进程）
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
        if len(plain) <= 14 and " " not in plain.strip():
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


def body_html(ed: B.Edition, sections: list[B.Section]) -> str:
    parts = [html_head(ed.title)]
    for sec in sections:
        cls = "chapter part" if sec.is_part else "chapter"
        parts.append(f'<section class="{cls}"><h1>{B.inline(sec.title)}</h1>{B.render_blocks(sec.lines)}</section>')
    parts.append("</body></html>")
    return mark_wide_tables("".join(parts))


def front_html(ed: B.Edition, toc: list[tuple[str, int, bool]], today: str) -> str:
    items = "".join(
        f'<li class="{"part" if is_part else ""}"><span class="t">{html.escape(t)}</span>'
        f'<span class="d"></span><span class="n">{p}</span></li>'
        for t, p, is_part in toc
    )
    return (html_head(ed.title) +
            f'<section class="title"><div class="eyebrow">{html.escape(ed.eyebrow)}</div>'
            f'<h1>{html.escape(ed.title)}</h1><div class="sub">{html.escape(ed.subtitle)}</div>'
            f'<div class="cap">{html.escape(ed.cover_caption)}</div>'
            f'<div class="meta">渡人渡己 · 道德经投资心法项目<br/>PDF 版　{today}　由仓库脚本从 Markdown 生成<br/>'
            f'本书是方法论，不是荐股；示例参数来自归一为 100 单位的案例账户</div></section>'
            f'<section class="toc"><h1>目录</h1><ol>{items}</ol>'
            f'<p class="hint">页码为正文页码（页脚所示）。阅读器侧栏的书签含各章之下的小节，可直接跳转；'
            f'每页页眉右侧为当前章节。</p></section></body></html>')


# --------------------------------------------------------------------------- #
# 装订：封面 + 扉页目录 + 正文，页眉页脚，页码标签，书签
# --------------------------------------------------------------------------- #

def extract_songti(tmp: Path) -> Path:
    out = tmp / "SongtiSC-Regular.ttf"
    for face in TTCollection(str(SONGTI_TTC)).fonts:
        if (face["name"].getDebugName(4) or "") == "Songti SC Regular":
            face.save(str(out))
            return out
    raise SystemExit("Songti.ttc 中未找到 Songti SC Regular")


def add_cover(doc: fitz.Document, png: Path) -> None:
    page = doc.new_page(pno=0, width=A4_W, height=A4_H)
    page.draw_rect(page.rect, color=None, fill=COVER_BG)
    img_w, img_h = 1600, 2400                       # build_cover 的尺寸
    scale = min(A4_W / img_w, A4_H / img_h)
    w, h = img_w * scale, img_h * scale
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


def build(key: str) -> None:
    ed = B.EDITIONS[key]
    out = PDF_OUT[key]
    if not ed.source.exists():
        raise SystemExit(f"缺少源文件：{ed.source}")
    sections = B.parse_document(ed.source, ed.split_h3)
    today = dt.date.today().isoformat()
    with tempfile.TemporaryDirectory(prefix="ddj-pdf-") as tmpdir:
        tmp = Path(tmpdir)
        # 1. 正文
        (tmp / "body.html").write_text(body_html(ed, sections), encoding="utf-8")
        chrome_pdf(tmp / "body.html", tmp / "body.pdf")
        body = fitz.open(tmp / "body.pdf")
        outline = body.get_toc()                     # [[level, title, page1], …]
        starts = [(t, p) for lvl, t, p in outline if lvl == 1]
        if len(starts) != len(sections):
            raise RuntimeError(f"{key}: 书签一级条目 {len(starts)} ≠ 章节数 {len(sections)}")
        toc = [(sec.title, p, sec.is_part) for sec, (_, p) in zip(sections, starts)]
        # 2. 扉页 + 目录
        (tmp / "front.html").write_text(front_html(ed, toc, today), encoding="utf-8")
        chrome_pdf(tmp / "front.html", tmp / "front.pdf")
        front = fitz.open(tmp / "front.pdf")
        # 3. 封面
        cover_png = tmp / "cover.png"
        B.build_cover(cover_png, ed)
        # 4. 合并
        doc = fitz.open()
        doc.insert_pdf(front)
        doc.insert_pdf(body)
        add_cover(doc, cover_png)
        first_body = 1 + front.page_count
        # 5. 页眉页脚
        font = fitz.Font(fontfile=str(extract_songti(tmp)))
        chapter_of_page: dict[int, str] = {}
        cur = ""
        bounds = {p - 1: t for t, p in starts}
        for i in range(body.page_count):
            cur = bounds.get(i, cur)
            chapter_of_page[first_body + i] = cur
        stamp(doc, first_body, chapter_of_page, ed.title, font)
        # 6. 书签与页码标签
        new_toc = [[1, "封面", 1], [1, "目录", 2]]
        new_toc += [[lvl, t, p + first_body] for lvl, t, p in outline]
        doc.set_toc(new_toc)
        doc.set_page_labels([{"startpage": 0, "prefix": "", "style": "r", "firstpagenum": 1},
                             {"startpage": first_body, "prefix": "", "style": "D", "firstpagenum": 1}])
        doc.set_metadata({"title": ed.title, "author": "渡人渡己 · 道德经投资心法项目",
                          "subject": ed.subtitle, "creationDate": fitz.get_pdf_now(), "modDate": fitz.get_pdf_now()})
        doc.subset_fonts()                      # 合并各页的字体子集，只留用到的字形
        doc.save(out, garbage=4, deflate=True)
        n_body, n_front = body.page_count, front.page_count
        body.close(); front.close(); doc.close()
    # 7. 自检
    check = fitz.open(out)
    toc_l1 = [t for lvl, t, _ in check.get_toc() if lvl == 1]
    probes = {"catalog": ("C01-001", "C18-022", "铁律"), "system": ("宪十二", "C01-001", "R18.20"),
              "playbook": ("R4.6", "案例账户", "附录 B")}[key]
    text_all = "".join(check[i].get_text() for i in range(check.page_count))
    missing = [p for p in probes if p not in text_all]
    if missing:
        raise RuntimeError(f"{key}: 成书缺少 {missing}")
    print(f"✅ {out.name}：{out.stat().st_size:,} 字节｜{check.page_count} 页（封面 1 + 前言 {n_front} + 正文 {n_body}）"
          f"｜书签 {len(check.get_toc())} 条（一级 {len(toc_l1) - 2} 章）｜自检通过")
    check.close()


def main() -> None:
    keys = sys.argv[1:] or list(PDF_OUT)
    for key in keys:
        if key not in PDF_OUT:
            raise SystemExit(f"未知版本：{key}（可选 {', '.join(PDF_OUT)}）")
        build(key)


if __name__ == "__main__":
    main()
