#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Persona Extractor v2.1
原作テキスト（ファイル/フォルダ）からキャラクターペルソナ YAML v3.3 を抽出

v2.1 Changes:
- ライブラリ化: extract_persona() を UI / pipeline から直接呼べる関数に
- LLM 呼び出しを core.llm に統一（BYOK・OpenAI/Anthropic 両対応・モデル登録表）
- ファイル読み込みを core.loaders に移動
- --reasoning は --effort の別名として残す

v2.0: OpenAI SDK (Responses API) 化、Pro/SOL ティアの background polling
v1.x: old/persona_extractor.py

Library:
    from divergence_z.core import LLM, Keys, load_source_corpus
    from divergence_z.persona_extractor_v2 import extract_persona
    corpus, _ = load_source_corpus("scripts/STARGAZER/")
    result = extract_persona(corpus, "宇宙から来た少女", llm=LLM(Keys(openai="sk-...")),
                             cast_text=open("casts/STARGAZER_cast.yaml").read(), output_lang="ja")
    result.yaml_text, result.valid, result.issues

CLI:
    python persona_extractor_v2.py -s scripts/STARGAZER/ --cast casts/STARGAZER_cast.yaml \\
      -c "宇宙から来た少女" --lang ja
    python persona_extractor_v2.py -s rezero_vol1.pdf -c "レム" --model claude-opus-5-5 --effort high
    python persona_extractor_v2.py -s steins_gate.txt --characters "牧瀬紅莉栖,岡部倫太郎" --lang en
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from divergence_z.core import (EFFORTS, LLM, Keys, LLMResult, Progress, appears_in,
                               clean_yaml_output, load_source_corpus, normalize_for_match,
                               print_progress, resolve_progress)

# 既定モデル。環境変数 PERSONA_EXTRACTOR_MODEL / PERSONA_EXTRACTOR_REASONING で上書き
DEFAULT_MODEL = os.getenv("PERSONA_EXTRACTOR_MODEL", "gpt-5.6-sol")
DEFAULT_EFFORT = os.getenv("PERSONA_EXTRACTOR_REASONING", "max")

SUPPORTED_LANGUAGES = {
    "ja": "Japanese (日本語)",
    "en": "English",
    "zh": "Chinese (中文)",
    "ko": "Korean (한국語)",
    "fr": "French (Français)",
    "es": "Spanish (Español)",
    "de": "German (Deutsch)",
    "pt": "Portuguese (Português)",
    "it": "Italian (Italiano)",
    "ru": "Russian (Русский)",
}


def build_cast_note(cast_text: str, character_name: str) -> str:
    """
    人物表（cast_extractor.py の出力など）をプロンプト用の注記にする。
    名前ではなく「宇宙から落ちてきた少女」「彼女」のような記述で人物を指す作品向け。
    """
    if not cast_text.strip():
        return ""
    return f"""## CHARACTER REFERENCE GUIDE (CAST SHEET)

In this work, characters are often referred to NOT by proper names but by descriptions,
roles, or pronouns (e.g. "宇宙から落ちてきた少女", "彼女", "搭乗者"). The same person may be
referred to differently depending on the chapter or the narrator, and the same pronoun
may point to different people.

Use the cast sheet below to resolve every reference in the source text.
The TARGET CHARACTER is the entry labeled "{character_name}" — collect ALL lines and
scenes that belong to this person under ANY of their references, and do NOT attribute
lines of other characters to them. Where the cast sheet gives disambiguation hints,
follow them. If the cast sheet is wrong in a specific scene, trust the text.

Use "{character_name}" as the character's name in the output (name / character_id),
unless the text reveals an actual proper name — then use that name and keep the label
as an alias.

```yaml
{cast_text.strip()}
```
"""




# =============================================================================
# SYSTEM PROMPT FOR PERSONA EXTRACTION — v3.3
# =============================================================================

