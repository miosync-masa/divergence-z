#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cast Extractor v1.1
原作テキスト（フォルダ可）から「人物表（cast sheet）」YAMLを作る前処理ツール

固有名ではなく「宇宙から落ちてきた少女」「彼女」「搭乗者」のような記述・代名詞で
人物を指す作品では、persona_extractor_v2 / episode_extractor に名前だけ渡しても
どの台詞が誰のものか LLM が取り違える。そこで先に人物表を作り、人が確認・修正してから
両ツールの --cast に渡す。

  cast_extractor       → 「誰がいて、本文でどう呼ばれているか」
  persona_extractor_v2 → 「この人は誰か」        (--cast で参照解決)
  episode_extractor    → 「この人は何を経験したか」(--cast で参照解決)

Usage:
    python cast_extractor.py -s scripts/STARGAZER/ --work "STARGAZER ≠consciousness"
    # → casts/STARGAZER_cast.yaml を確認・修正してから:
    python persona_extractor_v2.py -s scripts/STARGAZER/ --cast casts/STARGAZER_cast.yaml \\
      -c "宇宙から落ちてきた少女" --lang ja
    python episode_extractor.py -s scripts/STARGAZER/ --cast casts/STARGAZER_cast.yaml \\
      -c "宇宙から落ちてきた少女" --work "STARGAZER ≠consciousness"

v1.1: ライブラリ化（extract_cast）、LLM 呼び出しを core.llm に統一（BYOK）
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from divergence_z.core import (EFFORTS, LLM, Keys, LLMResult, Progress, clean_yaml_output,
                               load_source_corpus, print_progress, resolve_progress)
from divergence_z.persona_extractor_v2 import DEFAULT_MODEL

DEFAULT_EFFORT = "high"

SYSTEM_PROMPT = """You are a Cast Analyst for the Divergence-Z character extraction pipeline.

## YOUR TASK
Read the COMPLETE source text of a work (split into files, each starting with
`=== FILE: path ===`, in reading order) and produce a CAST SHEET: every character,
and EVERY way the text refers to them.

## WHY
In this kind of work, characters are often NOT referred to by proper names but by
descriptions, roles, or pronouns ("宇宙から落ちてきた少女", "彼女", "搭乗者", "僕", "当機").
The same person may be referred to differently by different narrators or in different
chapters, and the same pronoun may point to different people. Downstream tools read
this cast sheet to decide which lines and scenes belong to which character, so
misattribution here corrupts everything downstream.

## OUTPUT (YAML only)

```yaml
work: "作品名"
narration:
  - files: ["stargazer_ep00.md"]          # which files use this narration
    narrator: "label of the narrating character (or 'third_person')"
    style: "一人称 / 三人称 / 記録文体 など"
    notes: "語りの特徴。地の文の『僕』が誰か、等"

characters:
  - label: "宇宙から落ちてきた少女"        # canonical label; downstream tools use this as --character.
                                          # Use a proper name if the text gives one; otherwise the most
                                          # distinctive description used in the text (NOT a bare pronoun).
    id: "snake_case_id"
    proper_names: []                      # only names actually written in the text
    references:                           # EVERY expression used for this person, verbatim
      - expr: "彼女"
        where: "第4話以降の『僕』の地の文"
      - expr: "搭乗者"
        where: "Episode 0（船舶管理系の記録）"
    is_same_person_as_note: "例: Episode 0 の『搭乗者』と第4話の少女が同一人物である根拠"
    role: "物語上の役割"
    speaks: true                          # has dialogue of their own
    dialogue_markers: "その人物の台詞を見分ける手がかり（口調・一人称・話しかけ方など）"
    disambiguation: "同じ代名詞が別人を指す箇所と、その見分け方"
    appears_in: ["stargazer_ep04.md", "..."]
    importance: "main / supporting / minor"
```

## RULES
1. Text-grounded only. Quote reference expressions exactly as written.
2. Include non-human characters (AI, ship systems, animals) if they speak or act.
3. When identity across chapters is inferred, say so in is_same_person_as_note with the evidence;
   when uncertain, say "uncertain" and why.
4. Order characters by importance (main first).
5. Descriptions in Japanese. Output ONLY valid YAML."""


