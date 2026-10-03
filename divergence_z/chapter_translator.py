#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Chapter Translator v1.1
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

v1.1: ライブラリ化（open_book / build_chapter_prompt / translate_chapter）、
      LLM 呼び出しを core.llm に統一（BYOK）、実行前のコンテキスト適合チェック
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

    return [{"id": f"P{i:03d}", "text": s} for i, s in enumerate(segments, 1)]


def render_segments(segments: List[Dict[str, str]]) -> str:
    return "\n".join(f'<seg id="{s["id"]}">\n{s["text"]}\n</seg>' for s in segments)


_SEG_RE = re.compile(r'<seg id="(P\d+)">\n?(.*?)\n?</seg>', re.S)


def parse_segments(text: str) -> Dict[str, str]:
    return {m.group(1): m.group(2).strip("\n") for m in _SEG_RE.finditer(text)}


# =============================================================================
# CONTEXT: cast / persona / episode / notes
# =============================================================================

def _label_variants(label: str) -> List[str]:
    """persona_extractor_v2 / episode_extractor の保存名規則に合わせた候補"""
    underscored = label.replace(" ", "_")
    lowered = re.sub(r"[^\w\-]", "", label.lower().replace(" ", "_"))
    return list(dict.fromkeys([label, underscored, lowered]))


def find_character_file(label: str, directory: Path, kind: str) -> Optional[Path]:
    if not directory.is_dir():
        return None
    for v in _label_variants(label):
        if kind == "persona":
            candidates = [directory / f"{v}_extracted_v33.yaml", directory / f"{v}_v33.yaml"]
        else:
            candidates = [directory / f"{v}_Episode.yaml", directory / f"{v}_Episode_full.yaml"]
        for c in candidates:
            if c.exists():
                return c
    return None


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
into {lang}, one chapter at a time, as a single coherent book.

## WHAT YOU ARE GIVEN
- CAST SHEET: who is who, and how the text refers to each person (often by description or pronoun,
  not by name), plus who narrates which chapter.
- PERSONAS: for each character in this chapter — who they are (identity_core), how they speak in the
  original (original_speech_patterns), and recommended compensations for the target language
  (translation_compensations). conflict_axes / triggers / emotion_states describe how their speech
  shifts under emotion.
- EPISODE MEMORY: what each character has lived through, split into what already happened,
  what happens in this chapter, and what has not happened yet.
- TRANSLATION NOTES: decisions already made in earlier chapters (glossary, character voice, style).
  These are binding unless they are clearly wrong for this chapter.
- PREVIOUS CHAPTERS: your own translation of the preceding chapter(s), for continuity of voice.
- THIS CHAPTER: the source text, split into numbered segments <seg id="P001">…</seg>.

## HOW TO TRANSLATE
1. Translate the whole chapter as literature, not line by line. Read it all first.
2. Each character must sound like THEMSELVES in {lang}: use the persona to decide register, rhythm,
   verbal tics, how broken or fluent their speech is, and how it changes with emotion.
   A line's weight comes from the episodes behind it — let that shape word choice.
3. Resolve every pronoun/description to the right person using the cast sheet before translating.
4. Wordplay, non-standard grammar, mispronunciations, dialect, and language-learning speech are
   meaning, not noise: find a {lang} equivalent that does the same job, and record the decision.
5. Words already in a foreign/alien language in the source (e.g. romanized alien words) stay as they are.
6. Keep markdown exactly: headings, **bold**, ``` code blocks ``` (translate their contents, keep layout),
   --- separators, ［brackets］ styles may be adapted to {lang} conventions consistently.
7. Do not add, omit, merge, or split segments. Every input segment id appears exactly once in output.
8. Follow TRANSLATION NOTES. If you must deviate, add an updated entry explaining why.

## OUTPUT FORMAT (exactly this, nothing else)
<translation>
<seg id="P001">
…translated text…
</seg>
… (every segment, same ids, same order)
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