def build_extraction_prompt(output_lang: str) -> str:
    """ペルソナ抽出用のシステムプロンプトを構築（v3.3対応）"""

    lang_name = SUPPORTED_LANGUAGES.get(output_lang, "English")

    return f"""You are a Persona Extractor for the Z-Axis Translation System v3.3.

## YOUR TASK
Given a complete source text (novel, script, etc.) and a character name, extract a comprehensive persona YAML that captures the character's psychological structure for emotion-preserving translation.

## ANALYSIS METHODOLOGY

### Phase 1: Dialogue Collection
- Find ALL dialogue lines spoken by the target character
- Note the context of each line (who they're talking to, situation)
- Identify emotional state during each utterance

### Phase 2: Speech Pattern Analysis
- First-person pronouns (variations and when they change)
- Second-person address patterns (different for different relationships)
- Sentence endings and their emotional connotations
- Dialect features and speech quirks
- Verbal tics, catchphrases, unique expressions

### Phase 3: Psychological Structure
- Identify internal conflicts (conflict_axes) from behavior patterns
- Analyze defense mechanisms and biases
- Extract weaknesses from vulnerable moments
- Map emotional states to speech pattern changes

### Phase 4: Relationship Mapping
- How speech changes based on listener
- Power dynamics reflected in language
- Triggers that cause emotional shifts — BOTH negative AND positive

### Phase 5: Trigger Balance Analysis (NEW in v3.2)
- Identify moments where the character is HURT, STRESSED, or DESTABILIZED → negative triggers
- Identify moments where the character is COMFORTED, ENCOURAGED, or LOVED → positive triggers
- Distinguish LEVELS of positive impact (mild thanks vs deep acceptance vs love confession)
- A character's RECOVERY behavior is as important as their BREAKDOWN behavior

### Phase 6: Identity Core Extraction (NEW in v3.3)
- Find scenes where the character is NOT in conflict — relaxed, happy, being themselves
- What do they do in their free time? What makes them genuinely happy?
- How do other characters describe them when they're being natural?
- What are their hobbies, preferences, habits mentioned in the text?
- What do they enjoy that has NOTHING to do with their conflicts?
- This is the character's I₀ — who they ARE, not how they REACT

## OUTPUT FORMAT

Output MUST be valid YAML following the v3.3 schema.
All descriptions should be in {lang_name}.
`original_speech_patterns` section MUST preserve the SOURCE LANGUAGE of the text.

```yaml
meta:
  version: "3.3"
  generated_by: "persona_extractor"
  character_id: "unique_id"
  output_lang: "{output_lang}"
  source_work: "作品名"
  extraction_note: "Extracted from original text via LLM analysis"

persona:
  name: "キャラ名（原語）"
  name_en: "English Name"
  name_native: "原語での名前"
  source: "作品名"
  type: "キャラクタータイプ"
  summary: "1-2文の概要（{lang_name}）"
```

### IDENTITY_CORE (I₀ — 存在の核) — NEW in v3.3

This section describes WHO the character IS — not how they REACT.
conflict_axes/triggers/emotion_states describe Ln (surface dynamics).
identity_core describes I₀ (the subject experiencing those dynamics).

**Without I₀, the persona describes a "reaction machine" — not a person.**

```yaml
identity_core:
  essence: "1-2文。この人が何者かを、葛藤抜きで記述"  # ← REQUIRED
  true_nature: "防衛や葛藤がない時の素顔"              # optional
  desires:                                              # optional
    - "what they genuinely want"
  joys:                                                 # optional
    - joy: "何に喜ぶか"
      expression: "その時どうなるか"                    # optional
  likes: ["好きなもの"]                                 # optional
  dislikes: ["嫌いなもの"]                              # optional
  unfiltered_self: "葛藤がない時の自然な姿"             # optional
```

**EXTRACTION GUIDANCE (for persona_extractor):**
Extract from the SOURCE TEXT — do NOT invent or assume:
- Scenes where the character is relaxed, happy, or at peace
- Direct mentions of hobbies, preferences, or habits
- How other characters describe this character's personality
- What the character does in downtime (not during conflict)
- Moments of genuine joy or satisfaction unrelated to their conflicts
- If the text does not contain enough information, include only `essence` and omit other fields
- **DO NOT guess** — only include what the text directly supports

age:
  chronological: 数値
  mental_maturity: "teen_young / teen_mature / adult"
  age_context: "背景説明（{lang_name}）— expression patterns belong in emotion_states, NOT here"

language:
  original_speech_patterns:
    source_lang: "作品の言語コード"
    first_person: "一人称（原語）"
    first_person_nuance: "説明（{lang_name}）"
    first_person_variants:
      - form: "バリエーション"
        context: "使用場面"
    second_person:
      - form: "二人称"
        nuance: "説明"
        target: "対象"
    self_reference_in_third_person: false
    dialect: "方言"
    dialect_features: []
    sentence_endings:
      - pattern: "パターン（原語）"
        nuance: "説明（{lang_name}）"
    speech_quirks:
      - pattern: "口癖（原語）"
        frequency: "often/moderate/rare"
        trigger: "発動条件"

  translation_compensations:
    register: "overall tone"
    tone_keywords: [keywords]
    strategies:
      en: [strategies for English]
      zh: [strategies for Chinese]
    untranslatable_elements:
      - element: "要素"
        impact: "high/medium/low"
        note: "説明"

conflict_axes:
  - axis: "A vs B"
    side_a: "表層"
    side_b: "深層"
    weight: 0.0-1.0
    notes: "発動条件"

bias:
  expression_pattern: "パターン名"
  default_mode: "デフォルト状態"
  pattern: "表出フロー"
  rule: "行動ルール"
  tendencies: [観測可能な傾向]

weakness:
  primary: "主要な弱点"
  secondary: "二次的"
  tertiary: "三次的"
  fear: "根底の恐れ"
  notes: "発現パターン"

age_expression_rules:
  category: "teen_young/teen_mature/adult"
  high_z_patterns:
    vocabulary: "崩れ方"
    structure: "構造変化"
    markers: [特徴]
  low_z_patterns:
    vocabulary: "通常"
    structure: "安定"

emotion_states:
  - state: "状態名"
    z_intensity: "low/medium/high"
    z_mode: "collapse/rage/numb/plea/shame/leak/stable"
    description: "発生条件（{lang_name}）"
    surface_markers_hint:
      hesitation: 0-4
      stutter_count: 0-4
      negation_first: true/false
      overwrite: "none/optional/required"
      residual: "none/optional/required"
      tone: "声の質"
    z_leak: [markers]

example_lines:
  - situation: "コンテキスト（{lang_name}）"
    line: "実際の台詞（原語）"
    line_romanized: "ローマ字（該当する場合）"
    tags: [tags]
    z_intensity: "low/medium/high"
    z_mode: "対応z_mode"
```

### TRIGGERS (Z軸変動トリガー) — v3.2 BALANCED

**⚠️ CRITICAL: TRIGGERS MUST BE BALANCED (POSITIVE + NEGATIVE)**

Triggers are what cause Z-axis changes during dialogue. They are used by the
dialogue system's LLM to detect when another character's words affect this character.

An LLM reads these triggers and judges whether a line activates them.
Trigger descriptions should be MEANING-BASED (not keyword-based).

```yaml
triggers:
  - trigger: "Descriptive condition (meaning-based)"
    reaction: "z_spike / z_drop / z_shock / z_recovery"
    z_delta: "+0.3 / -0.5 etc."
    z_mode_shift: "target z_mode (optional)"
    surface_effect: "How it changes speech"
    example_response: "Actual quote from source text if available"
```

**TRIGGER CATEGORIES (must include ALL that apply):**

| Category | reaction | z_delta | When to use |
|----------|----------|---------|-------------|
| NEGATIVE SPIKE | z_spike | +0.3~+0.9 | Trauma, failure, fear, attack, humiliation |
| NEGATIVE BOOST | z_boost | +0.2~+0.5 | Stress accumulation, irritation, minor provocation |
| POSITIVE DROP | z_drop | -0.2~-0.4 | Mild encouragement, small kindness, casual thanks |
| POSITIVE RECOVERY | z_recovery | -0.4~-0.6 | Strong support, acceptance, "let's move forward" |
| OVERWHELMING POSITIVE | z_shock | -0.6~-0.8 | Love confession, total acceptance, existential affirmation |
| STABILIZING | z_stable | 0.0 | Neutral reset, routine, familiar comfort |

**⚠️ MINIMUM TRIGGER REQUIREMENTS:**
- At least 2-3 NEGATIVE triggers (z_spike / z_boost)
- At least 2-3 POSITIVE triggers (z_drop / z_recovery / z_shock)
- Positive triggers MUST be granular — DO NOT collapse all positive inputs into one trigger

**❌ BAD (too coarse):**
```yaml
triggers:
  - trigger: "仲間の励まし"  # Too vague! "good job" and "I love you" are NOT the same
    z_delta: "-0.4"
```

**✅ GOOD (granular positive triggers):**
```yaml
triggers:
  - trigger: "軽い励ましや感謝の言葉を受ける"
    reaction: "z_drop"
    z_delta: "-0.2"

  - trigger: "自分の行動や存在を強く肯定される"
    reaction: "z_recovery"
    z_delta: "-0.5"

  - trigger: "愛の告白を受ける、または存在を全肯定される"
    reaction: "z_shock"
    z_delta: "-0.7"
```

**WHY GRANULARITY MATTERS:**
In dialogue mode, an LLM reads these triggers and judges which one(s) a line activates.
If all positive inputs map to ONE trigger, the LLM cannot distinguish between:
- "Good job today" (mild encouragement → z_drop -0.2)
- "I love you" (love confession → z_shock -0.7)
- "Let's start over together" (existential recovery → z_recovery -0.5)

This causes incorrect Z-axis accumulation and wrong emotional trajectories.

**FOR EXTRACTION: Look for scenes in the source text where the character:**
- Receives comfort → how do they react? (denial, tears, silence, gratitude?)
- Is praised → do they deflect, accept, get embarrassed?
- Is confessed to → panic, joy, disbelief?
- Is given hope → resistance, cautious acceptance, emotional flood?

Each DIFFERENT reaction pattern = a SEPARATE positive trigger.

### ARC_DEFAULTS
```yaml
arc_defaults:
  typical_arc_targets: [targets]
  common_arc_patterns:
    - arc_id: "パターン名"
      phases: [phases]
      notes: "説明"
```

## CRITICAL RULES

1. **EVIDENCE-BASED**: Every claim must be supported by actual dialogue from the text
2. **ORIGINAL LANGUAGE**: `original_speech_patterns` must use the source text's language
3. **COMPREHENSIVE**: Include ALL emotion_states observed in the text
4. **SPECIFIC**: example_lines should be actual quotes from the source
5. **NUANCED**: Capture subtle variations in speech patterns
6. **TRIGGER BALANCE**: Include at least 2-3 positive AND 2-3 negative triggers
7. **POSITIVE GRANULARITY**: Positive triggers must distinguish mild from strong from overwhelming
8. **RECOVERY MATTERS**: A character's recovery behavior is as important as breakdown for translation
9. **age_context**: MUST NOT contain expression patterns (those go to emotion_states)
10. **identity_core.essence is REQUIRED**: Describe who this character IS, not just how they react
11. **identity_core — EXTRACT, don't invent**: Only include likes/joys/desires that are directly evidenced in the text. If the text doesn't show the character's hobbies or preferences, omit those fields — do NOT guess.
12. **I₀ vs Ln separation**: identity_core describes the person (I₀); conflict_axes/triggers describe their reactions (Ln). Keep them distinct.

## EXAMPLE ANALYSIS PROCESS

For the line: 「べ、別にあんたのためじゃないわよ」

1. **Observe**: Stutter on べ, denial pattern, わよ ending
2. **Classify**: tsundere_denial state, z_mode=leak
3. **Context**: Said when caught showing care
4. **Pattern**: negation_first=true, stutter_count=1
5. **Document**: Add to emotion_states and example_lines

For positive trigger extraction:
1. **Find**: Scene where character receives comfort/love/acceptance
2. **Observe**: How does their speech change? (softening, tears, denial weakening?)
3. **Classify**: What level? (mild drop vs recovery vs shock)
4. **Document**: Add as separate trigger with appropriate z_delta

Output ONLY valid YAML. No explanation before or after.
Start with the meta section."""



