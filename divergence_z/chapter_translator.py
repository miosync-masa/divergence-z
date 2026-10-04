#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Chapter Translator v1.2
キャラクター構築系の出力（cast / persona / episode）＋これまでの訳文を LLM に渡し、章単位で一括翻訳する

旧 Z軸翻訳系（old/）は「行ごとに z / z_mode を推定 → 訳す → ZAP/IAP で採点」だったが、
推定も採点もヒューリスティックで判定不能だった。現行は:

  [build]  cast_extractor       → 人物表（誰が、本文でどう呼ばれているか）
           persona_extractor_v2 → persona（この人は誰か）
           episode_extractor    → episode（この人は何を経験したか）
  [translate]
           chapter_translator   → 章ごとに:
             原文（段落番号付き）
             ＋ その章の登場人物の persona
             ＋ episode（この章より前 / この章 / この先 を区別）
             ＋ 訳語表（前章までの訳語・声の決定。章ごとに追記して持ち回る）
             ＋ 直前 N 章の訳文
             → 訳文（同じ段落番号）＋ 訳語表への追記
  [check]  機械的に検査できるものだけ（段落の欠落・余剰、台詞数のズレ）

Usage:
    cd divergence_z
    python chapter_translator.py \\
      --source ../../divergence-z/scripts/STARGAZER/ \\
      --cast casts/STARGAZER_cast.yaml \\
      --target-lang en \\
      --chapters 0-2

    # persona / episode は cast のラベルから personas/ episodes/ を自動探索。明示するなら:
    python chapter_translator.py ... \\
      --persona "宇宙から来た少女=personas/宇宙から来た少女_extracted_v33.yaml" \\
      --episode "宇宙から来た少女=episodes/宇宙から来た少女_Episode.yaml"

出力（--out-dir、既定 translations/{source名}_{lang}/）:
    {章}.{lang}.md            訳文（Markdown 構造を保持）
    {章}.{lang}.segments.json 原文と訳文の段落対応
    translation_notes.yaml    訳語表（章をまたいで持ち回る。手で直してよい）
既に訳済みの章はスキップ（--force で再翻訳）。

v1.2: 長い章は LLM が場面単位のセクションに分け（計画）、セクションごとに1回推論して訳す。
      各セクションには章の計画・直前の訳文・そのセクションの登場人物の資料だけを渡す。
      途中経過を {章}.{lang}.work.json に保存し、中断してもセクション単位で再開する
v1.1: ライブラリ化（open_book / translate_chapter）、LLM 呼び出しを core.llm に統一（BYOK）
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from divergence_z.core import (EFFORTS, LLM, FitReport, Keys, LLMResult, Progress, check_fit,
                               collect_source_files, dump_yaml, get_model, iter_episodes,
                               load_source_file,
                               print_progress, resolve_progress)
from divergence_z.persona_extractor_v2 import DEFAULT_MODEL, SUPPORTED_LANGUAGES

DEFAULT_EFFORT = "high"

NOTES_FILE = "translation_notes.yaml"


# =============================================================================
# SEGMENTATION
# =============================================================================

def segment_chapter(text: str) -> List[Dict[str, str]]:
    """
    章を段落単位に分割して番号を振る。
    空行区切りを1段落とし、``` コードブロックは中の空行ごと1段落として扱う。
    """
    segments: List[str] = []
    buf: List[str] = []
    in_code = False

    for line in text.splitlines():
        if line.strip().startswith("```"):
            in_code = not in_code
            buf.append(line)
            continue
        if not in_code and not line.strip():
            if buf:
                segments.append("\n".join(buf))
                buf = []
            continue
        buf.append(line)
    if buf:
        segments.append("\n".join(buf))

    # 青空文庫などは段落の間に空行が無く「1行 = 1段落」。ブロック内で全角スペースや
    # 鉤括弧から始まる行は新しい段落として分ける（コードブロック・見出しの続きはそのまま）
    split: List[str] = []
    for block in segments:
        lines = block.split("\n")
        if block.lstrip().startswith("```") or len(lines) == 1:
            split.append(block)
            continue
        cur: List[str] = []
        for line in lines:
            if cur and _PARA_START.match(line):
                split.append("\n".join(cur))
                cur = []
            cur.append(line)
        split.append("\n".join(cur))

    return [{"id": f"P{i:03d}", "text": s} for i, s in enumerate(split, 1)]


_PARA_START = re.compile(r"^[　「『（(]")


def render_segments(segments: List[Dict[str, str]]) -> str:
    return "\n".join(f'<seg id="{s["id"]}">\n{s["text"]}\n</seg>' for s in segments)


_SEG_RE = re.compile(r'<seg id="(P\d+)">\n?(.*?)\n?</seg>', re.S)


def parse_segments(text: str) -> Dict[str, str]:
    return {m.group(1): m.group(2).strip("\n") for m in _SEG_RE.finditer(text)}


# =============================================================================
# CONTEXT: cast / persona / episode / notes
# =============================================================================

def _label_variants(label: str) -> List[str]:
    """各ツールの保存名規則に合わせた候補
    persona_extractor_v2: 小文字化して英数字・_・- 以外を除去（「・」は消える）
    persona_generator:    小文字化して空白と「・」を _ に、英数と _ 以外を除去
    episode_*:            空白を _ に（「・」は残る）"""
    underscored = label.replace(" ", "_")
    lowered = re.sub(r"[^\w\-]", "", label.lower().replace(" ", "_"))
    generated = "".join(c for c in label.lower().replace(" ", "_").replace("・", "_")
                        if c.isalnum() or c == "_")
    return list(dict.fromkeys([label, underscored, lowered, generated]))


def find_character_file(label: str, directory: Path, kind: str) -> Optional[Path]:
    if not directory.is_dir():
        return None
    for v in _label_variants(label):
        if kind == "persona":
            # 抽出版 > Web 生成版（日本語）> Web 生成版（他言語 {name}_v33_{lang}.yaml）
            candidates = [directory / f"{v}_extracted_v33.yaml", directory / f"{v}_v33.yaml",
                          *sorted(directory.glob(f"{glob_escape(v)}_v33_*.yaml"))]
        else:
            candidates = [directory / f"{v}_Episode.yaml", directory / f"{v}_Episode_full.yaml"]
        for c in candidates:
            if c.exists():
                return c
    return None


