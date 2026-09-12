#!/usr/bin/env python3
"""检查来源覆盖、正文结构、算术与最终 EPUB / PDF 的完整性。"""
from __future__ import annotations

import argparse
import hashlib
import json
import posixpath
import re
import sys
import zipfile
from collections import Counter
from decimal import Decimal as D
from xml.etree import ElementTree as ET

from assemble_book import HERE, ROOT, OUTPUT, assemble, load_mapping


def require(condition, message):
    if not condition:
        raise ValueError(message)


def compact(text):
    return re.sub(r"\s+", "", text)


def visible_lines(text):
    """独立于 EPUB 转换器提取应当保留的文字，用于发现转换遗漏。"""
    for line in text.splitlines():
        if not line.strip() or re.fullmatch(r"[| :\-]+", line):
            continue
        line = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", line)
        line = re.sub(r"^#{1,6}\s+|^>\s*|^\d+\.\s+|^-\s+", "", line)
        line = line.replace("**", "").replace(chr(96), "").replace("|", "")
        if line.strip():
            yield compact(line)


def check_text():
    data = load_mapping()
    rules = data["rules"]
    require([r["number"] for r in rules] == list(range(1, 33)), "军规必须恰好01—32")
    catalog = json.loads((ROOT / "system/data/纪律总表.json").read_text())
    source_ids = {d["id"] for d in catalog}
    assigned = [i for r in rules for i in r["disciplines"]]
    counts = Counter(assigned)
    require(set(counts) == source_ids and all(n == 1 for n in counts.values()), "360条主归属遗漏或重复")
    require(len(source_ids) == 360, "源目录规模变化，需重新编辑")
    require(len({r["group"] for r in rules}) == 8, "须有八组")
    for path, digest in data["sources"].items():
        require(hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == digest, f"来源已变，请重审映射：{path}")
    rbase = set(re.findall(r"^- (R\d+\.\d+)\b", (ROOT / "playbook/BOOK_SPEC.md").read_text(), re.M))
    rnew = set(re.findall(r"^\| (R18\.\d+) \|", (ROOT / "system/SYSTEM_SPEC.md").read_text(), re.M))
    tids = set(re.findall(r"^\| (T\d+\.\d+)\b", (ROOT / "mindset/BOOK_SPEC.md").read_text(), re.M))
    pids = {p["id"] for p in json.loads((ROOT / "system/data/原则区.json").read_text())["principles"]}
    qids = set(re.findall(r"^\| (Q-C\d+) \|", (ROOT / "股票量化投资系统.md").read_text(), re.M))
    require(tuple(map(len, (rbase, rnew, tids, pids, qids))) == (54, 20, 36, 23, 19), "补充来源的规模变化")
    extra = data["supplementary"]
    require(set(extra) == rbase | rnew | tids | pids | qids, "补充来源归属不完整")
    require(all(1 <= n <= 32 for n in extra.values()), "补充归属编号越界")
    lengths = []
    for r in rules:
        n = r["number"]
        text = (HERE / f"book/{n:02d}.md").read_text()
        require(text.startswith(f'# 第{n:02d}条 · {r["title"]}\n'), f"标题不一致：{n}")
        headings = re.findall(r"^## (.+)$", text, re.M)
        require(headings == ["军规", "为什么", "操作指南", "触发与处置", "实操建议"], f"章节结构缺失：{n}")
        guide = text.split("## 操作指南\n", 1)[1].split("## 触发与处置", 1)[0]
        require(re.findall(r"^(\d)\. ", guide, re.M) == ["1", "2", "3", "4"], f"操作步骤不全：{n}")
        advice = compact(text.split("## 实操建议\n", 1)[1])
        require(0 < len(advice) < 100, f"建议超过百字：{n}")
        size = len(compact(text))
        require(550 <= size <= 1100, f"第{n:02d}条长度{size}不在550—1100内")
        require(bool(r["disciplines"]), f"军规没有法源：{n}")
        lengths.append(size)
    assembled = assemble()
    require(OUTPUT.exists() and OUTPUT.read_text() == assembled, "成稿与源文件不一致")
    require(len(re.findall(r"^## 第\d{2}条 · ", assembled, re.M)) == 32, "成稿条目数量错误")
    cited = set(re.findall(r"C\d{2}-\d{3}", assembled))
    require(cited == source_ids, "成稿原纪律编号有遗漏或伪造")
    for bad in ("TODO", "TBD", "待补写", "150万", "1.5M", "discovery-invest"):
        require(bad not in assembled, f"正文含不应出现的文本：{bad}")
    case = (HERE / "book/33-案例.md").read_text()
    shares = D("1.5") / D("1") + D("1.5") / D("0.8")
    proceeds = shares * D("0.7")
    loss = D("3") - proceeds
    net_loss = loss + D("0.02")
    for result in (shares, proceeds, loss, net_loss, D("100") - net_loss, D("60") - net_loss):
        require(str(result) in case, f"案例遗漏或错写演算结果：{result}")
    require((D("1.25") - D("1")) / D("1.25") == D("0.20"), "安全边际算术错误")
    weighted = D(".25") * D(".60") + D(".5") * D("1.25") + D(".25") * D("1.80")
    require(format(weighted.normalize(), "f") in case and weighted == D("1.225"), "三情景算术错误")
    print(f"正文通过：32条，长度{min(lengths)}—{max(lengths)}；360/360唯一主归属；54＋20＋36＋23＋19补充来源；案例算术正确")
    return assembled


