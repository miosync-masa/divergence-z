#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Episode Extractor v1.1
原作テキスト（ファイル/フォルダ）から Episode Memory YAML を抽出

episode_generator.py（web_search で調べて生成）の「原作テキスト直読み」版。

  persona_extractor_v2 → 原作テキストから「この人は誰か」
  episode_extractor    → 原作テキストから「この人は何を経験したか」

  - フォルダは自然順（vol2 < vol10）で連結し、各ファイルを `=== FILE: 相対パス ===` で区切る
  - --cast: 人物表YAML（cast_extractor.py）で「彼女」「宇宙から来た少女」等の記述を人物に解決
  - canonical_quotes を原文と照合し、実在しない台詞を報告

v1.1: ライブラリ化（extract_episodes）、LLM 呼び出しを core.llm に統一（BYOK）

Library:
    result = extract_episodes(corpus, "宇宙から来た少女", llm=LLM(Keys(...)), work="STARGAZER",
                              cast_text=cast_yaml)
    result.yaml_text, result.valid, result.quotes_total, result.quotes_missing

CLI:
    python episode_extractor.py -s scripts/STARGAZER/ --cast casts/STARGAZER_cast.yaml \\
      -c "宇宙から来た少女" --work "STARGAZER ≠consciousness"
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from divergence_z.core import (DEFAULT_EXTENSIONS, EFFORTS, LLM, Keys, LLMResult, Progress,
                               appears_in, clean_yaml_output, iter_episodes, load_source_corpus,
                               normalize_for_match, print_progress, resolve_progress)
from divergence_z.episode_generator import (EPISODE_SCHEMA, build_user_prompt, count_episodes,
                                            save_episodes, validate_episode_yaml)
from divergence_z.persona_extractor_v2 import (DEFAULT_EFFORT, DEFAULT_MODEL, SUPPORTED_LANGUAGES,
                                               build_cast_note)

# =============================================================================
# PROMPTS
# =============================================================================

def build_extraction_system_prompt(output_lang: str) -> str:
    """Episode 抽出用システムプロンプト（原作テキスト直読み版）"""
    lang_name = SUPPORTED_LANGUAGES.get(output_lang, output_lang)

    return f"""You are an Episode Extractor for the Divergence-Z translation system.

## YOUR TASK
Given the COMPLETE source text of a work (possibly split across multiple files) and a
character name, extract an Episode Memory YAML v1.0 that captures the character's key
experiences, memories, and narrative events. This complements the persona YAML
(which describes WHO a character is) by documenting WHAT they experienced.

## WHY EPISODE MEMORY MATTERS FOR TRANSLATION
A translator needs to know not just HOW the character speaks (persona), but WHAT shaped
them (episodes). A line like "I know how hard you've been trying" carries completely
different weight depending on what the character lived through before saying it.

## SOURCE TEXT FORMAT
The source is given as one or more files, each starting with a header line:
  === FILE: relative/path.txt ===
Files are in reading order (natural sort). Use the file name together with any
chapter/episode heading found in the text for `source_episode`
(e.g. "vol02.txt / 第3章 再会").

## ANALYSIS METHODOLOGY
1. Read the entire text and locate every scene where the target character appears,
   is mentioned, or is directly affected.
2. Group those scenes into episodes (one meaningful experience = one episode).
3. Order them chronologically within each timeline / route.
4. For each episode, copy the character's most important lines VERBATIM.
5. Identify arcs that connect episodes.

## SCHEMA
{EPISODE_SCHEMA}

## CRITICAL RULES
1. **TEXT-GROUNDED ONLY**: Every episode must occur in the provided text.
   Do NOT add events from your training knowledge, sequels, or adaptations that are not in the text.
2. **VERBATIM QUOTES**: canonical_quotes MUST be copied character-for-character from the text
   (same spelling, punctuation, line breaks may be collapsed). The full text is in front of you,
   so do NOT use "[unverified]" or approximate wording. If you cannot find a line, omit the quote.
   Quotes are automatically checked against the source text after generation.
3. **CHARACTER-CENTRIC**: Describe events from the CHARACTER's perspective.
4. **Z-RELEVANCE**: Every episode must include z_relevance explaining how it affects translation.
5. **EMOTIONAL TRUTH**: Focus on emotional impact, not just plot mechanics.
6. **LANGUAGE**: All descriptions in {lang_name}. canonical_quotes stay in the source language.
7. meta.generated_by must be "episode_extractor".

Output ONLY valid YAML. No explanation before or after. Start with the meta section."""


