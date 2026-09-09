#!/usr/bin/env python3
"""《成功投资者心性养成指南》书稿校验。用法：python3 mindset/validate_book.py [files...]

断言：道德经引文逐字（引用块与「《道德经》第N章「…」」两种写法）；语料引文逐字（引用块尾注「——《书名》第N章」）；
出处标签编号在范围内；练习编号 T 已在 BOOK_SPEC 注册；R 规则已在打法手册或投资系统注册；纪律编号 Cxx-nnn 存在；
宪N ≤ 十二；外部文献只来自附录 E；字数在规格区间；无真实金额与身份信息；无 mermaid、HTML 注释、美元价格。
"""
import re, sys, glob, os, json
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.join(ROOT, 'mindset')
DDJ = os.path.join(ROOT, '原文', '道德经-王弼本.md')
SPEC = os.path.join(HERE, 'BOOK_SPEC.md')
REFS = os.path.join(HERE, 'book', 'E-参考文献.md')
CN = '零一二三四五六七八九十'

def cn2int(s):
    s = s.replace('零', '')
    if s == '十': return 10
    if '十' in s:
        a, b = s.split('十')
        return (CN.index(a) if a else 1) * 10 + (CN.index(b) if b else 0)
    return CN.index(s)

def norm(s):
    s = re.sub(r'</?(mark|u|strong|em)>', '', s)
    s = re.sub(r'[\s*「」『』]', '', s)
    return s

txt = open(DDJ, encoding='utf-8').read()
parts = re.split(r'^## 第(\d+)章\s*$', txt, flags=re.M)
DDJ_CH = {int(parts[i]): norm(parts[i + 1]) for i in range(1, len(parts), 2)}

spec = open(SPEC, encoding='utf-8').read()
DRILLS = set(re.findall(r'\bT\d+\.\d+\b', spec))
RULES = set(re.findall(r'\bR\d+\.\d+\b', open(os.path.join(ROOT, 'playbook', 'BOOK_SPEC.md'), encoding='utf-8').read()))
RULES |= set(re.findall(r'\bR\d+\.\d+\b', open(os.path.join(ROOT, 'system', 'book', 'A-新增规则注册表.md'), encoding='utf-8').read()))
cat = json.load(open(os.path.join(ROOT, 'system', 'data', '纪律总表.json'), encoding='utf-8'))
CIDS, cnt = set(), {}
for it in cat:
    c = it['category']; cnt[c] = cnt.get(c, 0) + 1; CIDS.add(f"{c}-{cnt[c]:03d}")
TARGETS = {}
for m in re.finditer(r'^\| (\S+\.md) \| [^|]+ \| (\d+)[–-](\d+) \|', spec, flags=re.M):
    TARGETS[m.group(1)] = (int(m.group(2)), int(m.group(3)))

# 语料引文：书名 → (文件模式, 编号上限)
BOOKS = {
    '道德经81章投资心法': ('chapters/第{:02d}章.md', 81),
    '道德经81章投资心法·Codex版本': ('codex/第{:02d}章.md', 81),
    '第三只眼观投资心法': ('thethirdeye/第{:03d}章.md', 151),
    '人生悟道 渡人渡己·投资篇读书心法': ('jinbing-drdj/第{:02d}篇.md', 72),
    '投资心法100条精选版': ('投资心法100条精选版.md', 100),
    '道德经投资打法手册': ('道德经投资打法手册.md', 0),
    '道德经投资系统': ('道德经投资系统.md', 0),
    '投资纪律总表': ('投资纪律总表.md', 0),
}
TAG_RANGE = {'道': 81, 'Codex': 81, '三眼': 151, '金': 72, '选': 100, '罗盘': 100}
_cache = {}
def src(path):
    if path not in _cache:
        full = os.path.join(ROOT, path)
        _cache[path] = norm(open(full, encoding='utf-8').read()) if os.path.exists(full) else None
    return _cache[path]

PII = [
    (r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}', '疑似邮箱地址'),
    (r'\d{3,}\s*万', '疑似真实账户金额（三位数以上的「万」）'),
    (r'[$￥]\s?\d{1,3}(?:,\d{3})+', '疑似真实金额（带千分位）'),
    (r'\b\d+(?:\.\d+)?\s*[MK]\b', '疑似真实金额（M／K 简写）'),
    (r'\$\s?\d', '美元价格（本书只用案例账户单位）'),
]
refs = open(REFS, encoding='utf-8').read() if os.path.exists(REFS) else ''
ref_lines = refs.split('\n')