def build_user_prompt(source_text: str, character_name: str, output_lang: str,
                      cast_text: str = "") -> str:
    return f"""## SOURCE TEXT (COMPLETE)

{source_text}

{build_cast_note(cast_text, character_name)}
## TARGET CHARACTER

{character_name}

## INSTRUCTIONS

Analyze the complete source text above and extract a comprehensive persona YAML v3.3 for the character "{character_name}".

Focus on:
1. Every line of dialogue spoken by this character
2. How their speech patterns change with emotion
3. Their relationships with other characters
4. Internal conflicts revealed through behavior
5. Specific speech quirks and verbal tics
6. **BOTH negative AND positive emotional triggers — with granularity**
7. **How the character reacts to comfort, praise, love, and acceptance**
8. **WHO this character IS beyond their conflicts — their I₀ (identity_core)**

Output language for descriptions: {SUPPORTED_LANGUAGES.get(output_lang, output_lang)}
Keep original_speech_patterns in the source text's language.

REMEMBER:
- identity_core.essence is REQUIRED — describe who this character IS, not just their reactions
- identity_core: EXTRACT from the text, do NOT invent — omit fields with no textual evidence
- Look for scenes where the character is relaxed, happy, or simply being themselves
- Triggers MUST be balanced (at least 2-3 positive AND 2-3 negative)
- Positive triggers MUST be granular (mild encouragement ≠ love confession)
- Use actual quotes from the source text for example_responses when possible

Output ONLY valid YAML."""


