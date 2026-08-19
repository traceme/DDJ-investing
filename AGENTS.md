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
```

This rebuilds and validates the Codex EPUB; it requires Python 3 and Pillow. Before committing, run:

```sh
git diff --check
git status --short
```

These catch whitespace errors and confirm the intended change set.

## Coding Style & Naming Conventions

Use UTF-8 Markdown and simplified Chinese. Filenames are zero-padded; companion files use three digits, such as `thethirdeye/第017章.md`. Original chapters retain `# 第X章 · 核心句`, `## 原文`, then `## 投资心法`, including their `<mark>` and two `<u>` highlights. Codex chapters use `## 深层原理`, `## 投资推演`, and `## 实操建议`; advice must remain under 100 characters. In both editions, copy 原文 exactly from the authoritative source, including punctuation and editorial brackets. Use root-relative Docsify links.

## Testing Guidelines

Testing is editorial and manual. Compare every scripture change character-for-character with `原文/道德经-王弼本.md`; update that source and its editorial note first if a correction is required. Preview affected pages at desktop and narrow widths. Confirm sidebar entries, README indexes, media links, and previous/next navigation. Do not present illustrative sectors or market events as stock recommendations, and verify quote attributions against primary sources.

## Commit & Pull Request Guidelines

History uses concise Chinese, feature-focused subjects, often `主题：具体变化`, for example `网站化：docsify 阅读站`. Keep each commit limited to one editorial or publishing concern. Pull requests should summarize the intent, list affected chapters/assets, describe validation performed, link relevant issues, and include screenshots when `index.html`, navigation, or rendered styling changes.
