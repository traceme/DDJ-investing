#!/usr/bin/env python3
"""《读道德经悟投资心法》装配器（一书为源）。

onebook/book/00-总纲.md + 01.md … 81.md + 附录-*.md + Z-免责声明.md → 读道德经悟投资心法.md
- 每章 H1 降为 H2，H2 降为 H3；H1 之后自动插入 `### 原文`（王弼本逐字）。
- 行首 HTML 注释（编辑用的「吸收」清单）被剥掉。
用法：python3 onebook/assemble.py [--stats]
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOOK_DIR = ROOT / "onebook" / "book"
OUT = ROOT / "读道德经悟投资心法.md"
TITLE = "读道德经悟投资心法"
CN = "零一二三四五六七八九十"


def int2cn(n: int) -> str:
    if n <= 10:
        return CN[n]
    tens, ones = divmod(n, 10)
    return (CN[tens] if tens > 1 else "") + "十" + (CN[ones] if ones else "")


def ddj_chapters() -> dict[int, str]:
    text = (ROOT / "原文/道德经-王弼本.md").read_text(encoding="utf-8")
    out = {int(m.group(1)): m.group(2).strip() for m in re.finditer(r"^## 第(\d+)章\s*\n(.*?)(?=^## |\Z)", text, re.S | re.M)}
    assert len(out) == 81
    return out


def demote(text: str) -> str:
    text = re.sub(r"<!--.*?-->\s*", "", text, flags=re.S)
    text = re.sub(r"^## ", "### ", text, flags=re.M)
    text = re.sub(r"^# ", "## ", text, count=1, flags=re.M)
    return text.strip()


def chapter(n: int, ddj: dict[int, str]) -> str | None:
    p = BOOK_DIR / f"{n:02d}.md"
    if not p.exists():
        return None
    body = demote(p.read_text(encoding="utf-8"))
    head, rest = body.split("\n", 1)
    assert head.startswith(f"## 第{int2cn(n)}章 · "), f"{p.name} 标题应为「# 第{int2cn(n)}章 · …」，现为 {head}"
    orig = "### 原文\n\n> " + ddj[n].replace("\n", "\n> ")
    # 源稿里的「原文」块以王弼本为准重写（源稿写它是为了单看源稿也有原文；正文以底本为唯一标准）
    rest = re.sub(r"^### 原文\s*\n(?:>.*\n?)+\n*", "", rest.strip() + "\n", count=1, flags=re.M).strip()
    return f"{head}\n\n{orig}\n\n{rest}\n"


def main() -> None:
    ddj = ddj_chapters()
    parts = [f"# {TITLE}\n", demote((BOOK_DIR / "00-总纲.md").read_text(encoding="utf-8")) + "\n"]
    stats = []
    for n in range(1, 82):
        c = chapter(n, ddj)
        if c:
            parts.append(c)
            stats.append((n, len(re.sub(r"\s", "", c))))
    for p in sorted(BOOK_DIR.glob("附录-*.md")):
        parts.append(demote(p.read_text(encoding="utf-8")) + "\n")
    z = BOOK_DIR / "Z-免责声明.md"
    if z.exists():
        parts.append(demote(z.read_text(encoding="utf-8")) + "\n")
    doc = "\n".join(parts)
    OUT.write_text(doc, encoding="utf-8")
    sizes = [s for _, s in stats]
    print(f"写出 {OUT.name}：{len(re.sub(r'[\s]', '', doc)):,} 字；已写 {len(stats)}/81 章"
          + (f"，单章 {min(sizes):,}–{max(sizes):,} 字" if sizes else ""))
    if "--stats" in sys.argv:
        for n, s in stats:
            print(f"  第{n}章 {s:,} 字 ≈ {round(s / 300)} 分钟")


if __name__ == "__main__":
    main()