def build_extraction_user_prompt(corpus: str, name: str, work: str, description: str,
                                 output_lang: str, persona_context: str = "",
                                 max_episodes: int = 20, cast_text: str = "") -> str:
    """原作テキスト + episode_generator の選定基準/構造/YAMLルール"""
    # 選定基準・構造・アーク・YAMLクォートルールは episode_generator と共通
    shared = build_user_prompt(
        name, work, description, output_lang,
        search_context="",
        persona_context=persona_context,
        max_episodes=max_episodes,
        include_sequel=False,
    )

    return f"""## SOURCE TEXT (COMPLETE)

{corpus}

{build_cast_note(cast_text, name)}
## TARGET CHARACTER

{name}

{shared}

## SOURCE-TEXT MODE OVERRIDES
- The section "CANONICAL QUOTES" above mentions an "[unverified] Approximate" format.
  IGNORE it: in this mode quotes must be verbatim copies from the SOURCE TEXT, or omitted.
- "Focus on main work only" means: use ONLY the SOURCE TEXT above.
- If the text contains fewer than {max_episodes} meaningful episodes for this character,
  output fewer. Do not pad.

Output ONLY valid YAML."""



# =============================================================================
# QUOTE VERIFICATION
# =============================================================================

def verify_quotes(yaml_text: str, corpus: str) -> Tuple[int, List[Tuple[str, str]]]:
    """canonical_quotes が原文に実在するか照合。Returns (総数, [(episode_id, 不一致quote), ...])"""
    try:
        data = yaml.safe_load(yaml_text)
    except yaml.YAMLError:
        return 0, []
    if not isinstance(data, dict):
        return 0, []

    norm_corpus = normalize_for_match(corpus)
    total = 0
    missing: List[Tuple[str, str]] = []
    for ep in iter_episodes(data):
        for q in ep.get("canonical_quotes") or []:
            if isinstance(q, dict) and q.get("quote"):
                total += 1
                if not appears_in(str(q["quote"]), norm_corpus):
                    missing.append((str(ep.get("episode_id", "unknown")), str(q["quote"])))
    return total, missing


# =============================================================================
# LIBRARY
# =============================================================================

@dataclass
class EpisodeExtraction:
    character: str
    yaml_text: str
    valid: bool
    issues: List[str] = field(default_factory=list)
    episode_count: int = 0
    quotes_total: int = 0
    quotes_missing: List[Tuple[str, str]] = field(default_factory=list)
    llm: Optional[LLMResult] = None


def extract_episodes(corpus: str, character: str, *, llm: LLM, work: str = "",
                     description: str = "", model: str = DEFAULT_MODEL,
                     effort: Optional[str] = DEFAULT_EFFORT, output_lang: str = "ja",
                     persona_text: str = "", cast_text: str = "", max_episodes: int = 20,
                     max_output_tokens: int = 65536, background: Optional[bool] = None,
                     progress: Optional[Progress] = None) -> EpisodeExtraction:
    """原作全文から1キャラクターの Episode Memory YAML を抽出し、検証・原文照合する"""
    report = resolve_progress(progress)
    report(f"📖 Extracting episodes: {character} ({work})")
    result = llm.complete(
        build_extraction_system_prompt(output_lang),
        build_extraction_user_prompt(corpus, character, work, description, output_lang,
                                     persona_context=persona_text,
                                     max_episodes=min(max_episodes, 30), cast_text=cast_text),
        model=model, effort=effort, max_output_tokens=max_output_tokens, background=background)
    yaml_text = clean_yaml_output(result.text, progress=report)
    valid, issues = validate_episode_yaml(yaml_text)
    total, missing = verify_quotes(yaml_text, corpus)
    return EpisodeExtraction(character, yaml_text, valid, issues, count_episodes(yaml_text),
                             total, missing, result)