def glob_escape(text: str) -> str:
    return re.sub(r"([*?\[\]])", r"[\1]", text)


def parse_overrides(items: List[str]) -> Dict[str, Path]:
    out: Dict[str, Path] = {}
    for item in items:
        if "=" not in item:
            raise SystemExit(f"Expected LABEL=PATH, got: {item}")
        label, path = item.split("=", 1)
        out[label.strip()] = Path(path.strip())
    return out


def chapter_position(ref: str, chapter_names: List[str]) -> Optional[int]:
    """source_episode 等の文字列に含まれる章ファイル名から、最初の章の位置を返す"""
    hits = [i for i, name in enumerate(chapter_names) if name in ref or Path(name).stem in ref]
    return min(hits) if hits else None


def render_episodes(episode_yaml: Dict[str, Any], chapter_names: List[str],
                    current: int) -> str:
    """episode を「この章より前 / この章 / この先」に分けて渡す"""
    episodes = iter_episodes(episode_yaml)

    past, now, future, unknown = [], [], [], []
    for ep in episodes:
        pos = chapter_position(str(ep.get("source_episode", "")), chapter_names)
        if pos is None:
            unknown.append(ep)
        elif pos < current:
            past.append(ep)
        elif pos == current:
            now.append(ep)
        else:
            future.append(ep)

    def dump(eps: List[Dict[str, Any]], keys: List[str]) -> str:
        slim = [{k: e[k] for k in keys if k in e} for e in eps]
        return yaml.safe_dump(slim, allow_unicode=True, sort_keys=False, width=1000)

    full = ["episode_id", "source_episode", "title", "summary", "emotional_detail",
            "canonical_quotes", "z_relevance", "character_state_change"]
    brief = ["episode_id", "source_episode", "title", "summary", "character_state_change"]
    parts = []
    if past:
        parts.append("#### ALREADY HAPPENED (the character carries these)\n" + dump(past, brief))
    if now:
        parts.append("#### HAPPENS IN THIS CHAPTER\n" + dump(now, full))
    if future:
        parts.append("#### HAS NOT HAPPENED YET (for weight/foreshadowing awareness only — "
                     "the character does not know this; do not leak it)\n"
                     + dump(future, ["episode_id", "source_episode", "title"]))
    if unknown:
        parts.append("#### TIMING UNKNOWN\n" + dump(unknown, brief))
    return "\n".join(parts)


def load_notes(out_dir: Path) -> Dict[str, Any]:
    path = out_dir / NOTES_FILE
    if path.exists():
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if isinstance(data, dict):
            return data
    return {"glossary": [], "voice": [], "style": []}


def merge_notes(notes: Dict[str, Any], new: Dict[str, Any], chapter: str) -> Dict[str, Any]:
    """glossary は source、voice は character+aspect をキーに上書き、style は追記"""
    keys = {"glossary": ("source",), "voice": ("character", "aspect"), "style": ("decision",)}
    for section, key_fields in keys.items():
        existing = notes.setdefault(section, []) or []
        index = {tuple(str(e.get(k, "")) for k in key_fields): i
                 for i, e in enumerate(existing) if isinstance(e, dict)}
        for entry in new.get(section) or []:
            if not isinstance(entry, dict):
                continue
            entry = {**entry, "since": entry.get("since", chapter)}
            k = tuple(str(entry.get(f, "")) for f in key_fields)
            if k in index:
                entry["since"] = existing[index[k]].get("since", chapter)
                existing[index[k]] = entry
            else:
                index[k] = len(existing)
                existing.append(entry)
        notes[section] = existing
    return notes


# =============================================================================
# PROMPTS
# =============================================================================

def build_system_prompt(target_lang: str) -> str:
    lang = SUPPORTED_LANGUAGES.get(target_lang, target_lang)
    return f"""You are a literary translator for the Divergence-Z project, translating a work of fiction
into {lang} as a single coherent book. Long chapters are translated one SECTION at a time
(a scene or a run of related scenes); you translate exactly the section you are given.

## WHAT YOU ARE GIVEN
- CAST SHEET: the characters in this section — how the text refers to each of them (often by
  description or pronoun, not by name) and how to tell them apart — plus who narrates the chapter.
- PERSONAS: for each character in this section — who they are (identity_core), how they speak in the
  original (original_speech_patterns), and recommended compensations for the target language
  (translation_compensations). emotion_states describe how their speech shifts under emotion.
- EPISODE MEMORY: what each character has lived through, split into what already happened,
  what happens in this chapter, and what has not happened yet.
- TRANSLATION NOTES: decisions already made (glossary, character voice, style). Binding unless
  clearly wrong here.
- CHAPTER PLAN: every section of this chapter with a summary, so you know where this section sits.
- TRANSLATION SO FAR: your own translation of what comes immediately before this section.
- THIS SECTION: the source text, split into numbered segments <seg id="P001">…</seg>.

## HOW TO TRANSLATE
1. Translate as literature, not line by line. Read the whole section first, and keep continuity
   with TRANSLATION SO FAR (voice, tense, rhythm, names).
2. Each character must sound like THEMSELVES in {lang}: use the persona to decide register, rhythm,
   verbal tics, how broken or fluent their speech is, and how it changes with emotion.
   A line's weight comes from the episodes behind it — let that shape word choice.
3. Resolve every pronoun/description to the right person using the cast sheet before translating.
4. Wordplay, non-standard grammar, mispronunciations, dialect, and language-learning speech are
   meaning, not noise: find a {lang} equivalent that does the same job, and record the decision.
5. Words already in a foreign/alien language in the source stay as they are.
6. Do not replace culture-specific items (brand names, foods, religious terms, units, currency) with
   {lang}-culture equivalents: keep them, transliterating where needed. Localization is a separate,
   recorded step after translation.
7. Keep markdown exactly: headings, **bold**, ``` code blocks ``` (translate their contents, keep layout),
   --- separators; bracket styles may be adapted to {lang} conventions consistently.
8. Do not add, omit, merge, or split segments. Every input segment id appears exactly once in output.
9. Follow TRANSLATION NOTES. If you must deviate, add an updated entry explaining why.

## OUTPUT FORMAT (exactly this, nothing else)
<translation>
<seg id="P001">
…translated text…
</seg>
… (every segment of THIS SECTION, same ids, same order)
</translation>
<notes>
glossary:            # NEW or CHANGED decisions only (terms, names, invented words, recurring phrases)
  - source: "当機"
    target: "this unit"
    note: "why"
voice:               # NEW or CHANGED decisions about how a character sounds in {lang}
  - character: "cast label"
    aspect: "e.g. broken speech / first person / catchphrase"
    decision: "how it is rendered"
style:               # NEW chapter-independent conventions (punctuation, brackets, tense…)
  - decision: "…"
</notes>
Write the notes block as valid YAML. Use [] for an empty section."""


