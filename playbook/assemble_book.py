#!/usr/bin/env python3
"""把 playbook/book/*.md 装配成 道德经投资打法手册.md（根目录）。章文件 H1→H2、H2→H3、H3→H4。"""
import re, os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
B = os.path.join(ROOT, 'playbook', 'book')
PARTS = {
 'P1': ('第一部分 · 八个决策点', '一笔交易的顺序，也是本书的顺序：论点、证伪、估值、仓位、入场、加减、回撤、卖出。每章一句不变量、一组带编号的规则、一张填好的表。'),
 'P2': ('第二部分 · 案例与模板', '先用案例账户的一笔真实交易把八个决策点走完，再给四类生意各一套 KPI、证伪变量、估值方法与可信最大跌幅；四类之外的，从零建模板。'),
 'P3': ('第三部分 · 保险与运行', '期权只作保险；日、周、月、季、年的运行清单；以及把两种大师机制练成阶梯的修炼路径。'),
 'AP': ('附录', '参数与规则注册表、语料换算表、道德经原文对照、空白表单。'),
}
ORDER = ['00-卷首.md', '00-导论.md', 'TOC', 'P1', '01-论点.md', '02-证伪清单.md', '03-估值锚.md', '04-仓位.md', '05-入场.md', '06-加减.md', '07-回撤与心力.md', '08-卖出与复盘.md',
         'P2', '09-NBIS全程复盘.md', '10-半导体与代工.md', '11-AI基建与电力.md', '12-加密金融轨道.md', '13-企业软件.md', '14-从零建模板.md',
         'P3', '15-期权只作保险.md', '16-运行日历.md', '17-修炼.md',
         'AP', 'A-参数与规则注册表.md', 'B-语料换算表.md', 'C-道德经原文对照.md', 'D-表单.md', 'Z-免责声明.md']
def demote(s):
    lines = []
    in_code = False
    for ln in s.split('\n'):
        if ln.startswith('```'): in_code = not in_code
        if not in_code and re.match(r'^#{1,5} ', ln): ln = '#' + ln
        lines.append(ln)
    return '\n'.join(lines)
titles = []
for name in ORDER:
    if name in PARTS or name == 'TOC': continue
    s = open(os.path.join(B, name), encoding='utf-8').read()
    m = re.search(r'^#{1,2} (.+)$', s, flags=re.M)
    titles.append((name, m.group(1).strip()))
head = ['# 道德经投资打法手册', '', '**八个决策点 · 四类生意 · 一套参数** —— 把《道德经》投资心法换算成可执行的决策规则，从一笔真实交易到任何一只股票。', '',
        '📘 电子书：[下载 EPUB](https://traceme.github.io/DDJ-investing/道德经投资打法手册.epub)（含封面与分级目录，可导入微信读书、Apple Books、Kindle 等阅读器）', '',
        '> 本书是方法论，不是荐股；公司只作方法示例；公司事实截至 2026 年初，逐条标注「核对」；示例参数来自归一为 100 单位的案例账户。完整声明见书末。', '']
body = []
for name in ORDER:
    if name in PARTS:
        t, summary = PARTS[name]
        body += [f'## {t}', '', summary, '']
    elif name == 'TOC':
        body += ['## 目录', '']
        for n, t in titles:
            if n.startswith('00-'): continue
            body.append(f'- {t}')
        body.append('')
    else:
        s = open(os.path.join(B, name), encoding='utf-8').read().rstrip('\n')
        if name.startswith('00-') or name.startswith('Z-'):
            body += [s, '']
        else:
            body += [demote(s), '']
out = '\n'.join(head + body)
dst = os.path.join(ROOT, '道德经投资打法手册.md')
open(dst, 'w', encoding='utf-8').write(out)
print(f'{dst}: {len(out.encode())} 字节, {len(re.sub(r"\s", "", out))} 非空白字符, H2 {len(re.findall(r"^## ", out, flags=re.M))} 个')
