#!/usr/bin/env python3
"""把 mindset/book/*.md 装配成 成功投资者心性养成指南.md（根目录）。
章序、分部与说明取自 mindset/BOOK_SPEC.md 的「章节表」（| 文件 | 章题 | 字数 |；P 行为分部扉页，TOC 行插目录）。
章文件 H1→H2、H2→H3、H3→H4。"""
import re, os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.join(ROOT, 'mindset')
B = os.path.join(HERE, 'book')
spec = open(os.path.join(HERE, 'BOOK_SPEC.md'), encoding='utf-8').read()
rows = re.findall(r'^\| (\S+?) \| ([^|]+?) \| ([^|]*?) \|', spec, flags=re.M)   # 只读前三列，第四列「必须包含」给写手看
ORDER = []
for f, title, third in rows:
    if f in ('文件', '---', ':---'): continue
    if f.endswith('.md') or f == 'TOC' or re.match(r'^P\d$', f) or f == 'AP':
        ORDER.append((f, title.strip(), third.strip()))
assert ORDER, '规格里没有章节表'

def demote(s):
    lines, in_code = [], False
    for ln in s.split('\n'):
        if ln.startswith('```'): in_code = not in_code
        if not in_code and re.match(r'^#{1,5} ', ln): ln = '#' + ln
        lines.append(ln)
    return '\n'.join(lines)

titles = []
for f, _, _ in ORDER:
    if not f.endswith('.md'): continue
    s = open(os.path.join(B, f), encoding='utf-8').read()
    m = re.search(r'^#{1,2} (.+)$', s, flags=re.M)
    titles.append((f, m.group(1).strip()))
head = ['# 成功投资者心性养成指南', '',
        '**戒掉一把梭 · 练成守得住 · 一年训练手册** —— 把《道德经》提倡的心性（知止、知足、守静、不争、慎终如始、自胜者强）换算成可计数的日常练习，写给还在满仓梭哈、多次亏完本金、总觉得复利太慢的你。', '',
        '📘 电子书：[下载 EPUB](https://traceme.github.io/DDJ-investing/成功投资者心性养成指南.epub) ／ [下载 PDF](https://traceme.github.io/DDJ-investing/成功投资者心性养成指南.pdf)', '',
        '> 本书是训练手册，不是荐股，也不是医疗建议；账户一律用归一为 100 单位的案例账户；引文逐字、可核。完整声明见书末。', '']
body = []
for f, title, third in ORDER:
    if f == 'TOC':
        body += ['## 目录', '']
        for n, t in titles:
            if n.startswith('00-'): continue
            body.append(f'- {t}')
        body.append('')
    elif f.endswith('.md'):
        s = open(os.path.join(B, f), encoding='utf-8').read().rstrip('\n')
        body += [demote(s), '']            # 所有章文件一律降级：每个文件恰好一个 H1 → 书中的 H2
    else:
        body += [f'## {title}', '', third, '']
out = '\n'.join(head + body)
dst = os.path.join(ROOT, '成功投资者心性养成指南.md')
open(dst, 'w', encoding='utf-8').write(out)
print(f'{dst}: {len(out.encode())} 字节, {len(re.sub(r"\s", "", out))} 非空白字符, H2 {len(re.findall(r"^## ", out, flags=re.M))} 个')
