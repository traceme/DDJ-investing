#!/usr/bin/env python3
"""校验《道德经投资系统》：编号可追溯、规则已注册、矩阵全覆盖且格式合规、道德经引文逐字、无禁词。
用法（仓库根目录）：python3 system/validate_system.py"""
import re, os, glob, json, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
B = os.path.join(ROOT, 'system', 'book')
issues = []
def bad(msg): issues.append(msg)

catalog = json.load(open(os.path.join(ROOT, 'system', 'data', '纪律总表.json'), encoding='utf-8'))
IDS = {d['id'] for d in catalog}
spec = open(os.path.join(ROOT, 'playbook', 'BOOK_SPEC.md'), encoding='utf-8').read()
RIDS = set(re.findall(r'\bR\d+\.\d+\b', spec)) | {f'R18.{i}' for i in range(1, 21)}

book = open(os.path.join(ROOT, '道德经投资系统.md'), encoding='utf-8').read()
chapters = {os.path.basename(p): open(p, encoding='utf-8').read() for p in sorted(glob.glob(os.path.join(B, '*.md')))}

# 1. 纪律编号可追溯
cited = set(re.findall(r'\bC\d\d-\d{3}\b', book))
ghost = sorted(cited - IDS)
if ghost: bad(f'引用了不存在的纪律编号 {ghost[:20]}（共 {len(ghost)}）')
# 2. 规则编号已注册
rghost = sorted(set(re.findall(r'\bR\d+\.\d+\b', book)) - RIDS)
if rghost: bad(f'引用了未注册的规则 {rghost[:20]}')
# 3. 宪法与裁决编号范围
for m in set(re.findall(r'宪(十一|十二|[一二三四五六七八九十])(?![一二三四五六七八九十])', book)):
    n = {'一':1,'二':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9,'十':10,'十一':11,'十二':12}.get(m)
    if n is None: bad(f'宪法编号越界：宪{m}')
for m in set(re.findall(r'§4\.(\d+)', book)):
    if not 1 <= int(m) <= 49: bad(f'裁决编号越界 §4.{m}')
# 4. 矩阵覆盖与格式
rows = []
for name, s in chapters.items():
    if not re.match(r'07[a-f]-', name): continue
    for ln in s.split('\n'):
        m = re.match(r'^\| (C\d\d-\d{3}) \| (.*?) \| (.*?) \| (.*?) \| (.*?) \| (.*?) \|\s*$', ln)
        if m: rows.append((name,) + m.groups())
mids = [r[1] for r in rows]
dup = sorted({x for x in mids if mids.count(x) > 1})
if dup: bad(f'矩阵重复编号 {dup[:20]}')
missing = sorted(IDS - set(mids))
if missing: bad(f'矩阵未覆盖 {len(missing)} 条：{missing[:20]}')
extra = sorted(set(mids) - IDS)
if extra: bad(f'矩阵含不存在的编号 {extra[:20]}')
MECH = re.compile(r'宪[一二三四五六七八九十]+|R\d+\.\d+|§\d+\.\d+|裁决 ?§4\.\d+|不采纳|原则化')
LEVEL = re.compile(r'甲级|乙级|丙级|本条自身|不采纳|原则化|不记点|不适用|不构成|停留 S0|—')
for name, cid, disc, timing, det, cons, mech in rows:
    if not MECH.search(mech): bad(f'{cid} 机制列不合规：{mech[:40]}')
    if not LEVEL.search(cons) and '不采纳' not in mech and '原则化' not in mech: bad(f'{cid} 后果列缺记点级别：{cons[:40]}')
    if len(re.sub(r'\s', '', disc)) > 40: bad(f'{cid} 纪律概括过长（{len(disc)} 字）')
# 4b. 记点级别与所引宪法条一致（§3.3 条与级的对照）：
#     甲级条（宪一/三/四/五/十）任何违反都是甲级；乙级条（宪二/七/八/十一/十二）未处置是乙级，
#     在禁止状态下仍执行或逾期未处置才是甲级——后者的后果文本必须写明触发词。
JIA = {'一', '三', '四', '五', '十'}
YI = {'二', '七', '八', '十一', '十二'}
OVERRIDE = re.compile(r'下单|成交|作废|买入|买回|仍买|下一笔|开仓|开新仓|加仓|跟单|据此|据非|调仓|追高|停手期|S3|S4|擅入|逾周|逾期|削回|未削|期内|非复核日|第二次|违规修订|上调|连续两次|卖出|清仓|已买')
for name, cid, disc, timing, det, cons, mech in rows:
    hs = set(re.findall(r'宪(十一|十二|[一二三四五六七八九十])(?![一二三四五六七八九十])', mech))
    if not hs or '不采纳' in mech or '原则化' in mech: continue
    if hs & JIA and '甲级' not in cons:
        bad(f'{cid} 引用甲级条 宪{"、".join(sorted(hs & JIA))} 但后果未记甲级：{cons[:30]}')
    if not (hs & JIA) and '甲级' in cons and not OVERRIDE.search(cons):
        bad(f'{cid} 只引乙级条 宪{"、".join(sorted(hs))} 却记甲级且后果未写明「据此成交」或越权情形：{cons[:30]}')