PLAN_SYSTEM = """You plan the translation of one long chapter of a work of fiction.
The chapter will be translated section by section, one model call per section, so each
section must be readable on its own with a short summary of the rest.

Split the chapter into SECTIONS at natural boundaries: scene changes, shifts of place or time,
a change of who is talking, a new narrative movement. Never cut inside a conversation or a
continuous action if you can avoid it. Each section must stay at or below the character limit
given (the char count of every segment is shown); prefer fewer, larger sections over many tiny ones.

For each section also list the characters who appear, speak, or are referred to in a way that
matters for translation, using EXACT labels from the CAST LABELS list (use [] if nobody), give a
2–3 sentence summary, and note anything a translator must watch (wordplay, a pronoun that points to
someone unexpected, a recurring phrase, a voice change).

Output ONLY this JSON, nothing else:
{"sections": [
  {"start": "P001", "end": "P034", "title": "short title",
   "characters": ["cast label", "..."],
   "summary": "what happens",
   "translation_focus": "what to watch"}
]}
Sections must be contiguous, in order, and together cover every segment exactly once."""


def build_user_prompt(chapter_name: str, segments: List[Dict[str, str]], cast_text: str,
                      personas: Dict[str, str], episodes: Dict[str, str],
                      notes: Dict[str, Any], so_far: List[Tuple[str, str]],
                      narration: str, target_lang: str, plan_text: str = "",
                      section_label: str = "") -> str:
    parts: List[str] = []
    if cast_text:
        parts.append("## CAST SHEET\n```yaml\n" + cast_text.strip() + "\n```")
    if narration:
        parts.append("## NARRATION OF THIS CHAPTER\n" + narration)
    for label, text in personas.items():
        parts.append(f"## PERSONA: {label}\n```yaml\n{text.strip()}\n```")
    for label, text in episodes.items():
        parts.append(f"## EPISODE MEMORY: {label}\n{text}")
    parts.append("## TRANSLATION NOTES (binding)\n```yaml\n" + dump_yaml(notes) + "```")
    if plan_text:
        parts.append(f"## CHAPTER PLAN: {chapter_name}\n{plan_text}")
    for name, text in so_far:
        parts.append(f"## TRANSLATION SO FAR ({name})\n{text}")
    where = f"{chapter_name} — {section_label}" if section_label else chapter_name
    parts.append(f"## THIS SECTION: {where}\n{render_segments(segments)}")
    parts.append(f"Translate THIS SECTION into {SUPPORTED_LANGUAGES.get(target_lang, target_lang)}. "
                 f"Output <translation> with all {len(segments)} segments, then <notes>.")
    return "\n\n".join(parts)


# =============================================================================
# CHECKS (deterministic only)
# =============================================================================

_SRC_DIALOGUE = re.compile(r"「")
_TGT_DIALOGUE = re.compile(r"[“「«]|(?:^|\s)\"")


def check_alignment(segments: List[Dict[str, str]], translated: Dict[str, str]) -> List[str]:
    issues: List[str] = []
    ids = [s["id"] for s in segments]
    missing = [i for i in ids if not translated.get(i, "").strip()]
    extra = [i for i in translated if i not in ids]
    if missing:
        issues.append(f"missing segments: {', '.join(missing)}")
    if extra:
        issues.append(f"unexpected segments: {', '.join(extra)}")
    for s in segments:
        t = translated.get(s["id"], "")
        n_src = len(_SRC_DIALOGUE.findall(s["text"]))
        n_tgt = len(_TGT_DIALOGUE.findall(t))
        # 引用符の数は言語の慣習で変わる（仏語は « …, dit-il, … » と1組にまとめる等）ので、
        # 台詞が丸ごと消えた場合だけを検出する
        if n_src and t and n_tgt == 0:
            issues.append(f"{s['id']}: dialogue missing ({n_src} quote(s) in source, none in translation)")
    return issues


# =============================================================================
# LIBRARY
# =============================================================================

@dataclass
class Book:
    """翻訳対象の作品と、その章ごとに渡す人物資料"""
    source: Path
    files: List[Path]
    cast_text: str = ""
    cast: Dict[str, Any] = field(default_factory=dict)
    persona_paths: Dict[str, Path] = field(default_factory=dict)
    episode_paths: Dict[str, Path] = field(default_factory=dict)
    appears: Dict[str, List[str]] = field(default_factory=dict)
    narration_by_file: Dict[str, str] = field(default_factory=dict)

    @property
    def chapter_names(self) -> List[str]:
        return [f.name for f in self.files]

    @property
    def characters(self) -> List[str]:
        return list(dict.fromkeys(list(self.persona_paths) + list(self.episode_paths)))

    def present_in(self, idx: int) -> List[str]:
        """その章に登場し、persona / episode がある人物"""
        name = self.files[idx].name
        return [l for l in self.characters if not self.appears.get(l) or name in self.appears[l]]

    @property
    def cast_labels(self) -> List[str]:
        return [c["label"] for c in self.cast.get("characters") or [] if c.get("label")]

    def cast_present_in(self, idx: int) -> List[str]:
        """人物表でその章に登場する人物（資料の有無は問わない）。人物表が無ければ資料のある全員"""
        if not self.cast_labels:
            return self.characters
        name = self.files[idx].name
        return [l for l in self.cast_labels if not self.appears.get(l) or name in self.appears[l]]

    def cast_subset(self, labels: List[str]) -> str:
        """人物表のうち labels の人物のエントリだけを YAML で返す（語りは別に渡す）"""
        if not self.cast:
            return ""
        wanted = set(labels)
        chars = [c for c in self.cast.get("characters") or [] if c.get("label") in wanted]
        return dump_yaml({"work": self.cast.get("work", ""), "characters": chars}) if chars else ""