def check_artifacts(source):
    epub = ROOT / "投资三十二条军规.epub"
    pdf = ROOT / "投资三十二条军规.pdf"
    with zipfile.ZipFile(epub) as z:
        ns = {"opf": "http://www.idpf.org/2007/opf"}
        opf = ET.fromstring(z.read("EPUB/content.opf"))
        manifest = {e.attrib["id"]: e.attrib["href"] for e in opf.findall("opf:manifest/opf:item", ns)}
        spine = [
            manifest[e.attrib["idref"]] for e in opf.findall("opf:spine/opf:itemref", ns)
        ]
        texts = []
        chapter_titles = []
        for href in spine:
            doc = ET.fromstring(z.read("EPUB/" + href))
            texts.append("".join(doc.itertext()))
            for node in doc.iter():
                if node.tag.endswith("}h1") and re.match(r"第\d{2}条 · ", "".join(node.itertext())):
                    chapter_titles.append("".join(node.itertext()))
        joined = compact("".join(texts))
        require(len(chapter_titles) == 32, "EPUB中正文军规数量错误")
        for name in z.namelist():
            if not name.endswith(".xhtml"):
                continue
            for a in ET.fromstring(z.read(name)).iter("{http://www.w3.org/1999/xhtml}a"):
                href = a.attrib.get("href", "")
                if not href or ":" in href:
                    continue
                filepart, _, anchor = href.partition("#")
                target = posixpath.normpath(posixpath.join(posixpath.dirname(name), filepart)) if filepart else name
                require(target in z.namelist(), f"EPUB链接不存在：{name}→{href}")
                if anchor:
                    ids = {e.get("id") for e in ET.fromstring(z.read(target)).iter()}
                    require(anchor in ids, f"EPUB锚点不存在：{name}→{href}")
        for line in visible_lines(source):
            require(line in joined, f"EPUB丢失文字：{line[:90]}")
    import fitz
    doc = fitz.open(pdf)
    # 排除跨页插入的页眉和页脚，再核验完整段落。
    pdf_text = compact("".join(p.get_text(clip=fitz.Rect(0, 55, p.rect.width, p.rect.height - 50)) for p in doc))
    missing = [line for line in visible_lines(source) if line not in pdf_text]
    require(not missing, f"PDF丢失文字：{missing[:4]}")
    numbered = [(t, p) for level, t, p in doc.get_toc() if level == 1 and re.match(r"第\d{2}条 · ", t)]
    require(len(numbered) == 32, "PDF一级书签未覆盖32条正文")
    for title, page in numbered:
        require(compact(title) in compact(doc[page - 1].get_text()), f"书签错页：{title}")
    print(f"成书通过：EPUB全部正文逐行保留、目录与链接有效；PDF {len(doc)}页、全文逐行保留、32条书签定位正确")
    doc.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", action="store_true")
    args = parser.parse_args()
    try:
        source = check_text()
        if args.artifacts:
            check_artifacts(source)
    except (ValueError, FileNotFoundError) as exc:
        print(f"校验失败：{exc}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
