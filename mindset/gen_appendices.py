#!/usr/bin/env python3
"""附录 A（练习登记表、★参数、本书取值表）与附录 D（练习 ↔ 宪法／纪律／规则对照）由规格与最终设计机械生成。
用法：python3 mindset/gen_appendices.py"""
import re, os, json
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.join(ROOT, 'mindset')
spec = open(os.path.join(HERE, 'BOOK_SPEC.md'), encoding='utf-8').read()
design = open(os.path.join(HERE, 'design', 'DESIGN.md'), encoding='utf-8').read()

def section(text, start, end):
    i = text.index(start); j = text.index(end, i)
    return text[i:j]

def table_lines(block):
    return [l for l in block.split('\n') if l.startswith('|')]

# ---- 附录 A
reg = table_lines(section(spec, '## 2. 练习登记表', '## 3. 引文与出处的写法'))
p12 = table_lines(section(spec, '### 1.2 ★ 本书新增参数', '### 1.3 ★ 设计阶段新增的五项'))
p13 = table_lines(section(spec, '### 1.3 ★ 设计阶段新增的五项', '### 1.4 操作户上限的算式'))
p14 = section(spec, '### 1.4 操作户上限的算式', '## 2. 练习登记表').split('\n', 1)[1].strip()
vals = table_lines(section(design, '## 10. 本书取值表', '**★ 新增参数'))
rows = [l for l in reg if re.match(r'^\| T\d', l)]
kinds = {'安': 0, '节': 0, '事': 0}
for l in rows:
    k = l.split('|')[3].strip()
    for c in kinds:
        if c in k: kinds[c] += 1
A = ['# 附录 A · 练习登记表、★参数与本书取值表', '',
     f'全书 {len(rows)} 条练习：一次性安装 {kinds["安"]} 条、节律型 {kinds["节"]} 条、事件触发 {kinds["事"]} 条（一条可兼两类）。带 ★ 的十条印在附录 B 的一页纸上。支撑列是该练习在四层文本里的依据：宪N＝《道德经投资系统》宪法，Cxx-nnn＝《投资纪律总表》编号，Rx.y＝《道德经投资打法手册》与投资系统的规则编号。练习不改任何规则与参数，只让它们在冲动到来时仍然有效。', '',
     '## A1 练习登记表', ''] + reg + ['',
     '## A2 沿用的参数', '',
     '承受线 30%、永久亏损预算 10%、试错额度 5%、单票上限算式、冷却 7 个交易日、最短服役期 12 个月、清仓冷却 7 个交易日、季度复核日，全部沿用《道德经投资打法手册》附录 A；本书不重定义。', '',
     '## A3 ★ 本书参数（只在季度复核日改，只能收紧）', ''] + p12 + [''] + p13 + ['',
     '### 操作户上限的算式', '', p14, '',
     '## A4 本书取值表（每项取最严档并标来源；第三章 T3.4 要求抄写并签字）', ''] + vals + ['']
open(os.path.join(HERE, 'book', 'A-练习登记表.md'), 'w', encoding='utf-8').write('\n'.join(A))

# ---- 附录 D
cat = json.load(open(os.path.join(ROOT, 'system', 'data', '纪律总表.json'), encoding='utf-8'))
cnt, disc = {}, {}
for it in cat:
    c = it['category']; cnt[c] = cnt.get(c, 0) + 1; disc[f"{c}-{cnt[c]:03d}"] = it['discipline']
CONST = {'一': '本金：只用自有闲钱，零杠杆，生活钱永不进交易账户', '二': '上限：现金线、单票算式上限、因子上限', '三': '门槛：五样不全不下单', '四': '静时立法：数字只在平静时写、只在季度复核日改',
         '五': '触发即执行：T0 之后第三个交易日收盘前完成', '六': '价格不是理由：上涨不是买入理由，下跌不是卖出理由', '七': '身体是检测器：失眠、半夜看盘即超限', '八': '亏损日只平不开：亏因写满三条自己的错',
         '九': '源头信息：只依据年报、公告、原始披露与自核数字', '十': '不预测、不做空、不作方向：期权只作保险', '十一': '能力圈：三到五家，两三个领域', '十二': '记分只对自己：不晒、不辩、只与昨天的自己比'}
fwd, rev = [], {}
for l in rows:
    cells = [c.strip() for c in l.strip().strip('|').split('|')]
    tid, name, supports = cells[0].replace('★', '').strip(), cells[1], cells[-1]
    ids = [s.strip() for s in re.split(r'[、,，]', supports) if s.strip()]
    fwd.append((tid, name, ids))
    for s in ids: rev.setdefault(s, []).append(tid)
D = ['# 附录 D · 练习 ↔ 宪法／纪律／规则对照', '',
     '正向表：每条练习支撑哪些宪法条、纪律编号与规则；反向索引：每条宪法、每个被引用的纪律与规则各有哪些练习在支撑。由附录 A 的支撑列机械生成。', '',
     '## D1 正向表', '', '| 练习 | 名称 | 宪法 | 纪律 | 规则 |', '|---|---|---|---|---|']
for tid, name, ids in fwd:
    xs = [s for s in ids if s.startswith('宪')]; cs = [s for s in ids if re.match(r'C\d\d-\d{3}', s)]; rs = [s for s in ids if re.match(r'R\d', s)]
    D.append(f"| {tid} | {name} | {'、'.join(xs) or '—'} | {'、'.join(cs) or '—'} | {'、'.join(rs) or '—'} |")
D += ['', '## D2 反向索引 · 宪法', '', '| 宪 | 要义 | 支撑它的练习 |', '|---|---|---|']
order = ['一', '二', '三', '四', '五', '六', '七', '八', '九', '十', '十一', '十二']
for k in order:
    ts = rev.get('宪' + k, [])
    D.append(f"| 宪{k} | {CONST[k]} | {'、'.join(ts) or '—（本书未直接引用；由系统自身执行）'} |")
D += ['', '## D3 反向索引 · 纪律编号', '', '| 纪律 | 条文 | 练习 |', '|---|---|---|']
for s in sorted(k for k in rev if re.match(r'C\d\d-\d{3}', k)):
    D.append(f"| {s} | {disc.get(s, '')} | {'、'.join(rev[s])} |")
D += ['', '## D4 反向索引 · 规则编号', '', '| 规则 | 练习 |', '|---|---|']
def rkey(x):
    m = re.match(r'R(\d+)\.(\d+)', x); return (int(m.group(1)), int(m.group(2)))
for s in sorted((k for k in rev if re.match(r'R\d', k)), key=rkey):
    D.append(f"| {s} | {'、'.join(rev[s])} |")
nC = len([k for k in rev if re.match(r'C\d\d', k)]); nR = len([k for k in rev if re.match(r'R\d', k)])
D += ['', f'共 {len(fwd)} 条练习，引用 {len([k for k in rev if k.startswith("宪")])} 条宪法、{nC} 条纪律、{nR} 条规则。', '']
open(os.path.join(HERE, 'book', 'D-对照表.md'), 'w', encoding='utf-8').write('\n'.join(D))
print(f'A: {len(rows)} 条练习, 取值表 {len(vals)} 行; D: 宪 {len([k for k in rev if k.startswith("宪")])} / C {nC} / R {nR}')