def open_book(source: str, cast_path: str = "", persona_dir: str = "personas",
              episode_dir: str = "episodes",
              persona_overrides: Optional[Dict[str, Path]] = None,
              episode_overrides: Optional[Dict[str, Path]] = None) -> Book:
    """章フォルダ・人物表を読み、cast のラベルごとに persona / episode を解決する"""
    files = collect_source_files(source)
    cast_text = Path(cast_path).read_text(encoding="utf-8") if cast_path else ""
    cast = (yaml.safe_load(cast_text) or {}) if cast_text else {}
    persona_overrides = persona_overrides or {}
    episode_overrides = episode_overrides or {}

    book = Book(Path(source), files, cast_text, cast)
    labels = [c.get("label") for c in cast.get("characters") or [] if c.get("label")]
    for label in dict.fromkeys(labels + list(persona_overrides) + list(episode_overrides)):
        p = persona_overrides.get(label) or find_character_file(label, Path(persona_dir), "persona")
        e = episode_overrides.get(label) or find_character_file(label, Path(episode_dir), "episode")
        if p:
            book.persona_paths[label] = p
        if e:
            book.episode_paths[label] = e

    book.appears = {c["label"]: c.get("appears_in") or []
                    for c in cast.get("characters") or [] if c.get("label")}
    for n in cast.get("narration") or []:
        for f in n.get("files") or []:
            book.narration_by_file[f] = (f"narrator: {n.get('narrator')} / style: {n.get('style')}\n"
                                         f"{n.get('notes', '')}")
    return book


def chapter_output_path(book: Book, idx: int, out_dir: Path, target_lang: str) -> Path:
    return out_dir / f"{book.files[idx].stem}.{target_lang}.md"


def _work_path(book: Book, idx: int, out_dir: Path, target_lang: str) -> Path:
    return out_dir / f"{book.files[idx].stem}.{target_lang}.work.json"


# --- chapter plan (LLM がセクションに分ける) ------------------------------------------

@dataclass
class Section:
    id: str
    start: int                 # segments のインデックス（含む）
    end: int                   # segments のインデックス（含む）
    title: str = ""
    characters: List[str] = field(default_factory=list)
    summary: str = ""
    focus: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "start": self.start, "end": self.end, "title": self.title,
                "characters": self.characters, "summary": self.summary, "focus": self.focus}


def _chars(segments: List[Dict[str, str]], a: int, b: int) -> int:
    return sum(len(s["text"]) for s in segments[a:b + 1])


def split_by_chars(segments: List[Dict[str, str]], a: int, b: int, limit: int) -> List[Tuple[int, int]]:
    """[a, b] を段落の区切りで limit 字以下の塊に分ける（計画のフォールバック・長すぎるセクション用）"""
    spans, start, size = [], a, 0
    for i in range(a, b + 1):
        n = len(segments[i]["text"])
        if size and size + n > limit:
            spans.append((start, i - 1))
            start, size = i, 0
        size += n
    spans.append((start, b))
    return spans


def render_plan(sections: List[Section], segments: List[Dict[str, str]], current: str = "") -> str:
    lines = []
    for s in sections:
        mark = "  ← THIS SECTION" if s.id == current else ""
        lines.append(f"- {s.id} [{segments[s.start]['id']}–{segments[s.end]['id']}] {s.title}{mark}\n"
                     f"  characters: {', '.join(s.characters) or '—'}\n"
                     f"  summary: {s.summary}" + (f"\n  watch: {s.focus}" if s.focus else ""))
    return "\n".join(lines)


def _parse_plan(text: str, segments: List[Dict[str, str]], labels: List[str],
                limit: int) -> Optional[List[Section]]:
    """計画 JSON を検証して Section にする。連続性・網羅性が崩れていれば None"""
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    index = {s["id"]: i for i, s in enumerate(segments)}
    out: List[Section] = []
    expected = 0
    for raw in data.get("sections") or []:
        a, b = index.get(str(raw.get("start"))), index.get(str(raw.get("end")))
        if a is None or b is None or a != expected or b < a:
            return None
        chars = [c for c in raw.get("characters") or [] if c in labels]
        # 上限を大きく超えたセクションは段落の区切りで分ける（同じ計画情報を引き継ぐ）
        for k, (x, y) in enumerate(split_by_chars(segments, a, b, int(limit * 1.3))
                                   if _chars(segments, a, b) > limit * 1.3 else [(a, b)]):
            title = str(raw.get("title", "")) + (f" ({k + 1})" if k else "")
            out.append(Section("", x, y, title, chars, str(raw.get("summary", "")),
                               str(raw.get("translation_focus", ""))))
        expected = b + 1
    if expected != len(segments):
        return None
    for i, s in enumerate(out, 1):
        s.id = f"S{i}"
    return out