files = sys.argv[1:] or sorted(glob.glob(os.path.join(HERE, 'book', '*.md')))
bad = 0
for f in files:
    name = os.path.basename(f)
    s = open(f, encoding='utf-8').read()
    nchar = len(re.sub(r'\s', '', s))
    issues = []
    lo, hi = TARGETS.get(name, (0, 10 ** 9))
    if not (lo * 0.9 <= nchar <= hi * 1.15):
        issues.append(f'字数 {nchar} 超出目标 {lo}–{hi}')
    # 道德经引用块
    for m in re.finditer(r'^>[ \t　]*(.+?)[ \t　]*——[ \t　]*《道德经》第([一二三四五六七八九十零]+)章', s, flags=re.M):
        ch = cn2int(m.group(2))
        for piece in re.split(r'……|/|／', norm(m.group(1).lstrip('> '))):
            piece = piece.strip('。；，')
            if piece and (ch not in DDJ_CH or piece not in DDJ_CH[ch]):
                issues.append(f'道德经引文非逐字或章号错：第{ch}章「{piece[:20]}」')
    # 道德经行内引用：《道德经》第N章…「…」 或 第N章说／云／讲／中「…」
    for m in re.finditer(r'(?:《道德经》第([一二三四五六七八九十零]+)章[^「」\n]{0,8}|第([一二三四五六七八九十零]+)章(?:说|云|讲|写道|里|中|的)[^「」\n]{0,6})「([^」\n]{3,})」', s):
        ch = cn2int(m.group(1) or m.group(2))
        for piece in re.split(r'……', norm(m.group(3))):
            piece = piece.strip('。；，')
            if piece and (ch not in DDJ_CH or piece not in DDJ_CH[ch]):
                issues.append(f'行内道德经引文非逐字：第{ch}章「{piece[:20]}」')
    # 语料引用块
    for m in re.finditer(r'^>[ \t　]*(.+?)[ \t　]*——[ \t　]*《([^》]+)》第([一二三四五六七八九十零\d]+)(章|篇|条)', s, flags=re.M):
        book, n = m.group(2), m.group(3)
        if book == '道德经': continue
        if book not in BOOKS:
            issues.append(f'未知引文来源《{book}》'); continue
        pat, top = BOOKS[book]
        num = int(n) if n.isdigit() else cn2int(n)
        path = pat.format(num) if top else pat
        if top and not (1 <= num <= top):
            issues.append(f'《{book}》编号越界 {num}'); continue
        body = src(path)
        if body is None:
            issues.append(f'引文源文件缺失 {path}'); continue
        for piece in re.split(r'……', norm(m.group(1).lstrip('> '))):
            piece = piece.strip('。；，')
            if piece and piece not in body:
                issues.append(f'语料引文非逐字：《{book}》第{num}「{piece[:20]}」')
    # 出处标签
    for m in re.finditer(r'\[(道|Codex|三眼|金|选|罗盘)(\d+)(?:章)?(实操)?\]', s):
        k, n = m.group(1), int(m.group(2))
        if not (1 <= n <= TAG_RANGE[k]):
            issues.append(f'标签越界 [{k}{n}]')
    for m in re.finditer(r'\bT\d+\.\d+\b', s):
        if m.group(0) not in DRILLS:
            issues.append(f'未注册的练习编号 {m.group(0)}'); break
    for m in re.finditer(r'\bR\d+\.\d+\b', s):
        if m.group(0) not in RULES:
            issues.append(f'未注册的规则编号 {m.group(0)}'); break
    for m in re.finditer(r'\bC\d\d-\d{3}\b', s):
        if m.group(0) not in CIDS:
            issues.append(f'不存在的纪律编号 {m.group(0)}'); break
    for m in re.finditer(r'宪([一二三四五六七八九十]+)(?![一二三四五六七八九十])', s):
        if cn2int(m.group(1)) > 12:
            issues.append(f'宪{m.group(1)} 超出十二条'); break
    # 外部文献：作者（年）必须在附录 E 同一行出现
    if not name.startswith('E-'):
        for m in re.finditer(r'\b([A-Z][a-z]+(?:-[A-Z][a-z]+)?)\b[^.\n]{0,40}?[(（]((?:19|20)\d\d)[)）]', s):
            sur, yr = m.group(1), m.group(2)
            if not any(sur in ln and yr in ln for ln in ref_lines):
                issues.append(f'文献不在附录 E：{sur} ({yr})')
    m = re.search(r'承受线[^。\n%]{0,8}?(\d+)%', s)
    if m and m.group(1) != '30':
        issues.append(f'承受线写成 {m.group(1)}%（应 30%，参数只在打法手册定义）')
    for pat, why in PII:
        hit = set(re.findall(pat, s))
        if hit: issues.append(f'{why} {sorted(hit)[:3]}')
    if 'mermaid' in s: issues.append('含 mermaid')
    if '<!--' in s: issues.append('含 HTML 注释')
    h1 = len(re.findall(r'^# ', s, flags=re.M))
    if h1 != 1: issues.append(f'H1 数量 {h1}（每个文件恰好一个 H1，装配时降级为书中的 H2）')
    status = 'OK ' if not issues else 'BAD'
    if issues: bad += 1
    nt = len(set(re.findall(r'\bT\d+\.\d+\b', s)))
    nq = len(re.findall(r'——[ \t　]*《', s))
    print(f'{status} {name:<26} 字数 {nchar:>5}  练习 {nt:>2}  引文 {nq:>2}  ' + ('; '.join(issues) if issues else ''))
print(f'\n{len(files)} 个文件，{bad} 个有问题')
sys.exit(1 if bad else 0)
