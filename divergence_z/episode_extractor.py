#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Episode Extractor v1.0  (GPT-5.2+ / 5.6 SOL "Pro" ready)
任意のフォルダ（またはファイル）の原作テキストから Episode Memory YAML を抽出

episode_generator.py (web_search で調べて生成) の「原作テキスト直読み」版。
persona_extractor_v2.py と同じ方式で、フォルダ内の全テキストを1本に連結して
長コンテキストにドーン！ → Episode Memory YAML v1.0 を出力する。

  persona_extractor_v2 → 原作テキストから「この人は誰か」
  episode_extractor    → 原作テキストから「この人は何を経験したか」

再利用しているもの（コピーではなく import なので、元ファイルの修正が自動で反映される）:
  - persona_extractor_v2: ファイル読み込み(txt/pdf/epub, 文字コード自動判定),
                          OpenAI Responses クライアント(Pro/SOL の background polling)
  - episode_generator:    Episode スキーマ/プロンプト, YAML抽出, クォート修復, 検証

v1.0 で追加したもの:
  - フォルダ読み込み（自然順ソート: vol2 < vol10）。各ファイルは `=== FILE: 相対パス ===` で区切る
    （ローダ本体は persona_extractor_v2.load_source_corpus）
  - --cast: 人物表YAML（cast_extractor.py）で「彼女」「宇宙から落ちてきた少女」等の記述を人物に解決
  - canonical_quotes の原文照合（抽出元テキストに実在するかをチェックして報告）

Usage:
    # フォルダ内の全テキストから抽出
    python episode_extractor.py \\
      --source texts/steins_gate/ \\
      --character "椎名まゆり" \\
      --work "Steins;Gate" \\
      --lang ja

    # 既存ペルソナYAMLを文脈として渡す / 複数キャラ一括
    python episode_extractor.py \\
      --source texts/rezero/ \\
      --characters "レム,ナツキ・スバル" \\
      --work "Re:ゼロから始める異世界生活" \\
      --persona personas/レム_v33.yaml

    # サブフォルダは見ない / 拡張子を絞る
    python episode_extractor.py -s texts/ -c "ヂューリエット" --no-recursive --ext .txt

Requirements:
    pip install "openai>=2.0" anthropic python-dotenv pyyaml PyPDF2