def plan_chapter(book: Book, idx: int, segments: List[Dict[str, str]], *, llm: Optional[LLM],
                 model: str, max_section_chars: int, effort: Optional[str] = "medium",
                 progress: Optional[Progress] = None) -> Tuple[List[Section], Optional[LLMResult]]:
    """
    章をセクションに分ける。短い章は1セクション（LLM を呼ばない）。
    長い章は LLM が場面の切れ目で分け、登場人物・要約・注意点を付ける。失敗時は字数で分割。
    """
    report = resolve_progress(progress)
    present = book.cast_present_in(idx)
    total = _chars(segments, 0, len(segments) - 1)
    if total <= max_section_chars or llm is None:
        if total <= max_section_chars:
            return [Section("S1", 0, len(segments) - 1, "whole chapter", present)], None
        spans = split_by_chars(segments, 0, len(segments) - 1, max_section_chars)
        return [Section(f"S{i}", a, b, f"part {i}", present) for i, (a, b) in enumerate(spans, 1)], None

    labels = book.cast_labels
    roster = "\n".join(f"- {c['label']}: {c.get('role', '')}" for c in book.cast.get("characters") or []
                       if c.get("label")) or "(no cast sheet)"
    listing = "\n".join(f'<seg id="{s["id"]}" chars="{len(s["text"])}">\n{s["text"]}\n</seg>'
                        for s in segments)
    user = (f"## CAST LABELS\n{roster}\n\n## NARRATION\n{book.narration_by_file.get(book.files[idx].name, '')}\n\n"
            f"## CHAPTER: {book.files[idx].name} ({total:,} chars, {len(segments)} segments)\n{listing}\n\n"
            f"Character limit per section: {max_section_chars:,}. Produce the plan JSON now.")
    spec_efforts = get_model(model).efforts
    report(f"🗺  planning {book.files[idx].name}: {total:,} chars, {len(segments)} segments")
    result = llm.complete(PLAN_SYSTEM, user, model=model,
                          effort=effort if effort in spec_efforts else None,
                          max_output_tokens=16000)
    sections = _parse_plan(result.text, segments, labels, max_section_chars)
    if sections is None:
        report("   ⚠️  plan was invalid — splitting by paragraph instead")
        spans = split_by_chars(segments, 0, len(segments) - 1, max_section_chars)
        sections = [Section(f"S{i}", a, b, f"part {i}", present) for i, (a, b) in enumerate(spans, 1)]
    for s in sections:
        report(f"   {s.id} {segments[s.start]['id']}–{segments[s.end]['id']} "
               f"({_chars(segments, s.start, s.end):,} chars) {s.title} · {', '.join(s.characters) or '—'}")
    return sections, result


# --- prompts per section --------------------------------------------------------------

def _previous_chapter_tail(book: Book, idx: int, out_dir: Path, target_lang: str,
                           chars: int = 4000) -> Optional[Tuple[str, str]]:
    for j in range(idx - 1, -1, -1):
        prev = chapter_output_path(book, j, out_dir, target_lang)
        if prev.exists():
            text = prev.read_text(encoding="utf-8")
            return (f"end of previous chapter {book.files[j].name}",
                    ("…" if len(text) > chars else "") + text[-chars:])
    return None


def build_section_prompt(book: Book, idx: int, segments: List[Dict[str, str]],
                         sections: List[Section], k: int, translated: Dict[str, str],
                         out_dir: Path, target_lang: str, previous: int = 2,
                         use_bible: bool = True, context: Optional[str] = None
                         ) -> Tuple[str, str, List[str]]:
    """
    セクション k の (system, user, 登場人物) を組み立てる。
    context（比較実験用）:
      "full" 人物表のエントリ＋ペルソナ＋エピソード（既定）
      "cast" 人物表のエントリのみ（use_bible=False と同じ）
      "none" 人物資料も語りの情報も渡さない（翻訳の指示・訳語表・前後の訳文・原文だけ）
    計画が挙げた登場人物を人物表と照合し、その人物の「人物表のエントリ・ペルソナ・エピソード」
    だけを渡す（人物表の他の人物は渡さない）。計画に人物が無ければ人物表でその章に出る人物。
    """
    context = context or ("full" if use_bible else "cast")
    use_bible = context == "full"
    use_cast = context in ("full", "cast")
    sec = sections[k]
    known = set(book.cast_labels) or set(book.characters)
    people = [c for c in sec.characters if c in known] or book.cast_present_in(idx)
    personas = {l: book.persona_paths[l].read_text(encoding="utf-8")
                for l in people if use_bible and l in book.persona_paths}
    episodes = {
        l: render_episodes(yaml.safe_load(book.episode_paths[l].read_text(encoding="utf-8")) or {},
                           book.chapter_names, idx)
        for l in people if use_bible and l in book.episode_paths
    }

    so_far: List[Tuple[str, str]] = []
    if k == 0:
        tail = _previous_chapter_tail(book, idx, out_dir, target_lang)
        if tail:
            so_far.append(tail)
    for prev in sections[max(0, k - previous):k]:
        text = "\n\n".join(translated.get(s["id"], "") for s in segments[prev.start:prev.end + 1])
        so_far.append((f"{prev.id} {prev.title}", text))

    multi = len(sections) > 1
    user = build_user_prompt(
        book.files[idx].name, segments[sec.start:sec.end + 1],
        book.cast_subset(people) if (book.cast and use_cast) else "", personas, episodes,
        load_notes(out_dir), so_far,
        book.narration_by_file.get(book.files[idx].name, "") if use_cast else "", target_lang,
        plan_text=render_plan(sections, segments, sec.id) if multi else "",
        section_label=f"{sec.id}/{len(sections)} {sec.title}" if multi else "")
    return build_system_prompt(target_lang), user, people


# --- estimate ---------------------------------------------------------------------------

def estimate_chapter(book: Book, idx: int, out_dir: Path, model: str, target_lang: str = "en",
                     previous: int = 2, max_section_chars: int = 6000) -> FitReport:
    """
    API を呼ばずに、その章の全呼び出し（計画 + セクションごと）の合計トークン・概算費用と、
    各呼び出しがコンテキストに収まるかを返す。長い章は字数で仮分割して見積もる。
    """
    spec = get_model(model)
    segments = segment_chapter(load_source_file(str(book.files[idx])))
    total = _chars(segments, 0, len(segments) - 1)
    spans = ([(0, len(segments) - 1)] if total <= max_section_chars
             else split_by_chars(segments, 0, len(segments) - 1, max_section_chars))
    sections = [Section(f"S{i}", a, b, "", book.cast_present_in(idx)) for i, (a, b) in enumerate(spans, 1)]
    reports = []
    if len(sections) > 1:
        plan_in = PLAN_SYSTEM + "\n".join(s["text"] for s in segments)
        reports.append(check_fit(spec, plan_in, output_tokens=4000))
    # 前のセクションの訳文は、原文と同じ量があるものとして見積もる
    fake = {s["id"]: s["text"] for s in segments}
    for k in range(len(sections)):
        system, user, _ = build_section_prompt(book, idx, segments, sections, k, fake, out_dir,
                                               target_lang, previous)
        out = _chars(segments, sections[k].start, sections[k].end) * 3
        reports.append(check_fit(spec, system + user, output_tokens=out))
    tin = sum(r.input_tokens for r in reports)
    tout = sum(r.output_tokens for r in reports)
    fits = None if any(r.fits is None for r in reports) else all(r.fits for r in reports)
    cost = None if any(r.cost_usd is None for r in reports) else sum(r.cost_usd for r in reports)
    msg = (f"{len(reports)} call(s) ({len(sections)} section(s)) · ~{tin:,} in + {tout:,} out"
           + ("" if fits is None else f" · {'OK' if fits else 'TOO LARGE'}")
           + ("" if cost is None else f" · est. ${cost:.2f}"))
    return FitReport(tin, tout, spec.context_window, fits, cost, msg)


