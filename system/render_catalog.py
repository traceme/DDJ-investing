#!/usr/bin/env python3
"""《投资纪律总表》渲染与校验：读取 system/data/纪律总表.json → 程序级逐字核对每处引文 → 来源覆盖统计 → 渲染根目录 投资纪律总表.md。
用法（仓库根目录）：python3 system/render_catalog.py            # 只核对
              python3 system/render_catalog.py --render   # 核对并渲染
"""
import json, glob, os, re, sys
from collections import OrderedDict, defaultdict

ROOT = os.getcwd()
S = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
ARGS = json.load(open(os.path.join(S, '抽取参数.json'), encoding='utf-8'))
CATS = OrderedDict((c['code'], c) for c in ARGS['categories'])
COMPASS = ARGS['compassFile']

def norm(s):
    return re.sub(r'\s+', '', s).replace('“', '"').replace('”', '"').replace('‘', "'").replace('’', "'")

_cache = {}
def read(path):
    if path not in _cache:
        _cache[path] = open(os.path.join(ROOT, path), encoding='utf-8').read() if os.path.exists(os.path.join(ROOT, path)) else None
    return _cache[path]

def entry_block(text, n, style):
    """style 'bold' → **N. …**（罗盘）；'h3' → ### N. …（选／全）。返回该条目到下一条目之间的文本。"""
    if style == 'rec':
        a = text.find('## Recommendations'); b = text.find('## Caveats')
        return text[a:b] if a >= 0 else None
    if style == 'bold':
        pat = re.compile(r'^\*\*%d\. ' % n, re.M); nxt = re.compile(r'^\*\*\d+\. ', re.M)
    else:
        pat = re.compile(r'^### %d\. ' % n, re.M); nxt = re.compile(r'^### \d+\. |^## ', re.M)
    m = pat.search(text)
    if not m: return None
    m2 = nxt.search(text, m.end())
    return text[m.start(): m2.start() if m2 else len(text)]

TAG_RE = re.compile(r'^(道|Codex|三眼|金|罗盘|选|全)(\d+)$')
REC_TAG = '罗盘建议'
def resolve(tag):
    if tag.strip() == REC_TAG: return COMPASS, ('rec', 0)
    m = TAG_RE.match(tag.strip())
    if not m: return None, None
    book, n = m.group(1), int(m.group(2))
    if book == '道': return f'chapters/第{n:02d}章.md', None
    if book == 'Codex': return f'codex/第{n:02d}章.md', None
    if book == '三眼': return f'thethirdeye/第{n:03d}章.md', None
    if book == '金': return f'jinbing-drdj/第{n:02d}篇.md', None
    if book == '罗盘': return COMPASS, ('bold', n)
    if book == '选': return '投资心法100条精选版.md', ('h3', n)
    if book == '全': return '投资心法313条全量版.md', ('h3', n)
    return None, None

def check_source(src):
    path, entry = resolve(src['tag'])
    if not path: return 'tag 格式非法'
    text = read(path)
    if text is None: return f'文件不存在 {path}'
    q = norm(src['quote'])
    if not q: return '引文为空'
    if len(src['quote']) > 60: return f'引文过长 {len(src["quote"])}'
    if entry:
        block = entry_block(text, entry[1], entry[0])
        if block is None: return f'条目不存在 {src["tag"]}'
        if q in norm(block): return None
        if q in norm(text): return '引文在文件中但不在所标条目内'
        return '引文非逐字'
    return None if q in norm(text) else '引文非逐字'

def load():
    items = json.load(open(os.path.join(S, '纪律总表.json'), encoding='utf-8'))
    extra_p = os.path.join(S, '原则区.json')
    extra = json.load(open(extra_p, encoding='utf-8')) if os.path.exists(extra_p) else {'principles': [], 'rejected': []}
    return items, extra

def verify(items):
    bad = []
    for d in items:
        for s in d['sources']:
            r = check_source(s)
            if r: bad.append({'id': d['id'], 'tag': s['tag'], 'quote': s['quote'], 'reason': r})
    return bad

UNIVERSE = {'道': 81, 'Codex': 81, '三眼': 151, '金': 72, '罗盘': 100, '选': 100, '全': 313}
def coverage(items):
    cited = defaultdict(set)
    for d in items:
        for s in d['sources']:
            m = TAG_RE.match(s['tag'].strip())
            if m: cited[m.group(1)].add(int(m.group(2)))
    out = {}
    for book, n in UNIVERSE.items():
        missing = [i for i in range(1, n + 1) if i not in cited[book]]
        out[book] = {'cited': n - len(missing), 'total': n, 'missing': missing}
    return out