# =============================================================================
# LIBRARY
# =============================================================================

@dataclass
class PersonaResult:
    character: str
    yaml_text: str
    valid: bool
    issues: List[str] = field(default_factory=list)
    llm: Optional[LLMResult] = None
    lines_total: int = 0                                     # example_lines の数
    lines_missing: List[str] = field(default_factory=list)   # 原文に見つからなかった例文


def verify_example_lines(yaml_text: str, source_text: str) -> tuple:
    """example_lines が原文に実在するか（地の文で途切れた台詞をつないだものも可）"""
    import yaml as yaml_lib
    try:
        data = yaml_lib.safe_load(yaml_text) or {}
    except yaml_lib.YAMLError:
        return 0, []
    lines = [str(x["line"]) for x in data.get("example_lines") or []
             if isinstance(x, dict) and x.get("line")]
    corpus = normalize_for_match(source_text)
    return len(lines), [l for l in lines if not appears_in(l, corpus)]


def extract_persona(source_text: str, character_name: str, *, llm: LLM,
                    model: str = DEFAULT_MODEL, effort: Optional[str] = DEFAULT_EFFORT,
                    output_lang: str = "en", cast_text: str = "",
                    max_output_tokens: int = 65536, background: Optional[bool] = None,
                    progress: Optional[Progress] = None) -> PersonaResult:
    """原作全文から1キャラクターのペルソナ YAML v3.3 を抽出して検証する"""
    report = resolve_progress(progress)
    report(f"🎭 Extracting persona: {character_name} ({len(source_text):,} chars)")
    result = llm.complete(build_extraction_prompt(output_lang),
                          build_user_prompt(source_text, character_name, output_lang, cast_text),
                          model=model, effort=effort, max_output_tokens=max_output_tokens,
                          background=background)
    yaml_text = clean_yaml_output(result.text, progress=report)
    valid, issues = validate_v33_persona(yaml_text)
    total, missing = verify_example_lines(yaml_text, source_text)
    return PersonaResult(character_name, yaml_text, valid, issues, result, total, missing)


