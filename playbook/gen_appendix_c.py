#!/usr/bin/env python3
"""附录 C：扫描书稿中的道德经引文，按原文章号汇编全文对照。"""
import re, glob, os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CN = '零一二三四五六七八九十'
def cn2int(s):
    s = s.replace('零', '')
    if s == '十': return 10
    if '十' in s:
        a, b = s.split('十'); return (CN.index(a) if a else 1) * 10 + (CN.index(b) if b else 0)
    return CN.index(s)
def int2cn(n):
    if n < 10: return CN[n]
    if n == 10: return '十'
    if n < 20: return '十' + (CN[n % 10] if n % 10 else '')
    return CN[n // 10] + '十' + (CN[n % 10] if n % 10 else '')
txt = open(os.path.join(ROOT, '原文', '道德经-王弼本.md'), encoding='utf-8').read()
parts = re.split(r'^## 第(\d+)章\s*$', txt, flags=re.M)
DDJ = {int(parts[i]): parts[i+1].strip() for i in range(1, len(parts), 2)}
cites = {}  # ch -> list of (book chapter title, quote)
for f in sorted(glob.glob(os.path.join(ROOT, 'playbook', 'book', '[0-9]*.md'))):
    s = open(f, encoding='utf-8').read()
    mt = re.search(r'^#{1,2} (.+)$', s, flags=re.M)
    if not mt: continue
    title = mt.group(1).strip()
    for m in re.finditer(r'^>\s*(.+?)\s*——\s*《道德经》第([一二三四五六七八九十零]+)章', s, flags=re.M):
        cites.setdefault(cn2int(m.group(2)), []).append((title, m.group(1).strip()))
out = ['# 附录 C · 《道德经》原文对照', '',
       '正文各章引用的《道德经》章句，按原文章号汇编，附王弼通行本全文（简体，取自本项目 `原文/道德经-王弼本.md`）。「引于」列出引用该章的书稿章节与所引句子。', '']
for ch in sorted(cites):
    out.append(f'## 第{int2cn(ch)}章')
    out.append('')
    out.append('> ' + DDJ[ch].replace('\n', '\n> '))
    out.append('')
    for title, q in cites[ch]:
        out.append(f'- 引于{title}：{q}')
    out.append('')
out.append(f'共引用 {len(cites)} 章，{sum(len(v) for v in cites.values())} 处。')
open(os.path.join(ROOT, 'playbook', 'book', 'C-道德经原文对照.md'), 'w', encoding='utf-8').write('\n'.join(out) + '\n')
print(f'C: {len(cites)} 章 {sum(len(v) for v in cites.values())} 处')