def build_user_prompt(chapter_name: str, segments: List[Dict[str, str]], cast_text: str,
                      personas: Dict[str, str], episodes: Dict[str, str],
                      notes: Dict[str, Any], previous: List[Tuple[str, str]],
                      narration: str, target_lang: str) -> str:
    parts: List[str] = []
    if cast_text:
        parts.append("## CAST SHEET\n```yaml\n" + cast_text.strip() + "\n```")
    if narration:
        parts.append("## NARRATION OF THIS CHAPTER\n" + narration)
    for label, text in personas.items():
        parts.append(f"## PERSONA: {label}\n```yaml\n{text.strip()}\n```")
    for label, text in episodes.items():
        parts.append(f"## EPISODE MEMORY: {label}\n{text}")
    parts.append("## TRANSLATION NOTES (binding)\n```yaml\n"
                 + dump_yaml(notes)
                 + "```")
    for name, text in previous:
        parts.append(f"## PREVIOUS CHAPTER (your translation): {name}\n{text}")
    parts.append(f"## THIS CHAPTER: {chapter_name}\n{render_segments(segments)}")
    parts.append(f"Translate THIS CHAPTER into {SUPPORTED_LANGUAGES.get(target_lang, target_lang)}. "
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
        if n_src and t and n_tgt != n_src:
            issues.append(f"{s['id']}: dialogue count {n_src} → {n_tgt}")
    return issues


# =============================================================================
# MAIN
# =============================================================================


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
        """その章に登場する人物（cast に appears_in が無ければ全員）"""
        name = self.files[idx].name
        return [l for l in self.characters if not self.appears.get(l) or name in self.appears[l]]


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


@dataclass
class ChapterPrompt:
    system: str
    user: str
    segments: List[Dict[str, str]]
    present: List[str]
    previous: List[str]


def build_chapter_prompt(book: Book, idx: int, out_dir: Path, target_lang: str = "en",
                         previous: int = 2) -> ChapterPrompt:
    path = book.files[idx]
    segments = segment_chapter(load_source_file(str(path)))
    present = book.present_in(idx)
    personas = {l: book.persona_paths[l].read_text(encoding="utf-8")
                for l in present if l in book.persona_paths}
    episodes = {
        l: render_episodes(yaml.safe_load(book.episode_paths[l].read_text(encoding="utf-8")) or {},
                           book.chapter_names, idx)
        for l in present if l in book.episode_paths
    }

    prev: List[Tuple[str, str]] = []
    for j in range(idx - 1, -1, -1):
        if len(prev) >= previous:
            break
        prev_md = chapter_output_path(book, j, out_dir, target_lang)
        if prev_md.exists():
            prev.insert(0, (book.files[j].name, prev_md.read_text(encoding="utf-8")))

    user = build_user_prompt(path.name, segments, book.cast_text, personas, episodes,
                             load_notes(out_dir), prev, book.narration_by_file.get(path.name, ""),
                             target_lang)
    return ChapterPrompt(build_system_prompt(target_lang), user, segments, present,
                         [p[0] for p in prev])


def estimate_chapter(book: Book, idx: int, out_dir: Path, model: str, target_lang: str = "en",
                     previous: int = 2) -> FitReport:
    """API を呼ばずに、その章のプロンプトがモデルに収まるか・概算費用を返す（UI の事前表示用）"""
    prompt = build_chapter_prompt(book, idx, out_dir, target_lang, previous)
    source_chars = sum(len(s["text"]) for s in prompt.segments)
    # 訳文 + 訳語表追記 + 推論分のざっくりした出力見積もり
    return check_fit(get_model(model), prompt.system + prompt.user, output_tokens=source_chars * 3)


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


def translate_chapter(book: Book, idx: int, *, llm: LLM, out_dir: Path,
                      target_lang: str = "en", model: str = DEFAULT_MODEL,
                      effort: Optional[str] = DEFAULT_EFFORT, previous: int = 2,
                      max_output_tokens: int = 65536,
                      progress: Optional[Progress] = None) -> ChapterResult:
    """1章を翻訳し、訳文・段落対応・訳語表（out_dir 内）を更新する"""
    report = resolve_progress(progress)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = book.files[idx]
    stem = path.stem
    prompt = build_chapter_prompt(book, idx, out_dir, target_lang, previous)
    report(f"🌐 [{idx}] {path.name} → {target_lang}  segments={len(prompt.segments)} "
           f"characters={prompt.present} previous={prompt.previous}")

    result = llm.complete(prompt.system, prompt.user, model=model, effort=effort,
                          max_output_tokens=max_output_tokens)
    body = re.search(r"<translation>(.*?)</translation>", result.text, re.S)
    translated = parse_segments(body.group(1) if body else result.text)
    issues = check_alignment(prompt.segments, translated)

    # 訳語表の更新
    notes_added, notes_error = 0, None
    notes_match = re.search(r"<notes>(.*?)</notes>", result.text, re.S)
    if notes_match:
        raw = re.sub(r"^```(?:yaml)?\s*|\s*```$", "", notes_match.group(1).strip())
        try:
            new_notes = yaml.safe_load(raw) or {}
            merged = merge_notes(load_notes(out_dir), new_notes, path.name)
            (out_dir / NOTES_FILE).write_text(dump_yaml(merged), encoding="utf-8")
            notes_added = sum(len(new_notes.get(k) or []) for k in ("glossary", "voice", "style"))
        except yaml.YAMLError as e:
            notes_error = str(e)
            (out_dir / f"{stem}.notes_BROKEN.yaml").write_text(raw, encoding="utf-8")

    aligned = [{"id": s["id"], "source": s["text"], "target": translated.get(s["id"], "")}
               for s in prompt.segments]
    (out_dir / f"{stem}.{target_lang}.segments.json").write_text(
        json.dumps(aligned, ensure_ascii=False, indent=1), encoding="utf-8")

    complete = not any(i.startswith("missing") for i in issues)
    if complete:
        out_path = chapter_output_path(book, idx, out_dir, target_lang)
        out_path.write_text("\n\n".join(a["target"] for a in aligned) + "\n", encoding="utf-8")
    else:
        out_path = out_dir / f"{stem}.{target_lang}_INCOMPLETE.md"
        out_path.write_text("\n\n".join(a["target"] or f"[[{a['id']} MISSING]]" for a in aligned),
                            encoding="utf-8")
    return ChapterResult(path.name, len(prompt.segments), translated, issues, complete, out_path,
                         notes_added, notes_error, result)


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
        description="Chapter Translator v1.1 — translate chapter by chapter with cast/persona/episode context",
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
                        help="How many preceding translated chapters to include (default: 2)")
    parser.add_argument("--out-dir", "-o", default="")
    parser.add_argument("--force", action="store_true", help="Re-translate chapters already done")
    parser.add_argument("--model", "-m", default=DEFAULT_MODEL)
    parser.add_argument("--effort", "--reasoning", "-r", dest="effort", default=DEFAULT_EFFORT,
                        choices=EFFORTS)
    parser.add_argument("--max-output-tokens", type=int, default=65536)
    parser.add_argument("--dry-run", action="store_true",
                        help="Build prompts and show size / fit / cost without calling the API")
    args = parser.parse_args()

    book = open_book(args.source, args.cast, args.persona_dir, args.episode_dir,
                     parse_overrides(args.persona), parse_overrides(args.episode))
    out_dir = Path(args.out_dir or f"translations/{book.source.name}_{args.target_lang}")
    print(f"📚 {len(book.files)} chapter(s) in {book.source}")
    for label in book.characters:
        print(f"   🎭 {label}: persona={book.persona_paths.get(label)} "
              f"episode={book.episode_paths.get(label)}")

    llm = None if args.dry_run else LLM(Keys.from_env(), progress=print_progress)
    exit_code = 0
    for idx in parse_chapter_selection(args.chapters, len(book.files)):
        out_md = chapter_output_path(book, idx, out_dir, args.target_lang)
        if out_md.exists() and not args.force:
            print(f"⏭  {book.files[idx].name}: already translated ({out_md})")
            continue
        if args.dry_run:
            fit = estimate_chapter(book, idx, out_dir, args.model, args.target_lang, args.previous)
            print(f"   [{idx}] {book.files[idx].name}: {fit.message}")
            continue

        print(f"\n{'=' * 60}")
        r = translate_chapter(book, idx, llm=llm, out_dir=out_dir, target_lang=args.target_lang,
                              model=args.model, effort=args.effort, previous=args.previous,
                              max_output_tokens=args.max_output_tokens, progress=print_progress)
        if r.issues:
            print("⚠️  Checks:")
            for i in r.issues:
                print(f"   - {i}")
        else:
            print(f"✅ Checks: {r.segments}/{r.segments} segments aligned")
        if r.notes_error:
            print(f"⚠️  Notes YAML parse error (not merged): {r.notes_error}")
        else:
            print(f"📝 Notes: +{r.notes_added} decision(s)")
        if r.complete:
            print(f"📁 Saved: {r.output_path}")
        else:
            print(f"❌ Incomplete — saved as {r.output_path} (re-run to retry)")
            exit_code = 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