# =============================================================================
# VALIDATION (v3.3)
# =============================================================================

def validate_v33_persona(yaml_text: str) -> tuple[bool, list[str]]:
    """
    抽出されたYAMLがv3.3スキーマに準拠しているか検証
    Returns (is_valid, list_of_issues).
    """
    import yaml as yaml_lib

    issues = []

    try:
        data = yaml_lib.safe_load(yaml_text)
    except yaml_lib.YAMLError as e:
        return False, [f"YAML parse error: {e}"]

    # Check meta version
    meta_version = data.get("meta", {}).get("version", "")
    if meta_version not in ["3.0", "3.1", "3.2", "3.3"]:
        issues.append(f"meta.version should be '3.3' (got '{meta_version}')")

    # === v3.3 IDENTITY_CORE CHECK ===
    identity_core = data.get("identity_core", {})
    if not identity_core:
        issues.append(
            "v3.3 requires identity_core section — describes WHO the character IS (I₀). "
            "At minimum, identity_core.essence is required."
        )
    elif not identity_core.get("essence"):
        issues.append(
            "identity_core.essence is REQUIRED — a 1-2 sentence description of "
            "who this character is, independent of their conflicts."
        )

    # Check language structure
    language_data = data.get("language", {})
    osp = language_data.get("original_speech_patterns", {})
    if not osp:
        issues.append("language.original_speech_patterns is required")
    else:
        if "source_lang" not in osp:
            issues.append("original_speech_patterns.source_lang is required")
        if "first_person" not in osp:
            issues.append("original_speech_patterns.first_person is required")

    tc = language_data.get("translation_compensations", {})
    if not tc:
        issues.append("language.translation_compensations is required")

    # Check emotion_states for z_mode and z_leak
    emotion_states = data.get("emotion_states", [])
    for i, state in enumerate(emotion_states):
        if "z_mode" not in state:
            issues.append(f"emotion_states[{i}].z_mode is required")
        if "z_leak" not in state:
            issues.append(f"emotion_states[{i}].z_leak is required")

    # === v3.2 TRIGGER BALANCE CHECK ===
    triggers = data.get("triggers", [])
    if not triggers:
        issues.append("triggers section is required")
    else:
        positive_count = 0
        negative_count = 0

        for t in triggers:
            z_delta_str = str(t.get("z_delta", "+0.0"))
            try:
                z_delta_val = float(z_delta_str.replace("+", ""))
            except ValueError:
                z_delta_val = 0.0

            if z_delta_val < 0:
                positive_count += 1
            elif z_delta_val > 0:
                negative_count += 1

        if positive_count < 2:
            issues.append(
                f"v3.2 requires at least 2 positive triggers (z_drop/z_recovery/z_shock), "
                f"found {positive_count}. Positive triggers must be granular."
            )
        if negative_count < 2:
            issues.append(
                f"v3.2 requires at least 2 negative triggers (z_spike/z_boost), "
                f"found {negative_count}."
            )

    return len(issues) == 0, issues