# --- excerpt (範囲指定) と資料あり／なしの比較 -------------------------------------------

def segment_range(segments: List[Dict[str, str]], spec: str) -> Tuple[int, int]:
    """'P150-P168' → (149, 167)"""
    a, _, b = spec.partition("-")
    ids = {s["id"]: i for i, s in enumerate(segments)}
    a, b = a.strip(), (b or a).strip()
    if a not in ids or b not in ids or ids[b] < ids[a]:
        raise ValueError(f"invalid segment range: {spec} (chapter has P001–{segments[-1]['id']})")
    return ids[a], ids[b]


@dataclass
class ExcerptResult:
    chapter: str
    range: str
    characters: List[str]
    use_bible: bool
    aligned: List[Dict[str, str]]
    issues: List[str]
    output_path: Path
    llm: Optional[LLMResult] = None
    context: str = "full"


def translate_excerpt(book: Book, idx: int, spec: str, *, llm: LLM, out_dir: Path,
                      target_lang: str = "en", characters: Optional[List[str]] = None,
                      use_bible: bool = True, context: Optional[str] = None, model: str = DEFAULT_MODEL,
                      effort: Optional[str] = DEFAULT_EFFORT, max_output_tokens: int = 65536,
                      progress: Optional[Progress] = None) -> ExcerptResult:
    """
    章の一部（段落範囲）だけを1回で訳す。エピソードはその章を基準に「既に起きた／この章／この先」を
    切り替えるので、抜粋でも人物の時点は保たれる。訳語表は out_dir の中だけで使う（本番の訳語表を汚さない）。
    """
    report = resolve_progress(progress)
    out_dir.mkdir(parents=True, exist_ok=True)
    segments = segment_chapter(load_source_file(str(book.files[idx])))
    a, b = segment_range(segments, spec)
    known = set(book.cast_labels) or set(book.characters)
    people = [c for c in (characters or []) if c in known]
    unknown = [c for c in (characters or []) if c not in known]
    if unknown:
        raise ValueError(f"not in cast sheet: {unknown}")
    context = context or ("full" if use_bible else "cast")
    sec = Section("S1", a, b, f"excerpt {spec}", people)
    system, user, used = build_section_prompt(book, idx, segments, [sec], 0, {}, out_dir,
                                              target_lang, context=context)
    if context == "none":
        used = []
    report(f"✂️  {book.files[idx].name} {segments[a]['id']}–{segments[b]['id']} "
           f"({_chars(segments, a, b):,} chars) → {target_lang} · context={context} · "
           f"{', '.join(used) or '—'} · prompt {len(user):,} chars")
    result = llm.complete(system, user, model=model, effort=effort, max_output_tokens=max_output_tokens)
    body = re.search(r"<translation>(.*?)</translation>", result.text, re.S)
    got = parse_segments(body.group(1) if body else result.text)
    part = segments[a:b + 1]
    issues = check_alignment(part, got)
    _apply_notes(result.text, out_dir, book.files[idx].name, book.files[idx].stem)
    aligned = [{"id": s["id"], "source": s["text"], "target": got.get(s["id"], "")} for s in part]
    name = f"{book.files[idx].stem}.{target_lang}.{segments[a]['id']}-{segments[b]['id']}"
    (out_dir / f"{name}.segments.json").write_text(json.dumps(aligned, ensure_ascii=False, indent=1),
                                                    encoding="utf-8")
    out_path = out_dir / f"{name}.md"
    out_path.write_text("\n\n".join(x["target"] for x in aligned) + "\n", encoding="utf-8")
    return ExcerptResult(book.files[idx].name, spec, used, context == "full", aligned, issues, out_path,
                         result, context)


CONTEXT_LABELS = {
    "full": "完全版（人物表＋ペルソナ＋エピソード）",
    "cast": "人物表のみ",
    "none": "資料なし（人物資料も語りの情報も無し）",
}


def write_comparison(path: Path, title: str, results: List["ExcerptResult"]) -> Path:
    """条件ごとの訳を段落ごとに並べた Markdown を書く（results の順に列を並べる）"""
    first = results[0]
    lines = [f"# {title}", "",
             f"- 章: {first.chapter} / 範囲: {first.range}",
             f"- 登場人物: {', '.join(first.characters) or '—'}", ""]
    for r in results:
        lines.append(f"- **{r.context}** = {CONTEXT_LABELS.get(r.context, r.context)} · "
                     f"入力 {r.llm.usage.get('input_tokens', '?')} / 出力 {r.llm.usage.get('output_tokens', '?')} tokens")
    lines.append("")
    by_ctx = [{x["id"]: x["target"] for x in r.aligned} for r in results]
    for x in first.aligned:
        lines += [f"### {x['id']}", "", f"> {x['source']}", ""]
        for r, table in zip(results, by_ctx):
            lines += [f"**{r.context}**  ", table.get(x["id"], ""), ""]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


# --- translate ---------------------------------------------------------------------------

@dataclass
class ChapterResult:
    chapter: str
    segments: int
    translated: Dict[str, str]
    issues: List[str]
    complete: bool
    output_path: Optional[Path]
    notes_added: int = 0
    notes_error: Optional[str] = None
    llm: Optional[LLMResult] = None
    sections: List[Dict[str, Any]] = field(default_factory=list)