"""

from __future__ import annotations

import argparse
import re
import time
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from persona_extractor_v2 import (
    DEFAULT_EXTENSIONS,
    DEFAULT_MODEL,
    DEFAULT_REASONING,
    REASONING_EFFORTS,
    SUPPORTED_LANGUAGES,
    OpenAIResponsesClient,
    _is_pro_tier_model,
    _is_reasoning_model,
    build_cast_note,
    load_source_corpus,
)
from episode_generator import (
    EPISODE_SCHEMA,
    _extract_yaml,
    _fix_yaml_quoting,
    build_user_prompt,
    validate_episode_yaml,
)

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
# OPENAI CALL (persona_extractor_v2 のクライアントを流用)
# =============================================================================

def call_responses(client: OpenAIResponsesClient, system_prompt: str, user_prompt: str,
                   model: str, reasoning_effort: str,
                   background: Optional[bool], max_output_tokens: int) -> Dict[str, Any]:
    """Responses API 呼び出し（Pro/SOL は background + polling）"""
    is_reasoning = _is_reasoning_model(model)
    is_pro = _is_pro_tier_model(model)
    use_background = background if background is not None else is_pro

    params: Dict[str, Any] = {
        "model": model,
        "input": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_output_tokens": max_output_tokens,
    }
    if is_reasoning:
        params["reasoning"] = {"effort": reasoning_effort}
    if use_background:
        params["background"] = True
        params["store"] = True

    print(f"🚀 Sending request to {model} (SDK / Responses API)...")
    print(f"   Prompt: {len(user_prompt):,} characters")
    if is_reasoning:
        print(f"   Reasoning effort: {reasoning_effort}")
    if use_background:
        print(f"   Background mode: enabled (polling)")
    print()

    start = time.time()
    response = client.client.responses.create(**params)
    if use_background:
        print(f"   Background mode: status={getattr(response, 'status', '?')}, "
              f"id={getattr(response, 'id', '?')}")
        response = client._poll_background(response, max_wait=client.timeout)
    elapsed = time.time() - start
    print(f"⏱️  Response received in {elapsed:.1f}s")

    status = getattr(response, "status", None)
    if status == "failed":
        raise RuntimeError(f"Response failed: {getattr(response, 'error', None)}")
    if status == "incomplete":
        raise RuntimeError(
            f"Response incomplete: {getattr(response, 'incomplete_details', None)}. "
            f"max_output_tokens({max_output_tokens}) を増やすか "
            f"--max-episodes / reasoning effort を下げてください。"
        )

    return {
        "text": client._extract_output_text(response),
        "model": model,
        "reasoning_effort": reasoning_effort if is_reasoning else None,
        "background": use_background,
        "elapsed_seconds": elapsed,
    }


# =============================================================================
# QUOTE VERIFICATION
# =============================================================================

_QUOTE_STRIP = "「」『』“”\"'‘’（）()"


def _normalize(text: str) -> str:
    """照合用正規化: NFKC + 空白除去 + 外側の括弧除去"""
    text = unicodedata.normalize("NFKC", text)
    return re.sub(r"\s+", "", text)


def verify_quotes(yaml_text: str, corpus: str) -> Tuple[int, List[Tuple[str, str]]]:
    """
    canonical_quotes が原文に実在するか照合。
    Returns (総クォート数, [(episode_id, 見つからなかったquote), ...])
    """
    try:
        data = yaml.safe_load(yaml_text)
    except yaml.YAMLError:
        return 0, []
    if not isinstance(data, dict):
        return 0, []

    episodes: List[Dict[str, Any]] = []
    for tl in data.get("timelines") or []:
        if isinstance(tl, dict):
            episodes.extend(e for e in (tl.get("episodes") or []) if isinstance(e, dict))
    episodes.extend(e for e in (data.get("episodes") or []) if isinstance(e, dict))

    norm_corpus = _normalize(corpus)
    total = 0
    missing: List[Tuple[str, str]] = []

    for ep in episodes:
        for q in ep.get("canonical_quotes") or []:
            if not isinstance(q, dict) or not q.get("quote"):
                continue
            quote = str(q["quote"])
            total += 1
            needle = _normalize(quote).strip(_QUOTE_STRIP)
            if needle and needle not in norm_corpus:
                missing.append((str(ep.get("episode_id", "unknown")), quote))

    return total, missing


# =============================================================================
# MAIN
# =============================================================================

def output_path_for(name: str, output_dir: str) -> Path:
    """episode_generator と同じ命名: {name}_Episode.yaml"""
    safe_name = re.sub(r'[\\/:*?"<>|]', "", name.replace(" ", "_")) or "extracted"
    return Path(output_dir) / f"{safe_name}_Episode.yaml"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Episode Extractor v1.0 — extract Episode Memory YAML from a folder of source texts",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python episode_extractor.py -s texts/steins_gate/ -c "椎名まゆり" --work "Steins;Gate"
  python episode_extractor.py -s texts/rezero/ --characters "レム,ナツキ・スバル" \\
    --work "Re:ゼロから始める異世界生活" --persona personas/レム_v33.yaml
  python episode_extractor.py -s novel.pdf -c "レム" --lang en --reasoning high
        """,
    )

    parser.add_argument("--source", "-s", required=True,
                        help="Source folder (or single file: txt, md, pdf, epub)")
    parser.add_argument("--character", "-c", help="Character name to extract")
    parser.add_argument("--characters", help="Comma-separated list of character names")
    parser.add_argument("--work", "-w", default="",
                        help="Work title (default: source folder name)")
    parser.add_argument("--desc", default="", help="Brief character description (optional)")
    parser.add_argument("--cast", default="",
                        help="Cast sheet YAML (from cast_extractor.py) for works that refer to "
                             "characters by description instead of name")
    parser.add_argument("--persona", default="",
                        help="Companion persona YAML for context (single character only)")
    parser.add_argument("--max-episodes", type=int, default=20,
                        help="Maximum episodes (default: 20, max: 30)")
    parser.add_argument("--ext", default=",".join(DEFAULT_EXTENSIONS),
                        help=f"Comma-separated extensions to load (default: {','.join(DEFAULT_EXTENSIONS)})")
    parser.add_argument("--no-recursive", action="store_true",
                        help="Do not descend into subfolders")
    parser.add_argument("--lang", "-l", default="ja",
                        choices=list(SUPPORTED_LANGUAGES.keys()),
                        help="Output language for descriptions (default: ja)")
    parser.add_argument("--model", "-m", default=DEFAULT_MODEL,
                        help=f"Model to use (default: {DEFAULT_MODEL})")
    parser.add_argument("--reasoning", "-r", default=DEFAULT_REASONING,
                        choices=REASONING_EFFORTS,
                        help=f"Reasoning effort (default: {DEFAULT_REASONING})")
    parser.add_argument("--background", "-b", action="store_true", default=None,
                        help="Force background mode (Pro/SOL tiers auto-enable it anyway)")
    parser.add_argument("--no-background", dest="background", action="store_false",
                        help="Disable background even for Pro/SOL")
    parser.add_argument("--max-output-tokens", type=int, default=65536,
                        help="Max output tokens incl. reasoning (default: 65536)")
    parser.add_argument("--output-dir", "-o", default="episodes",
                        help="Output directory (default: episodes)")
    parser.add_argument("--print-only", action="store_true",
                        help="Print YAML without saving")

    args = parser.parse_args()

    characters: List[str] = []
    if args.character:
        characters.append(args.character)
    if args.characters:
        characters.extend(c.strip() for c in args.characters.split(",") if c.strip())
    if not characters:
        parser.error("--character or --characters is required")
    if args.persona and len(characters) > 1:
        parser.error("--persona can only be used with a single character")

    source_path = Path(args.source)
    work = args.work or (source_path.name if source_path.is_dir() else source_path.stem)
    extensions = [e.strip() for e in args.ext.split(",") if e.strip()]

    # ソース読み込み
    print(f"📖 Loading source: {args.source}")
    corpus, manifest = load_source_corpus(args.source, extensions,
                                          recursive=not args.no_recursive)
    print(f"   Loaded {len(manifest)} file(s), {len(corpus):,} characters")
    print()

    persona_context = ""
    if args.persona:
        persona_context = Path(args.persona).read_text(encoding="utf-8")
        print(f"   📋 Persona context: {args.persona} ({len(persona_context):,} chars)")

    cast_text = ""
    if args.cast:
        cast_text = Path(args.cast).read_text(encoding="utf-8")
        print(f"   🗂  Cast sheet: {args.cast} ({len(cast_text):,} chars)")

    client = OpenAIResponsesClient()
    system_prompt = build_extraction_system_prompt(args.lang)
    exit_code = 0

    for character in characters:
        print(f"{'=' * 60}")
        print(f"📖 Extracting episodes for: {character} ({work})")
        print(f"{'=' * 60}")

        user_prompt = build_extraction_user_prompt(
            corpus, character, work, args.desc, args.lang,
            persona_context=persona_context,
            max_episodes=min(args.max_episodes, 30),
            cast_text=cast_text,
        )
        result = call_responses(
            client, system_prompt, user_prompt,
            model=args.model,
            reasoning_effort=args.reasoning,
            background=args.background,
            max_output_tokens=args.max_output_tokens,
        )

        yaml_text = _fix_yaml_quoting(_extract_yaml(result["text"])).strip()

        # スキーマ検証
        print()
        is_valid, issues = validate_episode_yaml(yaml_text)
        if is_valid:
            print("✅ Episode YAML validation: PASSED")
        else:
            print("⚠️  Episode YAML Validation Issues:")
            for issue in issues:
                print(f"   - {issue}")

        # 原文照合
        total, missing = verify_quotes(yaml_text, corpus)
        if total:
            print(f"🔎 Quote verification: {total - len(missing)}/{total} found verbatim in source")
            for ep_id, quote in missing:
                print(f"   ✗ [{ep_id}] {quote[:80]}")

        print()
        print(f"📊 Model: {result['model']} / Reasoning: {result['reasoning_effort']} / "
              f"Background: {result['background']} / Time: {result['elapsed_seconds']:.1f}s")

        if args.print_only:
            print("=" * 60)
            print(yaml_text)
            print()
            continue

        out_path = output_path_for(character, args.output_dir)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if any("YAML parse error" in issue for issue in issues):
            broken = out_path.with_name(out_path.stem + "_BROKEN.yaml")
            broken.write_text(yaml_text, encoding="utf-8")
            print(f"❌ YAML parse error — saved as: {broken}")
            print("   ↳ Fix manually or re-run with fewer episodes (--max-episodes)")
            exit_code = 1
        else:
            out_path.write_text(yaml_text, encoding="utf-8")
            print(f"📁 Episode Memory saved to: {out_path} ({len(yaml_text):,} chars)")
        print()

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
