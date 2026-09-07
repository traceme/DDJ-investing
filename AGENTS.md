# Repository Guidelines

## Project Structure & Module Organization

This is a Chinese-language publishing repository, not an application. `chapters/` contains the original 81 essays; `codex/` contains the independent deep-analysis edition with per-chapter practical advice; both use names `第01章.md` through `第81章.md`. `thethirdeye/` contains 151 companion essays. `原文/道德经-王弼本.md` is the authoritative simplified-Chinese source for quoted scripture; treat `daodejing.md` as read-only input. Site files are `README.md`, `_sidebar.md`, `_coverpage.md`, and `index.html`; media live in `audiobook/` and root-level EPUB files. See `CLAUDE.md` for detailed editorial rules.

## Build, Test, and Development Commands

There is no application compilation step. Preview the Docsify site from the repository root:

```sh
python3 -m http.server 8000
```

Then visit `http://localhost:8000` and verify navigation, search, chapter pagination, and edited links. Rebuild the Codex EPUB with:

```sh
python3 scripts/build_codex_epub.py
python3 scripts/build_selection_epub.py
python3 scripts/build_jinbing_epub.py
python3 scripts/build_system_epub.py        # 三版一起构建；可加 playbook / catalog / system 只建一版
python3 playbook/assemble_book.py && python3 scripts/build_system_epub.py playbook   # 打法手册：先装配再构建
python3 system/render_catalog.py --render && python3 scripts/build_system_epub.py catalog   # 纪律总表：核对引文、渲染、构建 EPUB
python3 system/assemble_system.py && python3 system/validate_system.py && python3 scripts/build_system_epub.py system   # 投资系统：装配、校验、构建
```

These rebuild and validate the Codex EPUB, the 100-entry selection EPUB, the 72-article 渡人渡己 reading-notes EPUB, and 《道德经投资打法手册》 (assembled from `playbook/book/*.md` by `playbook/assemble_book.py`; run `python3 playbook/validate_book.py` first — it checks verbatim 《道德经》 quotes, registered rule IDs, lengths, and forbidden strings); plus 《道德经投资系统》 (assembled from `system/book/*.md`; `system/validate_system.py` asserts every cited `Cxx-nnn` exists in `system/data/纪律总表.json`, every `R` rule is registered, the 360-row matrix covers the catalog exactly, and 《道德经》 quotes are verbatim). `system/render_catalog.py` regenerates `投资纪律总表.md` and re-verifies all 2,526 quotes against the corpus files; `python3 scripts/build_system_epub.py catalog` builds `投资纪律总表.epub` (62 pages — the three long sections are split per category by the builder's `split_h3`, and the validator asserts all 360 ids survive the conversion). All require Python 3 and Pillow. The last one additionally verifies its quotes against the source PDF when it is present locally (PyMuPDF); the PDF itself is gitignored and never committed. Before committing, run:

```sh
git diff --check
git status --short
```

These catch whitespace errors and confirm the intended change set.

## Coding Style & Naming Conventions

Use UTF-8 Markdown and simplified Chinese. Filenames are zero-padded; companion files use three digits, such as `thethirdeye/第017章.md`. Chapters retain `# 第X章 · 核心句`, `## 原文`, `## 投资心法`, and `## 实操建议`, including their `<mark>` and `<u>` highlights. Essays should move from an everyday entry point to a concrete market scene, explain the quoted lines in plain language, and close with a memorable distillation. Advice must remain under 100 characters. Copy 原文 exactly from the authoritative source, including punctuation and editorial brackets. Use root-relative Docsify links.

## Testing Guidelines

Testing is editorial and manual. Compare every scripture change character-for-character with `原文/道德经-王弼本.md`; update that source and its editorial note first if a correction is required. The EPUB build also rejects a Codex essay whose normalized similarity to any main-book essay reaches 30%, or that reuses a complete paragraph of at least 50 characters. Preview affected pages at desktop and narrow widths. Confirm sidebar entries, README indexes, media links, and previous/next navigation. Do not present illustrative sectors or market events as stock recommendations, and verify quote attributions against primary sources.

## Commit & Pull Request Guidelines

History uses concise Chinese, feature-focused subjects, often `主题：具体变化`, for example `网站化：docsify 阅读站`. Keep each commit limited to one editorial or publishing concern. Pull requests should summarize the intent, list affected chapters/assets, describe validation performed, link relevant issues, and include screenshots when `index.html`, navigation, or rendered styling changes.
