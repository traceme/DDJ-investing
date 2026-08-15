# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Overview

This is a content repository, not a software project — there are no build, lint, or test commands and no code. It contains a Chinese-language book, 《道德经81章投资心法》, and its source material:

- `chapters/第01章.md` … `第81章.md` — the book: one essay per Tao Te Ching chapter (81 files, zero-padded names)
- `原文/道德经-王弼本.md` — the sole textual standard for all quoted 原文 (王弼通行本, split and numbered from `daodejing.md`; converted from traditional to simplified characters on 2026-08-15 per user request — the traditional original remains in `daodejing.md`; editorial and conversion notes in its header, e.g. 第33章 restoration, 第31章 校勘括号, 閒→间/繟-kept overrides)
- `README.md` — book index: 81-chapter table (core line, one-line essence, link) plus the unified disclaimer
- `验收报告.md` — acceptance report from the multi-agent build (seven criteria, per-group verdicts)
- `compass_artifact_wf-d0d02179-…_text_markdown.md` — the source essay 《道德经》里的投资心法 (100 entries in eight themes) whose insights the chapters absorbed; its Caveats section is the reference for quote attributions and textual variants
- `daodejing.md` — user-supplied raw text (unnumbered chapter markers); treat as read-only input

## Content Conventions

Every chapter file follows one fixed format — preserve it when editing:

- H1: `# 第X章 · 核心句` (Chinese-numeral chapter number + the chapter's most resonant line)
- `## 原文`: the full chapter as a blockquote, copied verbatim from `原文/道德经-王弼本.md` — simplified characters (base file is itself a t2s conversion; see its header for the conversion notes), including editorial brackets 〔〕 and small-form punctuation ﹖﹕﹗､, never paraphrased. Any 原文 change must first be made in the base file, with a header 校记 note.
- `## 投资心法`: a 600–1500-character simplified-Chinese essay in the established style: personal/life entry point → at least one concrete market scene (with sensory detail) → 先破后立 → circle back to the original lines → closing antithetical distillation (对仗式心法, e.g. "为学日益为向外求…／为道日损为向内修…"). Chapters on statecraft/war extend naturally into risk, cycles, or governance — never forced. No per-file disclaimer (README carries the single disclaimer).

Cross-cutting standards (apply to chapters and the compass essay alike):

- **Attribution rigor**: investor quotes must trace to verified primary sources; uncertain ones are phrased as paraphrase ("芒格说过，大意是……"). Known corrections stay corrected — the "stock forecasters / fortune tellers" line is Buffett (1992 shareholder letter), not Graham; Livermore's "sitting, not thinking" is Lefèvre's literary rendering in *Reminiscences of a Stock Operator*.
- **Empirical claims cite sources with scope limits**: e.g. Barber & Odean (2000, *The Journal of Finance*), 66,465 accounts, 1991–1996 US discount-broker sample — not extrapolated to today's Chinese market.
- **No stock tips**: sectors and episodes (光模块、2015配资牛市 etc.) appear only as illustrations of behavior, never recommendations.