# 5. 道德经引文逐字
ddj = open(os.path.join(ROOT, '原文', '道德经-王弼本.md'), encoding='utf-8').read()
parts = re.split(r'^## 第(\d+)章\s*$', ddj, flags=re.M)
CH = {int(parts[i]): re.sub(r'\s+', '', parts[i + 1]) for i in range(1, len(parts), 2)}
CN = '零一二三四五六七八九十'
def cn2int(s):
    s = s.replace('零', '')
    if s == '十': return 10
    if '十' in s:
        a, b = s.split('十'); return (CN.index(a) if a else 1) * 10 + (CN.index(b) if b else 0)
    return CN.index(s)
nq = 0
for m in re.finditer(r'^>[ \t　]*(.+?)[ \t　]*——[ \t　]*《道德经》第([一二三四五六七八九十零]+)章', book, flags=re.M):
    nq += 1
    q = re.sub(r'[\s「」『』*]', '', m.group(1)); n = cn2int(m.group(2))
    for piece in q.replace('／', '/').split('/'):
        piece = piece.strip('。；，')
        if piece and (n not in CH or piece not in CH[n]): bad(f'道德经引文非逐字：第{n}章「{piece[:20]}」')
# 5a. 审计表行数与接口章声明的项数一致
CN2I = {'三':3,'四':4,'五':5,'十':10,'十六':16,'十八':18}
au = chapters.get('05-审计与修宪.md', '')
iface = chapters.get('06-接口.md', '')
def rows_of(head):
    i = au.find(head)
    if i < 0: return None
    j = au.find('\n### ', i + 5)
    j = au.find('\n## ', i + 5) if j < 0 else j
    blk = au[i:len(au) if j < 0 else j]
    return len([l for l in blk.split('\n')
                if l.startswith('|') and not l.startswith('|---') and not re.match(r'^\| (项|序) ', l)])
n_q, n_y = rows_of('### 季（'), rows_of('### 年（')
for label, n, pat in (('季', n_q, r'季表[^|]*\| ([一二三四五六七八九十]+)项'), ('年', n_y, r'年表[^|]*\| ([一二三四五六七八九十]+)项')):
    m = re.search(pat, iface)
    if n is not None and m and CN2I.get(m.group(1)) != n:
        bad(f'{label}表实际 {n} 行，接口章却写「{m.group(1)}项」')

# 5b. 已知过时表述（改过的口径不得回潮）
STALE = [
    ('单笔亏损达账户永久亏损预算', '停手触发已改为「超过建仓日算式允许的最大证伪损失」'),
    ('市值膨胀造成的超限当周削回', '上限是买入时点口径，上涨漂移不算超限'),
    ('热区 → 进入 S3', '热区只抬现金线，不直接改状态'),
    ('同一因子合计不越六成', '因子上限＝min(六成, 承受线 ÷ 因子内最大可信跌幅)'),
    ('机制阶梯计数 −3、退回上一级', '改用独立的罚扣字段'),
    ('宪法其余八条', '可修的是九条'),
]
for bad_s, why in STALE:
    if bad_s in book: bad(f'含已废弃表述「{bad_s}」——{why}')

# 6. 禁词
# 真实金额与身份信息：用通用模式，不在公开脚本里写出要躲的具体数字
PII = [
    (r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}', '疑似邮箱地址'),
    (r'\d{3,}\s*万', '疑似真实账户金额（三位数以上的「万」）'),
    (r'[$￥]\s?\d{1,3}(?:,\d{3})+', '疑似真实金额（带千分位）'),
    (r'\b\d+(?:\.\d+)?\s*[MK]\b', '疑似真实金额（M／K 简写）'),
]
for pat, why in PII:
    for m in set(re.findall(pat, book)):
        bad(f'{why}：「{m}」——案例账户一律以「单位」计')
if 'mermaid' in book: bad('含 mermaid')
# 7. 每个章文件一个 H1
for name, s in chapters.items():
    if re.match(r'0[1-7]-|[AD]-', name) and len(re.findall(r'^# ', s, flags=re.M)) != 1: bad(f'{name} H1 数量 ≠ 1')

verdicts = {}
for name, cid, disc, timing, det, cons, mech in rows:
    v = '不采纳' if '不采纳' in mech else '原则化' if '原则化' in mech else '裁决限定' if '裁决' in mech else '采纳'
    verdicts[v] = verdicts.get(v, 0) + 1
print(f'纪律 {len(IDS)}｜矩阵行 {len(rows)}｜引用编号 {len(cited)}｜道德经引文 {nq} 处｜处置 {verdicts}')
if issues:
    print('\n'.join(issues)); sys.exit(1)
print('校验通过：编号可追溯、规则已注册、矩阵 360/360 且格式合规、引文逐字、无禁词')
