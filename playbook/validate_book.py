#!/usr/bin/env python3
"""书稿校验：道德经引文逐字、禁词、规则编号、字数、核对标记。用法：python3 playbook/validate_book.py [files...]"""
import re, sys, glob, os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DDJ = os.path.join(ROOT, '原文', '道德经-王弼本.md')
SPEC = os.path.join(ROOT, 'playbook', 'BOOK_SPEC.md')
CN = '零一二三四五六七八九十'
def cn2int(s):
    s = s.replace('零', '')
    if s == '十': return 10
    if '十' in s:
        a, b = s.split('十')
        return (CN.index(a) if a else 1) * 10 + (CN.index(b) if b else 0)
    return CN.index(s)
txt = open(DDJ, encoding='utf-8').read()
parts = re.split(r'^## 第(\d+)章\s*$', txt, flags=re.M)
DDJ_CH = {int(parts[i]): re.sub(r'\s+', '', parts[i+1]) for i in range(1, len(parts), 2)}
spec = open(SPEC, encoding='utf-8').read()
RULES = set(re.findall(r'\bR\d+\.\d+\b', spec))
TARGETS = {}
for m in re.finditer(r'^\| (\S+\.md) \| [^|]+ \| (\d+)[–-](\d+) \|', spec, flags=re.M):
    TARGETS[m.group(1)] = (int(m.group(2)), int(m.group(3)))
# 真实金额与身份信息：用通用模式，不在公开脚本里写出要躲的具体数字
PII = [
    (r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}', '疑似邮箱地址'),
    (r'\d{3,}\s*万', '疑似真实账户金额（三位数以上的「万」）'),
    (r'[$￥]\s?\d{1,3}(?:,\d{3})+', '疑似真实金额（带千分位）'),
    (r'\b\d+(?:\.\d+)?\s*[MK]\b', '疑似真实金额（M／K 简写）'),
]
files = sys.argv[1:] or sorted(glob.glob(os.path.join(ROOT, 'playbook', 'book', '*.md')))
bad = 0
for f in files:
    name = os.path.basename(f)
    s = open(f, encoding='utf-8').read()
    nchar = len(re.sub(r'\s', '', s))
    issues = []
    lo, hi = TARGETS.get(name, (0, 10**9))
    if not (lo * 0.9 <= nchar <= hi * 1.15):
        issues.append(f'字数 {nchar} 超出目标 {lo}–{hi}')
    # 道德经引文：blockquote 行含「——《道德经》第N章」
    for m in re.finditer(r'^>[ \t　]*(.+?)[ \t　]*——[ \t　]*《道德经》第([一二三四五六七八九十零]+)章', s, flags=re.M):
        quote, ch = m.group(1).lstrip('> '), cn2int(m.group(2))
        q = re.sub(r'[\s「」『』*]', '', quote)
        q = q.replace('／', '/').split('/')
        for piece in q:
            piece = piece.strip('。；，')
            if not piece: continue
            if ch not in DDJ_CH or piece not in DDJ_CH[ch]:
                issues.append(f'引文非逐字或章号错：第{ch}章「{piece[:20]}」')
    for m in re.finditer(r'\bR\d+\.\d+\b', s):
        if m.group(0) not in RULES:
            issues.append(f'未注册的规则编号 {m.group(0)}'); break
    for pat, why in PII:
        hit = set(re.findall(pat, s))
        if hit: issues.append(f'{why} {hit}')
    if 'mermaid' in s: issues.append('含 mermaid')
    h1 = len(re.findall(r'^# ', s, flags=re.M))
    if h1 != 1 and not (name.startswith('00-') or name.startswith('Z-')): issues.append(f'H1 数量 {h1}')
    nk = s.count('核对')
    nr = len(set(re.findall(r'\bR\d+\.\d+\b', s)))
    status = 'OK ' if not issues else 'BAD'
    if issues: bad += 1
    print(f'{status} {name:<22} 字数 {nchar:>5}  规则 {nr:>2}  核对 {nk:>2}  ' + ('; '.join(issues) if issues else ''))
print(f'\n{len(files)} 个文件，{bad} 个有问题')
sys.exit(1 if bad else 0)