@dataclass
class CastResult:
    yaml_text: str
    data: Optional[Dict[str, Any]]      # パースできなければ None
    error: Optional[str] = None
    llm: Optional[LLMResult] = None

    @property
    def characters(self) -> list:
        return (self.data or {}).get("characters") or []


def build_user_prompt(corpus: str, work: str, hint: str = "") -> str:
    hint_block = f"## AUTHOR HINT\n{hint}\n" if hint else ""
    return f"""## SOURCE TEXT (COMPLETE)

{corpus}

## WORK
{work}
{hint_block}
Produce the cast sheet YAML now."""


def extract_cast(corpus: str, *, llm: LLM, work: str = "", hint: str = "",
                 model: str = DEFAULT_MODEL, effort: Optional[str] = DEFAULT_EFFORT,
                 max_output_tokens: int = 65536,
                 progress: Optional[Progress] = None) -> CastResult:
    """原作全文から人物表（誰がいて、本文でどう呼ばれているか）を作る"""
    report = resolve_progress(progress)
    report(f"🗂  Extracting cast sheet: {work} ({len(corpus):,} chars)")
    result = llm.complete(SYSTEM_PROMPT, build_user_prompt(corpus, work, hint), model=model,
                          effort=effort, max_output_tokens=max_output_tokens)
    yaml_text = clean_yaml_output(result.text, progress=report)
    try:
        data = yaml.safe_load(yaml_text)
        if not isinstance(data, dict):
            raise ValueError("cast sheet root must be a mapping")
        return CastResult(yaml_text, data, None, result)
    except (yaml.YAMLError, ValueError) as e:
        return CastResult(yaml_text, None, str(e), result)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Cast Extractor v1.1 — build a cast sheet (who is who, and how the text refers to them)",
    )
    parser.add_argument("--source", "-s", required=True, help="Source folder or file")
    parser.add_argument("--work", "-w", default="", help="Work title (default: folder name)")
    parser.add_argument("--hint", default="", help="Optional hint from the author")
    parser.add_argument("--model", "-m", default=DEFAULT_MODEL)
    parser.add_argument("--effort", "--reasoning", "-r", dest="effort", default=DEFAULT_EFFORT,
                        choices=EFFORTS)
    parser.add_argument("--max-output-tokens", type=int, default=65536)
    parser.add_argument("--output", "-o", default="",
                        help="Output path (default: casts/{folder}_cast.yaml)")
    args = parser.parse_args()

    source = Path(args.source)
    stem = source.name if source.is_dir() else source.stem
    print(f"📖 Loading source: {args.source}")
    corpus, manifest = load_source_corpus(args.source)
    print(f"   Loaded {len(manifest)} file(s), {len(corpus):,} characters")

    result = extract_cast(corpus, llm=LLM(Keys.from_env(), progress=print_progress),
                          work=args.work or stem, hint=args.hint, model=args.model,
                          effort=args.effort, max_output_tokens=args.max_output_tokens,
                          progress=print_progress)

    safe_stem = re.sub(r"[^\w.-]", "_", stem)
    out = Path(args.output or f"casts/{safe_stem}_cast.yaml")
    if result.data is None:
        print(f"\n⚠️  YAML parse issue: {result.error}")
        out = out.with_name(out.stem + "_BROKEN.yaml")
    else:
        print(f"\n✅ {len(result.characters)} character(s):")
        for c in result.characters:
            refs = ", ".join(r.get("expr", "") for r in (c.get("references") or [])
                             if isinstance(r, dict))
            print(f"   - [{c.get('importance', '?')}] {c.get('label')}  ←  {refs}")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(result.yaml_text, encoding="utf-8")
    print(f"\n📁 Cast sheet saved to: {out}")
    print("   ↳ 内容を確認・修正してから --cast で persona_extractor_v2 / episode_extractor に渡してください")
    return 0 if result.data is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())
