#!/usr/bin/env python3
"""Validate the manuscript, not investment merit; standard-library only."""

import argparse
import hashlib
import json
import math
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
BOOK = ROOT / "价值投资者投资体系与交易系统.md"


def validate(body):
    checks = []

    def check(label, condition):
        if not condition:
            raise ValueError(label)
        checks.append(label)

    def near(label, actual, expected, tolerance=0.005):
        check(label, math.isfinite(actual) and abs(actual - expected) < tolerance)

    def section(number):
        match = re.search(rf"^### {re.escape(number)} .+?(?=^### |^<a id=|\Z)", body, re.M | re.S)
        check("section " + number, match is not None)
        return match.group()

    def stated(number, phrase, actual):
        match = re.search(phrase + r"[^\d\n]*([\d,.]+)", section(number))
        check("number present: " + phrase, match is not None)
        near("prose arithmetic: " + phrase, float(match[1].replace(",", "")), actual)

    def table(header):
        lines = body.splitlines()
        start = next((i for i, line in enumerate(lines) if line.startswith("| " + header + " |")), None)
        check("table present: " + header, start is not None)
        rows = []
        columns = len(lines[start].strip("|").split("|"))
        for line in lines[start + 2:]:
            if not line.startswith("|"):
                break
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            check("table columns: " + cells[0], len(cells) == columns)
            rows.append(cells)
        check("table row keys: " + header, len({row[0] for row in rows}) == len(rows))
        return rows

    def number(cell):
        return float(cell.replace(",", "").replace("%", "").strip())

    check("title", body.startswith("# 价值投资者投资体系与交易系统\n"))
    check("revision version", "增订版 v1.1" in body and "完整初稿" not in body)
    check("18 chapters", len(re.findall(r"^## 第[一二三四五六七八九十]+章：", body, re.M)) == 18)
    check("5 appendices", len(re.findall(r"^## 附录[一二三四五]：", body, re.M)) == 5)
    check("balanced code fences", len(re.findall(r"^```", body, re.M)) % 2 == 0)
    check("no trailing whitespace", all(line == line.rstrip() for line in body.splitlines()))
    check("no unfinished prose", not re.search(r"TODO|TBD|待撰写|此处省略|后续补写", body))
    anchors = re.findall(r'<a id="([^"]+)"></a>', body)
    check("23 unique anchors", len(anchors) == len(set(anchors)) == 23)
    for target in re.findall(r"\]\(([^)]+)\)", body):
        if target.startswith("#"):
            check("TOC " + target, target[1:] in anchors)
        elif target.startswith("/"):
            check("local link " + target, (ROOT / target.lstrip("/")).is_file())

    # These guardrails check presence and traceability, not the truth of a thesis.
    for part, phrase in {
        "1.4": "同一笔钱不能同时抵三项需要", "1.5": "生活与资本",
        "3.5": "原则说明为什么", "6.7": "重要程度不能靠计票",
        "6.8": "不猜测谁在操纵", "7.5": "不采用原语料中",
        "8.7": "等待记录写四行", "11.5": "不延迟已核实的必要退出",
        "12.5": "延期代价", "13.10": "互斥的失败路径",
        "14.5": "不为“日损”凑删除数量", "16.5": "由本人明确批准后才生效",
        "16.6": "没有样本写“暂无证据”", "16.7": "不预测通胀",
        "18.1": "不等于交易代理", "18.2": "风险提醒不能一起关掉",
        "18.3": "心情变好不能绕过它", "18.4": "不要求翻倍就取回本金",
    }.items():
        check("revision safeguard " + part, phrase in section(part))
    for heading in ["生活用途与资本边界卡", "反证与里程碑台账",
                    "四张“如果—那么”行为卡", "规则冲突与变更卡"]:
        check("revision template " + heading, "### " + heading in body)
    for header, count in [("环节", 6), ("原命题", 3), ("事前过程与事后结果", 4),
                          ("放在哪里", 4), ("如果出现这个触发", 4), ("提炼主题", 11)]:
        check("revision table coverage " + header, len(table(header)) == count)
    catalog = json.loads((ROOT / "system/data/纪律总表.json").read_text(encoding="utf-8"))
    ids = {row["id"] for row in catalog}
    check("catalog core coverage", len(catalog) == len(ids) == 360)
    check("catalog conflict count", sum(bool(row.get("conflict")) for row in catalog) == 47)
    for rule_id in sorted(set(re.findall(r"C\d{2}-\d{3}", body))):
        check("provenance discipline " + rule_id, rule_id in ids)
    provenance = (ROOT / "value-investing-book/增订研读与取舍.md").read_text(encoding="utf-8")
    for target in re.findall(r"\]\((/[^)]+)\)", provenance):
        check("provenance link " + target, (ROOT / target.lstrip("/")).is_file())
    source_hashes = re.findall(r"^\| ([^|]+) \| ([a-f0-9]{64}) \|$", provenance, re.M)
    check("five source snapshots", len(source_hashes) == 5)
    for name, digest in source_hashes:
        check("source unchanged " + name, hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest)

    canonical = (ROOT / "原文/道德经-王弼本.md").read_text(encoding="utf-8")
    chapters = {int(n): text for n, text in re.findall(r"^## 第(\d+)章\n(.*?)(?=^## |\Z)", canonical, re.M | re.S)}
    numerals = {"四十八": 48, "二十二": 22, "三十三": 33, "四十四": 44}
    quotes = re.findall(r"^> (.+)\n>\n> ——《道德经》第([^章]+)章", body, re.M)
    check("four attributed scripture excerpts", len(quotes) == 4)
    for quote, chapter in quotes:
        check("scripture in named chapter " + chapter, quote in chapters[numerals[chapter]])

    registry = {row[0]: row[1:] for row in table("编号")}
    expected = {
        "DD15": "实际峰值回撤 >= 15%", "DD25": "实际峰值回撤 >= 25%",
        "DD35": "实际峰值回撤 >= 35%", "DD50": "实际峰值回撤 >= 50%",
        "ST40": "指定情景下峰值回撤 > 40%", "LC30": "保守损失台账占用 >= 30单位",
        "LC40": "保守损失台账占用 >= 40单位", "SC20": "单一发行人市值占当前净值 > 20%",
    }
    check("approved registry coverage", set(registry) == set(expected))
    for key, condition in expected.items():
        check("approved threshold " + key, registry[key][0] == condition and registry[key][-1] == "已批准")
    actions = {
        "DD15": "核验贡献者、共同风险和资料时效", "DD25": "暂停增加整体风险",
        "DD35": "启动组合降风险评审与处置计划", "DD50": "记录失守，停止新增风险并评估体系",
        "ST40": "不通过压力检查，禁止据此新增风险", "LC30": "暂停扩大整体风险，复核共同错误",
        "LC40": "停止新增风险，重新审议主动投资方式", "SC20": "强制集中度评审，不自动卖出",
    }
    for key, action in actions.items():
        check("approved action unchanged " + key, registry[key][1] == action)
    for text in ["集中股票投资无法保证回撤绝不超过50%", "本书没有重新调研公司",
                 "当前无法满足压力线", "价格反弹不自动解除限制", "不构成任何下单授权",
                 "流程建议", "不需要再次批准"]:
        check("boundary marker " + text, text in body)
    check("no stale approval gate", not re.search(r"均待批准|本书没有替读者完成这一接受决定|须先批准的响应机制", body))

    for row in table("五家公司期末价值倍数"):
        near("equal weight scenario " + row[0], sum(map(float, row[0].split("、"))) / 5, number(row[1].replace(" 倍", "")))
    stated("2.1", "≈", (10 ** .2 - 1) * 100)
    stated("2.2", "股价对应约", 8 * 2 / 1.5 * .5)
    stated("10.3", "增长到原来的", (10 - .6) / .4)
    stated("10.5", "只有约", (1 - .6 / .7) * 100)
    stated("12.3", "赢家最终占组合约", 10 / 14 * 100)

    cash = {r[0]: list(map(number, r[1:])) for r in table("现金项目，百万美元")}
    flows = [k for k in cash if k not in {"期初现金", "期末现金／未融资缺口"}]
    for year in range(3):
        near("financing bridge year " + str(year+1), cash["期初现金"][year] + sum(cash[k][year] for k in flows), cash["期末现金／未融资缺口"][year])
        if year:
            near("opening cash continuity", cash["期初现金"][year], cash["期末现金／未融资缺口"][year-1])

    dcf = {r[0]: number(r[1]) for r in table("桥接项目")}
    flows = [10, 15, 20, 25, 30]
    pv = sum(c / 1.12 ** (i+1) for i, c in enumerate(flows))
    tv = 30 * 1.03 / (.12 - .03)
    ev = pv + tv / 1.12 ** 5
    equity = ev + dcf["加：可分配的非经营现金，百万美元"] - dcf["减：债务及其他优先索取权，百万美元"]
    shares = dcf["同口径经济稀释股数，百万股"]
    check("DCF positive share denominator", shares > 0)
    for key, value in [("前五年现金流现值，百万美元", pv), ("第五年末延续价值，百万美元", tv),
                       ("延续价值的当前现值，百万美元", tv / 1.12 ** 5), ("企业价值，百万美元", ev),
                       ("普通股价值，百万美元", equity), ("条件每股价值，美元", equity/shares)]:
        near("DCF " + key, dcf[key], value)
    stated("8.6", "本例约", tv / 1.12 ** 5 / ev * 100)

    valuation = {r[0]: list(map(number, r[1:])) for r in table("五年终期假设")}
    for i in range(3):
        profit = valuation["年收入，百万美元"][i] * valuation["净利润率"][i] / 100
        price = profit / valuation["股份，百万股"][i] * valuation["终期市盈率"][i]
        near("company profit scenario " + str(i), valuation["净利润，百万美元"][i], profit)
        near("company terminal scenario " + str(i), valuation["终期每股价格，美元"][i], price)
        near("company PV scenario " + str(i), valuation["按 15% 折现五年的条件现值，美元"][i], price/1.15**5)
    for part, phrase, value in [
        ("13.2", "首次买价上限约为", (5000*.2/120*25)/1.15**5*.8),
        ("13.3", "股票权重约", 100000/1012500*100),
        ("13.4", "折现约为", 450/1.15**3),
        ("13.4", "条件现值约为", 700/1.15**2),
        ("13.4", "两年折现值约", 500/1.15**2),
        ("13.4", "股票权重约", 200000/1112500*100),
        ("13.4", "股票占约", 400000/1312500*100),
        ("13.4", "现有损失贡献约", 400000/1312500*.7*100),
        ("13.4", "股票权重约 19.81%，指定压力损失贡献降至约", 260000/1312500*.7*100),
        ("13.4", "此时约占账户", 650000/1702500*100),
        ("13.4", "仓位约", 300000/1702500*100),
        ("13.4", "冲击贡献约", 300000/1702500*.7*100),
        ("13.5", "即起始账户的", 32500/1000000*100),
    ]:
        stated(part, phrase, value)

    stress = table("资产")
    contributions = []
    for row in stress[:-1]:
        loss_match = re.search(r"([\d.]+)%", row[2])
        check("stress assumption " + row[0], loss_match is not None)
        contribution = number(row[1]) * float(loss_match[1]) / 100
        near("stress contribution " + row[0], number(row[3]), contribution)
        contributions.append(contribution)
    near("stress total", sum(contributions), number(stress[-1][3]))
    near("stress weights", sum(number(r[1]) for r in stress[:-1]), 100)

    # The second table headed 资产 has a different column count; select it by full header.
    match = re.search(r"\| 资产 \| 初始成本 \|.*?\n\n", body, re.S)
    check("portfolio path table", match is not None)
    path = [[c.strip() for c in line.strip("|").split("|")] for line in match.group().splitlines()[2:] if line.startswith("|")]
    holdings = {r[0]: list(map(number, r[1:])) for r in path}
    for col in range(4):
        near("portfolio column total " + str(col), sum(values[col] for k, values in holdings.items() if k != "合计"), holdings["合计"][col])
    near("cash release", holdings["现金"][3]-holdings["现金"][2], sum(holdings[k][2]-holdings[k][3] for k in "ABCDE"))
    shock = dict(zip("ABCDE", [.5,.5,.7,1,.6]))
    before = sum(holdings[k][2]*shock[k] for k in "ABCDE")
    after = sum(holdings[k][3]*shock[k] for k in "ABCDE")
    stated("13.8", "额外损失合计为", before)
    stated("13.8", "回撤为", (1-(78-before)/120)*100)
    stated("13.8", "回撤约", (1-(78-after)/120)*100)
    stated("13.9", "合计已实现亏损", (6-4)+(8-2)+(6-1))
    stated("13.9", "台账合计占用", 13+(6-5)+(10-6)+(4-3))
    for factors, expected_end in [([3,2.5,2,1.5,1.5],152),([10,6,4,3,2],298)]:
        ending = 60+sum(holdings[k][0]*f for k,f in zip("ABCDE",factors))
        near("portfolio terminal scenario", ending, expected_end)
        check("portfolio terminal in prose", str(expected_end) + " 单位" in section("13.7"))
    hours = table("每周工作")
    near("weekly hours", sum(number(row[1]) for row in hours[:-1]), number(hours[-1][1]))
    stated("16.7", "约为", (1.10 / 1.03 - 1) * 100)
    return checks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nbis-delivery", type=Path, help="Optional private historical evidence directory; read only")
    parser.add_argument("--self-test", action="store_true", help="Verify that intentional manuscript corruptions are rejected")
    args = parser.parse_args()
    body = BOOK.read_text(encoding="utf-8")
    checks = validate(body)
    negative_tests = 0
    if args.self_test:
        mutations = [
            ("| 期末现金／未融资缺口 | 200 | 100 | -40 |", "| 期末现金／未融资缺口 | 200 | 100 | 40 |"),
            ("| DD25 | 实际峰值回撤 >= 25%", "| DD25 | 实际峰值回撤 >= 26%"),
            ("| 普通股价值，百万美元 | 232.85 |", "| 普通股价值，百万美元 | 233.85 |"),
            ("| 加：可分配的非经营现金，百万美元 | 40.00 |", "| 加：可分配的非经营现金，百万美元 | 400.00 |"),
            ("| 合计 | 100 | 120 | 78 | 78 |", "| 合计 | 100 | 120 | 78 | 79 |"),
            ("损之又损，以至于无为。", "损之又损，以至于有为。"),
            ("(#chapter-01)", "(#missing-chapter)"),
            ("强制集中度评审，不自动卖出 | 已批准", "自动全部卖出 | 已批准"),
            ("不延迟已核实的必要退出", "延迟已核实的必要退出"),
            ("C03-002", "C99-999"),
            ("约为6.80%", "约为7.00%"),
            ("心情变好不能绕过它", "心情变好可以绕过它"),
        ]
        for old, new in mutations:
            if old not in body:
                raise ValueError("self-test fixture missing: " + old)
            try:
                validate(body.replace(old, new, 1))
            except ValueError:
                negative_tests += 1
            else:
                raise ValueError("corruption was not rejected: " + old)
    nbis = "NOT_REQUESTED"
    if args.nbis_delivery:
        directory = args.nbis_delivery
        manifest = json.loads((directory / "manifest.json").read_text())
        for name in ["START.md", "portfolio-status.json"]:
            if hashlib.sha256((directory/name).read_bytes()).hexdigest() != manifest[name]:
                raise ValueError("NBIS historical file digest mismatch: " + name)
        status = json.loads((directory/"portfolio-status.json").read_text())
        if status["status"] != "PENDING_RESEARCH_REVIEW" or status["approval"] != "NOT_INFERRED":
            raise ValueError("NBIS historical state differs from manuscript description")
        nbis = "TWO_HISTORICAL_FILES_MATCH_MANIFEST_NOT_CURRENT_RESEARCH"
    print(json.dumps({"result": "PASS", "checks": len(checks), "negative_tests_rejected": negative_tests,
                      "characters": len(body), "chinese_characters": len(re.findall(r"[\u4e00-\u9fff]", body)),
                      "sha256": hashlib.sha256(BOOK.read_bytes()).hexdigest(), "nbis": nbis,
                      "scope": "Manuscript structure, links, approved thresholds, quotations and example arithmetic; NOT strategy or portfolio validation."},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