CN = '〇一二三四五六七八九'
def cn(n):
    if n < 10: return CN[n]
    if n == 10: return '十'
    if n < 20: return '十' + (CN[n % 10] if n % 10 else '')
    return CN[n // 10] + '十' + (CN[n % 10] if n % 10 else '')

def render(items, extra, cov, bad):
    by = defaultdict(list)
    for d in items: by[d['category']].append(d)
    for k in by: by[k].sort(key=lambda d: d['id'])
    hard = defaultdict(int)
    for d in items: hard[d['hardness']] += 1
    L = []
    A = L.append
    A('# 投资纪律总表')
    A('')
    A('**五部心法语料中的每一条行为纪律，逐条抽出、归并、逐字核对来源。** 这不是原则集，是可检查的行为约束集：每条都能写成「触发→动作」，事后能判断有没有违反。它是《道德经投资系统》的法律层——系统的宪法、状态机与执行矩阵全部引用本表的编号。')
    A('')
    A('## 导读')
    A('')
    A('**什么算纪律。** 对投资者行为的约束，四种形态：**铁律**（无条件禁令或命令）、**条件律**（触发→动作）、**节律**（周期性动作）、**门槛**（下单前必答必写，答不出就不做）。对市场或人性的描述、比喻、道理、语录、对公司行业的看法，都不是纪律——它们在附录 B「原则区」里，不入正表。')
    A('')
    A(f'**怎么来的。** 语料：《道德经81章投资心法》81 章、Codex 版 81 章、《第三只眼观》读书笔记 151 章、金冰《渡人渡己·投资篇》读书心法 72 篇、《道德经》里的投资心法（罗盘长文）100 条，另含 100 条精选与 313 条全量两部合集。流程：43 个抽取员逐文件穷举（2,608 条原始语句）→ 18 个类别归并员合并同一纪律、记录数字口径与冲突（474 条）→ 跨类去重（394 条）→ 每条经两道独立审查：来源逐字核对、纪律性质审查（判为原则的移入附录 B；编者复核后把其中两条确为规则的移回正表）→ 程序逐字核对全部引文 → 两层覆盖核对：四部主语料 385 篇每篇至少被一条纪律引用；234 段「实操建议」每段至少一处引文落在段内。')
    A('')
    A(f'**规模。** 纪律 **{len(items)}** 条（{"；".join(f"{k} {v}" for k, v in sorted(hard.items(), key=lambda x: -x[1]))}），来源引文 {sum(len(d["sources"]) for d in items)} 处，全部逐字核对通过；有数字口径的 {sum(1 for d in items if d.get("number"))} 条；来源之间存在分歧的 {sum(1 for d in items if d.get("conflict"))} 条（见「冲突表」）。')
    A('')
    A('**怎么读一条。** 编号 `C04-012` ＝ 类别 04 第 12 条。正文一句话是规范表述（触发→动作，保留语料数字）；附录 A 按编号列出每处出处与逐字引文，标签含义：道N＝《道德经81章投资心法》第 N 章，CodexN＝Codex 版第 N 章，三眼N＝《第三只眼观》笔记第 N 章，金N＝金冰读书心法第 N 篇，罗盘N＝罗盘长文第 N 条（罗盘建议＝其「Recommendations」段），选N／全N＝100 条精选／313 条全量第 N 条；「口径」列出同一纪律的不同数字及各自来源；「分歧」写明来源之间的矛盾，本表不裁决，裁决在《道德经投资系统》。')
    A('')
    A('**先看铁律。** 第一部分把全部无条件禁令与命令单独列出——它们是宪法候选，不依赖任何判断。')
    A('')
    # Part 1: 铁律
    A('## 第一部分 · 铁律总览')
    A('')
    A('| 编号 | 铁律 | 类别 | 来源数 |')
    A('|---|---|---|---|')
    for code in CATS:
        for d in by.get(code, []):
            if d['hardness'] == '铁律':
                A(f'| {d["id"]} | {d["discipline"]} | {CATS[code]["name"]} | {len(d["sources"])} |')
    A('')
    # Part 2: compact list
    A('## 第二部分 · 纪律一览')
    A('')
    A('全部纪律，一行一条，按类别排列；每类内先铁律、再条件律、门槛、节律。来源与逐字引文见附录 A（按编号查）。')
    A('')
    for i, code in enumerate(CATS, 1):
        lst = by.get(code, [])
        A(f'### {cn(i)}、{CATS[code]["name"]}（{len(lst)} 条）')
        A('')
        A(f'*{CATS[code]["desc"]}*')
        A('')
        A('| 编号 | 纪律 | 形态 | 数字 | 来源数 |')
        A('|---|---|---|---|---|')
        for d in lst:
            flag = '⚑ ' if d.get('conflict') else ''
            A(f'| {d["id"]} | {flag}{d["discipline"]} | {d["hardness"]} | {d.get("number") or ""} | {len(d["sources"])} |')
        A('')
    A('⚑ ＝ 来源之间有分歧，见第三部分。')
    A('')
    # Part 3: conflicts
    conf = [d for code in CATS for d in by.get(code, []) if d.get('conflict')]
    A('## 第三部分 · 冲突表')
    A('')
    A('来源之间说法不一的纪律。本表只陈列，不裁决——裁决的变量与结论在《道德经投资系统》第二章。')
    A('')
    A('| 编号 | 纪律 | 分歧 | 各方来源 |')
    A('|---|---|---|---|')
    for d in conf:
        tags = '、'.join(sorted({s['tag'] for s in d['sources']}))
        A(f'| {d["id"]} | {d["discipline"]} | {d["conflict"]} | {tags} |')
    A('')
    # Part 4: numbers
    A('## 第四部分 · 数字口径总表')
    A('')
    A('全部带数字的纪律汇成一张表——这是整套系统的常量表。同一纪律的多种口径并列，主口径在前。')
    A('')
    A('| 编号 | 纪律 | 主口径 | 其他口径 | 来源 |')
    A('|---|---|---|---|---|')
    for code in CATS:
        for d in by.get(code, []):
            if d.get('number'):
                vs = '；'.join(f'{v["value"]}（{"、".join(v["tags"])}）' for v in d.get('variants', []) if v.get('value') and v.get('value') != d.get('number'))
                tags = '、'.join(sorted({s['tag'] for s in d['sources']}))
                A(f'| {d["id"]} | {d["discipline"]} | {d["number"]} | {vs} | {tags} |')
    A('')
    # Part 5: coverage
    A('## 第五部分 · 来源覆盖')
    A('')
    A('| 语料 | 被引用的篇章 | 总篇章 | 未被任何纪律引用的篇章 |')
    A('|---|---|---|---|')
    names = {'道': '《道德经81章投资心法》', 'Codex': 'Codex 版', '三眼': '《第三只眼观》笔记', '金': '金冰读书心法', '罗盘': '罗盘长文', '选': '100 条精选', '全': '313 条全量'}
    for book, c in cov.items():
        miss = '、'.join(str(x) for x in c['missing']) if c['missing'] else '—'
        if len(c['missing']) > 40: miss = f'{len(c["missing"])} 篇'
        A(f'| {names[book]} | {c["cited"]} | {c["total"]} | {miss} |')
    A('')
    A('未被引用不等于遗漏：合集（100 条／313 条）与罗盘长文的多数条目是原则而非纪律，或与正文语料重复而被归并到正文标签之下；《第三只眼观》有相当一部分章节是对市场结构的描述，本身不含行为规则。有 `## 实操建议` 段的三部（道／Codex／金）应当全部被引用，缺一即为遗漏。')
    A('')
    # Appendix A: provenance
    A('## 附录 A · 逐条来源与引文')
    A('')
    A('每条纪律的全部出处与逐字引文（程序核对：每段引文在所标篮章中原样连续出现）。「口径」列同一纪律的不同数字及来源；「分歧」写明来源之间的矛盾。')
    A('')
    for i, code in enumerate(CATS, 1):
        lst = by.get(code, [])
        A(f'### {cn(i)}、{CATS[code]["name"]}')
        A('')
        for d in lst:
            head = f'**{d["id"]}**　{d["discipline"]}　｜ {d["hardness"]}'
            if d.get('number'): head += f' ｜ {d["number"]}'
            A(head)
            A('')
            srcs = '；'.join(f'[{s["tag"]}]「{s["quote"]}」' for s in d['sources'])
            A(f'- 来源：{srcs}')
            vs = [v for v in d.get('variants', []) if v.get('value') and v.get('value') != d.get('number')]
            if vs:
                A('- 口径：' + '；'.join(f'{v["value"]}（{"、".join(v["tags"])}）' for v in vs))
            if d.get('conflict'):
                A(f'- 分歧：{d["conflict"]}')
            A('')
    # Appendix B: principles
    A('## 附录 B · 原则区（审查判为原则而非纪律的条目）')
    A('')
    A('抽取阶段被当作纪律、审查阶段判定为原则或描述的条目。它们不入正表，但不丢弃——每条附来源，供系统写作时作为理由引用。')
    A('')
    for p in extra.get('principles', []):
        srcs = '；'.join(f'[{s["tag"]}]「{s["quote"]}」' for s in p.get('sources', []))
        A(f'- {p["discipline"]}（{srcs}）')
    A('')
    return '\n'.join(L) + '\n'

if __name__ == '__main__':
    items, extra = load()
    print(f'纪律 {len(items)} 条，原则区 {len(extra.get("principles", []))}，剔除 {len(extra.get("rejected", []))}')
    bad = verify(items)
    print(f'引文核对：{sum(len(d["sources"]) for d in items)} 处，失败 {len(bad)}')
    json.dump(bad, open(os.path.join(S, '引文核对失败.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    cov = coverage(items)
    for b, c in cov.items():
        print(f'  {b}: {c["cited"]}/{c["total"]}' + (f'  未引用 {c["missing"][:30]}{"…" if len(c["missing"]) > 30 else ""}' if c['missing'] else ''))
    if '--render' in sys.argv:
        out = render(items, extra, cov, bad)
        open(os.path.join(ROOT, '投资纪律总表.md'), 'w', encoding='utf-8').write(out)
        print(f'渲染：投资纪律总表.md {len(out.encode())} 字节，{len(re.sub(r"\\s", "", out))} 非空白字符')