def _apply_notes(text: str, out_dir: Path, chapter: str, stem: str) -> Tuple[int, Optional[str]]:
    m = re.search(r"<notes>(.*?)</notes>", text, re.S)
    if not m:
        return 0, None
    raw = re.sub(r"^```(?:yaml)?\s*|\s*```$", "", m.group(1).strip())
    try:
        new_notes = yaml.safe_load(raw) or {}
        merged = merge_notes(load_notes(out_dir), new_notes, chapter)
        (out_dir / NOTES_FILE).write_text(dump_yaml(merged), encoding="utf-8")
        return sum(len(new_notes.get(k) or []) for k in ("glossary", "voice", "style")), None
    except (yaml.YAMLError, AttributeError) as e:
        (out_dir / f"{stem}.notes_BROKEN.yaml").write_text(raw, encoding="utf-8")
        return 0, str(e)


def translate_chapter(book: Book, idx: int, *, llm: LLM, out_dir: Path,
                      target_lang: str = "en", model: str = DEFAULT_MODEL,
                      effort: Optional[str] = DEFAULT_EFFORT, previous: int = 2,
                      max_section_chars: int = 6000, plan_effort: Optional[str] = "medium",
                      max_output_tokens: int = 65536, force: bool = False,
                      cancel_check=None,
                      progress: Optional[Progress] = None) -> ChapterResult:
    """
    1章を翻訳する。長い章は LLM が場面単位のセクションに分け、セクションごとに1回推論する。
    途中経過は {章}.{lang}.work.json に保存し、中断しても完了済みのセクションから再開する。
    """
    report = resolve_progress(progress)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = book.files[idx]
    stem = path.stem
    segments = segment_chapter(load_source_file(str(path)))
    work_path = _work_path(book, idx, out_dir, target_lang)

    # 計画（再開時は保存済みの計画を使う）
    work: Dict[str, Any] = {}
    if work_path.exists() and not force:
        work = json.loads(work_path.read_text(encoding="utf-8"))
        sections = [Section(**s) for s in work["sections"]]
        report(f"↻  resuming {path.name}: {len(work.get('done', []))}/{len(sections)} section(s) done")
    else:
        sections, _ = plan_chapter(book, idx, segments, llm=llm, model=model,
                                   max_section_chars=max_section_chars, effort=plan_effort,
                                   progress=report)
        work = {"sections": [s.to_dict() for s in sections], "translated": {}, "done": []}
        work_path.write_text(json.dumps(work, ensure_ascii=False, indent=1), encoding="utf-8")

    translated: Dict[str, str] = dict(work.get("translated") or {})
    done = set(work.get("done") or [])
    notes_added, notes_error, last = 0, None, None
    report(f"🌐 [{idx}] {path.name} → {target_lang}  segments={len(segments)} sections={len(sections)}")

    for k, sec in enumerate(sections):
        if sec.id in done:
            continue
        if cancel_check:
            cancel_check()
        sec_segments = segments[sec.start:sec.end + 1]
        system, user, people = build_section_prompt(book, idx, segments, sections, k, translated,
                                                    out_dir, target_lang, previous)
        tags = [p + ("[P" if p in book.persona_paths else "[") + ("E]" if p in book.episode_paths else "]")
                for p in people]
        report(f"🧩 {sec.id}/{len(sections)} {sec_segments[0]['id']}–{sec_segments[-1]['id']} "
               f"({_chars(segments, sec.start, sec.end):,} chars) {sec.title} · "
               f"{', '.join(t.replace('[]', '') for t in tags) or '—'}")
        for attempt in range(2):
            last = llm.complete(system, user, model=model, effort=effort,
                                max_output_tokens=max_output_tokens)
            body = re.search(r"<translation>(.*?)</translation>", last.text, re.S)
            got = parse_segments(body.group(1) if body else last.text)
            missing = [s["id"] for s in sec_segments if not got.get(s["id"], "").strip()]
            if not missing or attempt == 1:
                break
            report(f"   ↻ {len(missing)} segment(s) missing — retrying {sec.id}")
        for s in sec_segments:
            if got.get(s["id"], "").strip():
                translated[s["id"]] = got[s["id"]]
        added, err = _apply_notes(last.text, out_dir, path.name, stem)
        notes_added += added
        notes_error = notes_error or err
        if not missing:
            done.add(sec.id)
        work.update(translated=translated, done=sorted(done, key=lambda x: int(x[1:])))
        work_path.write_text(json.dumps(work, ensure_ascii=False, indent=1), encoding="utf-8")

    issues = check_alignment(segments, translated)
    aligned = [{"id": s["id"], "source": s["text"], "target": translated.get(s["id"], "")}
               for s in segments]
    (out_dir / f"{stem}.{target_lang}.segments.json").write_text(
        json.dumps(aligned, ensure_ascii=False, indent=1), encoding="utf-8")

    complete = not any(i.startswith("missing") for i in issues)
    incomplete_path = out_dir / f"{stem}.{target_lang}_INCOMPLETE.md"
    if complete:
        out_path = chapter_output_path(book, idx, out_dir, target_lang)
        out_path.write_text("\n\n".join(a["target"] for a in aligned) + "\n", encoding="utf-8")
        work_path.unlink(missing_ok=True)
        incomplete_path.unlink(missing_ok=True)
    else:
        out_path = incomplete_path
        out_path.write_text("\n\n".join(a["target"] or f"[[{a['id']} MISSING]]" for a in aligned),
                            encoding="utf-8")
    return ChapterResult(path.name, len(segments), translated, issues, complete, out_path,
                         notes_added, notes_error, last, [s.to_dict() for s in sections])


# =============================================================================
# CLI
# =============================================================================

def parse_chapter_selection(spec: str, total: int) -> List[int]:
    """'0-2,5' → [0,1,2,5]（0始まりのファイル順インデックス）"""
    if not spec:
        return list(range(total))
    picked: List[int] = []
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            picked.extend(range(int(a), int(b) + 1))
        elif part:
            picked.append(int(part))
    return [i for i in dict.fromkeys(picked) if 0 <= i < total]



