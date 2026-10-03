#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Chapter Translator v1.0
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
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from persona_extractor_v2 import (
    DEFAULT_MODEL,
    REASONING_EFFORTS,
    SUPPORTED_LANGUAGES,
    OpenAIResponsesClient,
    collect_source_files,
    load_source_file,
)
from episode_extractor import call_responses

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
    episodes: List[Dict[str, Any]] = []
    for tl in episode_yaml.get("timelines") or []:
        if isinstance(tl, dict):
            episodes.extend(e for e in tl.get("episodes") or [] if isinstance(e, dict))
    episodes.extend(e for e in episode_yaml.get("episodes") or [] if isinstance(e, dict))

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
                 + yaml.safe_dump(notes, allow_unicode=True, sort_keys=False, width=1000)
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
        description="Chapter Translator v1.0 — translate chapter by chapter with cast/persona/episode context",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--source", "-s", required=True, help="Source folder (one file per chapter)")
    parser.add_argument("--cast", default="", help="Cast sheet YAML (cast_extractor.py)")
    parser.add_argument("--persona-dir", default="personas")
    parser.add_argument("--episode-dir", default="episodes")
    parser.add_argument("--persona", action="append", default=[], metavar="LABEL=PATH",
                        help="Explicit persona for a cast label (repeatable)")
    parser.add_argument("--episode", action="append", default=[], metavar="LABEL=PATH",
                        help="Explicit episode memory for a cast label (repeatable)")
    parser.add_argument("--target-lang", "-t", default="en", choices=list(SUPPORTED_LANGUAGES.keys()))
    parser.add_argument("--chapters", default="",
                        help="Chapter indices in file order, e.g. '0-2,5' (default: all)")
    parser.add_argument("--previous", type=int, default=2,
                        help="How many preceding translated chapters to include (default: 2)")
    parser.add_argument("--out-dir", "-o", default="")
    parser.add_argument("--force", action="store_true", help="Re-translate chapters already done")
    parser.add_argument("--model", "-m", default=DEFAULT_MODEL)
    parser.add_argument("--reasoning", "-r", default="high", choices=REASONING_EFFORTS,
                        help="Reasoning effort (default: high)")
    parser.add_argument("--max-output-tokens", type=int, default=65536)
    parser.add_argument("--dry-run", action="store_true",
                        help="Build prompts and print their size without calling the API")
    args = parser.parse_args()

    source = Path(args.source)
    files = collect_source_files(str(source))
    chapter_names = [f.name for f in files]
    out_dir = Path(args.out_dir or f"translations/{source.name}_{args.target_lang}")
    out_dir.mkdir(parents=True, exist_ok=True)

    cast: Dict[str, Any] = {}
    cast_text = ""
    if args.cast:
        cast_text = Path(args.cast).read_text(encoding="utf-8")
        cast = yaml.safe_load(cast_text) or {}

    persona_over = parse_overrides(args.persona)
    episode_over = parse_overrides(args.episode)

    # cast のラベルごとに persona / episode を解決
    persona_paths: Dict[str, Path] = {}
    episode_paths: Dict[str, Path] = {}
    labels = [c.get("label") for c in cast.get("characters") or [] if c.get("label")]
    for label in dict.fromkeys(labels + list(persona_over) + list(episode_over)):
        p = persona_over.get(label) or find_character_file(label, Path(args.persona_dir), "persona")
        e = episode_over.get(label) or find_character_file(label, Path(args.episode_dir), "episode")
        if p:
            persona_paths[label] = p
        if e:
            episode_paths[label] = e
    print(f"📚 {len(files)} chapter(s) in {source}")
    for label in dict.fromkeys(list(persona_paths) + list(episode_paths)):
        print(f"   🎭 {label}: persona={persona_paths.get(label)} episode={episode_paths.get(label)}")

    appears: Dict[str, List[str]] = {
        c["label"]: c.get("appears_in") or [] for c in cast.get("characters") or [] if c.get("label")
    }
    narration_by_file: Dict[str, str] = {}
    for n in cast.get("narration") or []:
        for f in n.get("files") or []:
            narration_by_file[f] = (f"narrator: {n.get('narrator')} / style: {n.get('style')}\n"
                                    f"{n.get('notes', '')}")

    client = None if args.dry_run else OpenAIResponsesClient()
    system_prompt = build_system_prompt(args.target_lang)
    exit_code = 0

    for idx in parse_chapter_selection(args.chapters, len(files)):
        path = files[idx]
        stem = path.stem
        out_md = out_dir / f"{stem}.{args.target_lang}.md"
        if out_md.exists() and not args.force:
            print(f"⏭  {path.name}: already translated ({out_md})")
            continue

        print(f"\n{'=' * 60}\n🌐 [{idx}] {path.name} → {args.target_lang}\n{'=' * 60}")
        segments = segment_chapter(load_source_file(str(path)))

        # この章に登場する人物（cast に appears_in が無ければ全員）
        present = [l for l in dict.fromkeys(list(persona_paths) + list(episode_paths))
                   if not appears.get(l) or path.name in appears[l]]
        personas = {l: persona_paths[l].read_text(encoding="utf-8")
                    for l in present if l in persona_paths}
        episodes = {
            l: render_episodes(yaml.safe_load(episode_paths[l].read_text(encoding="utf-8")) or {},
                               chapter_names, idx)
            for l in present if l in episode_paths
        }

        previous: List[Tuple[str, str]] = []
        for j in range(idx - 1, -1, -1):
            if len(previous) >= args.previous:
                break
            prev_md = out_dir / f"{files[j].stem}.{args.target_lang}.md"
            if prev_md.exists():
                previous.insert(0, (files[j].name, prev_md.read_text(encoding="utf-8")))

        notes = load_notes(out_dir)
        user_prompt = build_user_prompt(path.name, segments, cast_text, personas, episodes,
                                        notes, previous, narration_by_file.get(path.name, ""),
                                        args.target_lang)
        print(f"   segments={len(segments)} characters={present} previous={[p[0] for p in previous]}")

        if args.dry_run:
            print(f"   (dry-run) prompt: {len(user_prompt):,} chars")
            continue

        result = call_responses(client, system_prompt, user_prompt,
                                model=args.model, reasoning_effort=args.reasoning,
                                background=None, max_output_tokens=args.max_output_tokens)
        text = result["text"]

        body = re.search(r"<translation>(.*?)</translation>", text, re.S)
        translated = parse_segments(body.group(1) if body else text)

        issues = check_alignment(segments, translated)
        if issues:
            print("⚠️  Checks:")
            for i in issues:
                print(f"   - {i}")
        else:
            print(f"✅ Checks: {len(segments)}/{len(segments)} segments aligned")

        # 訳語表の更新
        notes_match = re.search(r"<notes>(.*?)</notes>", text, re.S)
        if notes_match:
            raw = re.sub(r"^```(?:yaml)?\s*|\s*```$", "", notes_match.group(1).strip())
            try:
                new_notes = yaml.safe_load(raw) or {}
                notes = merge_notes(notes, new_notes, path.name)
                (out_dir / NOTES_FILE).write_text(
                    yaml.safe_dump(notes, allow_unicode=True, sort_keys=False, width=1000),
                    encoding="utf-8")
                added = sum(len(new_notes.get(k) or []) for k in ("glossary", "voice", "style"))
                print(f"📝 Notes: +{added} decision(s) → {out_dir / NOTES_FILE}")
            except yaml.YAMLError as e:
                print(f"⚠️  Notes YAML parse error (not merged): {e}")
                (out_dir / f"{stem}.notes_BROKEN.yaml").write_text(raw, encoding="utf-8")

        aligned = [{"id": s["id"], "source": s["text"], "target": translated.get(s["id"], "")}
                   for s in segments]
        (out_dir / f"{stem}.{args.target_lang}.segments.json").write_text(
            json.dumps(aligned, ensure_ascii=False, indent=1), encoding="utf-8")

        if any(i.startswith("missing") for i in issues):
            broken = out_dir / f"{stem}.{args.target_lang}_INCOMPLETE.md"
            broken.write_text("\n\n".join(a["target"] or f"[[{a['id']} MISSING]]" for a in aligned),
                              encoding="utf-8")
            print(f"❌ Incomplete — saved as {broken} (re-run to retry)")
            exit_code = 1
            continue

        out_md.write_text("\n\n".join(a["target"] for a in aligned) + "\n", encoding="utf-8")
        print(f"📁 Saved: {out_md}  ({result['elapsed_seconds']:.0f}s)")

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
