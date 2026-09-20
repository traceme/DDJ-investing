#!/usr/bin/env python3
"""校验《读道德经悟投资心法》（onebook/BOOK_SPEC.md §2）。

检查：结构与块序；原文逐字；<mark> 引文逐字出自本章（或注明章号的章）；「三眼说：「…」」逐字出自三眼笔记；
「原书的实操建议：「…」」逐字出自该章两本 81 章书；金冰不得逐字引用（只许「金冰说，大意是」）；
不得出现编号（Cxx-nnn／Rx.y／Tx.y／宪N）；通用 PII；单章长度；素材吸收进度（信息）。
用法：python3 onebook/validate.py [--strict]   # strict：81 章齐全、吸收表全覆盖才通过
"""
from __future__ import annotations

import glob
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import assemble as A  # noqa: E402

ROOT = A.ROOT
BOOK = A.OUT
BLOCKS = ["原文", "心法", "案例", "纪律", "实操", "练习", "研究与努力方向"]
MIN_CHAPTER, MAX_CHAPTER, WARN_CHAPTER = 2_500, 12_000, 9_000
PII = [
    (r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "疑似邮箱地址"),
    (r"\d{3,}\s*万", "疑似真实账户金额（三位数以上的「万」）"),
    (r"[$￥]\s?\d{1,3}(?:,\d{3})+", "疑似真实金额（带千分位）"),
    (r"\b\d+(?:\.\d+)?\s*[MK]\b", "疑似真实金额（M／K 简写）"),
    (r"\$\s?\d", "美元价格（本书只用案例账户单位）"),
]
IDS = [(r"\bC\d\d-\d{3}\b", "纪律编号"), (r"\bR\d+\.\d+\b", "规则编号"), (r"\bT\d+\.\d+\b", "练习编号"),
       (r"宪[一二三四五六七八九十]+", "宪法编号"), (r"\bS[0-4]\b", "状态编号"), (r"\bP[0-8]\b", "仓位状态编号")]


def nchars(s: str) -> int:
    return len(re.sub(r"\s", "", s))


def norm(s: str) -> str:
    return re.sub(r"\s+", "", s).replace("“", "\"").replace("”", "\"").replace("‘", "'").replace("’", "'")


def section(text: str, heading: str, level: str = "### ") -> str:
    m = re.search(r"^" + re.escape(level + heading) + r"\s*\n(.*?)(?=^" + re.escape(level) + r"|\Z)", text, re.S | re.M)
    return m.group(1).strip() if m else ""


