#!/usr/bin/env python3
"""装配《道德经投资系统》：system/book/*.md → 道德经投资系统.md（仓库根目录）。
章文件 H1→H2、H2→H3、H3→H4；卷首与免责声明的 H2 原样保留。
顺带生成附录 B（一页纸宪法，抄自第一章的表）与附录 C（道德经原文对照）。"""
import re, os, glob
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
B = os.path.join(ROOT, 'system', 'book')
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

def read(name): return open(os.path.join(B, name), encoding='utf-8').read().rstrip('\n')

def demote(s):
    out, code = [], False
    for ln in s.split('\n'):
        if ln.startswith('```'): code = not code
        if not code and re.match(r'^#{1,5} ', ln): ln = '#' + ln
        out.append(ln)
    return '\n'.join(out)

def matrix_chapter():
    parts = sorted(glob.glob(os.path.join(B, '07[a-f]-*.md')))
    head = read('07-执行矩阵.md') if os.path.exists(os.path.join(B, '07-执行矩阵.md')) else '# 第七章 · 执行矩阵'
    body = [head, '']
    total = 0
    for p in parts:
        s = open(p, encoding='utf-8').read().strip('\n')
        # 去掉写手文件顶部的斜体说明行
        lines = s.split('\n')
        if lines and lines[0].startswith('*') and lines[0].endswith('*'): lines = lines[1:]
        s = '\n'.join(lines).strip('\n')
        total += len(re.findall(r'^\| C\d\d-\d{3} \|', s, flags=re.M))
        body += [s, '']
    body.append(f'**全表统计：** 纪律 {total} 条，每条一行；覆盖核对由 `python3 system/validate_system.py` 执行（矩阵编号集合必须与《投资纪律总表》编号集合完全相等）。')
    return '\n'.join(body), total

def appendix_b():
    s = read('01-宪法.md')
    m = re.search(r'^\| 条 \| 条文 \| 违反即 \|\n\|---\|---\|---\|\n((?:\|.*\|\n?)+)', s, flags=re.M)
    table = m.group(0).strip() if m else ''
    return '# 附录 B · 一页纸宪法（打印版）\n\n打印本页，贴在下单页旁（C04-029）。下单前逐条扫过，扫不过去就不下。修改只在年度修宪窗口（§5.3）。\n\n' + table + '\n'

def appendix_c(chapter_texts):
    txt = open(os.path.join(ROOT, '原文', '道德经-王弼本.md'), encoding='utf-8').read()
    parts = re.split(r'^## 第(\d+)章\s*$', txt, flags=re.M)
    DDJ = {int(parts[i]): parts[i + 1].strip() for i in range(1, len(parts), 2)}
    cites = {}
    for title, s in chapter_texts:
        for m in re.finditer(r'^>[ \t　]*(.+?)[ \t　]*——[ \t　]*《道德经》第([一二三四五六七八九十零]+)章', s, flags=re.M):
            cites.setdefault(cn2int(m.group(2)), []).append((title, m.group(1).strip()))
    out = ['# 附录 C · 《道德经》原文对照', '', '正文引用的《道德经》章句，按原文章号汇编，附王弼通行本全文（简体，取自本项目 `原文/道德经-王弼本.md`）。', '']
    for ch in sorted(cites):
        out += [f'## 第{int2cn(ch)}章', '', '> ' + DDJ[ch].replace('\n', '\n> '), '']
        for t, q in cites[ch]: out.append(f'- 引于{t}：{q}')
        out.append('')
    out.append(f'共引用 {len(cites)} 章，{sum(len(v) for v in cites.values())} 处。')
    return '\n'.join(out) + '\n'

def main():
    chapters = ['01-宪法.md', '02-状态机.md', '03-权限引擎.md', '04-裁决.md', '05-审计与修宪.md', '06-接口.md']
    texts = []
    for c in chapters:
        s = read(c); t = re.search(r'^# (.+)$', s, flags=re.M).group(1).strip(); texts.append((t, s))
    matrix, total = matrix_chapter()
    texts.append((re.search(r'^# (.+)$', matrix, flags=re.M).group(1).strip(), matrix))
    appA = read('A-新增规则注册表.md'); appB = appendix_b(); appC = appendix_c(texts); appD = read('D-表单.md')
    head = ['# 道德经投资系统', '',
            '**宪法 · 状态机 · 权限引擎 · 裁决 · 审计与修宪 · 执行矩阵** —— 坐在心法、纪律总表与打法手册之上的第四层：一台让你在最坏的日子也只能做对的事的机器。', '',
            '📘 电子书：[下载 EPUB](https://traceme.github.io/DDJ-investing/道德经投资系统.epub)（含封面与分级目录，可导入微信读书、Apple Books、Kindle 等阅读器）　｜　法源：[投资纪律总表](投资纪律总表.md)　｜　算法：[道德经投资打法手册](道德经投资打法手册.md)', '',
            '> 本书是方法论，不是荐股；示例参数来自归一为 100 单位的案例账户；每条规定引用《投资纪律总表》编号 `Cxx-nnn` 与手册规则 `Rx.y`。完整声明见书末。', '']
    toc = ['## 目录', '']
    for t, _ in texts: toc.append(f'- {t}')
    toc += ['- 附录 A · 新增规则注册表（R18）', '- 附录 B · 一页纸宪法（打印版）', '- 附录 C · 《道德经》原文对照', '- 附录 D · 表单字段', '- 免责声明', '']
    body = [read('00-卷首.md'), ''] + toc
    for _, s in texts: body += [demote(s), '']
    body += ['## 附录', '', '新增规则的索引、可打印的一页纸、引用过的《道德经》章句全文，以及执行矩阵检测器所依赖的表单字段。', '']
    body += [demote(appA), '', demote(appB), '', demote(appC), '', demote(appD), '', read('Z-免责声明.md'), '']
    out = '\n'.join(head + body)
    dst = os.path.join(ROOT, '道德经投资系统.md')
    open(dst, 'w', encoding='utf-8').write(out)
    print(f'{dst}: {len(out.encode())} 字节, {len(re.sub(r"\s", "", out))} 非空白字符, 矩阵 {total} 行, H2 {len(re.findall(r"^## ", out, flags=re.M))} 个')

if __name__ == '__main__':
    main()