def output_path_for(name: str, output_dir: str) -> Path:
    """episode_generator と同じ命名: {name}_Episode.yaml"""
    safe_name = re.sub(r'[\\/:*?"<>|]', "", name.replace(" ", "_")) or "extracted"
    return Path(output_dir) / f"{safe_name}_Episode.yaml"


# =============================================================================
# CLI
# =============================================================================

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Episode Extractor v1.1 — extract Episode Memory YAML from source texts",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--source", "-s", required=True, help="Source folder or file")
    parser.add_argument("--character", "-c", help="Character name to extract")
    parser.add_argument("--characters", help="Comma-separated list of character names")
    parser.add_argument("--work", "-w", default="", help="Work title (default: folder name)")
    parser.add_argument("--desc", default="", help="Brief character description (optional)")
    parser.add_argument("--cast", default="", help="Cast sheet YAML (cast_extractor.py)")
    parser.add_argument("--persona", default="",
                        help="Companion persona YAML for context (single character only)")
    parser.add_argument("--max-episodes", type=int, default=20)
    parser.add_argument("--ext", default=",".join(DEFAULT_EXTENSIONS))
    parser.add_argument("--no-recursive", action="store_true")
    parser.add_argument("--lang", "-l", default="ja", choices=list(SUPPORTED_LANGUAGES.keys()))
    parser.add_argument("--model", "-m", default=DEFAULT_MODEL)
    parser.add_argument("--effort", "--reasoning", "-r", dest="effort", default=DEFAULT_EFFORT,
                        choices=EFFORTS)
    parser.add_argument("--background", "-b", action="store_true", default=None)
    parser.add_argument("--no-background", dest="background", action="store_false")
    parser.add_argument("--max-output-tokens", type=int, default=65536)
    parser.add_argument("--output-dir", "-o", default="episodes")
    parser.add_argument("--print-only", action="store_true")
    args = parser.parse_args()

    characters = ([args.character] if args.character else []) + \
        [c.strip() for c in (args.characters or "").split(",") if c.strip()]
    if not characters:
        parser.error("--character or --characters is required")
    if args.persona and len(characters) > 1:
        parser.error("--persona can only be used with a single character")

    source_path = Path(args.source)
    work = args.work or (source_path.name if source_path.is_dir() else source_path.stem)
    print(f"📖 Loading source: {args.source}")
    corpus, manifest = load_source_corpus(
        args.source, [e.strip() for e in args.ext.split(",") if e.strip()],
        recursive=not args.no_recursive)
    print(f"   Loaded {len(manifest)} file(s), {len(corpus):,} characters")
    persona_text = Path(args.persona).read_text(encoding="utf-8") if args.persona else ""
    cast_text = Path(args.cast).read_text(encoding="utf-8") if args.cast else ""

    llm = LLM(Keys.from_env(), progress=print_progress)
    exit_code = 0
    for character in characters:
        print(f"\n{'=' * 60}")
        r = extract_episodes(corpus, character, llm=llm, work=work, description=args.desc,
                             model=args.model, effort=args.effort, output_lang=args.lang,
                             persona_text=persona_text, cast_text=cast_text,
                             max_episodes=args.max_episodes,
                             max_output_tokens=args.max_output_tokens,
                             background=args.background, progress=print_progress)
        print(f"   📊 Episodes found: {r.episode_count}")
        if r.valid:
            print("✅ Episode YAML validation: PASSED")
        else:
            print("⚠️  Episode YAML Validation Issues:")
            for issue in r.issues:
                print(f"   - {issue}")
        if r.quotes_total:
            print(f"🔎 Quote verification: {r.quotes_total - len(r.quotes_missing)}/"
                  f"{r.quotes_total} found verbatim in source")
            for ep_id, quote in r.quotes_missing:
                print(f"   ✗ [{ep_id}] {quote[:80]}")

        if args.print_only:
            print(r.yaml_text)
            continue
        path, ok = save_episodes(r.yaml_text, str(output_path_for(character, args.output_dir)),
                                 r.issues)
        if ok:
            print(f"📁 Episode Memory saved to: {path} ({len(r.yaml_text):,} chars)")
        else:
            print(f"❌ YAML parse error — saved as: {path}")
            exit_code = 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
