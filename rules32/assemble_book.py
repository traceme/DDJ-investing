#!/usr/bin/env python3
"""装配《投资三十二条军规》及完整来源索引；--check 不写文件。"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent
OUTPUT = ROOT / "投资三十二条军规.md"


def load_mapping():
    return json.loads((HERE / "data/归并映射.json").read_text(encoding="utf-8"))


def demote(text):
    return re.sub(r"^(#{1,5}) ", r"#\1 ", text.strip(), flags=re.M)


def assemble():
    data = load_mapping()
    parts = ["# 投资三十二条军规", demote((HERE / "book/00-卷首.md").read_text())]
    parts.append("## 三十二条速查\n\n每组四条。正文提供操作指南；准备下单时先查资金、证据、价格、风险与退路五项。")
    group = None
    for r in data["rules"]:
        if group != r["group"]:
            group = r["group"]
            parts.append(f"### {group}\n\n| 条 | 军规 | 负责的问题 |\n|---|---|---|")
        anchor = f'第{r["number"]:02d}条-·-{r["title"]}'
        link = f'[{r["title"]}](/投资三十二条军规.md?id={anchor})'
        parts[-1] += f'\n| {r["number"]:02d} | {link} | {r["scope"]} |'
    for r in data["rules"]:
        n = r["number"]
        text = (HERE / f"book/{n:02d}.md").read_text(encoding="utf-8")
        parts.append(demote(text))
        parts.append(f'本条归并{len(r["disciplines"])}条原纪律，来源编号见附录A第{n:02d}条；{r["scope"]}。')
    for filename in ("33-案例.md", "34-操作卡.md", "35-编者说明.md"):
        parts.append(demote((HERE / "book" / filename).read_text(encoding="utf-8")))
    parts.append("## 附录A · 360条原纪律的归并索引\n\n每个C编号只登记一个主归属，共360条。这里的归属表示决策问题被吸收；不同数字与路线的取舍见编者说明。原句及各处摘引可在《投资纪律总表》中按编号查找。")
    for r in data["rules"]:
        parts.append(f'### 第{r["number"]:02d}条 · {r["title"]}\n\n吸收范围：{r["scope"]}。\n\n原纪律：' + "、".join(r["disciplines"]) + "。")
    parts.append("## 附录B · 原则、执行规则与训练的归属\n\n本附录登记原则区23条、手册54条R规则、系统20条R18规则、心性指南36条T练习及量化设计19项Q-C问题。合计152个补充编号均有归属。它们提供理由、执行结构或边界，并不把专门训练的全部参数改成人人必做的军规。\n\nP编号查纪律总表原则区，R编号查手册及投资系统，T编号查心性指南，Q-C编号查量化设计第四节。")
    for r in data["rules"]:
        ids = [k for k, n in data["supplementary"].items() if n == r["number"]]
        note = "补充来源：" + "、".join(ids) + "。" if ids else "本条的具体法源已列附录A，不另增加补充条目。"
        parts.append(f'### 第{r["number"]:02d}条 · {r["title"]}\n\n' + note)
    parts.append("### 版本与核对\n\n本版编写日期：2026年9月12日。源文件指纹保存在本项目的归并映射中；更改来源后须重新审阅归属，再构建电子书。正文三十二条均有军规、理由、四步操作指南、触发处置和百字以内建议。案例算术、完整编号、EPUB目录与PDF正文另行校验。")
    return "\n\n".join(parts).strip() + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    text = assemble()
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != text:
            raise SystemExit("成稿与分章／映射不一致，请重新装配")
        print("装配一致性通过")
    else:
        OUTPUT.write_text(text, encoding="utf-8")
        size = len(re.sub(r"\s", "", text))
        print(f"已装配：{OUTPUT.name}，{size:,}个非空白字符")


if __name__ == "__main__":
    main()