def main() -> int:
    strict = "--strict" in sys.argv
    text = BOOK.read_text(encoding="utf-8")
    problems, warn = [], []
    ddj = A.ddj_chapters()

    if re.findall(r"^# (.+)$", text, re.M) != [A.TITLE]:
        problems.append("H1 应恰好一个且为书名")
    sanyan = norm("".join(Path(f).read_text(encoding="utf-8") for f in glob.glob(str(ROOT / "thethirdeye/第*章.md"))))
    sanyan = re.sub(r"<.*?>", "", sanyan)

    chunks = re.split(r"^## ", text, flags=re.M)[1:]
    chapters = {}
    for ch in chunks:
        m = re.match(r"第([一二三四五六七八九十]+)章 · ", ch)
        if m:
            chapters[A.CN.index(m.group(1)) if len(m.group(1)) == 1 else _cn(m.group(1))] = ch
    if strict and sorted(chapters) != list(range(1, 82)):
        problems.append(f"章不齐：缺 {sorted(set(range(1, 82)) - set(chapters))}")

    for n, body in sorted(chapters.items()):
        tag = f"第{n}章"
        heads = re.findall(r"^### (.+)$", body, re.M)
        if [h for h in heads if h not in BLOCKS]:
            problems.append(f"{tag} 未知的块：{[h for h in heads if h not in BLOCKS]}")
        order = [BLOCKS.index(h) for h in heads if h in BLOCKS]
        if order != sorted(order) or len(order) != len(set(order)):
            problems.append(f"{tag} 块序错误：{heads}")
        if section(body, "原文").replace("> ", "").strip() != ddj[n]:
            problems.append(f"{tag} 原文与王弼本不一致")
        for h in ("心法", "纪律", "实操"):
            if not section(body, h):
                problems.append(f"{tag} 缺「{h}」块")
        size = nchars(body)
        if size < MIN_CHAPTER or size > MAX_CHAPTER:
            problems.append(f"{tag} {size} 字，应在 {MIN_CHAPTER}–{MAX_CHAPTER}")
        elif size > WARN_CHAPTER:
            warn.append(f"{tag} {size} 字，可分两天读")
        prose = body[body.index("### 心法"):] if "### 心法" in body else body
        for m in re.finditer(r"<mark>(.*?)</mark>", prose, re.S):
            q = norm(m.group(1))
            if q in norm(ddj[n]):
                continue
            ctx = prose[max(0, m.start() - 30):m.start()]
            k = re.search(r"《道德经》第([一二三四五六七八九十]+)章", ctx)
            if k and q in norm(ddj[_cn(k.group(1))]):
                continue
            problems.append(f"{tag} <mark> 引文不在本章原文（且未注章号）：{m.group(1)}")
        for m in re.finditer(r"三眼说：「([^」]+)」", prose):
            if norm(m.group(1)) not in sanyan:
                problems.append(f"{tag} 三眼引文与笔记不一致：{m.group(1)}")
        if re.search(r"金冰说：「", prose):
            problems.append(f"{tag} 金冰只许转述（金冰说，大意是），不得逐字引用")
        own = norm(section((ROOT / f"chapters/第{n:02d}章.md").read_text(encoding="utf-8"), "实操建议", "## ")
                   + (ROOT / f"codex/第{n:02d}章.md").read_text(encoding="utf-8"))
        for m in re.finditer(r"原书的实操建议：「([^」]+)」", prose):
            if norm(m.group(1)) not in own:
                problems.append(f"{tag} 实操建议引文与原书不一致：{m.group(1)[:30]}")
        for pat, why in IDS:
            for m in re.finditer(pat, body):
                problems.append(f"{tag} 出现{why}（本书不用编号）：{m.group(0)}")
        for pat, why in PII:
            for m in re.finditer(pat, body):
                problems.append(f"{tag} {why}：{m.group(0)}")

    # 附录：引文、编号、PII 同样受检
    for ch in chunks:
        if not ch.startswith("附录"):
            continue
        tag = ch.splitlines()[0].strip()
        for m in re.finditer(r"三眼说：「([^」]+)」", ch):
            if norm(m.group(1)) not in sanyan:
                problems.append(f"{tag} 三眼引文与笔记不一致：{m.group(1)}")
        if re.search(r"金冰说：「", ch):
            problems.append(f"{tag} 金冰只许转述（金冰说，大意是），不得逐字引用")
        for m in re.finditer(r"<mark>(.*?)</mark>", ch, re.S):
            q = norm(m.group(1))
            ctx = ch[max(0, m.start() - 30):m.start()]
            k = re.search(r"《道德经》第([一二三四五六七八九十]+)章", ctx)
            if not (k and q in norm(ddj[_cn(k.group(1))])):
                problems.append(f"{tag} <mark> 引文未注章号或不在所注章：{m.group(1)}")
        for pat, why in IDS + PII:
            for m in re.finditer(pat, ch):
                problems.append(f"{tag} {why}：{m.group(0)}")

    # 总纲
    zg = text.split("\n## ", 2)[1] if "\n## 总纲" in text else ""
    if len(re.findall(r"^- \*\*[^*]+。\*\*", section(zg, "账户的十二条根本规矩"), re.M)) != 12:
        problems.append("总纲：根本规矩应为十二条加粗条目")
    if len(re.findall(r"^\| \*\*", section(zg, "账户的五种状态"), re.M)) != 5:
        problems.append("总纲：账户状态应为五行")
    for pat, why in IDS + PII:
        for m in re.finditer(pat, zg):
            problems.append(f"总纲 {why}：{m.group(0)}")

    # 吸收进度（编辑用）
    absorbed = set()
    for p in sorted(A.BOOK_DIR.glob("[0-9][0-9].md")) + sorted(A.BOOK_DIR.glob("附录-*.md")):
        m = re.search(r"<!--\s*吸收：(.*?)-->", p.read_text(encoding="utf-8"), re.S)
        if m:
            absorbed |= set(m.group(1).split())
        elif p.stem.isdigit():
            warn.append(f"{p.name} 缺「吸收」注释")
    items = json.load(open(ROOT / "system/data/纪律总表.json", encoding="utf-8"))
    universe = {it["id"] for it in items} | {f"三眼{i}" for i in range(1, 152)} | {f"金{i}" for i in range(1, 73)} \
        | {f"道{i}" for i in range(1, 82)} | {f"Codex{i}" for i in range(1, 82)} | {f"军规{i:02d}" for i in range(1, 33)}
    left = universe - absorbed
    msg = f"素材吸收：{len(universe) - len(left)}/{len(universe)}（纪律 {sum(1 for x in absorbed if re.fullmatch(r'C\d\d-\d{3}', x))}/360，三眼 {sum(1 for x in absorbed if x.startswith('三眼'))}/151，金 {sum(1 for x in absorbed if x.startswith('金'))}/72）"
    (problems if strict and left else warn).append(msg)

    for w in warn:
        print("提示：", w)
    for p in problems:
        print("问题：", p)
    print(f"{'通过' if not problems else '失败'}：{len(problems)} 个问题，{len(warn)} 个提示；已写 {len(chapters)} 章，全书 {nchars(text):,} 字")
    return 1 if problems else 0


def _cn(s: str) -> int:
    s = s.replace("零", "")
    if s == "十":
        return 10
    if "十" in s:
        a, b = s.split("十")
        return (A.CN.index(a) if a else 1) * 10 + (A.CN.index(b) if b else 0)
    return A.CN.index(s)


if __name__ == "__main__":
    sys.exit(main())