# =============================================================================
# MAIN
# =============================================================================

def save_persona(yaml_text: str, character_name: str, output_dir: str = "personas") -> str:
    """生成されたペルソナを保存"""
    os.makedirs(output_dir, exist_ok=True)

    # 安全なファイル名を生成
    safe_name = character_name.lower().replace(" ", "_")
    safe_name = re.sub(r'[^\w\-]', '', safe_name)
    if not safe_name:
        safe_name = "extracted"

    filename = f"{safe_name}_extracted_v33.yaml"
    filepath = os.path.join(output_dir, filename)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(yaml_text)

    return filepath



# =============================================================================
# CLI
# =============================================================================

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Persona Extractor v2.1 — extract persona YAML v3.3 from source text",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--source", "-s",
                        help="Source file or folder (txt, md, pdf, epub). "
                             "Folders are loaded in natural order (ep2 < ep10)")
    parser.add_argument("--cast",
                        help="Cast sheet YAML (from cast_extractor.py) for works that refer to "
                             "characters by description instead of name")
    parser.add_argument("--character", "-c", help="Character name to extract")
    parser.add_argument("--characters", help="Comma-separated list of character names")
    parser.add_argument("--lang", "-l", default="en", choices=list(SUPPORTED_LANGUAGES.keys()),
                        help="Output language for descriptions (default: en)")
    parser.add_argument("--model", "-m", default=DEFAULT_MODEL,
                        help=f"Model to use (default: {DEFAULT_MODEL})")
    parser.add_argument("--effort", "--reasoning", "-r", dest="effort", default=DEFAULT_EFFORT,
                        choices=EFFORTS, help=f"Reasoning effort (default: {DEFAULT_EFFORT})")
    parser.add_argument("--background", "-b", action="store_true", default=None,
                        help="Force background mode (registry decides by default)")
    parser.add_argument("--no-background", dest="background", action="store_false")
    parser.add_argument("--max-output-tokens", type=int, default=65536)
    parser.add_argument("--output-dir", "-o", default="personas")
    parser.add_argument("--print-only", action="store_true", help="Print YAML without saving")
    parser.add_argument("--list-languages", action="store_true")
    args = parser.parse_args()

    if args.list_languages:
        for code, name in SUPPORTED_LANGUAGES.items():
            print(f"  {code:4} : {name}")
        return 0
    if not args.source:
        parser.error("--source is required")
    characters = ([args.character] if args.character else []) + \
        [c.strip() for c in (args.characters or "").split(",") if c.strip()]
    if not characters:
        parser.error("--character or --characters is required")

    print(f"📖 Loading source: {args.source}")
    source_text, manifest = load_source_corpus(args.source)
    print(f"   Loaded {len(manifest)} file(s), {len(source_text):,} characters")
    cast_text = Path(args.cast).read_text(encoding="utf-8") if args.cast else ""
    if cast_text:
        print(f"   Cast sheet: {args.cast} ({len(cast_text):,} chars)")

    llm = LLM(Keys.from_env(), progress=print_progress)
    for character in characters:
        print(f"\n{'=' * 60}")
        result = extract_persona(source_text, character, llm=llm, model=args.model,
                                 effort=args.effort, output_lang=args.lang, cast_text=cast_text,
                                 max_output_tokens=args.max_output_tokens,
                                 background=args.background, progress=print_progress)
        if result.valid:
            print("✅ v3.3 Schema Validation: PASSED")
        else:
            print("⚠️  v3.3 Schema Validation Issues:")
            for issue in result.issues:
                print(f"   - {issue}")

        if result.lines_total:
            print(f"🔎 example_lines: {result.lines_total - len(result.lines_missing)}/"
                  f"{result.lines_total} found in source")
            for line in result.lines_missing:
                print(f"   ✗ {line[:80]}")

        if args.print_only:
            print(result.yaml_text)
        else:
            print(f"✅ Saved to: {save_persona(result.yaml_text, character, args.output_dir)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