def main() -> int:
    parser = argparse.ArgumentParser(
        description="Chapter Translator v1.2 — section-by-section translation with cast/persona/episode context",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--source", "-s", required=True, help="Source folder (one file per chapter)")
    parser.add_argument("--cast", default="", help="Cast sheet YAML (cast_extractor.py)")
    parser.add_argument("--persona-dir", default="personas")
    parser.add_argument("--episode-dir", default="episodes")
    parser.add_argument("--persona", action="append", default=[], metavar="LABEL=PATH")
    parser.add_argument("--episode", action="append", default=[], metavar="LABEL=PATH")
    parser.add_argument("--target-lang", "-t", default="en", choices=list(SUPPORTED_LANGUAGES.keys()))
    parser.add_argument("--chapters", default="",
                        help="Chapter indices in file order, e.g. '0-2,5' (default: all)")
    parser.add_argument("--previous", type=int, default=2,
                        help="Preceding translated sections passed as context (default: 2)")
    parser.add_argument("--max-section-chars", type=int, default=6000,
                        help="Chapters longer than this are planned into sections (default: 6000)")
    parser.add_argument("--plan-effort", default="medium", choices=EFFORTS,
                        help="Reasoning effort for the section plan (default: medium)")
    parser.add_argument("--out-dir", "-o", default="")
    parser.add_argument("--force", action="store_true", help="Re-translate chapters already done")
    parser.add_argument("--model", "-m", default=DEFAULT_MODEL)
    parser.add_argument("--effort", "--reasoning", "-r", dest="effort", default=DEFAULT_EFFORT,
                        choices=EFFORTS)
    parser.add_argument("--max-output-tokens", type=int, default=65536)
    parser.add_argument("--dry-run", action="store_true",
                        help="Show calls / size / fit / cost without calling the API")
    parser.add_argument("--segments", default="",
                        help="Translate only this paragraph range of ONE chapter, e.g. P150-P168")
    parser.add_argument("--characters", default="",
                        help="With --segments: comma-separated cast labels in the excerpt")
    parser.add_argument("--no-bible", action="store_true",
                        help="With --segments: same as --context cast")
    parser.add_argument("--context", default="full", choices=["full", "cast", "none"],
                        help="With --segments: full = cast+persona+episode, cast = cast entries only, "
                             "none = no character or narration info")
    parser.add_argument("--compare", nargs="?", const="full,cast", default="",
                        help="With --segments: translate under each context (default 'full,cast'; "
                             "e.g. 'full,none' or 'full,cast,none') and write a side-by-side file")
    args = parser.parse_args()

    book = open_book(args.source, args.cast, args.persona_dir, args.episode_dir,
                     parse_overrides(args.persona), parse_overrides(args.episode))
    out_dir = Path(args.out_dir or f"translations/{book.source.name}_{args.target_lang}")
    print(f"📚 {len(book.files)} chapter(s) in {book.source}")
    for label in book.characters:
        print(f"   🎭 {label}: persona={book.persona_paths.get(label)} "
              f"episode={book.episode_paths.get(label)}")

    llm = None if args.dry_run else LLM(Keys.from_env(), progress=print_progress)

    if args.segments:
        chapters = parse_chapter_selection(args.chapters, len(book.files))
        if len(chapters) != 1 or llm is None:
            parser.error("--segments needs exactly one --chapters index and no --dry-run")
        idx = chapters[0]
        chars = [c.strip() for c in args.characters.split(",") if c.strip()]
        common = dict(llm=llm, target_lang=args.target_lang, characters=chars, model=args.model,
                      effort=args.effort, max_output_tokens=args.max_output_tokens,
                      progress=print_progress)
        if args.compare:
            contexts = [c.strip() for c in args.compare.split(",") if c.strip()]
            bad = [c for c in contexts if c not in ("full", "cast", "none")]
            if bad:
                parser.error(f"unknown context(s) in --compare: {bad}")
        else:
            contexts = ["cast" if args.no_bible else args.context]
        results = []
        for ctx in contexts:
            r = translate_excerpt(book, idx, args.segments, out_dir=out_dir / "excerpts" / ctx,
                                  context=ctx, **common)
            results.append(r)
            print(f"{'✅' if not r.issues else '⚠️ '} {r.output_path}  {r.issues[:3]}")
        if len(results) > 1:
            path = (out_dir / "excerpts" /
                    f"compare_{book.files[idx].stem}_{args.segments}_{'-'.join(contexts)}.{args.target_lang}.md")
            write_comparison(path, f"{book.files[idx].name} {args.segments} → {args.target_lang}", results)
            print(f"📊 {path}")
        print(f"usage: {llm.total_usage()}")
        return 0

    exit_code = 0
    for idx in parse_chapter_selection(args.chapters, len(book.files)):
        out_md = chapter_output_path(book, idx, out_dir, args.target_lang)
        if out_md.exists() and not args.force:
            print(f"⏭  {book.files[idx].name}: already translated ({out_md})")
            continue
        if args.dry_run:
            fit = estimate_chapter(book, idx, out_dir, args.model, args.target_lang, args.previous,
                                   args.max_section_chars)
            print(f"   [{idx}] {book.files[idx].name}: {fit.message}")
            continue

        print(f"\n{'=' * 60}")
        r = translate_chapter(book, idx, llm=llm, out_dir=out_dir, target_lang=args.target_lang,
                              model=args.model, effort=args.effort, previous=args.previous,
                              max_section_chars=args.max_section_chars, plan_effort=args.plan_effort,
                              max_output_tokens=args.max_output_tokens, force=args.force,
                              progress=print_progress)
        if r.issues:
            print("⚠️  Checks:")
            for i in r.issues:
                print(f"   - {i}")
        else:
            print(f"✅ Checks: {r.segments}/{r.segments} segments aligned ({len(r.sections)} section(s))")
        if r.notes_error:
            print(f"⚠️  Notes YAML parse error (not merged): {r.notes_error}")
        else:
            print(f"📝 Notes: +{r.notes_added} decision(s)")
        if r.complete:
            print(f"📁 Saved: {r.output_path}")
        else:
            print(f"❌ Incomplete — saved as {r.output_path} (re-run to resume)")
            exit_code = 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
